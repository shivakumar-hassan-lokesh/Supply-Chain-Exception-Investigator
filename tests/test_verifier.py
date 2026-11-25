"""The verifier must catch reports that are not supported by evidence."""
import copy
from dataclasses import replace

from fakes import ScriptedProvider, reactive_policy

from scagent.agent import investigate
from scagent.verifier import reference_assessment, verify


def run(cfg, request):
    return investigate(request, ScriptedProvider(reactive_policy), cfg)


def status_of(v, name):
    return next(c["status"] for c in v["checks"] if c["name"] == name)


def test_honest_report_passes(cfg):
    assert run(cfg, "Investigate why ORD-1003 is delayed").verification["overall"] == "PASS"


def test_invented_date_is_caught(cfg):
    res = run(cfg, "Investigate why ORD-1003 is delayed")
    bad = copy.deepcopy(res.report)
    bad["evidence"].append("Carrier promised delivery on 2026-03-21")
    v = verify(bad, res.trace, cfg)
    assert status_of(v, "dates_grounded") == "fail" and v["overall"] == "FAIL"


def test_invented_shipment_id_is_caught(cfg):
    res = run(cfg, "Investigate why ORD-1003 is delayed")
    bad = copy.deepcopy(res.report)
    bad["summary"] = "Shipment SHP-7777 was lost."
    assert status_of(verify(bad, res.trace, cfg), "ids_grounded") == "fail"


def test_mistyped_id_is_caught(cfg):
    """Regression: a real qwen3:8b run wrote 'SPH-5003' instead of 'SHP-5003'."""
    res = run(cfg, "Investigate why ORD-1003 is delayed")
    bad = copy.deepcopy(res.report)
    bad["evidence"].append("get_shipment_status: SPH-5003 status DELAYED")
    assert status_of(verify(bad, res.trace, cfg), "ids_grounded") == "fail"


def test_unsupported_transfer_is_caught(cfg):
    res = run(cfg, "Why hasn't ORD-1002 been fulfilled?")  # no single source exists
    bad = copy.deepcopy(res.report)
    bad["recommended_source_warehouse"] = "WH-BOS"
    assert status_of(verify(bad, res.trace, cfg), "transfer_recommendation_supported") == "fail"


def test_claiming_success_after_tool_failure_is_caught(cfg):
    c = replace(cfg, failing_tools={"get_shipment_status"})
    res = run(c, "Investigate why ORD-1003 is delayed")
    assert res.report["investigation_complete"] is False
    bad = copy.deepcopy(res.report)
    bad["investigation_complete"] = True
    assert status_of(verify(bad, res.trace, c), "failure_honesty") == "fail"


def test_invented_problem_is_caught(cfg):
    res = run(cfg, "Check ORD-1005")  # really NO_EXCEPTION
    bad = copy.deepcopy(res.report)
    bad["issue_type"] = "DELAYED_DELIVERY"
    v = verify(bad, res.trace, cfg)
    assert status_of(v, "issue_supported_by_evidence") == "fail"
    assert status_of(v, "matches_database") == "fail"


def test_no_exception_without_checking_shipment_is_caught(cfg):
    res = run(cfg, "Check ORD-1005")
    trace = copy.deepcopy(res.trace)
    trace.steps = [s for s in trace.steps
                   if not (s["type"] == "tool_execution" and s["name"] == "get_shipment_status")]
    assert status_of(verify(res.report, trace, cfg), "issue_supported_by_evidence") == "fail"


def test_reference_assessment_matches_data_design(db_path, cfg):
    expected = {
        "ORD-1001": "INSUFFICIENT_INVENTORY", "ORD-1002": "INSUFFICIENT_INVENTORY",
        "ORD-1003": "DELAYED_DELIVERY", "ORD-1004": "DELAYED_DELIVERY", "ORD-1005": "NO_EXCEPTION",
        "ORD-1006": "NO_EXCEPTION", "ORD-1007": "MISSING_DATA", "ORD-1008": "INSUFFICIENT_INVENTORY",
        "ORD-1009": "NO_EXCEPTION", "ORD-1010": "DELAYED_DELIVERY", "ORD-1011": "DELAYED_DELIVERY",
        "ORD-1012": "INSUFFICIENT_INVENTORY", "ORD-9999": "ORDER_NOT_FOUND",
    }
    for oid, issue in expected.items():
        assert reference_assessment(db_path, oid, cfg.investigation_date)["issue_type"] == issue, oid


