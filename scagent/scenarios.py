"""Scenario definitions, per-scenario scoring, and accuracy metrics.

A scenario PASSES when all of these hold:
  * the evidence verifier passes (grounding, honesty, database agreement),
  * the issue type, cause category and transfer source are acceptable,
  * every required action group is covered and no action outside "allowed" is proposed,
  * required/forbidden mentions and required tools (in any order) are satisfied.

Across scenarios we also report accuracy metrics, which is how success is measured:
  issue accuracy, cause accuracy, action recall, action precision, evidence-grounding rate,
  and the overall scenario pass rate. No exact wording or fixed tool sequence is required.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .config import PROJECT_ROOT, Config
from .report import action_names
from .verifier import score_actions

SCENARIO_FILE = PROJECT_ROOT / "scenarios" / "scenarios.json"


def load_scenarios(path: Path = SCENARIO_FILE) -> list[dict]:
    return json.loads(Path(path).read_text())["scenarios"]


def scenario_config(base: Config, scenario: dict) -> Config:
    return replace(base, failing_tools=set(scenario.get("fail_tools", [])))


def evaluate_scenario(scenario: dict, report: dict, trace, verification: dict) -> dict:
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    issue_ok = report.get("issue_type") in scenario["acceptable_issue_types"]
    causes = scenario.get("acceptable_causes")
    cause_ok = causes is None or report.get("cause_category") in causes
    actions = action_names(report)
    act = score_actions(actions, scenario["expected_actions"]) if scenario.get("expected_actions") else None

    add("evidence_verifier", verification["overall"] == "PASS", f"verifier overall = {verification['overall']}")
    add("issue_type", issue_ok,
        f"got {report.get('issue_type')}, acceptable {scenario['acceptable_issue_types']}")
    if causes is not None:
        add("cause_category", cause_ok, f"got {report.get('cause_category')}, acceptable {causes}")
    add("transfer_source", report.get("recommended_source_warehouse") in scenario["acceptable_source_warehouses"],
        f"got {report.get('recommended_source_warehouse')}, acceptable {scenario['acceptable_source_warehouses']}")
    if act is not None:
        add("required_actions", not act["missing"],
            f"proposed {actions}; required one of each {scenario['expected_actions']['required_any_of']}"
            + (f"; missing {act['missing']}" if act["missing"] else ""))
        add("no_inappropriate_actions", not act["inappropriate"],
            f"not expected here: {act['inappropriate']}" if act["inappropriate"] else "all proposed actions are appropriate")
    if scenario.get("expect_complete") is not None:
        add("investigation_complete", report.get("investigation_complete") == scenario["expect_complete"],
            f"got {report.get('investigation_complete')}, expected {scenario['expect_complete']}")
    if scenario.get("expect_cause_status"):
        add("cause_status", report.get("cause_status") in scenario["expect_cause_status"],
            f"got {report.get('cause_status')}, acceptable {scenario['expect_cause_status']}")
    if scenario.get("expect_missing_information"):
        add("missing_information_listed", bool(report.get("missing_information")),
            f"missing_information = {report.get('missing_information')}")

    text = json.dumps(report).lower()
    for term in scenario.get("must_mention", []):
        found = term.lower() in text
        add(f"mentions:{term}", found, f"'{term}' {'found' if found else 'NOT found'} in report")
    for term in scenario.get("must_not_mention", []):
        found = term.lower() in text
        add(f"does_not_mention:{term}", not found, f"'{term}' {'appears (possible invention)' if found else 'absent'}")

    used = {e["name"] for e in trace.tool_executions()}
    for tool in scenario.get("required_tools_any_order", []):
        add(f"used_tool:{tool}", tool in used, f"{tool} {'was' if tool in used else 'was NOT'} called")

    return {
        "scenario": scenario["id"],
        "passed": all(c["status"] == "pass" for c in checks),
        "checks": checks,
        "tools_called_in_order": [e["name"] for e in trace.tool_executions()],
        "scores": {
            "issue_correct": issue_ok,
            "cause_correct": cause_ok,
            "action_recall": act["recall"] if act else None,
            "action_precision": act["precision"] if act else None,
            "grounded": verification["overall"] == "PASS",
        },
        "report": {k: report.get(k) for k in ("issue_type", "cause_category", "cause_status",
                                               "recommended_source_warehouse", "investigation_complete")}
                  | {"actions": actions},
    }


def aggregate(results: list[dict]) -> dict:
    """Accuracy metrics over a list of evaluate_scenario() results (any number of runs)."""
    n = len(results)
    if not n:
        return {}

    def mean(key):
        vals = [r["scores"][key] for r in results if r["scores"][key] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "runs": n,
        "scenario_pass_rate": round(sum(r["passed"] for r in results) / n, 3),
        "issue_accuracy": mean("issue_correct"),
        "cause_accuracy": mean("cause_correct"),
        "action_recall": mean("action_recall"),
        "action_precision": mean("action_precision"),
        "evidence_grounding_rate": mean("grounded"),
    }


def format_metrics(m: dict) -> str:
    def pct(v):
        return "n/a" if v is None else f"{v * 100:.0f}%"

    return "\n".join([
        f"  Scenario pass rate        {pct(m['scenario_pass_rate'])}   (all checks passed)",
        f"  Issue identification      {pct(m['issue_accuracy'])}   (correct problem type)",
        f"  Cause accuracy            {pct(m['cause_accuracy'])}   (correct cause category)",
        f"  Action recall             {pct(m['action_recall'])}   (required actions recommended)",
        f"  Action precision          {pct(m['action_precision'])}   (recommended actions that were appropriate)",
        f"  Evidence grounding        {pct(m['evidence_grounding_rate'])}   (verifier PASS: no invented facts)",
        f"  Runs scored               {m['runs']}",
    ])
