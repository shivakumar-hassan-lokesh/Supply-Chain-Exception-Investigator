"""OpenAI (or any OpenAI-compatible endpoint) provider using Chat Completions tool calling.

Reads OPENAI_API_KEY, and optionally OPENAI_BASE_URL (e.g. for a local
OpenAI-compatible server), from the environment.
"""
from __future__ import annotations

import json

from .base import ModelTurn, ToolCall, ToolResult


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, client=None):
        import os
        from urllib.parse import urlparse

        import openai  # imported lazily so tests don't need the SDK installed

        base_url = os.environ.get("OPENAI_BASE_URL")
        is_local = bool(base_url) and urlparse(base_url).hostname in ("localhost", "127.0.0.1", "::1")
        # Local servers (e.g. Ollama) need no key; don't send a real OpenAI key to them.
        self.client = client or (openai.OpenAI(api_key="local-no-key") if is_local else openai.OpenAI())
        self.model = model
        self.tools: list[dict] = []
        self.messages: list[dict] = []

    def start(self, system_prompt: str, user_message: str, tools: list[dict]) -> None:
        self.tools = [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
            for t in tools
        ]
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    def step(self) -> ModelTurn:
        response = self.client.chat.completions.create(
            model=self.model, messages=self.messages, tools=self.tools, tool_choice="auto",
        )
        choice = response.choices[0]
        msg = choice.message
        self.messages.append(msg.model_dump(exclude_none=True))

        calls = []
        for tc in msg.tool_calls or []:
            try:
                args, err = json.loads(tc.function.arguments or "{}"), None
            except json.JSONDecodeError as exc:
                args, err = None, f"Tool arguments were not valid JSON: {exc}"
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args, parse_error=err))
        usage = response.usage
        return ModelTurn(
            text=(msg.content or "").strip(),
            tool_calls=calls,
            stop_reason=choice.finish_reason or "",
            usage={
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
            },
            refused=bool(getattr(msg, "refusal", None)),
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            self.messages.append({"role": "tool", "tool_call_id": r.call_id, "content": r.content})

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
