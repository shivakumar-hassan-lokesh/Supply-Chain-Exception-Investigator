"""Tool registry, argument validation, and safe execution.

The model only ever *requests* a tool. This module decides whether the request
is valid and, if so, runs the matching Python function. Every outcome is
returned as a structured envelope:

    {"ok": true,  "data": {...}}
    {"ok": false, "error": {"code": "...", "message": "..."}}

Error codes:
    UNKNOWN_TOOL      model asked for a tool that does not exist
    INVALID_ARGUMENT  missing / extra / malformed arguments (nothing was executed)
    NOT_FOUND         arguments were valid but the record does not exist
    TOOL_FAILURE      the tool crashed or is unavailable (e.g. database outage)
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import tools
from .db import connect

ORDER_ID_RE = re.compile(r"^ORD-\d{4}$")
SKU_RE = re.compile(r"^SKU-\d{3}$")
WAREHOUSE_RE = re.compile(r"^WH-[A-Z]{3}$")
FREE_TEXT_RE = re.compile(r"^[A-Za-z][A-Za-z .,&'-]{1,59}$")


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict           # JSON Schema sent to the model
    func: Callable[..., dict]  # Python implementation


def _order_id_prop() -> dict:
    return {"type": "string", "description": "Order ID, format ORD-#### (e.g. ORD-1003)."}


TOOL_SPECS: dict[str, ToolSpec] = {
    "get_order_details": ToolSpec(
        name="get_order_details",
        description=(
            "Look up an order: customer, fulfillment warehouse, ordered SKUs and quantities, "
            "promised delivery date, and fulfillment_status (PENDING_FULFILLMENT, SHIPPED, "
            "DELIVERED). Also reports whether the promised date has passed as of the "
            "investigation date."
        ),
        parameters={
            "type": "object",
            "properties": {"order_id": _order_id_prop()},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        func=tools.get_order_details,
    ),
    "get_shipment_status": ToolSpec(
        name="get_shipment_status",
        description=(
            "Get shipment records for an order that has shipped: carrier, tracking number, "
            "status, dispatch date, original and current estimated delivery dates, delivered "
            "date, any delay reason recorded by the carrier, and the tracking event history. "
            "Includes computed flags such as is_overdue and days_past_promised_date. Returns "
            "NOT_FOUND if the order has no shipment record."
        ),
        parameters={
            "type": "object",
            "properties": {"order_id": _order_id_prop()},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        func=tools.get_shipment_status,
    ),
    "check_inventory": ToolSpec(
        name="check_inventory",
        description=(
            "Check stock of one SKU at one warehouse. Returns on_hand, reserved, and "
            "available (= on_hand - reserved). Use this to see whether the order's own "
            "warehouse can fulfill a line item."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Product SKU, format SKU-### (e.g. SKU-202)."},
                "warehouse_id": {"type": "string", "description": "Warehouse ID, format WH-XXX (e.g. WH-BOS)."},
            },
            "required": ["sku", "warehouse_id"],
            "additionalProperties": False,
        },
        func=tools.check_inventory,
    ),
    "find_alternative_stock": ToolSpec(
        name="find_alternative_stock",
        description=(
            "Search other warehouses for available stock of a SKU. Reports, for each "
            "warehouse, whether it alone can cover required_quantity. Use it only after "
            "confirming a shortage, to support (or rule out) a stock-transfer recommendation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Product SKU, format SKU-###."},
                "required_quantity": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Units needed from a single other warehouse (e.g. the shortfall).",
                },
                "exclude_warehouse_id": {
                    "type": "string",
                    "description": "Optional: warehouse to leave out (usually the order's own warehouse).",
                },
            },
            "required": ["sku", "required_quantity"],
            "additionalProperties": False,
        },
        func=tools.find_alternative_stock,
    ),
    "get_carrier_alerts": ToolSpec(
        name="get_carrier_alerts",
        description=(
            "List service alerts a carrier has published up to the investigation date, such as hub "
            "closures, weather or backlogs, with location, dates and whether each is still active. "
            "Optionally filter by location (e.g. 'Toledo, OH'). Useful for explaining a stalled or "
            "late shipment when the shipment record itself gives no delay reason."
        ),
        parameters={
            "type": "object",
            "properties": {
                "carrier": {"type": "string", "description": "Carrier name exactly as in shipment data, e.g. 'Great Lakes Freight'."},
                "location": {"type": "string", "description": "Optional: 'City, ST' as shown in tracking events."},
            },
            "required": ["carrier"],
            "additionalProperties": False,
        },
        func=tools.get_carrier_alerts,
    ),
}

FIELD_PATTERNS = {
    "order_id": (ORDER_ID_RE, "ORD-#### (e.g. ORD-1003)"),
    "sku": (SKU_RE, "SKU-### (e.g. SKU-202)"),
    "warehouse_id": (WAREHOUSE_RE, "WH-XXX (e.g. WH-BOS)"),
    "exclude_warehouse_id": (WAREHOUSE_RE, "WH-XXX (e.g. WH-BOS)"),
    "carrier": (FREE_TEXT_RE, "a carrier name of 2-60 letters, e.g. Great Lakes Freight"),
    "location": (FREE_TEXT_RE, "a 'City, ST' location of 2-60 characters"),
}


def validate_arguments(spec: ToolSpec, args: Any) -> list[str]:
    """Return a list of problems with `args`; empty list means valid."""
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    schema = spec.parameters
    props = schema["properties"]
    problems = []
    for name in schema["required"]:
        if name not in args or args[name] in (None, ""):
            problems.append(f"missing required argument '{name}'")
    for name in args:
        if name not in props:
            problems.append(f"unexpected argument '{name}'")
    for name, value in args.items():
        if name not in props or value is None:
            continue
        expected = props[name]["type"]
        if expected == "string":
            if not isinstance(value, str):
                problems.append(f"'{name}' must be a string")
                continue
            if name in FIELD_PATTERNS:
                pattern, human = FIELD_PATTERNS[name]
                if not pattern.match(value):
                    problems.append(f"'{name}'='{value}' is not in the expected format {human}")
        elif expected == "integer":
            # bool is a subclass of int in Python; reject it explicitly.
            if not isinstance(value, int) or isinstance(value, bool):
                problems.append(f"'{name}' must be an integer")
            elif value < props[name].get("minimum", value):
                problems.append(f"'{name}' must be >= {props[name]['minimum']}")
    return problems


class ToolExecutor:
    """Validates and runs tool requests against the database."""

    def __init__(self, db_path: Path, investigation_date: date, failing_tools: set[str] | None = None):
        self.db_path = Path(db_path)
        self.investigation_date = investigation_date
        self.failing_tools = set(failing_tools or ())

    def tool_definitions(self) -> list[ToolSpec]:
        return list(TOOL_SPECS.values())

    def execute(self, name: str, args: Any) -> dict:
        """Run one tool request. Never raises; always returns an envelope + metadata."""
        started = time.perf_counter()
        spec = TOOL_SPECS.get(name)
        meta = {
            "python_function": f"scagent.tools.{spec.func.__name__}" if spec else None,
            "executed": False,
        }
        if spec is None:
            return self._finish(started, meta, error=("UNKNOWN_TOOL",
                f"Unknown tool '{name}'. Available tools: {', '.join(TOOL_SPECS)}."))

        problems = validate_arguments(spec, args)
        if problems:
            return self._finish(started, meta, error=("INVALID_ARGUMENT",
                "Request rejected before execution: " + "; ".join(problems)))

        meta["executed"] = True
        if name in self.failing_tools:
            # Simulated outage, used by the tool-failure scenario and tests.
            return self._finish(started, meta, error=("TOOL_FAILURE",
                f"{name} is unavailable: simulated upstream database timeout. "
                "No data was returned; retrying is unlikely to help during this run."))
        try:
            conn = connect(self.db_path, read_only=True)
            try:
                data = spec.func(conn, self.investigation_date, **args)
            finally:
                conn.close()
        except tools.NotFound as exc:
            return self._finish(started, meta, error=("NOT_FOUND", str(exc)))
        except (sqlite3.Error, FileNotFoundError, OSError) as exc:
            return self._finish(started, meta, error=("TOOL_FAILURE", f"{type(exc).__name__}: {exc}"))
        except Exception as exc:  # defensive: a bug in a tool must not crash the agent
            return self._finish(started, meta, error=("TOOL_FAILURE", f"Unexpected {type(exc).__name__}: {exc}"))
        return self._finish(started, meta, data=data)

    @staticmethod
    def _finish(started: float, meta: dict, data: dict | None = None,
                error: tuple[str, str] | None = None) -> dict:
        envelope = {"ok": True, "data": data} if error is None else {
            "ok": False, "error": {"code": error[0], "message": error[1]}}
        return {"result": envelope, "meta": {**meta, "duration_ms": round((time.perf_counter() - started) * 1000, 2)}}
