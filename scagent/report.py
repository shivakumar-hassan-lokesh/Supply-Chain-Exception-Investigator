"""The final investigation report: schema the model fills in, validation, rendering.

The model finishes an investigation by calling the `submit_report` tool. Using a
tool (instead of free text) gives us a structured report that Python can check
field by field against the evidence: the issue, its cause category, and the
recommended actions (chosen from a fixed catalog so they can be scored).
"""
from __future__ import annotations

ISSUE_TYPES = [
    "INSUFFICIENT_INVENTORY",  # stock at the fulfillment warehouse < ordered quantity
    "DELAYED_DELIVERY",        # overdue vs. promised date (or certain to be)
    "NO_EXCEPTION",            # evidence shows no problem
    "ORDER_NOT_FOUND",         # order ID does not exist
    "MISSING_DATA",            # a record needed for a conclusion is missing
    "INCONCLUSIVE",            # could not determine (e.g. tool failure, conflicting data)
]

# Why the problem happened. Each category needs specific evidence (see verifier.py).
CAUSE_CATEGORIES = {
    "CARRIER_REPORTED_DELAY":     "the shipment record contains a delay reason recorded by the carrier",
    "CARRIER_SERVICE_DISRUPTION": "a carrier service alert (hub closure, weather, backlog) matches where the shipment is held",
    "TRACKING_STALLED":           "no tracking movement for several days and no recorded reason or matching alert",
    "LATE_DISPATCH":              "the warehouse handed the order to the carrier after its ship-by date",
    "STOCK_SHORTAGE":             "available stock at the fulfillment warehouse is below the ordered quantity",
    "MISSING_SHIPMENT_RECORD":    "the order is marked shipped but no shipment record exists",
    "UNKNOWN":                    "evidence is insufficient to determine a cause",
    "NOT_APPLICABLE":             "there is no exception, or the order does not exist",
}
CAUSE_STATUSES = ["confirmed", "suspected", "unknown", "not_applicable"]

# What the agent may recommend. It recommends only; it never performs these.
ACTION_CATALOG = {
    "TRANSFER_STOCK":          "move stock from another warehouse that alone can cover the shortfall",
    "EXPEDITE_REPLENISHMENT":  "rush a purchase/replenishment order for the short SKU",
    "SHIP_PARTIAL":            "ship the units available now, the rest later",
    "CONTACT_CARRIER":         "ask the carrier for a trace, current location, or confirmed ETA",
    "NOTIFY_CUSTOMER":         "tell the customer about the delay and the expected date",
    "ESCALATE_TO_WAREHOUSE":   "ask the warehouse team to explain or fix a dispatch / record problem",
    "VERIFY_ORDER_ID":         "confirm the order number with the requester",
    "RETRY_LATER":             "re-run the investigation once a failed system is available",
    "NO_ACTION_NEEDED":        "nothing needs to be done; use ONLY when there is no exception, never together with other actions",
}

SUBMIT_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string", "description": "The order investigated, e.g. ORD-1003."},
        "issue_type": {"type": "string", "enum": ISSUE_TYPES},
        "summary": {"type": "string", "description": "One or two sentences stating the finding."},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Facts copied from tool results, each naming its tool and quoting the "
                           "specific IDs, quantities, statuses and dates, e.g. "
                           "\"get_shipment_status: SHP-5003 status DELAYED, ETA 2026-03-18\". "
                           "A bare tool name is not evidence.",
        },
        "cause_category": {
            "type": "string",
            "enum": list(CAUSE_CATEGORIES),
            "description": "Why it happened: " + "; ".join(f"{k} = {v}" for k, v in CAUSE_CATEGORIES.items()),
        },
        "likely_cause": {"type": "string", "description": "The cause in words, or 'unknown' if not supported by evidence."},
        "cause_status": {
            "type": "string",
            "enum": CAUSE_STATUSES,
            "description": "confirmed = the reason for the problem is stated directly in tool data; "
                           "suspected = inferred from indirect evidence (e.g. a matching carrier alert); "
                           "unknown = no evidence of the reason; not_applicable = no exception. For "
                           "TRACKING_STALLED or UNKNOWN the reason behind the delay is not in the data, so use "
                           "unknown or suspected, not confirmed.",
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {
            "type": "array",
            "minItems": 1,
            "description": "Actions to recommend, most important first. Choose from: "
                           + "; ".join(f"{k} = {v}" for k, v in ACTION_CATALOG.items()),
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(ACTION_CATALOG)},
                    "details": {"type": "string", "description": "Specifics (who, what, how much), with the evidence that justifies it."},
                },
                "required": ["action", "details"],
                "additionalProperties": False,
            },
        },
        "recommendation": {"type": "string", "description": "One-sentence summary of the recommended plan. Recommend only; do not claim it was done."},
        "recommended_source_warehouse": {
            "type": ["string", "null"],
            "description": "Warehouse ID to transfer stock from, ONLY if find_alternative_stock "
                           "showed it can cover the need. Otherwise null.",
        },
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "investigation_complete": {
            "type": "boolean",
            "description": "false if a tool failed or data was missing so the conclusion is not reliable.",
        },
    },
    "required": [
        "order_id", "issue_type", "summary", "evidence", "cause_category", "likely_cause", "cause_status",
        "uncertainties", "recommended_actions", "recommendation", "recommended_source_warehouse",
        "missing_information", "investigation_complete",
    ],
    "additionalProperties": False,
}

