"""Generate ILLUSTRATIVE example traces using the scripted TEST DOUBLE (no LLM).

These show the trace FORMAT only. They are not real model runs. Real traces are
produced by `python -m scagent investigate ...` / `python -m scagent scenarios`.

    python tests/make_illustrative_traces.py
"""
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fakes import ScriptedProvider, reactive_policy  # noqa: E402

from scagent.agent import investigate  # noqa: E402
from scagent.config import load_config  # noqa: E402
from scagent.db import init_db  # noqa: E402

OUT = HERE.parent / "traces" / "examples"
BANNER = ("ILLUSTRATIVE ONLY: produced by the scripted test double in tests/fakes.py, "
          "NOT by a language model. It shows the trace format.")


def main():
    cfg = load_config()
    init_db(cfg.db_path)
    cases = [
        ("ILLUSTRATIVE_test_double_S1_shortage", "Order ORD-1001 hasn't shipped yet. Investigate why and what we should do.", set()),
        ("ILLUSTRATIVE_test_double_S4_tool_failure", "Investigate why order ORD-1003 is delayed.", {"get_shipment_status"}),
    ]
    for label, request, failing in cases:
        c = replace(cfg, failing_tools=failing)
        res = investigate(request, ScriptedProvider(reactive_policy), c)
        res.trace.meta = {"WARNING": BANNER, **res.trace.meta}
        md = OUT / f"{label}.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(f"> **{BANNER}**\n\n" + res.trace.to_markdown())
        print("wrote", md)


if __name__ == "__main__":
    main()
