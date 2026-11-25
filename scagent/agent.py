"""The agent loop.

    request ──► model ──(tool request)──► validate ──► run Python tool ──► result ──► model ...
                  └──(submit_report)──► validate report ──► verifier ──► done

Python never decides *which* tool to call next; the model does, based on the
results it has seen. Python only enforces the rules: argument validation, the
tool-call limit, the turn limit, and the report format.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .config import Config
from .executor import ToolExecutor
from .providers.base import LLMProvider, ToolResult
from .report import (SUBMIT_REPORT_DESCRIPTION, SUBMIT_REPORT_SCHEMA, system_fallback_report,
                     validate_report)
from .trace import Trace
from .verifier import verify

SYSTEM_PROMPT = """You are a supply chain exception investigator for a fictional distribution company.
Investigation date (treat as "today"): {today}.

Your job: given a request about an order, (1) identify whether there is a problem, especially a
shipment delay, (2) investigate its cause using evidence, and (3) recommend practical, data-driven
actions. The problems you handle:
  - Delayed delivery: an order is overdue (or certain to be) against its promised delivery date.
  - Insufficient inventory: available stock at the order's warehouse is below the ordered quantity
    (which delays an order that has not shipped).
It is also a valid outcome that there is no exception, that the order does not exist, or that data
is missing.

Investigating the cause of a delay: possible causes are a delay the carrier recorded on the
shipment, a carrier service disruption (a carrier alert matching where the shipment is held),
tracking that has stalled with no explanation, a late dispatch by the warehouse (dispatched after
the ship-by date), a stock shortage, or a missing shipment record. Look for the evidence that
distinguishes these; do not settle on "unknown" while a relevant tool could still explain it, and do
not claim a cause the data does not support. A carrier alert only explains a delay if its carrier,
location and dates match the shipment.

