"""Web interface for the investigation agent (Flask).

    python -m scagent web                 # http://127.0.0.1:8000, this computer only
    python -m scagent web --host 0.0.0.0  # also reachable from your local network

The page calls the SAME `investigate()` function as the CLI. Each step of the
trace is streamed to the browser as one JSON line (NDJSON) the moment it
happens, so viewers watch the model decide, the tools run, and the verifier
check the report.

Safety for shared use:
  * WEB_ACCESS_CODE (env): if set, every API call must send it (header X-Access-Code).
  * WEB_MAX_CONCURRENT (env, default 2): investigations running at once.
  * Requests are length-limited; only known tool names may be "failed".
Every investigation spends API credits on the key configured in .env.
"""
from __future__ import annotations

import hmac
import json
import os
import queue
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from flask import Flask, Response, jsonify, request, send_from_directory

from .config import PROJECT_ROOT, Config, load_config
from .db import connect, init_db
from .executor import TOOL_SPECS
from .report import ACTION_CATALOG, CAUSE_CATEGORIES, render_report
from .scenarios import load_scenarios
from .verifier import reference_assessment

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_REQUEST_CHARS = 500


def create_app(cfg: Config | None = None, provider_factory: Callable | None = None,
               access_code: str | None = None, max_concurrent: int | None = None) -> Flask:
    from .agent import investigate

    cfg = cfg or load_config()
    if provider_factory is None:
        from .providers import make_provider as provider_factory
    access_code = access_code if access_code is not None else os.environ.get("WEB_ACCESS_CODE", "")
    slots = threading.BoundedSemaphore(max_concurrent or int(os.environ.get("WEB_MAX_CONCURRENT", "2")))
    if not Path(cfg.db_path).exists():
        init_db(cfg.db_path)

    app = Flask(__name__, static_folder=None)

    @app.before_request
    def check_access():
        if request.path.startswith("/api/") and access_code:
            supplied = request.headers.get("X-Access-Code", "")
            if not hmac.compare_digest(supplied.encode(), access_code.encode()):
                return jsonify({"error": "Access code required or incorrect."}), 401
        return None

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/meta")
    def meta():
        return jsonify({
            "provider": cfg.provider,
            "model": cfg.model,
            "investigation_date": cfg.investigation_date.isoformat(),
            "max_tool_calls": cfg.max_tool_calls,
            "tools": [{"name": s.name, "description": s.description} for s in TOOL_SPECS.values()],
            "causes": CAUSE_CATEGORIES,
            "actions": ACTION_CATALOG,
            "examples": [{"id": s["id"], "request": s["request"], "fail_tools": s.get("fail_tools", []),
                          "expected": s["expected_facts"]} for s in load_scenarios()],
            "access_code_required": bool(access_code),
        })

    @app.get("/api/data")
    def data():
        """The whole fictional database, so viewers can check the agent's claims themselves."""
        conn = connect(cfg.db_path)
        try:
            def rows(sql):
                return [dict(r) for r in conn.execute(sql).fetchall()]
            return jsonify({
                "orders": rows("SELECT o.*, GROUP_CONCAT(oi.sku || ' x' || oi.quantity, ', ') AS items "
                               "FROM orders o LEFT JOIN order_items oi USING(order_id) "
                               "GROUP BY o.order_id ORDER BY o.order_id"),
                "inventory": rows("SELECT sku, warehouse_id, on_hand, reserved, on_hand - reserved AS available "
                                  "FROM inventory ORDER BY sku, warehouse_id"),
                "alerts": rows("SELECT * FROM carrier_alerts ORDER BY start_date DESC"),
                "shipments": rows("SELECT shipment_id, order_id, carrier, tracking_number, status, dispatch_date, "
                                  "original_estimated_date, current_estimated_date, delivered_date, delay_reason "
                                  "FROM shipments ORDER BY shipment_id"),
            })
        finally:
            conn.close()

    @app.get("/api/evaluation")
    def evaluation():
        """The most recent scenario evaluation that has accuracy metrics (from `python -m scagent scenarios`)."""
        candidates = sorted(Path(cfg.trace_dir).rglob("summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("metrics"):
                rel = path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path.name
                root = Path(cfg.trace_dir)

                def trace_id(r):
                    # Scenario traces are saved next to summary.json as <time>_<scenario>_run<n>.json
                    hits = sorted(path.parent.glob(f"*_{r['scenario']}_run{r.get('run', 1)}.json"))
                    return hits[-1].relative_to(root).as_posix() if hits else None

                return jsonify({
                    "file": str(rel), "provider": data.get("provider"), "model": data.get("model"),
                    "created": data.get("created"), "repeat": data.get("repeat", 1),
                    "passed": data.get("passed"), "total": data.get("total"), "metrics": data["metrics"],
                    "results": [{"scenario": r["scenario"], "run": r.get("run", 1), "passed": r["passed"],
                                 "scores": r.get("scores", {}), "report": r.get("report", {}),
                                 "failed_checks": [c for c in r["checks"] if c["status"] != "pass"],
                                 "trace_id": trace_id(r)}
                                for r in data.get("results", [])],
                })
        return jsonify({"metrics": None})

    @app.get("/api/order/<order_id>")
    def order_detail(order_id: str):
        """Everything stored about one order, for the Orders explorer drawer (read directly, not via the agent)."""
        if len(order_id) > 20:
            return jsonify({"error": "invalid order id"}), 400
        conn = connect(cfg.db_path)
        try:
            order = conn.execute("SELECT o.*, w.name AS warehouse_name FROM orders o "
                                 "JOIN warehouses w USING(warehouse_id) WHERE order_id = ?", (order_id,)).fetchone()
            if order is None:
                return jsonify({"error": f"No order {order_id}"}), 404
            items = [dict(r) for r in conn.execute(
                "SELECT oi.sku, p.name AS product_name, oi.quantity FROM order_items oi "
                "JOIN products p USING(sku) WHERE order_id = ? ORDER BY sku", (order_id,))]
            for it in items:
                it["stock"] = [dict(r) for r in conn.execute(
                    "SELECT warehouse_id, on_hand - reserved AS available FROM inventory WHERE sku = ? "
                    "ORDER BY warehouse_id", (it["sku"],))]
            shipments = [dict(r) for r in conn.execute("SELECT * FROM shipments WHERE order_id = ?", (order_id,))]
            for s in shipments:
                s["events"] = [dict(r) for r in conn.execute(
                    "SELECT event_date, location, event_type, description FROM shipment_events "
                    "WHERE shipment_id = ? ORDER BY event_date, event_id", (s["shipment_id"],))]
                s["carrier_alerts"] = [dict(r) for r in conn.execute(
                    "SELECT * FROM carrier_alerts WHERE carrier = ? ORDER BY start_date DESC", (s["carrier"],))]
            return jsonify({"order": dict(order), "items": items, "shipments": shipments,
                            "investigation_date": cfg.investigation_date.isoformat()})
        finally:
            conn.close()

    def _trace_files():
        root = Path(cfg.trace_dir)
        files = [p for p in root.rglob("*.json") if p.name != "summary.json"] if root.exists() else []
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    @app.get("/api/history")
    def history():
        """Recent saved runs (website, CLI and evaluations) that can be replayed without calling the model."""
        root = Path(cfg.trace_dir)
        out = []
        for path in _trace_files()[:60]:
            try:
                d = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            rep, ver = d.get("final_report") or {}, d.get("verification") or {}
            if not rep or not d.get("steps"):
                continue  # nothing to replay
            out.append({"id": path.relative_to(root).as_posix(), "request": d.get("request"),
                        "model": (d.get("meta") or {}).get("model"), "scenario": (d.get("meta") or {}).get("scenario"),
                        "order_id": rep.get("order_id"), "issue_type": rep.get("issue_type"),
                        "cause_category": rep.get("cause_category"), "overall": ver.get("overall"),
                        "steps": len(d.get("steps") or []), "modified": int(path.stat().st_mtime)})
        return jsonify({"runs": out})

    @app.get("/api/trace")
    def trace_file():
        """One saved trace, by the id that /api/history returned (path inside the traces folder only)."""
        root = Path(cfg.trace_dir).resolve()
        rel = request.args.get("id", "")
        target = (root / rel).resolve()
        if (not rel or not target.is_relative_to(root) or target.suffix != ".json"
                or target.name == "summary.json" or not target.is_file()):
            return jsonify({"error": "Unknown trace"}), 404
        d = json.loads(target.read_text())
        if d.get("final_report"):
            d["rendered"] = render_report(d["final_report"])
        return jsonify(d)

    @app.get("/api/truth/<order_id>")
    def truth(order_id: str):
        if len(order_id) > 20:
            return jsonify({"error": "invalid order id"}), 400
        return jsonify(reference_assessment(cfg.db_path, order_id, cfg.investigation_date))

    @app.post("/api/investigate")
    def run_investigation():
        body = request.get_json(silent=True) or {}
        text = str(body.get("request", "")).strip()
        fail_tools = body.get("fail_tools") or []
        if not text:
            return jsonify({"error": "Please enter a request."}), 400
        if len(text) > MAX_REQUEST_CHARS:
            return jsonify({"error": f"Request is limited to {MAX_REQUEST_CHARS} characters."}), 400
        if not isinstance(fail_tools, list) or any(t not in TOOL_SPECS for t in fail_tools):
            return jsonify({"error": "fail_tools must be a list of known tool names."}), 400
        if not slots.acquire(blocking=False):
            return jsonify({"error": "The agent is busy with other investigations. Try again in a minute."}), 429

        run_cfg = replace(cfg, failing_tools=set(fail_tools))
        events: queue.Queue = queue.Queue()

        def worker():
            try:
                provider = provider_factory(run_cfg)
                result = investigate(text, provider, run_cfg,
                                     on_step=lambda s: events.put({"event": "step", "step": s}))
                json_path, _ = result.trace.save(run_cfg.trace_dir / "web", result.report.get("order_id") or "run")
                events.put({"event": "done", "report": result.report, "rendered": render_report(result.report),
                            "verification": result.verification, "tool_calls_used": result.tool_calls_used,
                            "trace_file": str(json_path.relative_to(PROJECT_ROOT)) if json_path.is_relative_to(PROJECT_ROOT) else json_path.name,
                            "trace_id": json_path.relative_to(Path(run_cfg.trace_dir)).as_posix()})
            except Exception as exc:  # never leave the browser hanging
                events.put({"event": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                slots.release()
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def stream():
            yield json.dumps({"event": "start", "request": text, "fail_tools": fail_tools,
                              "provider": run_cfg.provider, "model": run_cfg.model}) + "\n"
            while True:
                item = events.get()
                if item is None:
                    break
                yield json.dumps(item, default=str) + "\n"

        return Response(stream(), mimetype="application/x-ndjson",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def _key_problem(cfg: Config) -> str | None:
    """Explain a missing API key in plain words (None if the provider looks configured)."""
    if cfg.provider == "openai":
        if os.environ.get("OPENAI_BASE_URL", "").startswith(("http://localhost", "http://127.0.0.1")):
            return None  # local model server, no key needed
        return None if os.environ.get("OPENAI_API_KEY") else "OPENAI_API_KEY is empty"
    if cfg.provider == "anthropic":
        return None if os.environ.get("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY is empty"
    return f"unknown LLM_PROVIDER '{cfg.provider}'"


def run_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False) -> None:
    cfg = load_config()
    local_only = host in ("127.0.0.1", "localhost")
    # The access code protects a shared server. On localhost only you can reach it, so it is off.
    code = "" if local_only else os.environ.get("WEB_ACCESS_CODE", "")
    app = create_app(cfg, access_code=code)
    url = f"http://localhost:{port}" if local_only else f"http://<this-computer's-IP>:{port}"

    print("\n  Supply Chain Exception Investigator")
    print(f"  Open:     {url}")
    print(f"  Model:    {cfg.model} ({cfg.provider})")
    print(f"  Access:   {'this computer only' if local_only else 'your network'}"
          f"{'' if local_only else (', access code ON' if code else ', NO access code')}")
    problem = _key_problem(cfg)
    if problem:
        print(f"\n  WARNING: {problem}. Investigations will fail until you add your key to .env")
        print("           (see .env.example), then restart.")
    if not local_only and not code:
        print("\n  WARNING: reachable from other machines without an access code; every visitor's "
              "investigation is billed to your API key. Set WEB_ACCESS_CODE in .env.")
    print("\n  Press Ctrl+C to stop.\n")
    if open_browser:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host=host, port=port, threaded=True, debug=False)
