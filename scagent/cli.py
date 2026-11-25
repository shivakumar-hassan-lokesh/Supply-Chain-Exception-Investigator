"""Command-line interface.

    python -m scagent init-db
    python -m scagent investigate "Investigate why order ORD-1003 is delayed"
    python -m scagent investigate "..." --fail-tool get_shipment_status
    python -m scagent tool get_order_details '{"order_id": "ORD-1003"}'
    python -m scagent scenarios [--only S1_shortage_with_alternative]
    python -m scagent truth ORD-1003
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from .config import load_config
from .db import init_db


def _cfg(args):
    overrides = {}
    if getattr(args, "max_tool_calls", None):
        overrides["max_tool_calls"] = args.max_tool_calls
    cfg = load_config(**overrides)
    if getattr(args, "fail_tool", None):
        cfg = replace(cfg, failing_tools=cfg.failing_tools | set(args.fail_tool))
    return cfg


def cmd_init_db(args) -> int:
    cfg = load_config()
    path = init_db(cfg.db_path)
    print(f"Database created at {path}")
    return 0


def cmd_tool(args) -> int:
    """Run a single tool directly, without the model (useful for checking facts)."""
    from .executor import ToolExecutor

    cfg = _cfg(args)
    ex = ToolExecutor(cfg.db_path, cfg.investigation_date, cfg.failing_tools)
    try:
        tool_args = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        print(f"arguments must be JSON: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(ex.execute(args.name, tool_args), indent=2, default=str))
    return 0


def cmd_truth(args) -> int:
    """Show what the database says is true for an order (the verifier's reference)."""
    from .verifier import reference_assessment

    cfg = load_config()
    print(json.dumps(reference_assessment(cfg.db_path, args.order_id, cfg.investigation_date), indent=2))
    return 0


def _print_verification(v: dict) -> None:
    print("\nEVIDENCE VERIFICATION (computed by Python from tool results + database)")
    for c in v["checks"]:
        print(f"  [{c['status'].upper():4}] {c['name']}: {c['detail']}")
    print(f"  Overall: {v['overall']}")


def cmd_investigate(args) -> int:
    from .agent import investigate
    from .providers import make_provider
    from .report import render_report

    cfg = _cfg(args)
    provider = make_provider(cfg)
    printer = None if args.quiet else print
    print(f"Provider={cfg.provider} model={cfg.model} date={cfg.investigation_date} "
          f"max_tool_calls={cfg.max_tool_calls} failing_tools={sorted(cfg.failing_tools) or 'none'}\n")
    result = investigate(args.request, provider, cfg, printer=printer)
    print("\n" + render_report(result.report))
    _print_verification(result.verification)
    summary = result.report.get("summary", "")
    if "AuthenticationError" in summary or "authentication method" in summary or "TypeError" in summary:
        print("\nHint: the API key was missing or rejected. Check .env (see .env.example) and LLM_PROVIDER.")
    elif "RateLimitError" in summary:
        print("\nHint: the provider refused for quota/rate reasons (e.g. no credits). Check billing, or wait and retry.")
    elif "API error" in summary:
        print("\nHint: the model API call failed. Check LLM_PROVIDER, LLM_MODEL and network access.")
    if not args.no_save:
        label = (result.report.get("order_id") or "run").replace("/", "_")
        json_path, md_path = result.trace.save(cfg.trace_dir, label)
        print(f"\nTrace saved: {json_path}\n             {md_path}")
    return 0 if result.verification["overall"] == "PASS" else 1


def cmd_scenarios(args) -> int:
    from .agent import investigate
    from .providers import make_provider
    from datetime import datetime

    from .scenarios import aggregate, evaluate_scenario, format_metrics, load_scenarios, scenario_config

    base = _cfg(args)
    scenarios = [s for s in load_scenarios() if not args.only or s["id"] in args.only]
    outcomes = []
    for run in range(1, args.repeat + 1):
        for sc in scenarios:
            cfg = scenario_config(base, sc)
            print(f"\n=== {sc['id']}  (run {run}/{args.repeat}) ===\n"
                  f"Request: {sc['request']}  (failing tools: {sorted(cfg.failing_tools) or 'none'})")
            result = investigate(sc["request"], make_provider(cfg), cfg, printer=None if args.quiet else print)
            ev = evaluate_scenario(sc, result.report, result.trace, result.verification)
            ev["run"] = run
            for c in ev["checks"]:
                print(f"  [{c['status'].upper():4}] {c['name']}: {c['detail']}")
            print(f"  -> {'PASSED' if ev['passed'] else 'FAILED'}  tools: {ev['tools_called_in_order']}")
            result.trace.meta.update(scenario=sc["id"], scenario_passed=ev["passed"], run=run)
            result.trace.save(cfg.trace_dir / "scenarios", f"{sc['id']}_run{run}")
            outcomes.append(ev)

    metrics = aggregate(outcomes)
    passed = sum(o["passed"] for o in outcomes)
    print(f"\nSCENARIO SUMMARY: {passed}/{len(outcomes)} passed  ({base.provider} / {base.model})")
    print(format_metrics(metrics))
    per_scenario = {}
    for o in outcomes:
        per_scenario.setdefault(o["scenario"], []).append(o["passed"])
    summary_path = base.trace_dir / "scenarios" / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({
        "provider": base.provider, "model": base.model, "created": datetime.now().isoformat(timespec="seconds"),
        "repeat": args.repeat, "passed": passed, "total": len(outcomes), "metrics": metrics,
        "pass_count_by_scenario": {k: f"{sum(v)}/{len(v)}" for k, v in per_scenario.items()},
        "results": outcomes,
    }, indent=2))
    print(f"Summary saved: {summary_path}")
    return 0 if passed == len(outcomes) else 1


def cmd_web(args) -> int:
    from .web import run_server

    run_server(args.host, args.port, open_browser=args.open)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scagent", description="Supply Chain Exception Investigation Agent")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create/reset the SQLite database with fictional data").set_defaults(func=cmd_init_db)

    inv = sub.add_parser("investigate", help="run the agent on one request")
    inv.add_argument("request")
    inv.add_argument("--fail-tool", action="append", help="simulate an outage of this tool (repeatable)")
    inv.add_argument("--max-tool-calls", type=int)
    inv.add_argument("--quiet", action="store_true", help="hide step-by-step output")
    inv.add_argument("--no-save", action="store_true", help="do not save a trace file")
    inv.set_defaults(func=cmd_investigate)

    sc = sub.add_parser("scenarios", help="run all evaluation scenarios with the real model")
    sc.add_argument("--only", nargs="*", help="scenario IDs to run")
    sc.add_argument("--max-tool-calls", type=int)
    sc.add_argument("--repeat", type=int, default=1, help="run every scenario N times (reports pass rates)")
    sc.add_argument("--quiet", action="store_true")
    sc.set_defaults(func=cmd_scenarios, fail_tool=None)

    tl = sub.add_parser("tool", help="call one tool directly (no model)")
    tl.add_argument("name")
    tl.add_argument("arguments", help='JSON, e.g. \'{"order_id": "ORD-1003"}\'')
    tl.add_argument("--fail-tool", action="append")
    tl.set_defaults(func=cmd_tool)

    web = sub.add_parser("web", help="start the web interface")
    web.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow other machines on your network")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--open", action="store_true", help="open the page in your browser")
    web.set_defaults(func=cmd_web)

    tr = sub.add_parser("truth", help="show the database reference assessment for an order")
    tr.add_argument("order_id")
    tr.set_defaults(func=cmd_truth)

    args = p.parse_args(argv)
    return args.func(args)
