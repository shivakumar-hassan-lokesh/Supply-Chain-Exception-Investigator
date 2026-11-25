"""Execution trace: an ordered record of every model decision and tool execution.

Saved as JSON (machine-readable, used by tests and the verifier) and Markdown
(human-readable, for the demo and the submission).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable


class Trace:
    def __init__(self, request: str, meta: dict, printer: Callable[[str], None] | None = None,
                 on_step: Callable[[dict], None] | None = None):
        self.request = request
        self.meta = meta
        self.steps: list[dict] = []
        self.report: dict | None = None
        self.verification: dict | None = None
        self._print = printer        # CLI: receives a formatted line per step
        self._on_step = on_step      # web UI: receives the structured step dict

    # -- recording -------------------------------------------------------- #
    def add(self, kind: str, **data) -> dict:
        step = {"step": len(self.steps) + 1, "type": kind, **data}
        self.steps.append(step)
        if self._print:
            self._print(self._format_step(step))
        if self._on_step:
            self._on_step(step)
        return step

    def tool_executions(self) -> list[dict]:
        return [s for s in self.steps if s["type"] == "tool_execution"]

    # -- output ----------------------------------------------------------- #
    def to_dict(self) -> dict:
        return {
            "request": self.request,
            "meta": self.meta,
            "steps": self.steps,
            "final_report": self.report,
            "verification": self.verification,
        }

    def save(self, directory: Path, label: str) -> tuple[Path, Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = directory / f"{stamp}_{label}"
        json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
        json_path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        md_path.write_text(self.to_markdown())
        return json_path, md_path

    def to_markdown(self) -> str:
        from .report import render_report

        lines = [
            "# Execution trace",
            "",
            f"- **Request:** {self.request}",
            *[f"- **{k}:** {v}" for k, v in self.meta.items()],
            "",
            "## Steps",
            "",
        ]
        for s in self.steps:
            lines.append(f"### Step {s['step']}: {s['type']}")
            lines.append("```")
            lines.append(self._format_step(s, full=True))
            lines.append("```")
        if self.report:
            lines += ["", "## Final report", "```", render_report(self.report), "```"]
        if self.verification:
            lines += ["", "## Evidence verification (Python, not the model)", ""]
            for c in self.verification["checks"]:
                lines.append(f"- **{c['status'].upper()}** `{c['name']}`: {c['detail']}")
            lines.append(f"\n**Overall:** {self.verification['overall']}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_step(s: dict, full: bool = False) -> str:
        t = s["type"]
        if t == "model_turn":
            out = []
            if s.get("text"):
                out.append(f"[model says] {s['text']}")
            for c in s.get("tool_requests", []):
                out.append(f"[model requests] {c['name']}({json.dumps(c['arguments'])})")
            if not out:
                out.append(f"[model] (no text, no tool call; stop_reason={s.get('stop_reason')})")
            return "\n".join(out)
        if t == "tool_execution":
            res = s["result"]
            status = "ok" if res["ok"] else f"ERROR {res['error']['code']}"
            fn = s["meta"].get("python_function") or "(none: not executed)"
            body = json.dumps(res, indent=2 if full else None, default=str)
            if not full and len(body) > 400:
                body = body[:400] + " ..."
            return f"[python] {fn} executed={s['meta']['executed']} -> {status} ({s['meta']['duration_ms']} ms)\n[result] {body}"
        if t == "final_report":
            return f"[model submitted report] issue_type={s['report'].get('issue_type')}"
        if t == "report_rejected":
            return f"[python] submit_report rejected: {s['problems']}"
        if t == "limit_reached":
            return f"[python] tool-call limit reached ({s['limit']}); request refused: {s['tool']}"
        if t == "nudge":
            return f"[python] {s['message']}"
        if t == "stopped":
            return f"[python] loop stopped: {s['reason']}"
        return json.dumps(s, default=str)
