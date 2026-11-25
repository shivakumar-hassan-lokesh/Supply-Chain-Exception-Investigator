"""Validation and error envelopes: invalid requests are rejected before execution."""
from pathlib import Path

from conftest import TODAY
from scagent.executor import ToolExecutor


def ex(db_path, failing=()):
    return ToolExecutor(db_path, TODAY, set(failing))


def test_success_envelope(db_path):
    out = ex(db_path).execute("get_order_details", {"order_id": "ORD-1003"})
    assert out["result"]["ok"] is True
    assert out["meta"]["python_function"] == "scagent.tools.get_order_details"
    assert out["meta"]["executed"] is True


def test_unknown_tool(db_path):
    out = ex(db_path).execute("cancel_order", {"order_id": "ORD-1003"})
    assert out["result"]["error"]["code"] == "UNKNOWN_TOOL"
    assert out["meta"]["executed"] is False


def test_missing_and_extra_arguments(db_path):
    out = ex(db_path).execute("check_inventory", {"sku": "SKU-202", "warehouse": "WH-BOS"})
    msg = out["result"]["error"]["message"]
    assert out["result"]["error"]["code"] == "INVALID_ARGUMENT"
    assert "missing required argument 'warehouse_id'" in msg and "unexpected argument 'warehouse'" in msg
    assert out["meta"]["executed"] is False


def test_bad_formats(db_path):
    for name, args in [
        ("get_order_details", {"order_id": "1003"}),
        ("get_order_details", {"order_id": 1003}),
        ("check_inventory", {"sku": "sku-202", "warehouse_id": "WH-BOS"}),
        ("find_alternative_stock", {"sku": "SKU-202", "required_quantity": 0}),
        ("find_alternative_stock", {"sku": "SKU-202", "required_quantity": "50"}),
        ("find_alternative_stock", {"sku": "SKU-202", "required_quantity": True}),
        ("get_order_details", "ORD-1003"),
    ]:
        out = ex(db_path).execute(name, args)
        assert out["result"]["error"]["code"] == "INVALID_ARGUMENT", (name, args)


def test_not_found(db_path):
    out = ex(db_path).execute("get_order_details", {"order_id": "ORD-9999"})
    assert out["result"]["error"]["code"] == "NOT_FOUND"


def test_simulated_tool_failure(db_path):
    out = ex(db_path, ["get_shipment_status"]).execute("get_shipment_status", {"order_id": "ORD-1003"})
    assert out["result"]["ok"] is False and out["result"]["error"]["code"] == "TOOL_FAILURE"
    assert "data" not in out["result"]


def test_real_failure_missing_database(tmp_path):
    out = ToolExecutor(Path(tmp_path / "nope.db"), TODAY).execute("get_order_details", {"order_id": "ORD-1001"})
    assert out["result"]["error"]["code"] == "TOOL_FAILURE"


def test_carrier_argument_validation(db_path):
    for bad in ["", "x", "Great Lakes'; DROP TABLE shipments;--", "A" * 80, 42]:
        out = ex(db_path).execute("get_carrier_alerts", {"carrier": bad})
        assert out["result"]["error"]["code"] == "INVALID_ARGUMENT", bad
    ok = ex(db_path).execute("get_carrier_alerts", {"carrier": "Great Lakes Freight", "location": "Toledo, OH"})
    assert ok["result"]["ok"] and ok["result"]["data"]["alert_count"] == 1
