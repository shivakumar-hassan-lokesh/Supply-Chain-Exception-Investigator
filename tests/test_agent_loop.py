"""Agent-loop mechanics, using scripted TEST DOUBLES instead of a real model.

These tests check what Python enforces (validation, limits, failure handling,
verification). They do not test the model's judgement; tests/test_live_scenarios.py does.
"""
from dataclasses import replace

import pytest
from fakes import ScriptedProvider, act, reactive_policy, report, tc, turn

from scagent.agent import investigate
from scagent.scenarios import evaluate_scenario, load_scenarios, scenario_config


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda s: s["id"])
def test_reactive_double_passes_every_scenario(cfg, scenario):
    """End to end through loop + executor + verifier + scenario checks."""
    c = scenario_config(cfg, scenario)
    res = investigate(scenario["request"], ScriptedProvider(reactive_policy), c)
    ev = evaluate_scenario(scenario, res.report, res.trace, res.verification)
    assert ev["passed"], ev["checks"]


def test_tool_sequence_depends_on_results(cfg):
    """Different orders lead to different tools: no fixed sequence."""
    shipped = investigate("Investigate ORD-1003", ScriptedProvider(reactive_policy), cfg)
    pending = investigate("Investigate ORD-1001", ScriptedProvider(reactive_policy), cfg)
    assert [e["name"] for e in shipped.trace.tool_executions()] == ["get_order_details", "get_shipment_status"]
    assert "check_inventory" in [e["name"] for e in pending.trace.tool_executions()]
    assert "get_shipment_status" not in [e["name"] for e in pending.trace.tool_executions()]


def test_parallel_tool_calls_in_one_turn(cfg):
    res = investigate("Investigate ORD-1008", ScriptedProvider(reactive_policy), cfg)
    inv_calls = [e for e in res.trace.tool_executions() if e["name"] == "check_inventory"]
    assert {e["arguments"]["sku"] for e in inv_calls} == {"SKU-303", "SKU-606"}
    assert res.report["recommended_source_warehouse"] == "WH-BOS"


def test_invalid_arguments_returned_to_model_then_corrected(cfg):
    def policy(history, request):
        if not history:
            return turn("", tc("get_order_details", {"order_id": "1005"}))
        if len(history) == 1:
            assert history[0][2]["error"]["code"] == "INVALID_ARGUMENT"
            return turn("Fixing the ID format.", tc("get_order_details", {"order_id": "ORD-1005"}))
        if len(history) == 2:
            return turn("", tc("get_shipment_status", {"order_id": "ORD-1005"}))
        return turn("", tc("submit_report", report()))

    res = investigate("Check ORD-1005", ScriptedProvider(policy), cfg)
    first = res.trace.tool_executions()[0]
    assert first["meta"]["executed"] is False and first["result"]["error"]["code"] == "INVALID_ARGUMENT"
    assert res.verification["overall"] == "PASS"


def test_unknown_tool_and_malformed_json(cfg):
    def policy(history, request):
        if not history:
            return turn("", tc("cancel_order", {"order_id": "ORD-1005"}),
                        tc("get_order_details", None, parse_error="Tool arguments were not valid JSON"))
        return turn("", tc("submit_report", report(issue_type="INCONCLUSIVE", cause_status="unknown",
                                                    investigation_complete=False)))

    res = investigate("Check ORD-1005", ScriptedProvider(policy), cfg)
    codes = [e["result"]["error"]["code"] for e in res.trace.tool_executions()]
    assert codes == ["UNKNOWN_TOOL", "INVALID_ARGUMENT"]


def test_max_tool_call_limit_stops_endless_loop(cfg):
    cfg = replace(cfg, max_tool_calls=3, max_model_turns=6)

    def looping(history, request):  # never submits a report
        return turn("Checking again.", tc("get_order_details", {"order_id": "ORD-1003"}))

    res = investigate("Investigate ORD-1003", ScriptedProvider(looping), cfg)
    assert res.tool_calls_used == 3
    assert any(s["type"] == "limit_reached" for s in res.trace.steps)
    assert res.report["generated_by"] == "system"
    assert res.report["investigation_complete"] is False
    assert res.verification["overall"] == "FAIL"


def test_model_submits_after_limit(cfg):
    cfg = replace(cfg, max_tool_calls=1)

    def policy(history, request):
        if not history:
            return turn("", tc("get_order_details", {"order_id": "ORD-1003"}))
        if history[-1][2].get("error", {}).get("code") == "TOOL_LIMIT_REACHED":
            return turn("", tc("submit_report", report(
                order_id="ORD-1003", issue_type="INCONCLUSIVE", cause_category="UNKNOWN", cause_status="unknown",
                recommended_actions=act("CONTACT_CARRIER"),
                missing_information=["shipment status"], investigation_complete=False)))
        return turn("", tc("get_shipment_status", {"order_id": "ORD-1003"}))

    res = investigate("Investigate ORD-1003", ScriptedProvider(policy), cfg)
    assert res.report.get("generated_by") is None
    assert res.verification["overall"] == "PASS"


def test_text_only_answer_gets_one_nudge_then_fallback(cfg):
    p = ScriptedProvider(lambda h, r: turn("I think it's fine."))
    res = investigate("Check ORD-1005", p, cfg)
    assert len(p.user_messages) == 1
    assert res.report["generated_by"] == "system"


def test_invalid_report_rejected_then_fixed(cfg):
    def policy(history, request):
        if not history:
            return turn("", tc("get_order_details", {"order_id": "ORD-9999"}))
        if len(history) == 1:
            return turn("", tc("submit_report", {"order_id": "ORD-9999", "issue_type": "LOST"}))
        return turn("", tc("submit_report", report(order_id="ORD-9999", issue_type="ORDER_NOT_FOUND",
                                                    cause_status="unknown")))

    res = investigate("Investigate ORD-9999", ScriptedProvider(policy), cfg)
    assert any(s["type"] == "report_rejected" for s in res.trace.steps)
    assert res.report["issue_type"] == "ORDER_NOT_FOUND"


def test_api_error_produces_honest_fallback(cfg):
    def boom(history, request):
        raise ConnectionError("network down")

    res = investigate("Investigate ORD-1003", ScriptedProvider(boom), cfg)
    assert res.report["generated_by"] == "system" and res.report["investigation_complete"] is False
    assert res.verification["overall"] == "FAIL"


def test_trace_saved_with_required_fields(cfg):
    res = investigate("Investigate ORD-1003", ScriptedProvider(reactive_policy), cfg)
    json_path, md_path = res.trace.save(cfg.trace_dir, "t")
    import json
    data = json.loads(json_path.read_text())
    ex = [s for s in data["steps"] if s["type"] == "tool_execution"][0]
    assert {"name", "arguments", "meta", "result"} <= ex.keys()
    assert ex["meta"]["python_function"].startswith("scagent.tools.")
    assert data["final_report"] and data["verification"]["overall"] == "PASS"
    assert "Evidence verification" in md_path.read_text()
