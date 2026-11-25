"""Anthropic Claude provider (official `anthropic` Python SDK, Messages API tool use).

Reads ANTHROPIC_API_KEY from the environment (the SDK does this itself).
"""
from __future__ import annotations

from .base import ModelTurn, ToolCall, ToolResult


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, effort: str = "medium", fallbacks: str = "default",
                 max_tokens: int = 16000, client=None):
        import anthropic  # imported lazily so tests don't need the SDK installed

        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        self.max_tokens = max_tokens
        self.system = ""
        self.tools: list[dict] = []
        self.messages: list = []

    def start(self, system_prompt: str, user_message: str, tools: list[dict]) -> None:
        self.system = system_prompt
        self.tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in tools
        ]
        self.messages = [{"role": "user", "content": user_message}]

    def _request_kwargs(self) -> dict:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "tools": self.tools,
            "messages": self.messages,
        }
        extra_body: dict = {}
        betas: list[str] = []
        if self.effort:
            extra_body["output_config"] = {"effort": self.effort}
        # Server-side refusal fallback: if the model declines, the API retries on a
        # fallback model in the same call. Disable with ANTHROPIC_FALLBACKS=off.
        if self.fallbacks and self.fallbacks.lower() != "off" and not self.model.startswith("claude-haiku"):
            extra_body["fallbacks"] = self.fallbacks
            betas.append("server-side-fallback-2026-07-01")
        if extra_body:
            kwargs["extra_body"] = extra_body
        if betas:
            kwargs["betas"] = betas
        return kwargs

    def step(self) -> ModelTurn:
        response = self.client.beta.messages.create(**self._request_kwargs())
        # Append the full content (including any thinking blocks) unchanged.
        self.messages.append({"role": "assistant", "content": response.content})

        text_parts, calls = [], []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                # The SDK already parsed the JSON input into a dict.
                calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))
        usage = getattr(response, "usage", None)
        return ModelTurn(
            text="\n".join(t for t in text_parts if t).strip(),
            tool_calls=calls,
            stop_reason=response.stop_reason or "",
            usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            },
            refused=response.stop_reason == "refusal",
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        # All results for one assistant turn go back in a single user message.
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                for r in results
            ],
        })

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
