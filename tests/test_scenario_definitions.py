"""The scenario expectations themselves are checked against the database,
so a wrong expectation can't make a wrong answer look right."""
from scagent.scenarios import load_scenarios
from scagent.verifier import reference_assessment

SCENARIOS = load_scenarios()


def test_required_scenarios_1_to_5_present():
    assert {s["required_scenario"] for s in SCENARIOS} >= {1, 2, 3, 4, 5}


def test_expectations_consistent_with_database(db_path, cfg):
    for s in SCENARIOS:
        ref = reference_assessment(db_path, s["order_id"], cfg.investigation_date)
        if not s.get("fail_tools"):
            assert ref["issue_type"] in s["acceptable_issue_types"], s["id"]
        viable = {wh for whs in ref.get("viable_sources", {}).values() for wh in whs}
        for src in s["acceptable_source_warehouses"]:
            assert src is None or src in viable, (s["id"], src)
        if viable and len(ref.get("short_items", [])) == 1:
            # A shortage that CAN be covered expects that warehouse to be recommended.
            assert set(s["acceptable_source_warehouses"]) == viable, s["id"]


def test_cause_and_action_expectations_match_database(db_path, cfg):
    """For scenarios without a simulated failure, expectations must equal the database reference."""
    for s in SCENARIOS:
        if s.get("fail_tools"):
            continue
        ref = reference_assessment(db_path, s["order_id"], cfg.investigation_date)
        assert ref["cause_category"] in s["acceptable_causes"], s["id"]
        assert set(s["acceptable_causes"]) <= set(ref["acceptable_causes"]), s["id"]
        assert s["expected_actions"]["required_any_of"] == ref["expected_actions"]["required_any_of"], s["id"]
        assert sorted(s["expected_actions"]["allowed"]) == ref["expected_actions"]["allowed"], s["id"]


def test_delay_cause_scenarios_present():
    causes = {c for s in SCENARIOS for c in s["acceptable_causes"]}
    assert {"CARRIER_REPORTED_DELAY", "CARRIER_SERVICE_DISRUPTION", "TRACKING_STALLED", "LATE_DISPATCH",
            "STOCK_SHORTAGE", "MISSING_SHIPMENT_RECORD"} <= causes


def test_metrics_aggregation():
    from scagent.scenarios import aggregate
    rows = [
        {"passed": True, "scores": {"issue_correct": True, "cause_correct": True, "action_recall": 1.0,
                                    "action_precision": 1.0, "grounded": True}},
        {"passed": False, "scores": {"issue_correct": True, "cause_correct": False, "action_recall": 0.5,
                                     "action_precision": 0.5, "grounded": False}},
    ]
    m = aggregate(rows)
    assert m == {"runs": 2, "scenario_pass_rate": 0.5, "issue_accuracy": 1.0, "cause_accuracy": 0.5,
                 "action_recall": 0.75, "action_precision": 0.75, "evidence_grounding_rate": 0.5}