# ---- cause and action checks ------------------------------------------------
def test_disruption_cause_without_checking_alerts_is_caught(cfg):
    res = run(cfg, "Investigate why ORD-1004 is late")  # stalled, no alert exists
    bad = copy.deepcopy(res.report)
    bad["cause_category"] = "CARRIER_SERVICE_DISRUPTION"
    v = verify(bad, res.trace, cfg)
    assert status_of(v, "cause_supported_by_evidence") == "fail"
    assert status_of(v, "cause_matches_database") == "fail"


def test_disruption_found_through_alerts(cfg):
    res = run(cfg, "Why is ORD-1010 late?")
    assert "get_carrier_alerts" in [e["name"] for e in res.trace.tool_executions()]
    assert res.report["cause_category"] == "CARRIER_SERVICE_DISRUPTION"
    assert status_of(res.verification, "cause_supported_by_evidence") == "pass"


def test_wrong_cause_is_caught(cfg):
    res = run(cfg, "Investigate the delay on ORD-1011")  # really a late dispatch
    bad = copy.deepcopy(res.report)
    bad["cause_category"] = "CARRIER_REPORTED_DELAY"
    v = verify(bad, res.trace, cfg)
    assert status_of(v, "cause_supported_by_evidence") == "fail"
    assert status_of(v, "cause_matches_database") == "fail"


def test_action_without_evidence_is_caught(cfg):
    res = run(cfg, "Investigate why ORD-1003 is delayed")
    for action in ("TRANSFER_STOCK", "VERIFY_ORDER_ID", "RETRY_LATER", "EXPEDITE_REPLENISHMENT", "NO_ACTION_NEEDED"):
        bad = copy.deepcopy(res.report)
        bad["recommended_actions"] = [{"action": action, "details": "x"}]
        assert status_of(verify(bad, res.trace, cfg), "actions_supported_by_evidence") == "fail", action


def test_inappropriate_action_is_flagged(cfg):
    res = run(cfg, "Check ORD-1005")  # no exception
    bad = copy.deepcopy(res.report)
    bad["recommended_actions"].append({"action": "ESCALATE_TO_WAREHOUSE", "details": "x"})
    assert status_of(verify(bad, res.trace, cfg), "actions_appropriate") == "warn"


def test_future_follow_up_date_allowed_but_past_invented_date_caught(cfg):
    res = run(cfg, "Investigate why ORD-1003 is delayed")
    ok = copy.deepcopy(res.report)
    ok["recommended_actions"][0]["details"] = "Follow up with the customer by 2026-03-17."
    assert status_of(verify(ok, res.trace, cfg), "dates_grounded") == "pass"
    bad = copy.deepcopy(res.report)
    bad["recommended_actions"][0]["details"] = "Carrier promised delivery on 2026-03-11."
    assert status_of(verify(bad, res.trace, cfg), "dates_grounded") == "fail"


def test_reference_causes_and_actions(db_path, cfg):
    expected = {
        "ORD-1003": ("CARRIER_REPORTED_DELAY", [["NOTIFY_CUSTOMER"]]),
        "ORD-1004": ("TRACKING_STALLED", [["CONTACT_CARRIER"]]),
        "ORD-1007": ("MISSING_SHIPMENT_RECORD", [["ESCALATE_TO_WAREHOUSE"]]),
        "ORD-1010": ("CARRIER_SERVICE_DISRUPTION", [["CONTACT_CARRIER"]]),
        "ORD-1011": ("LATE_DISPATCH", [["ESCALATE_TO_WAREHOUSE"]]),
        "ORD-1012": ("STOCK_SHORTAGE", [["TRANSFER_STOCK"], ["NOTIFY_CUSTOMER"]]),
        "ORD-1002": ("STOCK_SHORTAGE", [["EXPEDITE_REPLENISHMENT"]]),
    }
    for oid, (cause, req) in expected.items():
        ref = reference_assessment(db_path, oid, cfg.investigation_date)
        assert ref["cause_category"] == cause, oid
        assert ref["expected_actions"]["required_any_of"] == req, oid
