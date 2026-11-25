"""LIVE tests: run every scenario against the real model and check the results.

Skipped unless RUN_LIVE=1 and the provider's API key is set. These cost money
and are not deterministic, so they are kept separate from the offline suite.

    RUN_LIVE=1 pytest -m live -v
"""
import os

import pytest

from scagent.agent import investigate
from scagent.config import load_config
from scagent.providers import make_provider
from scagent.scenarios import evaluate_scenario, load_scenarios, scenario_config

KEY_VAR = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
_provider = os.environ.get("LLM_PROVIDER", "anthropic")
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1" or not os.environ.get(KEY_VAR.get(_provider, "")),
                       reason="set RUN_LIVE=1 and the provider API key to run live scenarios"),
]


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda s: s["id"])
def test_live_scenario(cfg, scenario):
    live = load_config()
    c = scenario_config(live.__class__(**{**live.__dict__, "db_path": cfg.db_path,
                                          "trace_dir": cfg.trace_dir}), scenario)
    res = investigate(scenario["request"], make_provider(c), c)
    res.trace.save(c.trace_dir, scenario["id"])
    ev = evaluate_scenario(scenario, res.report, res.trace, res.verification)
    assert ev["passed"], ev["checks"]
