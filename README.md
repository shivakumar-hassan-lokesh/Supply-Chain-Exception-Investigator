# Supply Chain Exception Investigation Agent

CSYE 7374 Agentic AI mini project: an agent that **identifies shipment delays, investigates their causes, and recommends possible solutions**. You give it a request such as *"Investigate why order ORD-1003 is delayed."* The agent then:

1. **chooses its own tools** to gather evidence from a fictional SQLite database (orders, shipments, tracking events, inventory, carrier service alerts),
2. **identifies the problem**: a delayed delivery, an inventory shortage, no problem, or missing data,
3. **finds the cause**, as one of 6 categories: carrier-reported delay, carrier service disruption, stalled tracking, late warehouse dispatch, stock shortage, or missing shipment record,
4. **recommends data-driven actions** from a fixed catalog (transfer stock, expedite replenishment, contact the carrier, notify the customer, escalate to the warehouse, and others). Each action cites its evidence. It recommends only and never acts.

After every run, Python checks the report against the tool results and the database. The report is never accepted just because the model says it is right. **Success is measured** by issue accuracy, cause accuracy, action recall and precision, and the evidence-grounding rate across 13 test scenarios (section 6).

- **Language model:** a real one, with Anthropic Claude as the default. Any OpenAI-compatible API also works.
- **Stack:** plain Python and SQLite, with no LangGraph. There's an optional local website, plus a command-line interface.

## Quick start (anyone, about 2 minutes)

You need Python 3.10 or newer and an API key (OpenAI or Anthropic), or Ollama for a free local model.

| Your computer | Do this |
|---|---|
| macOS / Linux | Open a terminal in this folder and run `./start.sh` |
| Windows | Double-click `start.bat` |

The first run creates a private environment, installs everything, and asks which model to use and for your key. On macOS/Linux it asks in the terminal, with hidden typing. On Windows, it opens `.env` in Notepad. Then your browser opens the website at **http://localhost:8000**. Later runs just start the site. The site runs only on your own computer, and investigations are billed to your own key.

**Sharing the project:** run `./package.sh` to get `dist/supply-chain-agent-<date>.zip`. It leaves out `.env` (your key), the environment and run logs, and refuses to build if a key-shaped string is found anywhere. Send the zip; the recipient unzips it and runs `./start.sh` or `start.bat`. **Don't share the folder itself**, because it contains your `.env`.

---

## 1. Architecture

```
            ┌──────────────────────── agent.py (loop) ────────────────────────┐
 request ──►│ model (providers/) ──tool request──► executor.py ──► tools.py ──┼──► SQLite (read-only)
            │      ▲                  validate args    run SQL      │         │
            │      └──────── structured result / error ◄────────────┘         │
            │ model ──submit_report──► report.py (schema check)               │
            └───────────────────────────────┬─────────────────────────────────┘
                                            ▼
                         verifier.py: report vs. tool results vs. database
                                            ▼
                         trace.py: JSON + Markdown execution trace
```

| File | Responsibility |
|---|---|
| `scagent/agent.py` | The loop. It sends the request and tool definitions to the model, runs the model's tool requests, returns the results, and repeats until the model calls `submit_report`. It enforces the tool-call and turn limits. |
| `scagent/providers/` | Adapters for each model provider (`anthropic_provider.py`, `openai_provider.py`), selected with `LLM_PROVIDER`. |
| `scagent/executor.py` | Tool registry, JSON schemas, argument validation, error envelopes, and fault injection. |
| `scagent/tools.py` | The five read-only tools: `get_order_details`, `get_shipment_status`, `check_inventory`, `find_alternative_stock`, `get_carrier_alerts`. They use parameterized SQL and compute derived values (available stock, days overdue, days dispatched late, days since the last scan) in Python. |
| `scagent/report.py` | The `submit_report` schema, report validation, and the plain-text report renderer. |
| `scagent/verifier.py` | Evidence checks, plus `reference_assessment()`, which works out the true answer for an order directly from SQL. |
| `scagent/scenarios.py` + `scenarios/scenarios.json` | Scenario expectations and how they are scored. |
| `scagent/trace.py` | Records each model turn and tool execution, then saves them as JSON and Markdown. |
| `scagent/cli.py` | The command-line interface. |
| `scagent/web.py` + `scagent/static/index.html` | The website: a Flask backend that streams each trace step to the browser, and a single-page front end with no external libraries. |