SUBMIT_REPORT_DESCRIPTION = (
    "Submit the final investigation report. Call this exactly once, when you have enough "
    "evidence or cannot gather more. Every fact must come from a tool result in this "
    "investigation. All fields are required: use [] for empty lists and null for "
    "recommended_source_warehouse when no transfer is supported."
)


def validate_report(report) -> list[str]:
    if not isinstance(report, dict):
        return ["report must be a JSON object"]
    problems = []
    props = SUBMIT_REPORT_SCHEMA["properties"]
    for key in SUBMIT_REPORT_SCHEMA["required"]:
        if key not in report:
            problems.append(f"missing field '{key}'")
    for key in report:
        if key not in props:
            problems.append(f"unexpected field '{key}'")
    if report.get("issue_type") not in ISSUE_TYPES:
        problems.append(f"issue_type must be one of {ISSUE_TYPES}")
    if report.get("cause_category") not in CAUSE_CATEGORIES:
        problems.append(f"cause_category must be one of {list(CAUSE_CATEGORIES)}")
    if report.get("cause_status") not in CAUSE_STATUSES:
        problems.append(f"cause_status must be one of {CAUSE_STATUSES}")
    for key in ("evidence", "uncertainties", "missing_information"):
        if key in report and not (isinstance(report[key], list) and all(isinstance(x, str) for x in report[key])):
            problems.append(f"'{key}' must be a list of strings")
    actions = report.get("recommended_actions")
    if "recommended_actions" in report:
        if not isinstance(actions, list) or not actions:
            problems.append("'recommended_actions' must be a non-empty list")
        else:
            for i, a in enumerate(actions):
                if not isinstance(a, dict) or a.get("action") not in ACTION_CATALOG:
                    problems.append(f"recommended_actions[{i}].action must be one of {list(ACTION_CATALOG)}")
                elif not isinstance(a.get("details"), str) or set(a) - {"action", "details"}:
                    problems.append(f"recommended_actions[{i}] needs exactly 'action' and a string 'details'")
    for key in ("order_id", "summary", "likely_cause", "recommendation"):
        if key in report and not isinstance(report[key], str):
            problems.append(f"'{key}' must be a string")
    src = report.get("recommended_source_warehouse")
    if src is not None and not isinstance(src, str):
        problems.append("'recommended_source_warehouse' must be a string or null")
    if "investigation_complete" in report and not isinstance(report["investigation_complete"], bool):
        problems.append("'investigation_complete' must be true or false")
    return problems


def action_names(report: dict) -> list[str]:
    return [a.get("action") for a in report.get("recommended_actions") or [] if isinstance(a, dict)]


def system_fallback_report(order_id: str | None, reason: str) -> dict:
    """Report written by Python (not the model) when the loop ends without a valid report."""
    return {
        "order_id": order_id or "UNKNOWN",
        "issue_type": "INCONCLUSIVE",
        "summary": f"Investigation stopped without a model-submitted report: {reason}",
        "evidence": [],
        "cause_category": "UNKNOWN",
        "likely_cause": "unknown",
        "cause_status": "unknown",
        "uncertainties": [reason],
        "recommended_actions": [{"action": "RETRY_LATER", "details": "Review the execution trace and re-run the investigation."}],
        "recommendation": "Review the execution trace and re-run the investigation.",
        "recommended_source_warehouse": None,
        "missing_information": [reason],
        "investigation_complete": False,
        "generated_by": "system",
    }


def render_report(report: dict) -> str:
    def bullets(items):
        return "\n".join(f"  - {x}" for x in items) if items else "  - (none)"

    actions = [f"{a.get('action')}: {a.get('details')}" for a in report.get("recommended_actions") or []]
    origin = " [SYSTEM-GENERATED: the model did not submit a report]" if report.get("generated_by") == "system" else ""
    return "\n".join([
        f"INVESTIGATION REPORT{origin}",
        f"Order:            {report.get('order_id')}",
        f"Issue:            {report.get('issue_type')}",
        f"Complete:         {report.get('investigation_complete')}",
        f"Summary:          {report.get('summary')}",
        "Evidence:",
        bullets(report.get("evidence", [])),
        f"Cause category:   {report.get('cause_category')}  ({report.get('cause_status')})",
        f"Likely cause:     {report.get('likely_cause')}",
        "Uncertainties:",
        bullets(report.get("uncertainties", [])),
        "Recommended actions:",
        bullets(actions),
        f"Plan:             {report.get('recommendation')}",
        f"Transfer source:  {report.get('recommended_source_warehouse') or '-'}",
        "Missing information:",
        bullets(report.get("missing_information", [])),
    ])
