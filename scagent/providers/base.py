"""Provider-neutral interface used by the agent loop.

Each provider keeps its own conversation history in its own wire format and
exposes the same four methods. The agent loop never touches SDK objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any                 # parsed JSON (dict), or None if parsing failed
    parse_error: str | None = None  # set when the model produced malformed JSON


@dataclass
class ModelTurn:
    text: str                                  # visible text the model wrote (its stated reason/plan)
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    usage: dict = field(default_factory=dict)
    refused: bool = False


@dataclass
class ToolResult:
    call_id: str
    content: str     # JSON string sent back to the model
    is_error: bool


class LLMProvider(Protocol):
    name: str
    model: str

    def start(self, system_prompt: str, user_message: str, tools: list[dict]) -> None:
        """Begin a conversation. `tools` items have keys: name, description, parameters."""

    def step(self) -> ModelTurn:
        """Send the conversation so far and return the model's next turn."""

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """Append results for every tool call in the previous turn."""

    def add_user_message(self, text: str) -> None:
        """Append a plain user message (used for a single nudge to submit the report)."""