### Key design decisions (be ready to explain these)

1. **The model decides; Python enforces.** The loop has no `if order shipped then call X` logic. The model sees the tool descriptions and earlier results and picks the next call. Python only validates arguments, runs the tools, caps the number of calls, and checks the report.
2. **The final answer is a tool call (`submit_report`), not free text.** This gives a structured report (issue type, evidence, cause status, recommendation, completeness flag) that can be checked field by field. Python rejects invalid reports and sends the error back so the model can fix them.
3. **Tools do the arithmetic.** `available = on_hand - reserved`, `days_past_promised_date`, `is_overdue` and `warehouses_with_sufficient_stock` are computed in Python. This keeps date and stock math away from the model, which is a common source of hallucinated numbers.
4. **Every tool result uses one envelope.** It is either `{"ok": true, "data": ...}` or `{"ok": false, "error": {"code", "message"}}`, with error codes `INVALID_ARGUMENT`, `NOT_FOUND`, `TOOL_FAILURE`, `UNKNOWN_TOOL` and `TOOL_LIMIT_REACHED`. Invalid requests are rejected *before* anything runs (`executed: false` in the trace).
5. **Verification is independent of the model.** See section 6.
6. **Reproducible.** "Today" is fixed by `INVESTIGATION_DATE` (default `2026-03-16`), and the database is rebuilt from SQL files.
7. **Read-only by construction.** Tools open SQLite in `mode=ro`. The agent can only *recommend* actions.

### Folder structure

```
supply-chain-agent/
├── README.md               ← you are here
├── start.sh  start.bat    ← one-step launchers (website)
├── package.sh              ← builds a shareable zip without secrets
├── requirements.txt        .env.example        pytest.ini       demo.sh
├── data/
│   ├── schema.sql          ← tables: warehouses, products, orders, order_items,
│   └── seed.sql               inventory, shipments, shipment_events (all fictional)
├── scagent/                ← the agent package (see table above)
│   ├── providers/
│   └── static/index.html   ← the website front end
├── scenarios/scenarios.json
├── tests/                  ← offline tests + live tests + test doubles
├── traces/examples/        ← example traces (see traces/examples/README.md)
└── docs/
    ├── DEMO.md             ← demonstration script
    ├── WORK_PLAN.md        ← four-week plan
    ├── CONTRIBUTIONS.md    ← individual contribution template
    └── RESULTS.md          ← live scenario results and prompt-tuning log
```

---

## 2. Installation

Requires Python 3.10 or later.

```bash
cd supply-chain-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then put your API key in .env
python -m scagent init-db   # creates data/supply_chain.db
```

