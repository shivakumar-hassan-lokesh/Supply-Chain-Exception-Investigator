"""TEST DOUBLES ONLY. These are NOT the working agent.

The real agent's decisions come from a language model (scagent/providers/).
These scripted providers exist so the loop, validation, limits, and verifier
can be tested deterministically and offline. Their output must never be
presented as a real model run.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from scagent.providers.base import ModelTurn, ToolCall, ToolResult


class ScriptedProvider:
    """Calls `policy(history, request)` each turn. `history` is a list of
    (name, arguments, result_envelope) for every tool call answered so far."""

    name = "test-double"
    model = "scripted-policy"

    def __init__(self, policy: Callable[[list, str], ModelTurn]):
        self.policy = policy
        self.history: list[tuple[str, dict, dict]] = []
        self.request = ""
        self._pending: dict[str, tuple[str, dict]] = {}
        self.user_messages: list[str] = []

    def start(self, system_prompt, user_message, tools):
        self.request = user_message
        self.tool_names = [t["name"] for t in tools]

    def step(self) -> ModelTurn:
        turn = self.policy(self.history, self.request)
        for c in turn.tool_calls:
            self._pending[c.id] = (c.name, c.arguments)
        return turn

    def add_tool_results(self, results: list[ToolResult]):
        for r in results:
            name, args = self._pending.pop(r.call_id)
            self.history.append((name, args, json.loads(r.content)))

    def add_user_message(self, text):
        self.user_messages.append(text)


_counter = {"n": 0}


def tc(name, args=None, parse_error=None) -> ToolCall:
    _counter["n"] += 1
    return ToolCall(id=f"call_{_counter['n']}", name=name, arguments=args, parse_error=parse_error)


def turn(text="", *calls) -> ModelTurn:
    return ModelTurn(text=text, tool_calls=list(calls), stop_reason="tool_use" if calls else "end_turn")


def act(*names) -> list[dict]:
    return [{"action": n, "details": f"{n.lower().replace('_', ' ')} (test double)"} for n in names]


def report(**overrides) -> dict:
    base = {
        "order_id": "ORD-1005", "issue_type": "NO_EXCEPTION", "summary": "s", "evidence": [],
        "cause_category": "NOT_APPLICABLE", "likely_cause": "n/a", "cause_status": "not_applicable",
        "uncertainties": [], "recommended_actions": act("NO_ACTION_NEEDED"),
        "recommendation": "none", "recommended_source_warehouse": None,
        "missing_information": [], "investigation_complete": True,
    }
    base.update(overrides)
    return base


def reactive_policy(history, request) -> ModelTurn:
    """A rule-based stand-in for the model that reacts to tool results.

    It makes the same kinds of decisions we want the LLM to make, so the loop and
    verifier can be exercised end to end without an API key.
    """
    order_id = re.search(r"ORD-\d{4}", request).group(0)
    done = {(n, json.dumps(a, sort_keys=True)): r for n, a, r in history}

    def get(name, **a):
        return done.get((name, json.dumps(a, sort_keys=True)))

    def submit(**fields):
        return turn("", tc("submit_report", report(order_id=order_id, **fields)))

    order = get("get_order_details", order_id=order_id)
    if order is None:
        return turn("First I'll look up the order.", tc("get_order_details", {"order_id": order_id}))
    if not order["ok"]:
        if order["error"]["code"] == "NOT_FOUND":
            return submit(issue_type="ORDER_NOT_FOUND", summary=f"{order_id} does not exist.",
                          evidence=[f"get_order_details: NOT_FOUND for {order_id}"], likely_cause="unknown",
                          cause_status="unknown", recommended_actions=act("VERIFY_ORDER_ID"),
                          recommendation="Confirm the order ID with the customer.",
                          missing_information=["order record"])
        return submit(issue_type="INCONCLUSIVE", summary="Order lookup failed.", cause_category="UNKNOWN",
                      likely_cause="unknown", cause_status="unknown", recommended_actions=act("RETRY_LATER"),
                      recommendation="Retry later.", missing_information=["order details"],
                      investigation_complete=False)

    od = order["data"]
    ev = [f"get_order_details: {order_id} status {od['fulfillment_status']}, promised {od['promised_delivery_date']}"]

    if od["fulfillment_status"] in ("SHIPPED", "DELIVERED"):
        ship = get("get_shipment_status", order_id=order_id)
        if ship is None:
            return turn("The order has shipped, so I'll check tracking.", tc("get_shipment_status", {"order_id": order_id}))
        if not ship["ok"]:
            missing = ship["error"]["code"] == "NOT_FOUND"
            return submit(issue_type="MISSING_DATA" if missing else "INCONCLUSIVE",
                          summary=f"Shipment data unavailable ({ship['error']['code']}).",
                          evidence=ev + [f"get_shipment_status: {ship['error']['code']}"],
                          cause_category="MISSING_SHIPMENT_RECORD" if missing else "UNKNOWN",
                          likely_cause="unknown", cause_status="unknown", uncertainties=["carrier status unknown"],
                          recommended_actions=act("ESCALATE_TO_WAREHOUSE") if missing else act("RETRY_LATER", "CONTACT_CARRIER"),
                          recommendation="Obtain shipment records before concluding.",
                          missing_information=["shipment status and tracking events"], investigation_complete=False)
        s = ship["data"]["shipments"][0]
        ev.append(f"get_shipment_status: {s['shipment_id']} status {s['status']}, ETA {s['current_estimated_delivery_date']}")
        if not (s["is_overdue"] or s["eta_after_promised_date"]):
            return submit(evidence=ev, summary="On track.", recommendation="No action needed.")
        if s["recorded_delay_reason"]:
            return submit(issue_type="DELAYED_DELIVERY", summary="Carrier-reported delay.", evidence=ev,
                          cause_category="CARRIER_REPORTED_DELAY", likely_cause=s["recorded_delay_reason"],
                          cause_status="confirmed", recommended_actions=act("NOTIFY_CUSTOMER"),
                          recommendation="Notify the customer of the revised ETA.")
        if s["dispatched_late"]:
            ev.append(f"get_shipment_status: dispatched {s['dispatch_date']} vs ship-by {s['ship_by_date']}")
            return submit(issue_type="DELAYED_DELIVERY", summary="Warehouse dispatched late.", evidence=ev,
                          cause_category="LATE_DISPATCH", likely_cause="Late dispatch", cause_status="confirmed",
                          recommended_actions=act("ESCALATE_TO_WAREHOUSE", "NOTIFY_CUSTOMER"),
                          recommendation="Escalate the late dispatch to the warehouse.")
        alerts = get("get_carrier_alerts", carrier=s["carrier"])
        if alerts is None:
            return turn("No reason recorded; checking carrier alerts.", tc("get_carrier_alerts", {"carrier": s["carrier"]}))
        matching = [a for a in alerts["data"]["alerts"] if a["location"] == s["last_event_location"]] if alerts["ok"] else []
        if matching:
            ev.append(f"get_carrier_alerts: {matching[0]['alert_id']} at {matching[0]['location']}")
            return submit(issue_type="DELAYED_DELIVERY", summary="Carrier service disruption.", evidence=ev,
                          cause_category="CARRIER_SERVICE_DISRUPTION", likely_cause=matching[0]["description"],
                          cause_status="suspected", recommended_actions=act("CONTACT_CARRIER", "NOTIFY_CUSTOMER"),
                          recommendation="Ask the carrier to confirm status.", investigation_complete=False)
        return submit(issue_type="DELAYED_DELIVERY", summary="Overdue with stalled tracking.", evidence=ev,
                      cause_category="TRACKING_STALLED", likely_cause="unknown", cause_status="unknown",
                      recommended_actions=act("CONTACT_CARRIER"), recommendation="Request a carrier trace.",
                      missing_information=["carrier explanation for the delay"])

    # Pending: check every line item at the order's warehouse (parallel calls in one turn).
    wh = od["fulfillment_warehouse_id"]
    unchecked = [i for i in od["items"] if get("check_inventory", sku=i["sku"], warehouse_id=wh) is None]
    if unchecked:
        return turn("Order not shipped; checking stock for each item.",
                    *[tc("check_inventory", {"sku": i["sku"], "warehouse_id": wh}) for i in unchecked])
    shorts = []
    for i in od["items"]:
        inv = get("check_inventory", sku=i["sku"], warehouse_id=wh)["data"]
        ev.append(f"check_inventory: {i['sku']} at {wh} available {inv['available']} vs needed {i['quantity']}")
        if inv["available"] < i["quantity"]:
            shorts.append((i["sku"], i["quantity"] - inv["available"]))
    if not shorts:
        return submit(evidence=ev, summary="Stock is sufficient.", recommendation="No action needed.")
    pending_alt = [(sku, q) for sku, q in shorts
                   if get("find_alternative_stock", sku=sku, required_quantity=q, exclude_warehouse_id=wh) is None]
    if pending_alt:
        sku, q = pending_alt[0]
        return turn(f"{sku} is short by {q}; checking other warehouses.",
                    tc("find_alternative_stock", {"sku": sku, "required_quantity": q, "exclude_warehouse_id": wh}))
    source = None
    for sku, q in shorts:
        alt = get("find_alternative_stock", sku=sku, required_quantity=q, exclude_warehouse_id=wh)["data"]
        ev.append(f"find_alternative_stock: {sku} sufficient at {alt['warehouses_with_sufficient_stock']}")
        if alt["warehouses_with_sufficient_stock"] and len(shorts) == 1:
            source = alt["warehouses_with_sufficient_stock"][0]
    actions = ["TRANSFER_STOCK"] if source else ["EXPEDITE_REPLENISHMENT"]
    if od["is_past_promised_date"]:
        actions.append("NOTIFY_CUSTOMER")
    return submit(issue_type="INSUFFICIENT_INVENTORY", summary="Stock shortage.", evidence=ev,
                  cause_category="STOCK_SHORTAGE", likely_cause="Available stock below ordered quantity",
                  cause_status="confirmed", recommended_actions=act(*actions),
                  recommendation=f"Transfer from {source}." if source else "Expedite replenishment.",
                  recommended_source_warehouse=source)
