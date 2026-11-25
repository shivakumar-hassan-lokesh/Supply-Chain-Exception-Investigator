"""Runtime configuration, read from environment variables (and an optional .env file).

Nothing secret is hardcoded here. API keys are read by the provider SDKs from
ANTHROPIC_API_KEY / OPENAI_API_KEY.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is optional; plain environment variables also work
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-5",
}


@dataclass
class Config:
    provider: str = "anthropic"
    model: str = ""
    db_path: Path = PROJECT_ROOT / "data" / "supply_chain.db"
    investigation_date: date = date(2026, 3, 16)
    max_tool_calls: int = 8
    max_model_turns: int = 12
    trace_dir: Path = PROJECT_ROOT / "traces"
    # Fault injection: names of tools that should simulate an outage (scenario 4).
    failing_tools: set[str] = field(default_factory=set)
    anthropic_effort: str = "medium"
    anthropic_fallbacks: str = "default"

    def __post_init__(self) -> None:
        if not self.model:
            self.model = DEFAULT_MODELS.get(self.provider, "")


def load_config(**overrides) -> Config:
    """Build a Config from environment variables, then apply explicit overrides."""
    env = os.environ
    cfg = Config(
        provider=env.get("LLM_PROVIDER", "anthropic").strip().lower(),
        model=env.get("LLM_MODEL", "").strip(),
        db_path=Path(env.get("DB_PATH", str(PROJECT_ROOT / "data" / "supply_chain.db"))),
        investigation_date=date.fromisoformat(env.get("INVESTIGATION_DATE", "2026-03-16")),
        max_tool_calls=int(env.get("MAX_TOOL_CALLS", "8")),
        max_model_turns=int(env.get("MAX_MODEL_TURNS", "12")),
        trace_dir=Path(env.get("TRACE_DIR", str(PROJECT_ROOT / "traces"))),
        failing_tools={t.strip() for t in env.get("FAIL_TOOLS", "").split(",") if t.strip()},
        anthropic_effort=env.get("ANTHROPIC_EFFORT", "medium").strip(),
        anthropic_fallbacks=env.get("ANTHROPIC_FALLBACKS", "default").strip(),
    )
    for key, value in overrides.items():
        if value is not None:
            setattr(cfg, key, value)
    if not cfg.model:
        cfg.model = DEFAULT_MODELS.get(cfg.provider, "")
    return cfg
