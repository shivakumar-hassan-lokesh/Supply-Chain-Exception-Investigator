"""Tool functions return correct facts from the database and clear errors."""
import pytest

from conftest import TODAY
from scagent import tools


def test_order_details_basic(conn):
    d = tools.get_order_details(conn, TODAY, "ORD-1001")
    assert d["fulfillment_warehouse_id"] == "WH-BOS"
    assert d["fulfillment_status"] == "PENDING_FULFILLMENT"
    assert d["items"] == [{"sku": "SKU-202", "product_name": "Industrial Shelf Bracket", "quantity": 50}]
    assert d["days_until_promised_date"] == 3 and d["is_past_promised_date"] is False


def test_order_details_multi_item(conn):
    skus = {i["sku"]: i["quantity"] for i in tools.get_order_details(conn, TODAY, "ORD-1008")["items"]}
    assert skus == {"SKU-303": 30, "SKU-606": 100}


def test_order_not_found(conn):
    with pytest.raises(tools.NotFound):
        tools.get_order_details(conn, TODAY, "ORD-9999")


def test_shipment_documented_delay(conn):
    s = tools.get_shipment_status(conn, TODAY, "ORD-1003")["shipments"][0]
    assert s["shipment_id"] == "SHP-5003" and s["status"] == "DELAYED"
    assert "winter storm" in s["recorded_delay_reason"]
    assert s["current_estimated_delivery_date"] == "2026-03-18"
    assert s["is_overdue"] is True and s["days_past_promised_date"] == 7
    assert s["eta_after_promised_date"] is True


def test_shipment_overdue_without_reason(conn):
    s = tools.get_shipment_status(conn, TODAY, "ORD-1004")["shipments"][0]
    assert s["recorded_delay_reason"] is None and s["current_estimated_delivery_date"] is None
    assert s["is_overdue"] is True and s["days_since_last_event"] == 9


def test_shipment_on_time(conn):
    s = tools.get_shipment_status(conn, TODAY, "ORD-1005")["shipments"][0]
    assert s["is_overdue"] is False and s["eta_after_promised_date"] is False


def test_shipment_delivered_on_time(conn):
    s = tools.get_shipment_status(conn, TODAY, "ORD-1006")["shipments"][0]
    assert s["is_delivered"] and not s["is_overdue"]


def test_shipment_missing_record(conn):
    with pytest.raises(tools.NotFound, match="no shipment record"):
        tools.get_shipment_status(conn, TODAY, "ORD-1007")


def test_check_inventory(conn):
    inv = tools.check_inventory(conn, TODAY, "SKU-202", "WH-CHI")
    assert (inv["on_hand"], inv["reserved"], inv["available"]) == (95, 15, 80)


def test_check_inventory_unknown_sku_and_warehouse(conn):
    with pytest.raises(tools.NotFound):
        tools.check_inventory(conn, TODAY, "SKU-999", "WH-BOS")
    with pytest.raises(tools.NotFound):
        tools.check_inventory(conn, TODAY, "SKU-202", "WH-XYZ")


def test_find_alternative_stock_single_source(conn):
    r = tools.find_alternative_stock(conn, TODAY, "SKU-202", 38, "WH-BOS")
    assert r["warehouses_with_sufficient_stock"] == ["WH-CHI"]
    assert all(w["warehouse_id"] != "WH-BOS" for w in r["warehouses_checked"])


def test_find_alternative_stock_none_sufficient(conn):
    r = tools.find_alternative_stock(conn, TODAY, "SKU-404", 22, "WH-ATL")
    assert r["warehouses_with_sufficient_stock"] == []
    assert r["total_available_in_checked_warehouses"] == 19


def test_tools_use_parameterized_sql_injection_is_harmless(conn):
    # Even if validation were bypassed, a quote in the ID cannot change the query.
    with pytest.raises(tools.NotFound):
        tools.get_order_details(conn, TODAY, "ORD-1001' OR '1'='1")


def test_tool_connection_is_read_only(conn):
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM orders")


# ---- delay-cause data -------------------------------------------------------
def test_carrier_alerts_for_carrier(conn):
    r = tools.get_carrier_alerts(conn, TODAY, "Great Lakes Freight")
    assert [a["alert_id"] for a in r["alerts"]] == ["ALR-701"]
    assert r["alerts"][0]["location"] == "Toledo, OH"
    assert r["alerts"][0]["active_on_investigation_date"] is False  # ended 2026-03-13


def test_carrier_alerts_location_filter_and_none(conn):
    assert tools.get_carrier_alerts(conn, TODAY, "Great Lakes Freight", "Chicago, IL")["alert_count"] == 0
    assert tools.get_carrier_alerts(conn, TODAY, "Lone Star Parcel")["alert_count"] == 0


def test_carrier_alerts_unknown_carrier(conn):
    with pytest.raises(tools.NotFound, match="Known carriers"):
        tools.get_carrier_alerts(conn, TODAY, "Acme Freight")


def test_late_dispatch_fields(conn):
    late = tools.get_shipment_status(conn, TODAY, "ORD-1011")["shipments"][0]
    assert late["dispatched_late"] is True and late["dispatch_days_after_ship_by"] == 4
    on_time = tools.get_shipment_status(conn, TODAY, "ORD-1003")["shipments"][0]
    assert on_time["dispatched_late"] is False


def test_stalled_shipment_last_location(conn):
    s = tools.get_shipment_status(conn, TODAY, "ORD-1010")["shipments"][0]
    assert s["last_event_location"] == "Toledo, OH" and s["days_since_last_event"] == 9
    assert s["recorded_delay_reason"] is None


def test_pending_past_ship_by(conn):
    assert tools.get_order_details(conn, TODAY, "ORD-1012")["is_past_ship_by_date"] is True
    assert tools.get_order_details(conn, TODAY, "ORD-1001")["is_past_ship_by_date"] is False
