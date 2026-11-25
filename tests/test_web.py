"""Web interface: endpoints, streaming, input validation, access code.

Uses the scripted TEST DOUBLE instead of a real model (no API key needed).
"""
import json

import pytest
from fakes import ScriptedProvider, reactive_policy

flask = pytest.importorskip("flask")
from scagent.web import create_app  # noqa: E402


@pytest.fixture()
def client(cfg):
    app = create_app(cfg, provider_factory=lambda c: ScriptedProvider(reactive_policy), access_code="")
    return app.test_client()


def events(resp):
    return [json.loads(line) for line in resp.get_data(as_text=True).splitlines() if line.strip()]


def test_index_and_meta(client):
    assert b"Supply Chain Exception Investigator" in client.get("/").data
    meta = client.get("/api/meta").get_json()
    assert {t["name"] for t in meta["tools"]} == {"get_order_details", "get_shipment_status", "check_inventory",
                                                   "find_alternative_stock", "get_carrier_alerts"}
    assert len(meta["examples"]) == 13 and meta["access_code_required"] is False


def test_investigate_streams_steps_then_report(client):
    resp = client.post("/api/investigate", json={"request": "Investigate why order ORD-1003 is delayed."})
    assert resp.mimetype == "application/x-ndjson"
    evs = events(resp)
    assert evs[0]["event"] == "start" and evs[-1]["event"] == "done"
    tools = [e["step"]["name"] for e in evs if e["event"] == "step" and e["step"]["type"] == "tool_execution"]
    assert tools == ["get_order_details", "get_shipment_status"]
    done = evs[-1]
    assert done["report"]["issue_type"] == "DELAYED_DELIVERY"
    assert done["verification"]["overall"] == "PASS"


def test_simulated_outage_from_ui(client):
    resp = client.post("/api/investigate", json={"request": "Investigate ORD-1003",
                                                 "fail_tools": ["get_shipment_status"]})
    done = events(resp)[-1]
    assert done["report"]["investigation_complete"] is False


@pytest.mark.parametrize("body,msg", [
    ({"request": ""}, "enter a request"),
    ({"request": "x" * 501}, "limited"),
    ({"request": "ORD-1003", "fail_tools": ["drop_tables"]}, "known tool"),
])
def test_input_validation(client, body, msg):
    resp = client.post("/api/investigate", json=body)
    assert resp.status_code == 400 and msg in resp.get_json()["error"]


def test_data_and_truth(client):
    data = client.get("/api/data").get_json()
    assert len(data["orders"]) == 12 and any(s["shipment_id"] == "SHP-5003" for s in data["shipments"])
    assert client.get("/api/truth/ORD-1001").get_json()["issue_type"] == "INSUFFICIENT_INVENTORY"


def test_access_code_enforced(cfg):
    app = create_app(cfg, provider_factory=lambda c: ScriptedProvider(reactive_policy), access_code="s3cret")
    c = app.test_client()
    assert c.get("/").status_code == 200                       # page itself loads
    assert c.get("/api/meta").status_code == 401               # API needs the code
    assert c.get("/api/meta", headers={"X-Access-Code": "wrong"}).status_code == 401
    assert c.get("/api/meta", headers={"X-Access-Code": "s3cret"}).status_code == 200


def test_busy_when_all_slots_taken(cfg):
    import threading
    gate = threading.Event()

    def slow_policy(history, request):
        gate.wait(5)
        return reactive_policy(history, request)

    app = create_app(cfg, provider_factory=lambda c: ScriptedProvider(slow_policy), access_code="", max_concurrent=1)
    c = app.test_client()
    first = c.post("/api/investigate", json={"request": "Investigate ORD-1003"}, buffered=False)
    second = c.post("/api/investigate", json={"request": "Investigate ORD-1005"})
    assert second.status_code == 429
    gate.set()
    first.get_data()  # drain the stream


def test_meta_lists_causes_and_actions(client):
    meta = client.get("/api/meta").get_json()
    assert "LATE_DISPATCH" in meta["causes"] and "TRANSFER_STOCK" in meta["actions"]


def test_evaluation_endpoint(cfg, client):
    assert client.get("/api/evaluation").get_json()["metrics"] is None  # nothing run yet
    path = cfg.trace_dir / "scenarios" / "summary.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"provider": "p", "model": "m", "passed": 1, "total": 1,
                                "metrics": {"scenario_pass_rate": 1.0},
                                "results": [{"scenario": "S1", "passed": True, "checks": [], "scores": {}, "report": {}}]}))
    e = client.get("/api/evaluation").get_json()
    assert e["metrics"]["scenario_pass_rate"] == 1.0 and e["results"][0]["scenario"] == "S1"


def test_order_detail(client):
    d = client.get("/api/order/ORD-1010").get_json()
    assert d["order"]["ship_by_date"] == "2026-03-05"
    assert d["shipments"][0]["events"][-1]["location"] == "Toledo, OH"
    assert d["shipments"][0]["carrier_alerts"][0]["alert_id"] == "ALR-701"
    assert any(s["warehouse_id"] == "WH-CHI" for s in d["items"][0]["stock"])
    assert client.get("/api/order/ORD-9999").status_code == 404


def test_history_and_replay(client):
    done = events(client.post("/api/investigate", json={"request": "Investigate ORD-1003"}))[-1]
    runs = client.get("/api/history").get_json()["runs"]
    assert runs and runs[0]["id"] == done["trace_id"] and runs[0]["order_id"] == "ORD-1003"
    t = client.get("/api/trace", query_string={"id": done["trace_id"]}).get_json()
    assert t["final_report"]["order_id"] == "ORD-1003" and t["steps"] and "rendered" in t


@pytest.mark.parametrize("bad", ["../.env", "../../README.md", "/etc/passwd", "scenarios/summary.json", ""])
def test_trace_endpoint_blocks_path_traversal(client, bad):
    assert client.get("/api/trace", query_string={"id": bad}).status_code == 404
