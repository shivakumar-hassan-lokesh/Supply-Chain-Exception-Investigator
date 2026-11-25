"""Evidence verification: checks the model's report against what actually happened.

The model's claim of success is never trusted on its own. After every
investigation, Python checks the report against:
  (a) the tool results recorded in the trace (did the model see this fact?), and
  (b) an independent query of the database (is the conclusion actually true?).

Each check returns pass / fail / warn / skip. Any "fail" makes the run FAIL.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .db import connect
from .report import action_names

# Matches anything shaped like an identifier (ORD-1003, SKU-202, SHP-5003, GLF-88231, WH-BOS, ALR-701),
# deliberately broad so a mistyped ID such as "SPH-5003" is flagged rather than ignored.
ID_RE = re.compile(r"\b(?:[A-Z]{2,4}-\d{3,6}|WH-[A-Z]{3})\b")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
FACT_FIELDS = ("summary", "evidence", "likely_cause", "uncertainties", "missing_information")
STALLED_AFTER_DAYS = 3


# --------------------------------------------------------------------------- #
# Ground truth computed directly from the database (independent of the agent)
# --------------------------------------------------------------------------- #
def reference_assessment(db_path: Path, order_id: str, today: date) -> dict:
    """What the database says is true about this order: issue, cause, and the
    actions an investigator should (and may) recommend. Plain SQL + simple rules."""
    conn = connect(db_path)
    try:
        ref = _assess(conn, order_id, today)
    finally:
        conn.close()
    ref.setdefault("acceptable_issue_types", [ref["issue_type"]])
    ref.setdefault("acceptable_causes", [ref["cause_category"]])
    ref["expected_actions"] = _expected_actions(ref)
    return ref


def _assess(conn, order_id: str, today: date) -> dict:
    order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if order is None:
        return {"order_id": order_id, "issue_type": "ORDER_NOT_FOUND", "cause_category": "NOT_APPLICABLE",
                "acceptable_causes": ["NOT_APPLICABLE", "UNKNOWN"]}
    promised = date.fromisoformat(order["promised_delivery_date"])
    past_promise = today > promised
    ref = {"order_id": order_id, "fulfillment_status": order["fulfillment_status"], "past_promise": past_promise,
           "short_items": [], "viable_sources": {}}

    if order["fulfillment_status"] == "PENDING_FULFILLMENT":
        items = conn.execute("SELECT sku, quantity FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
        for it in items:
            row = conn.execute("SELECT on_hand - reserved AS available FROM inventory WHERE sku = ? AND warehouse_id = ?",
                               (it["sku"], order["warehouse_id"])).fetchone()
            available = row["available"] if row else 0
            if available < it["quantity"]:
                shortfall = it["quantity"] - available
                ref["short_items"].append({"sku": it["sku"], "required": it["quantity"],
                                           "available": available, "shortfall": shortfall})
                sources = conn.execute("SELECT warehouse_id FROM inventory WHERE sku = ? AND warehouse_id <> ? "
                                       "AND on_hand - reserved >= ?",
                                       (it["sku"], order["warehouse_id"], shortfall)).fetchall()
                ref["viable_sources"][it["sku"]] = [r["warehouse_id"] for r in sources]
        if ref["short_items"]:
            ref["issue_type"], ref["cause_category"] = "INSUFFICIENT_INVENTORY", "STOCK_SHORTAGE"
            if past_promise:
                ref["acceptable_issue_types"] = ["INSUFFICIENT_INVENTORY", "DELAYED_DELIVERY"]
        elif past_promise:
            ref["issue_type"], ref["cause_category"] = "DELAYED_DELIVERY", "LATE_DISPATCH"
        else:
            ref["issue_type"], ref["cause_category"] = "NO_EXCEPTION", "NOT_APPLICABLE"
        return ref

    shipments = conn.execute("SELECT * FROM shipments WHERE order_id = ?", (order_id,)).fetchall()
    if not shipments:
        ref["issue_type"], ref["cause_category"] = "MISSING_DATA", "MISSING_SHIPMENT_RECORD"
        # A shipped order past its promise with no record is also reasonably called delayed.
        if past_promise:
            ref["acceptable_issue_types"] = ["MISSING_DATA", "DELAYED_DELIVERY"]
        return ref

    late = False
    for s in shipments:
        if s["delivered_date"]:
            late |= date.fromisoformat(s["delivered_date"]) > promised
        else:
            late |= past_promise or bool(s["current_estimated_date"]
                                         and date.fromisoformat(s["current_estimated_date"]) > promised)
    if not late:
        ref["issue_type"], ref["cause_category"] = "NO_EXCEPTION", "NOT_APPLICABLE"
        return ref

    ref["issue_type"] = "DELAYED_DELIVERY"
    s = shipments[0]
    last = conn.execute("SELECT event_date, location FROM shipment_events WHERE shipment_id = ? "
                        "ORDER BY event_date DESC, event_id DESC LIMIT 1", (s["shipment_id"],)).fetchone()
    alerts = []
    if last:
        alerts = [r["alert_id"] for r in conn.execute(
            "SELECT alert_id FROM carrier_alerts WHERE carrier = ? AND location = ? "
            "AND start_date <= ? AND end_date >= ?",
            (s["carrier"], last["location"], today.isoformat(), last["event_date"]))]
    ref["matching_alerts"] = alerts
    ref["dispatched_late"] = s["dispatch_date"] > order["ship_by_date"]
    stalled = bool(last) and (today - date.fromisoformat(last["event_date"])).days >= STALLED_AFTER_DAYS
    if s["delay_reason"]:
        ref["cause_category"] = "CARRIER_REPORTED_DELAY"
        ref["acceptable_causes"] = ["CARRIER_REPORTED_DELAY"] + (["CARRIER_SERVICE_DISRUPTION"] if alerts else [])
    elif ref["dispatched_late"]:
        ref["cause_category"] = "LATE_DISPATCH"
    elif alerts:
        ref["cause_category"] = "CARRIER_SERVICE_DISRUPTION"
    elif stalled:
        ref["cause_category"] = "TRACKING_STALLED"
        ref["acceptable_causes"] = ["TRACKING_STALLED", "UNKNOWN"]
    else:
        ref["cause_category"] = "UNKNOWN"
    return ref


def _expected_actions(ref: dict) -> dict:
    """Which actions are required (each inner list: at least one of them) and which are allowed."""
    issue, cause = ref["issue_type"], ref["cause_category"]
    req: list[list[str]] = []
    allowed: set[str] = set()
    if issue == "ORDER_NOT_FOUND":
        req, allowed = [["VERIFY_ORDER_ID"]], {"VERIFY_ORDER_ID"}
    elif issue == "NO_EXCEPTION":
        req, allowed = [["NO_ACTION_NEEDED"]], {"NO_ACTION_NEEDED", "NOTIFY_CUSTOMER"}
    elif cause == "STOCK_SHORTAGE":
        viable = any(ref["viable_sources"].get(i["sku"]) for i in ref["short_items"])
        partial = any(i["available"] > 0 for i in ref["short_items"])
        req = [["TRANSFER_STOCK"]] if viable else [["EXPEDITE_REPLENISHMENT"]]
        allowed = {"EXPEDITE_REPLENISHMENT", "NOTIFY_CUSTOMER"} | ({"TRANSFER_STOCK"} if viable else set()) \
            | ({"SHIP_PARTIAL"} if partial else set())
        if ref.get("past_promise"):
            req.append(["NOTIFY_CUSTOMER"])
    elif cause == "CARRIER_REPORTED_DELAY":
        req, allowed = [["NOTIFY_CUSTOMER"]], {"NOTIFY_CUSTOMER", "CONTACT_CARRIER"}
    elif cause in ("CARRIER_SERVICE_DISRUPTION", "TRACKING_STALLED", "UNKNOWN"):
        req, allowed = [["CONTACT_CARRIER"]], {"CONTACT_CARRIER", "NOTIFY_CUSTOMER"}
    elif cause == "LATE_DISPATCH":
        req, allowed = [["ESCALATE_TO_WAREHOUSE"]], {"ESCALATE_TO_WAREHOUSE", "NOTIFY_CUSTOMER", "CONTACT_CARRIER"}
    elif cause == "MISSING_SHIPMENT_RECORD":
        req, allowed = [["ESCALATE_TO_WAREHOUSE"]], {"ESCALATE_TO_WAREHOUSE", "NOTIFY_CUSTOMER", "CONTACT_CARRIER"}
    return {"required_any_of": req, "allowed": sorted(allowed)}


def score_actions(actions: list[str], expected: dict) -> dict:
    """Recall over required groups, precision over proposed actions."""
    groups = expected["required_any_of"]
    met = [g for g in groups if any(a in g for a in actions)]
    unique = list(dict.fromkeys(actions))
    inappropriate = [a for a in unique if a not in expected["allowed"]]
    return {
        "required_groups": len(groups), "required_met": len(met),
        "missing": [g for g in groups if g not in met],
        "proposed": len(unique), "inappropriate": inappropriate,
        "recall": len(met) / len(groups) if groups else 1.0,
        "precision": (len(unique) - len(inappropriate)) / len(unique) if unique else 0.0,
    }


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def _text(report: dict, fields) -> str:
    parts = []
    for key in fields:
        value = report.get(key)
        parts.extend(value if isinstance(value, list) else [value or ""])
    return "\n".join(str(p) for p in parts)


def _action_text(report: dict) -> str:
    details = [a.get("details", "") for a in report.get("recommended_actions") or [] if isinstance(a, dict)]
    return "\n".join([report.get("recommendation") or "", *details])


def verify(report: dict, trace, cfg) -> dict:
    execs = trace.tool_executions()
    ok_execs = [e for e in execs if e["result"]["ok"]]
    seen_text = json.dumps([e["result"]["data"] for e in ok_execs], default=str)
    error_text = json.dumps([e["result"]["error"] for e in execs if not e["result"]["ok"]], default=str)
    checks: list[dict] = []
    order_id = report.get("order_id", "")
    issue = report.get("issue_type")
    complete = report.get("investigation_complete")
    today = cfg.investigation_date.isoformat()

    # 1. Did the model (rather than the fallback) produce the report?
    if report.get("generated_by") == "system":
        checks.append(_check("model_submitted_report", "fail", "loop ended without a valid model report"))
    else:
        checks.append(_check("model_submitted_report", "pass", "report submitted via submit_report"))

    # 2. The investigated order was actually looked up.
    looked_up = [e for e in execs if e["name"] == "get_order_details"
                 and isinstance(e["arguments"], dict) and e["arguments"].get("order_id") == order_id]
    if any(e["result"]["ok"] for e in looked_up):
        checks.append(_check("order_looked_up", "pass", f"get_order_details succeeded for {order_id}"))
    elif looked_up:
        checks.append(_check("order_looked_up", "pass", f"get_order_details was called for {order_id} and returned an error"))
    else:
        checks.append(_check("order_looked_up", "fail", f"no get_order_details call for {order_id}"))

    # 3. Every ID mentioned anywhere in the report appeared in a successful tool result (or the request).
    all_text = _text(report, FACT_FIELDS) + "\n" + _action_text(report)
    allowed_ids = set(ID_RE.findall(seen_text)) | set(ID_RE.findall(trace.request))
    unsupported_ids = sorted(set(ID_RE.findall(all_text)) - allowed_ids)
    checks.append(_check("ids_grounded", "fail" if unsupported_ids else "pass",
                         f"IDs not found in any tool result: {unsupported_ids}" if unsupported_ids
                         else "all IDs in the report appear in tool results"))

    # 4. Dates stated as facts must come from tool results. In recommendations, future dates are
    #    proposed deadlines ("follow up by ..."), so only past dates there need grounding.
    allowed_dates = set(DATE_RE.findall(seen_text)) | {today}
    bad_fact_dates = set(DATE_RE.findall(_text(report, FACT_FIELDS))) - allowed_dates
    bad_action_dates = {d for d in DATE_RE.findall(_action_text(report)) if d not in allowed_dates and d < today}
    unsupported_dates = sorted(bad_fact_dates | bad_action_dates)
    checks.append(_check("dates_grounded", "fail" if unsupported_dates else "pass",
                         f"dates not found in any tool result: {unsupported_dates}" if unsupported_dates
                         else "all factual dates in the report appear in tool results"))

    # 5. The claimed issue type is supported by evidence the model actually received.
    checks.append(_issue_supported(issue, order_id, execs, ok_execs, cfg))

    # 6. The claimed cause category is supported by evidence the model actually received.
    checks.append(_cause_supported(report.get("cause_category"), execs, ok_execs))

    # 7. A transfer recommendation is backed by both tool results and the database.
    checks.append(_transfer_supported(report.get("recommended_source_warehouse"), order_id, ok_execs, cfg))

    # 8. Every recommended action has the evidence it depends on.
    checks.append(_actions_supported(report, execs, ok_execs))

    # 9. Honesty after failures: no "complete" claim if a tool failed and was never recovered.
    unrecovered = _unrecovered_failures(execs)
    limit_hit = any(s["type"] == "limit_reached" for s in trace.steps)
    if (unrecovered or limit_hit) and complete:
        checks.append(_check("failure_honesty", "fail",
                             f"report claims investigation_complete=true despite {unrecovered or 'tool-call limit'}"))
    elif unrecovered or limit_hit:
        checks.append(_check("failure_honesty", "pass", "failure acknowledged (investigation_complete=false)"))
    else:
        checks.append(_check("failure_honesty", "skip", "no tool failures in this run"))

    # 10-12. Compare issue, cause and actions with the database's own answer.
    ref = None
    try:
        if order_id.startswith("ORD-"):
            ref = reference_assessment(cfg.db_path, order_id, cfg.investigation_date)
    except Exception as exc:  # e.g. DB missing
        checks.append(_check("matches_database", "skip", f"could not compute reference: {exc}"))
    if ref is not None:
        if complete:
            ok = issue in ref["acceptable_issue_types"]
            checks.append(_check("matches_database", "pass" if ok else "fail",
                                 f"database says {'/'.join(ref['acceptable_issue_types'])}, report says {issue}"))
            cause = report.get("cause_category")
            ok = cause in ref["acceptable_causes"]
            checks.append(_check("cause_matches_database", "pass" if ok else "fail",
                                 f"database says {'/'.join(ref['acceptable_causes'])}, report says {cause}"))
            sc = score_actions(action_names(report), ref["expected_actions"])
            good = not sc["missing"] and not sc["inappropriate"]
            detail = f"required met {sc['required_met']}/{sc['required_groups']}"
            if sc["missing"]:
                detail += f"; missing one of {sc['missing']}"
            if sc["inappropriate"]:
                detail += f"; not expected for this case: {sc['inappropriate']}"
            # Appropriateness is a quality score, not a grounding failure: warn instead of fail.
            checks.append(_check("actions_appropriate", "pass" if good else "warn", detail))
        else:
            checks.append(_check("matches_database", "skip",
                                 f"report is marked incomplete; database says {ref['issue_type']} "
                                 f"({ref['cause_category']}), report says {issue} ({report.get('cause_category')})"))

    overall = "FAIL" if any(c["status"] == "fail" for c in checks) else "PASS"
    return {"overall": overall, "checks": checks, "reference": ref, "tool_errors_seen": error_text}


def _results(ok_execs, tool):
    return [e["result"]["data"] for e in ok_execs if e["name"] == tool]


def _shortages_seen(ok_execs) -> list[dict]:
    quantities = {}
    for od in _results(ok_execs, "get_order_details"):
        quantities.update({i["sku"]: i["quantity"] for i in od["items"]})
    return [inv for inv in _results(ok_execs, "check_inventory")
            if inv["sku"] in quantities and inv["available"] < quantities[inv["sku"]]]


def _error_seen(execs, tool, code) -> bool:
    return any(e["name"] == tool and not e["result"]["ok"] and e["result"]["error"]["code"] == code for e in execs)


def _issue_supported(issue, order_id, execs, ok_execs, cfg) -> dict:
    name = "issue_supported_by_evidence"

    if issue == "INSUFFICIENT_INVENTORY":
        short = _shortages_seen(ok_execs)
        if short:
            return _check(name, "pass", "check_inventory showed available < ordered for "
                          + ", ".join(f"{s['sku']}@{s['warehouse_id']} ({s['available']})" for s in short))
        return _check(name, "fail", "no check_inventory result showed stock below an ordered quantity")

    if issue == "DELAYED_DELIVERY":
        overdue = any(s["is_overdue"] or s["eta_after_promised_date"]
                      for r in _results(ok_execs, "get_shipment_status") for s in r["shipments"])
        past_promise = any(od["is_past_promised_date"] and od["fulfillment_status"] != "DELIVERED"
                           for od in _results(ok_execs, "get_order_details"))
        if overdue:
            return _check(name, "pass", "get_shipment_status showed the shipment overdue / ETA after promise")
        if past_promise:
            return _check(name, "warn", "only the order's promised date shows lateness; no shipment data confirms it")
        return _check(name, "fail", "no tool result shows the order is late")

    if issue == "NO_EXCEPTION":
        ods = _results(ok_execs, "get_order_details")
        if not ods:
            return _check(name, "fail", "NO_EXCEPTION claimed without a successful order lookup")
        od = ods[-1]
        if od["fulfillment_status"] in ("SHIPPED", "DELIVERED") and not _results(ok_execs, "get_shipment_status"):
            return _check(name, "fail", "shipped order judged fine without checking shipment status")
        if od["fulfillment_status"] == "PENDING_FULFILLMENT":
            checked = {r["sku"] for r in _results(ok_execs, "check_inventory")
                       if r["warehouse_id"] == od["fulfillment_warehouse_id"]}
            missing = [i["sku"] for i in od["items"] if i["sku"] not in checked]
            if missing:
                return _check(name, "fail", f"pending order judged fine without checking inventory for {missing}")
        return _check(name, "pass", "order and the relevant shipment/inventory data were checked")

    if issue == "ORDER_NOT_FOUND":
        nf = _error_seen(execs, "get_order_details", "NOT_FOUND")
        return _check(name, "pass" if nf else "fail",
                      "get_order_details returned NOT_FOUND" if nf else "no NOT_FOUND result supports this")

    if issue in ("MISSING_DATA", "INCONCLUSIVE"):
        problems = [e for e in execs if not e["result"]["ok"]]
        if problems:
            return _check(name, "pass", "tool errors recorded: " + ", ".join(
                f"{e['name']}:{e['result']['error']['code']}" for e in problems))
        return _check(name, "warn", f"{issue} claimed but no tool returned an error")

    return _check(name, "fail", f"unknown issue_type {issue!r}")


def _cause_supported(cause, execs, ok_execs) -> dict:
    name = "cause_supported_by_evidence"
    shipments = [s for r in _results(ok_execs, "get_shipment_status") for s in r["shipments"]]
    if cause == "CARRIER_REPORTED_DELAY":
        ok = any(s["recorded_delay_reason"] for s in shipments)
        return _check(name, "pass" if ok else "fail",
                      "shipment record contains a carrier delay reason" if ok
                      else "no shipment result the model saw contains a recorded delay reason")
    if cause == "CARRIER_SERVICE_DISRUPTION":
        held_at = {(s["carrier"], s["last_event_location"]) for s in shipments}
        matching = [a["alert_id"] for r in _results(ok_execs, "get_carrier_alerts") for a in r["alerts"]
                    if (r["carrier"], a["location"]) in held_at]
        if matching:
            return _check(name, "pass", f"carrier alert(s) {matching} match where the shipment was last scanned")
        any_alert = any(r["alerts"] for r in _results(ok_execs, "get_carrier_alerts"))
        return _check(name, "fail", "an alert was seen but not for the shipment's carrier and location" if any_alert
                      else "no carrier alert was retrieved to support a service disruption")
    if cause == "TRACKING_STALLED":
        ok = any((s["days_since_last_event"] or 0) >= STALLED_AFTER_DAYS and not s["is_delivered"] for s in shipments)
        return _check(name, "pass" if ok else "fail",
                      f"tracking shows no movement for {STALLED_AFTER_DAYS}+ days" if ok
                      else "no shipment result shows stalled tracking")
    if cause == "LATE_DISPATCH":
        late = any(s["dispatched_late"] for s in shipments) or any(
            od.get("is_past_ship_by_date") for od in _results(ok_execs, "get_order_details"))
        return _check(name, "pass" if late else "fail",
                      "dispatch happened after the ship-by date" if late
                      else "no tool result shows a dispatch after the ship-by date")
    if cause == "STOCK_SHORTAGE":
        ok = bool(_shortages_seen(ok_execs))
        return _check(name, "pass" if ok else "fail",
                      "check_inventory showed a shortage" if ok else "no check_inventory result showed a shortage")
    if cause == "MISSING_SHIPMENT_RECORD":
        ok = _error_seen(execs, "get_shipment_status", "NOT_FOUND")
        return _check(name, "pass" if ok else "fail",
                      "get_shipment_status returned NOT_FOUND" if ok else "no NOT_FOUND shipment result supports this")
    if cause in ("UNKNOWN", "NOT_APPLICABLE"):
        return _check(name, "skip", f"cause reported as {cause}")
    return _check(name, "fail", f"unknown cause_category {cause!r}")


def _actions_supported(report, execs, ok_execs) -> dict:
    name = "actions_supported_by_evidence"
    problems = []
    shortages = _shortages_seen(ok_execs)
    for a in action_names(report):
        if a == "TRANSFER_STOCK" and not report.get("recommended_source_warehouse"):
            problems.append("TRANSFER_STOCK without a supported recommended_source_warehouse")
        elif a in ("EXPEDITE_REPLENISHMENT", "SHIP_PARTIAL") and not shortages:
            problems.append(f"{a} but no shortage was seen")
        elif a == "SHIP_PARTIAL" and not any(s["available"] > 0 for s in shortages):
            problems.append("SHIP_PARTIAL but no units are available to ship")
        elif a == "VERIFY_ORDER_ID" and not _error_seen(execs, "get_order_details", "NOT_FOUND"):
            problems.append("VERIFY_ORDER_ID but the order was found")
        elif a == "RETRY_LATER" and not any(not e["result"]["ok"] and e["result"]["error"]["code"] == "TOOL_FAILURE"
                                            for e in execs):
            problems.append("RETRY_LATER but no tool failed")
        elif a == "NO_ACTION_NEEDED" and report.get("issue_type") != "NO_EXCEPTION":
            problems.append(f"NO_ACTION_NEEDED for an order with issue {report.get('issue_type')}")
    if problems:
        return _check(name, "fail", "; ".join(problems))
    return _check(name, "pass", f"{len(action_names(report))} action(s), each with the evidence it needs")


def _transfer_supported(source, order_id, ok_execs, cfg) -> dict:
    name = "transfer_recommendation_supported"
    if not source:
        return _check(name, "skip", "no transfer recommended")
    in_tool = any(source in r["result"]["data"].get("warehouses_with_sufficient_stock", [])
                  for r in ok_execs if r["name"] == "find_alternative_stock")
    if not in_tool:
        return _check(name, "fail", f"{source} was not reported as sufficient by any find_alternative_stock call")
    try:
        ref = reference_assessment(cfg.db_path, order_id, cfg.investigation_date)
    except Exception as exc:
        return _check(name, "warn", f"tool support found, but DB check failed: {exc}")
    viable = {wh for whs in ref.get("viable_sources", {}).values() for wh in whs}
    if source in viable:
        return _check(name, "pass", f"{source} has enough available stock to cover the shortfall (database confirmed)")
    return _check(name, "fail", f"database shows {source} cannot cover the shortfall")


def _unrecovered_failures(execs) -> list[str]:
    """Tool calls that failed (TOOL_FAILURE) with no later success for the same tool + arguments."""
    out = []
    for i, e in enumerate(execs):
        if not e["result"]["ok"] and e["result"]["error"]["code"] == "TOOL_FAILURE":
            later_ok = any(x["name"] == e["name"] and x["arguments"] == e["arguments"] and x["result"]["ok"]
                           for x in execs[i + 1:])
            if not later_ok:
                out.append(f"{e['name']}({json.dumps(e['arguments'])})")
    return out
