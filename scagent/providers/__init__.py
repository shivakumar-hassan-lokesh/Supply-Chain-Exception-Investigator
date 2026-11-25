"""Choose an LLM provider from configuration (LLM_PROVIDER env var)."""
from __future__ import annotations

from ..config import Config
from .base import LLMProvider, ModelTurn, ToolCall, ToolResult

__all__ = ["make_provider", "LLMProvider", "ModelTurn", "ToolCall", "ToolResult"]


def make_provider(cfg: Config) -> LLMProvider:
    if cfg.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg.model, effort=cfg.anthropic_effort, fallbacks=cfg.anthropic_fallbacks)
    if cfg.provider == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg.model)
    raise ValueError(f"Unknown LLM_PROVIDER '{cfg.provider}'. Use 'anthropic' or 'openai'.")