Configuration is read from environment variables or `.env`. API keys are never written in the code.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` (any OpenAI-compatible API; set `OPENAI_BASE_URL` for others) |
| `LLM_MODEL` | `claude-opus-5-5` / `gpt-5` | Model ID |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | none | Read by the SDKs |
| `INVESTIGATION_DATE` | `2026-03-16` | Treated as "today" |
| `MAX_TOOL_CALLS` | `8` | Maximum data-tool calls per investigation |
| `MAX_MODEL_TURNS` | `12` | Maximum model turns, as a second guard against loops |
| `FAIL_TOOLS` | empty | Comma-separated tools that simulate an outage |
| `ANTHROPIC_EFFORT` | `medium` | Reasoning effort for Claude |
| `ANTHROPIC_FALLBACKS` | `default` | Server-side refusal fallback (`off` to disable) |

---

## 3. Running

### Website (easiest way to see it work)

```bash
python -m scagent web          # then open http://localhost:8000
```

Pick a scenario card (or an order, or type a question) and press **Run investigation** (or Ctrl/⌘ + Enter).

| Tab | What it shows |
|---|---|
| **Investigate** | The question form, with an optional order picker and collapsible **Demo controls** for simulated tool outages, plus scenario cards ("Use scenario" / "Run now"). While a run is in progress, a compact progress card shows the latest real event, with a **View live investigation** button. When it finishes, the final report appears: issue, cause, numbered actions, evidence grouped by source tool (expandable), limitations, a verification ring, and **Model vs. database**. You can copy the report, or download it (Markdown) or the full execution trace (JSON). |
| **Orders** | Search and status filters over all 12 orders. **Details** opens the stock, tracking timeline and carrier alerts; **Investigate this order** fills in the form. |
| **Live Investigation** | A decision map plus a timeline built only from real execution events. Each card shows the tool, its status (running / succeeded / failed / missing information), its duration, and a readable summary, and expands to the arguments and returned data. There are Expand all, Collapse all and Auto-scroll controls, and a green or red dot on the tab shows run status. Runs continue when you switch tabs, and the trace stays after completion. **Saved runs** can be replayed with no model call. |
| **Evaluation** | Accuracy metrics and a scenario × run pass/fail matrix. Click a cell for details or to replay that run. |
| **How it works** | Five flashcards (request, decision, tool execution, evidence review, final report), each flipping to an example. **Walk through an example** is a step-by-step tour, clearly labelled *illustrative*. It also shows the different paths recorded in real runs, and reference lists of tools, causes and actions. |

The site uses a dark theme by default (with a light toggle) and works at phone, tablet and desktop widths. It's keyboard accessible (arrow keys move between tabs, and focus is always visible), and it turns off animation for users who have reduced motion enabled. It calls the same `investigate()` function as the CLI, and every web run is saved to `traces/web/`.

### Command line

```bash
# One investigation, showing each step live. Saves traces/<time>_<order>.json and .md
python -m scagent investigate "Investigate why order ORD-1003 is delayed."

# Simulate a tool outage
python -m scagent investigate "Investigate why order ORD-1003 is delayed." --fail-tool get_shipment_status

# Run every evaluation scenario with the real model and score them
python -m scagent scenarios            # or: --only S1_shortage_with_alternative S4_tool_failure

