"""The four read-only investigation tools.

Each tool:
  * takes already-validated arguments (validation lives in executor.py),
  * runs parameterized SQL only (no string-formatted queries),
  * returns a plain dict that is JSON-serializable,
  * raises NotFound when the record does not exist.

Derived values (available stock, days overdue, shortfall) are computed here in
Python so the model never has to do date or stock arithmetic itself.
"""
from __future__ import annotations

import sqlite3
from datetime import date


class NotFound(Exception):
    """The requested record does not exist in the database."""


def _days_between(later: str | date, earlier: str | date) -> int:
    later_d = later if isinstance(later, date) else date.fromisoformat(later)
    earlier_d = earlier if isinstance(earlier, date) else date.fromisoformat(earlier)
    return (later_d - earlier_d).days


# --------------------------------------------------------------------------- #
# Tool 1
# --------------------------------------------------------------------------- #
def get_order_details(conn: sqlite3.Connection, today: date, order_id: str) -> dict:
    """Order header + line items + promise-date status."""
    row = conn.execute(
        "SELECT o.order_id, o.customer_name, o.warehouse_id, w.name AS warehouse_name, "
        "       o.order_date, o.promised_delivery_date, o.ship_by_date, o.fulfillment_status "
        "FROM orders o JOIN warehouses w ON w.warehouse_id = o.warehouse_id "
        "WHERE o.order_id = ?",
        (order_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"No order with order_id '{order_id}' exists.")

    items = conn.execute(
        "SELECT oi.sku, p.name AS product_name, oi.quantity "
        "FROM order_items oi JOIN products p ON p.sku = oi.sku "
        "WHERE oi.order_id = ? ORDER BY oi.sku",
        (order_id,),
    ).fetchall()

    promised = row["promised_delivery_date"]
    days_to_promise = _days_between(promised, today)
    return {
        "order_id": row["order_id"],
        "customer_name": row["customer_name"],
        "fulfillment_warehouse_id": row["warehouse_id"],
        "fulfillment_warehouse_name": row["warehouse_name"],
        "order_date": row["order_date"],
        "promised_delivery_date": promised,
        "ship_by_date": row["ship_by_date"],
        "fulfillment_status": row["fulfillment_status"],
        "items": [dict(i) for i in items],
        "investigation_date": today.isoformat(),
        "days_until_promised_date": days_to_promise,
        "is_past_promised_date": days_to_promise < 0,
        "is_past_ship_by_date": row["fulfillment_status"] == "PENDING_FULFILLMENT"
                                and _days_between(today, row["ship_by_date"]) > 0,
    }


# --------------------------------------------------------------------------- #
# Tool 2
# --------------------------------------------------------------------------- #
def get_shipment_status(conn: sqlite3.Connection, today: date, order_id: str) -> dict:
    """Shipment record(s) and tracking events for an order."""
    order = conn.execute(
        "SELECT order_id, promised_delivery_date, ship_by_date, fulfillment_status FROM orders WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        raise NotFound(f"No order with order_id '{order_id}' exists.")

    shipments = conn.execute(
        "SELECT * FROM shipments WHERE order_id = ? ORDER BY dispatch_date", (order_id,)
    ).fetchall()
    if not shipments:
        raise NotFound(
            f"Order '{order_id}' exists (fulfillment_status={order['fulfillment_status']}) "
            "but has no shipment record."
        )

    promised = order["promised_delivery_date"]
    ship_by = order["ship_by_date"]
    result_shipments = []
    for s in shipments:
        events = conn.execute(
            "SELECT event_date, location, event_type, description FROM shipment_events "
            "WHERE shipment_id = ? ORDER BY event_date, event_id",
            (s["shipment_id"],),
        ).fetchall()
        delivered = s["delivered_date"]
        if delivered:
            days_late = max(0, _days_between(delivered, promised))
        else:
            days_late = max(0, _days_between(today, promised))
        current_eta = s["current_estimated_date"]
        last_event = events[-1]["event_date"] if events else None
        result_shipments.append({
            "shipment_id": s["shipment_id"],
            "carrier": s["carrier"],
            "tracking_number": s["tracking_number"],
            "status": s["status"],
            "dispatch_date": s["dispatch_date"],
            "original_estimated_delivery_date": s["original_estimated_date"],
            "current_estimated_delivery_date": current_eta,  # None = carrier gave no revised ETA
            "delivered_date": delivered,
            "recorded_delay_reason": s["delay_reason"],       # None = no delay recorded
            "events": [dict(e) for e in events],
            "last_event_date": last_event,
            "last_event_location": events[-1]["location"] if events else None,
            "days_since_last_event": _days_between(today, last_event) if last_event else None,
            # Warehouse side: was the order handed to the carrier on time?
            "ship_by_date": ship_by,
            "dispatch_days_after_ship_by": max(0, _days_between(s["dispatch_date"], ship_by)),
            "dispatched_late": s["dispatch_date"] > ship_by,
            # Derived flags (computed against the order's promised date):
            "promised_delivery_date": promised,
            "is_delivered": delivered is not None,
            "is_overdue": (delivered is None and today > date.fromisoformat(promised))
                          or (delivered is not None and delivered > promised),
            "days_past_promised_date": days_late,
            "eta_after_promised_date": bool(current_eta and current_eta > promised),
        })
    return {
        "order_id": order_id,
        "investigation_date": today.isoformat(),
        "shipments": result_shipments,
    }


# --------------------------------------------------------------------------- #
# Tool 3
# --------------------------------------------------------------------------- #
def check_inventory(conn: sqlite3.Connection, today: date, sku: str, warehouse_id: str) -> dict:
    """Stock for one SKU at one warehouse."""
    if conn.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone() is None:
        raise NotFound(f"No product with sku '{sku}' exists.")
    if conn.execute("SELECT 1 FROM warehouses WHERE warehouse_id = ?", (warehouse_id,)).fetchone() is None:
        raise NotFound(f"No warehouse with warehouse_id '{warehouse_id}' exists.")

    row = conn.execute(
        "SELECT on_hand, reserved FROM inventory WHERE sku = ? AND warehouse_id = ?",
        (sku, warehouse_id),
    ).fetchone()
    on_hand, reserved = (row["on_hand"], row["reserved"]) if row else (0, 0)
    return {
        "sku": sku,
        "warehouse_id": warehouse_id,
        "on_hand": on_hand,
        "reserved": reserved,
        "available": on_hand - reserved,
        "inventory_record_exists": row is not None,
    }


# --------------------------------------------------------------------------- #
# Tool 4
# --------------------------------------------------------------------------- #
def find_alternative_stock(
    conn: sqlite3.Connection,
    today: date,
    sku: str,
    required_quantity: int,
    exclude_warehouse_id: str | None = None,
) -> dict:
    """Which other warehouses could cover `required_quantity` of `sku` on their own."""
    if conn.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone() is None:
        raise NotFound(f"No product with sku '{sku}' exists.")

    rows = conn.execute(
        "SELECT i.warehouse_id, w.name, i.on_hand - i.reserved AS available "
        "FROM inventory i JOIN warehouses w ON w.warehouse_id = i.warehouse_id "
        "WHERE i.sku = ? AND (? IS NULL OR i.warehouse_id <> ?) "
        "ORDER BY available DESC, i.warehouse_id",
        (sku, exclude_warehouse_id, exclude_warehouse_id),
    ).fetchall()
    warehouses = [
        {
            "warehouse_id": r["warehouse_id"],
            "warehouse_name": r["name"],
            "available": r["available"],
            "can_cover_required_quantity": r["available"] >= required_quantity,
        }
        for r in rows
    ]
    sufficient = [w["warehouse_id"] for w in warehouses if w["can_cover_required_quantity"]]
    return {
        "sku": sku,
        "required_quantity": required_quantity,
        "excluded_warehouse_id": exclude_warehouse_id,
        "warehouses_checked": warehouses,
        "warehouses_with_sufficient_stock": sufficient,
        "total_available_in_checked_warehouses": sum(max(0, w["available"]) for w in warehouses),
    }


# --------------------------------------------------------------------------- #
# Tool 5
# --------------------------------------------------------------------------- #
def get_carrier_alerts(conn: sqlite3.Connection, today: date, carrier: str, location: str | None = None) -> dict:
    """Service alerts (hub closures, weather, backlogs) a carrier has published up to today."""
    known = conn.execute("SELECT 1 FROM shipments WHERE carrier = ? LIMIT 1", (carrier,)).fetchone()
    if known is None:
        carriers = [r[0] for r in conn.execute("SELECT DISTINCT carrier FROM shipments ORDER BY carrier")]
        raise NotFound(f"Unknown carrier '{carrier}'. Known carriers: {', '.join(carriers)}.")
    rows = conn.execute(
        "SELECT * FROM carrier_alerts WHERE carrier = ? AND start_date <= ? "
        "AND (? IS NULL OR location = ?) ORDER BY start_date DESC",
        (carrier, today.isoformat(), location, location),
    ).fetchall()
    alerts = [{
        "alert_id": r["alert_id"], "location": r["location"], "alert_type": r["alert_type"],
        "start_date": r["start_date"], "end_date": r["end_date"], "description": r["description"],
        "active_on_investigation_date": r["start_date"] <= today.isoformat() <= r["end_date"],
    } for r in rows]
    return {"carrier": carrier, "location_filter": location, "investigation_date": today.isoformat(),
            "alerts": alerts, "alert_count": len(alerts)}
