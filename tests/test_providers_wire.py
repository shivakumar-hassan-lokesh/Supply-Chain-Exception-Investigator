"""Provider adapters tested against the REAL SDKs with a mocked HTTP transport.

No network and no API key: we intercept the HTTP request the SDK would send,
check its shape (tools, tool results, headers), and return a canned response.
This proves the adapter code paths work with the installed SDK versions; it
does not test model quality.
"""
import json

import httpx2 as httpx  # the anthropic>=2 and openai>=3 SDKs use httpx2
import pytest

from scagent.agent import investigate


def _report_input():
    return {
        "order_id": "ORD-9999", "issue_type": "ORDER_NOT_FOUND", "summary": "Order does not exist.",
        "evidence": ["get_order_details returned NOT_FOUND for ORD-9999"], "cause_category": "NOT_APPLICABLE",
        "likely_cause": "unknown", "cause_status": "unknown", "uncertainties": [],
        "recommended_actions": [{"action": "VERIFY_ORDER_ID", "details": "Ask the customer to confirm the order number."}],
        "recommendation": "Confirm the order ID.",
        "recommended_source_warehouse": None, "missing_information": ["order record"],
        "investigation_complete": True,
    }


def test_anthropic_adapter_round_trip(cfg):
    anthropic = pytest.importorskip("anthropic")
    from scagent.providers.anthropic_provider import AnthropicProvider

    sent = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        sent.append((dict(request.headers), body))
        if len(sent) == 1:
            content = [
                {"type": "text", "text": "I'll look up the order first."},
                {"type": "tool_use", "id": "toolu_1", "name": "get_order_details", "input": {"order_id": "ORD-9999"}},
            ]
        else:
            content = [{"type": "tool_use", "id": "toolu_2", "name": "submit_report", "input": _report_input()}]
        return httpx.Response(200, json={
            "id": f"msg_{len(sent)}", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": content, "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })

    client = anthropic.Anthropic(api_key="test-key", base_url="http://mock.local",
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = investigate("Investigate ORD-9999", AnthropicProvider("claude-opus-5-5", client=client), cfg)

    headers, first = sent[0]
    assert first["model"] == "claude-opus-5-5"
    assert {t["name"] for t in first["tools"]} == {
        "get_order_details", "get_shipment_status", "check_inventory", "find_alternative_stock",
        "get_carrier_alerts", "submit_report"}
    assert all("input_schema" in t for t in first["tools"])
    assert first["fallbacks"] == "default" and first["output_config"] == {"effort": "medium"}
    assert "server-side-fallback-2026-07-01" in headers.get("anthropic-beta", "")

    _, second = sent[1]
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert tool_result["is_error"] is True and "NOT_FOUND" in tool_result["content"]
    assert second["messages"][1]["role"] == "assistant"  # prior turn replayed unchanged

    assert res.report["issue_type"] == "ORDER_NOT_FOUND"
    assert res.verification["overall"] == "PASS"
    assert res.trace.steps[0]["text"] == "I'll look up the order first."


def test_openai_adapter_round_trip(cfg):
    openai = pytest.importorskip("openai")
    from scagent.providers.openai_provider import OpenAIProvider

    sent = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) == 1:
            msg = {"role": "assistant", "content": "Looking up the order.", "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "get_order_details", "arguments": json.dumps({"order_id": "ORD-9999"})}}]}
        else:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_2", "type": "function",
                "function": {"name": "submit_report", "arguments": json.dumps(_report_input())}}]}
        return httpx.Response(200, json={
            "id": f"chatcmpl-{len(sent)}", "object": "chat.completion", "created": 0, "model": "gpt-5",
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        })

    client = openai.OpenAI(api_key="test-key", base_url="http://mock.local/v1",
                           http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = investigate("Investigate ORD-9999", OpenAIProvider("gpt-5", client=client), cfg)

    assert sent[0]["tools"][0]["type"] == "function"
    tool_msg = sent[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
    assert res.report["issue_type"] == "ORDER_NOT_FOUND"
    assert res.verification["overall"] == "PASS"