Recommending actions: choose recommended_actions from the catalog in the submit_report schema. Each
action's details must say what to do and cite the evidence that justifies it. Recommend only what
the data supports (for example TRANSFER_STOCK only when find_alternative_stock shows a warehouse
that alone can cover the need). If there is no exception, recommend NO_ACTION_NEEDED alone; for a
real problem, never include NO_ACTION_NEEDED (follow-up monitoring belongs in an action's details).

How to work:
- Decide which tool to use next based on what you have learned so far. An order that has not
  shipped usually calls for inventory checks; a shipped order usually calls for shipment tracking.
  Do not call tools you don't need. Once an order has SHIPPED or been DELIVERED, current stock
  levels cannot explain a late delivery, so inventory tools are not relevant to it.
- Before each tool call, write one short sentence saying what you are checking and why.
- Check every line item of an order when inventory is relevant.
- Only recommend a transfer from another warehouse if find_alternative_stock shows that warehouse
  alone can cover the need. Otherwise set recommended_source_warehouse to null.
- The tools are read-only. You cannot modify orders, book shipments, or contact anyone. Recommend
  actions; never claim to have taken them.

Honesty rules (these matter most):
- Use only facts that appear in tool results. Never invent shipment events, quantities, dates,
  causes, or delivery estimates.
- Distinguish confirmed facts (stated in tool data) from inferences. If no cause is recorded, say
  the cause is unknown.
- If a tool fails or returns NOT_FOUND, say so. If that prevents a reliable conclusion, set
  investigation_complete to false and list what is missing. Never describe what a failed or
  missing record would have contained (for example, do not say "no delay reason was recorded"
  when you could not retrieve the shipment). If a required record is missing, report
  MISSING_DATA rather than guessing a cause from unrelated data.
- Evidence items must quote the specific values you received, naming the tool, e.g.
  "check_inventory: SKU-202 at WH-BOS available 12 (ordered 50)". A tool name alone is not evidence.
- If the evidence shows no problem, report NO_EXCEPTION. Do not invent an issue.

When you are done, call submit_report exactly once. You have at most {max_calls} data-tool calls."""

ORDER_ID_IN_TEXT = re.compile(r"ORD-\d{4}")


@dataclass
class InvestigationResult:
    report: dict
    trace: Trace
    verification: dict
    tool_calls_used: int


def _tool_dicts(executor: ToolExecutor) -> list[dict]:
    defs = [{"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in executor.tool_definitions()]
    defs.append({"name": "submit_report", "description": SUBMIT_REPORT_DESCRIPTION,
                 "parameters": SUBMIT_REPORT_SCHEMA})
    return defs


def investigate(request: str, provider: LLMProvider, cfg: Config,
                printer: Callable[[str], None] | None = None,
                on_step: Callable[[dict], None] | None = None) -> InvestigationResult:
    executor = ToolExecutor(cfg.db_path, cfg.investigation_date, cfg.failing_tools)
    trace = Trace(request, meta={
        "provider": getattr(provider, "name", "?"),
        "model": getattr(provider, "model", "?"),
        "investigation_date": cfg.investigation_date.isoformat(),
        "max_tool_calls": cfg.max_tool_calls,
        "simulated_failing_tools": sorted(cfg.failing_tools) or "none",
    }, printer=printer, on_step=on_step)

    provider.start(
        SYSTEM_PROMPT.format(today=cfg.investigation_date.isoformat(), max_calls=cfg.max_tool_calls),
        request,
        _tool_dicts(executor),
    )

    data_calls = 0
    nudged = False
    report: dict | None = None

    for _turn in range(cfg.max_model_turns):
        try:
            turn = provider.step()
        except Exception as exc:  # API/network errors end the run honestly
            trace.add("stopped", reason=f"model API error: {type(exc).__name__}: {exc}")
            report = system_fallback_report(_guess_order_id(request), f"model API error ({type(exc).__name__})")
            break

        trace.add("model_turn", text=turn.text, stop_reason=turn.stop_reason, usage=turn.usage,
                  tool_requests=[{"id": c.id, "name": c.name, "arguments": c.arguments} for c in turn.tool_calls])

        if turn.refused:
            trace.add("stopped", reason="model refused the request")
            report = system_fallback_report(_guess_order_id(request), "model refused the request")
            break

        if not turn.tool_calls:
            # The model answered in plain text instead of submitting a report. Nudge once.
            if nudged:
                trace.add("stopped", reason="model did not call submit_report after a reminder")
                report = system_fallback_report(_guess_order_id(request), "model did not submit a structured report")
                break
            nudged = True
            msg = "Please finish by calling the submit_report tool with your findings."
            trace.add("nudge", message=msg)
            provider.add_user_message(msg)
            continue

        results: list[ToolResult] = []
        for call in turn.tool_calls:
            if call.name == "submit_report":
                problems = [call.parse_error] if call.parse_error else validate_report(call.arguments)
                if problems:
                    trace.add("report_rejected", problems=problems)
                    results.append(_result(call.id, {"ok": False, "error": {
                        "code": "INVALID_ARGUMENT", "message": "Report rejected: " + "; ".join(problems)}}))
                else:
                    report = call.arguments
                    trace.add("final_report", report=report)
                    results.append(_result(call.id, {"ok": True, "data": {"accepted": True}}))
                continue

            if data_calls >= cfg.max_tool_calls:
                trace.add("limit_reached", limit=cfg.max_tool_calls, tool=call.name)
                results.append(_result(call.id, {"ok": False, "error": {
                    "code": "TOOL_LIMIT_REACHED",
                    "message": f"The limit of {cfg.max_tool_calls} tool calls is reached. "
                               "Call submit_report now with the evidence you have; mark anything "
                               "you could not check as missing."}}))
                continue

            data_calls += 1
            if call.parse_error:
                outcome = {"result": {"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": call.parse_error}},
                           "meta": {"python_function": None, "executed": False, "duration_ms": 0}}
            else:
                outcome = executor.execute(call.name, call.arguments)
            trace.add("tool_execution", tool_call_id=call.id, name=call.name, arguments=call.arguments,
                      meta=outcome["meta"], result=outcome["result"])
            results.append(_result(call.id, outcome["result"]))

        if report is not None:
            break
        provider.add_tool_results(results)
    else:
        trace.add("stopped", reason=f"reached the limit of {cfg.max_model_turns} model turns")
        report = system_fallback_report(_guess_order_id(request), "model turn limit reached")

    trace.report = report
    verification = verify(report, trace, cfg)
    trace.verification = verification
    return InvestigationResult(report=report, trace=trace, verification=verification, tool_calls_used=data_calls)


def _result(call_id: str, envelope: dict) -> ToolResult:
    return ToolResult(call_id=call_id, content=json.dumps(envelope, default=str), is_error=not envelope["ok"])


def _guess_order_id(request: str) -> str | None:
    m = ORDER_ID_IN_TEXT.search(request)
    return m.group(0) if m else None