# Check facts without the model
python -m scagent tool get_order_details '{"order_id": "ORD-1001"}'
python -m scagent truth ORD-1001       # what the database says the right answer is
```

`investigate` exits with code 0 when verification passes and 1 when it fails.

---

## 4. How the agent chooses tools

The model receives five data tools and `submit_report`. Each tool has a description and a JSON schema (`scagent/executor.py`). The system prompt (`scagent/agent.py`) describes the job and the honesty rules but **does not prescribe an order of calls**. On each turn the model:

1. writes a short sentence saying what it will check and why (this text is recorded in the trace),
2. asks for one or more tools with arguments,
3. sees the structured results and decides what to do next.

Typical adaptive behavior (what you should see in real traces):

| What the model sees | Typical next step |
|---|---|
| `fulfillment_status = PENDING_FULFILLMENT` | `check_inventory` for **each** line item at the order's warehouse |
| `available < quantity` | `find_alternative_stock` with the shortfall, excluding the order's warehouse |
| `warehouses_with_sufficient_stock = []` | **No** transfer recommendation (`recommended_source_warehouse = null`) |
| `fulfillment_status = SHIPPED` | `get_shipment_status` |
| `recorded_delay_reason` present | Cause CARRIER_REPORTED_DELAY (confirmed); NOTIFY_CUSTOMER with the revised ETA |
| `dispatched_late = true` (dispatch after ship-by date) | Cause LATE_DISPATCH; ESCALATE_TO_WAREHOUSE |
| Overdue, no delay reason, last scan days ago at a hub | `get_carrier_alerts` for that carrier and location |
| An alert matches the carrier, location and dates | Cause CARRIER_SERVICE_DISRUPTION (suspected); CONTACT_CARRIER |
| No matching alert | Cause TRACKING_STALLED; CONTACT_CARRIER for a trace |
| Pending order past its promise date, stock short | Cause STOCK_SHORTAGE; TRANSFER_STOCK (if a source exists) **and** NOTIFY_CUSTOMER |
| `NOT_FOUND` / `TOOL_FAILURE` | Report it; `investigation_complete = false` when it blocks a conclusion |

---

## 5. Testing

```bash
pytest -q                   # offline suite: no API key needed
RUN_LIVE=1 pytest -m live   # real model, all 13 scenarios (costs API credits)
```

| Test file | What it proves |
|---|---|
| `test_tools.py` | Tools return the right facts from the database, raise clear NOT_FOUND errors, resist SQL injection, and cannot write |
| `test_executor.py` | Bad arguments, unknown tools and outages produce structured errors, and nothing runs on invalid input |
| `test_agent_loop.py` | Loop mechanics: tool-call limit, invalid-argument recovery, parallel calls, nudge and fallback, API errors, trace contents |
| `test_verifier.py` | The verifier **catches** invented dates and IDs, unsupported transfers, claiming success after a failure, invented problems, causes without evidence (for example a "carrier disruption" without checking alerts), wrong causes, and actions without the data they need |
| `test_scenario_definitions.py` | The scenario expectations (issue, cause, actions) match the database, so a wrong expectation can't hide a wrong answer; the metric calculation is correct |
| `test_web.py` | Website endpoints, live streaming, input limits, access code, busy limit, evaluation view (uses the test double) |
| `test_providers_wire.py` | The Anthropic and OpenAI adapters work with the real installed SDKs (HTTP is mocked, no key needed) |
| `test_live_scenarios.py` | The real model passes each scenario (skipped unless `RUN_LIVE=1`) |

**About the test double.** `tests/fakes.py` contains a scripted, rule-based stand-in for the model. It exists only so the loop and verifier can be tested offline. **It is not the working agent and its output is never presented as a model run.**

### Scenarios (`scenarios/scenarios.json`)

| ID | Required # | Order | Expected outcome |
|---|---|---|---|
| S1_shortage_with_alternative | 1 | ORD-1001 | INSUFFICIENT_INVENTORY; transfer from **WH-CHI** only |
| S2_delay_with_carrier_reason | 2 | ORD-1003 | DELAYED_DELIVERY; cause **confirmed** (storm at Toledo hub), ETA 2026-03-18 |
| S3a_unknown_order | 3 | ORD-9999 | ORDER_NOT_FOUND; no invented shipment |
| S3b_missing_shipment_record | 3 | ORD-1007 | MISSING_DATA / INCONCLUSIVE; missing info listed |
| S4_tool_failure | 4 | ORD-1003 + `get_shipment_status` down | Not complete; must **not** mention storm, Toledo, SHP-5003 or the ETA |
| S5_no_exception | 5 | ORD-1005 | NO_EXCEPTION |
| X1_shortage_no_single_source | extra | ORD-1002 | Shortage; **no** transfer recommended |
| X2_multi_item_shortage | extra | ORD-1008 | Only SKU-303 is short; transfer from WH-BOS |
| X3_overdue_unknown_cause | extra | ORD-1004 | Delayed; TRACKING_STALLED or UNKNOWN; CONTACT_CARRIER; no invented weather |
| X4_pending_but_fine | extra | ORD-1009 | NO_EXCEPTION; NO_ACTION_NEEDED (no invented shortage) |
| D1_carrier_disruption_alert | delay cause | ORD-1010 | Delayed; CARRIER_SERVICE_DISRUPTION, found only through `get_carrier_alerts` (ALR-701); CONTACT_CARRIER |
| D2_late_dispatch | delay cause | ORD-1011 | Delayed; LATE_DISPATCH (ship-by 2026-03-09, dispatched 2026-03-13); ESCALATE_TO_WAREHOUSE; must not blame the old Hartford alert |
| D3_shortage_past_promise | delay cause | ORD-1012 | Shortage that has already delayed the order; TRANSFER_STOCK from WH-BOS or WH-DAL **and** NOTIFY_CUSTOMER |

Each scenario lists **acceptable** issue types, cause categories and transfer sources, the **expected actions**, terms that must and must not appear, and tools that must be used *in any order*. Expected actions are given as "required" groups (at least one action from each group) plus an "allowed" list; anything outside "allowed" counts against precision. No exact wording is required.

---

## 6. How results are verified (not just "the model said so")

`verifier.py` runs after **every** investigation, not only in tests, and prints PASS/FAIL per check:

| Check | Fails when |
|---|---|
| `model_submitted_report` | The loop ended without a valid model report |
| `order_looked_up` | The model reported on an order it never looked up |
| `ids_grounded` | The report mentions an ORD/SKU/WH/SHP/tracking ID that no tool returned |
| `dates_grounded` | The report mentions a date that no tool returned |
| `issue_supported_by_evidence` | For example, a shortage is claimed without any `check_inventory` result below the ordered quantity, or NO_EXCEPTION is claimed for a shipped order without checking the shipment |
| `transfer_recommendation_supported` | The recommended warehouse wasn't reported as sufficient by `find_alternative_stock`, **or** the database shows it can't cover the shortfall |
| `failure_honesty` | `investigation_complete = true` after an unrecovered tool failure or after hitting the tool limit |
| `cause_supported_by_evidence` | The cause has no supporting tool result. For example, CARRIER_SERVICE_DISRUPTION without an alert matching the shipment's carrier and last location, or LATE_DISPATCH without a dispatch after the ship-by date |
| `actions_supported_by_evidence` | An action lacks the data it needs: TRANSFER_STOCK without a supported source, EXPEDITE_REPLENISHMENT without a shortage, VERIFY_ORDER_ID when the order was found, RETRY_LATER with no failure, NO_ACTION_NEEDED for a real problem |
| `matches_database` | A report marked complete disagrees with `reference_assessment()` (plain SQL) on the issue |
| `cause_matches_database` | A report marked complete names a cause the database reference does not accept |
| `actions_appropriate` | *(warns, does not fail)* A required action is missing, or an action is not expected for this case |

Dates stated as facts must come from tool results. Future dates in recommended actions (proposed follow-up deadlines) are allowed.

### How success is measured

`python -m scagent scenarios --repeat 2` runs every scenario (twice here) with the real model, then prints and saves (`traces/scenarios/summary.json`):

| Metric | Meaning |
|---|---|
| Scenario pass rate | Share of runs where every check passed |
| Issue identification | Correct problem type |
| Cause accuracy | Correct cause category |
| Action recall | Share of required action groups covered |
| Action precision | Share of recommended actions that were appropriate for the case |
| Evidence grounding | Share of runs with verifier PASS (no invented IDs, dates, causes or unsupported actions) |

The website's **Evaluation** tab shows the latest results. The expected issue, cause and actions for each order come from `reference_assessment()`, a set of plain SQL rules in `verifier.py` that is independent of the model.

---

## 7. Limitations

- The data is small and fictional. Two exception types are modelled; there is no partial shipment or multi-warehouse split logic.
- Grounding checks are pattern-based (IDs and dates). A model could still paraphrase a fact incorrectly in words. The structured fields and `matches_database` reduce, but do not remove, this risk.
- `reference_assessment()` encodes *our* definition of each exception. Edge cases (for example, an order delivered exactly on its promise date) follow those rules.
- Live results depend on the model and are not fully deterministic. `gpt-5` scored 10/10 and then 9/10 with no changes in between; `qwen3:8b` produced different failures in each run (see `docs/RESULTS.md`). Run the scenarios more than once and report the pass rate.
- Even a strong model can contradict itself. In one `gpt-5` run it listed the shipment record as missing but still marked the investigation complete. The verifier flagged this, but only because the database reference disagreed; there is no direct check that "complete" agrees with "missing information".
- Small local models ignore some prompt guidance. For example, they still call inventory tools for shipped orders and rarely state a reason before each call.
- Wording can still be wrong where no ID or date is involved. In one run the model said a shipment "arrived earlier" when it was only due earlier, and no check caught it.
- Tool failure is *simulated* (`--fail-tool`). Real failures such as a missing database are also caught, but they are not part of the scenarios.
- The agent only recommends. It never changes data or contacts anyone, by design.

---

## 8. What has been executed and what you still need to run

**Offline (no API key):**
- `pytest -q`: 63 passed, 10 live tests skipped.
- Every scenario passes end to end with the **test double**.
- The Anthropic and OpenAI adapters were exercised against the installed SDKs (`anthropic 2.9.0`, `openai 3.52.0`) through a mocked HTTP transport.

**Live, with real models** (details in [docs/RESULTS.md](docs/RESULTS.md); traces in `traces/examples/REAL_*`):

| Model | Runs | Passed |
|---|---|---|
| `gpt-5`, current version (13 scenarios with causes and actions) | 2 | 19/26 passed; issue 100%, cause 100%, action recall 100%, precision 92% |
| `gpt-5`, earlier version (10 scenarios) | 2 | **10/10**, then **9/10** (19/20) |
| `qwen3:8b` (local Ollama) | 2 | 7/10, then 7/10 (14/20) |

- Both models chose different tool paths for different orders and never invented a problem in the no-exception cases.
- The verifier caught every real model error, including claiming success after a tool failure, an unsupported transfer, and conclusions that contradicted the database. One verifier gap (a mistyped ID) was found and fixed.

**Not yet run:**
- Claude. The Anthropic key was rejected (401). The adapter is tested against the SDK, but there have been no live Claude runs.

### Website: verified in a browser
`python -m scagent web` was run and driven in a browser with `gpt-5`. The ORD-1001 shortage case (3 tool calls, verification PASS) and the unknown order ORD-9999 (1 call, PASS) both streamed live; the Data tab and phone-width layout were checked.

## 9. Sharing the website with other people

**Important:** when you share *your* running server, every investigation, by anyone, is billed to the API key in `.env`. The access code applies only when the server is reachable from other machines (`--host 0.0.0.0`); on localhost it is off.

```bash
# in .env
WEB_ACCESS_CODE=pick-a-code      # visitors must enter it; the page asks for it
WEB_MAX_CONCURRENT=2             # investigations allowed at once (others get "busy")
```

| Option | Who can use it | How |
|---|---|---|
| Each person on their own computer (recommended) | Anyone with the zip from `./package.sh` | They run `./start.sh` or `start.bat` with their own key; nothing depends on your machine |
| Your computer only | You | `./start.sh` or `python -m scagent web` (binds to 127.0.0.1; no access code needed) |
| Same Wi-Fi / classroom network | Teammates, the grader during a demo | `python -m scagent web --host 0.0.0.0`, then share `http://<your-computer's-IP>:8000` |
| Temporary public link | Anyone with the link, while your laptop runs | A tunnel such as `cloudflared tunnel --url http://localhost:8000` or `ngrok http 8000` (separate tools, not included) |
| Always-on hosting | Anyone, anytime | Deploy to a host such as Render or Railway, set the API key and `WEB_ACCESS_CODE` as secrets there, and run behind a production server (for example gunicorn). Not set up in this project. |

The built-in server is Flask's development server: fine for a demo, not for heavy public traffic. Requests are capped at 500 characters, and only the four tool names can be "failed".

### Running with a local model (free)
```bash
ollama pull qwen3:8b        # any model with tool-calling support
# in .env:
LLM_PROVIDER=openai
LLM_MODEL=qwen3:8b
OPENAI_BASE_URL=http://localhost:11434/v1
```
For local servers the adapter sends a dummy key, so your real OpenAI key never goes to the local server. Expect about 2 minutes per investigation on a laptop, and lower reliability than hosted models.
