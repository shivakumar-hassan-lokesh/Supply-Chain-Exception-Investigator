# Individual contributions

> **Note for the team:** this division of work is a proposed split, drafted from the project's structure and history. Before submitting, each member should check it and edit anything that does not match what they actually did. Graders will ask each of you to explain your parts.

## Project-level note
- **Starter code origin:** the initial implementation was generated with Claude Code (AI coding assistant) starting on 2026-11-17. We then ran it with real models, reviewed it, changed the prompt, report schema and verifier based on the results, and added the website. The changes are listed below.
- **Models and providers used for live runs:**
  - `gpt-5` through the OpenAI API (main results).
  - `qwen3:8b` running locally in Ollama, for comparison.
- **Live results (details in `docs/RESULTS.md`):**

  | Version | Model | Result |
  |---|---|---|
  | Earlier version, 10 scenarios | gpt-5 | 10/10 and 9/10 (19/20) |
  | Earlier version, 10 scenarios | qwen3:8b | 7/10 and 7/10 (14/20) |
  | Current version, 13 scenarios × 2 runs | gpt-5 | 19/26 passed; issue accuracy 100%, cause accuracy 100%, action recall 100%, action precision 92% |

---

## Member 1: Nishchay Linge Gowda  NUID: 002309438

**Primary responsibilities:** the agent loop, LLM providers, live runs and evaluation, and the website.

**Work completed**
| Date | What I did | Files | Evidence |
|---|---|---|---|
| 2026-11-17 | Set up the configurable LLM provider (env vars, no hardcoded keys). Tried Anthropic, then OpenAI, then a local Ollama model. | `scagent/config.py`, `scagent/providers/`, `.env.example` | `tests/test_providers_wire.py` |
| 2026-11-17 | Agent loop: the model chooses tools, Python validates arguments and enforces the tool-call and turn limits, and a fallback report is used if the model never submits one | `scagent/agent.py`, `scagent/trace.py` | `tests/test_agent_loop.py` |
| 2026-11-17 | Ran the live scenario evaluations (qwen3:8b baseline and tuned; gpt-5 runs 1 and 2; gpt-5 eval 1 on the current version) | `scagent/scenarios.py`, `traces/examples/REAL_*` | `docs/RESULTS.md`, `REAL_*_summary_*.json` |
| 2026-11-17 | Tuned the system prompt after failures: quoted evidence, no guessing when a record is missing, never describing a failed record | `scagent/agent.py` | `docs/RESULTS.md` (Part B changes table) |
| 2026-11-17–18 | Website: live investigation timeline, scenario cards, orders browser, evaluation view, How it works page, report and trace downloads | `scagent/web.py`, `scagent/static/index.html` | `tests/test_web.py` |
| 2026-11-17 | One-step launcher and packaging for sharing | `start.sh`, `start.bat`, `package.sh` | `dist/` zip |
| | Command-line interface (`investigate`, `scenarios`, `tool`, `truth`, `web`) | `scagent/cli.py` | |

**Changes I made to the starter code, and why**
- Made API errors give clearer hints (bad key versus no credits), because real runs hit both.
- Allowed a local OpenAI-compatible server (Ollama) so the agent could run without paid credits.
- Moved the live investigation into its own website tab so the professor can watch every decision, tool call and result.

**Tests and scenarios I ran or wrote**
- All live scenario runs with gpt-5 and qwen3:8b.
- `test_agent_loop.py`, `test_providers_wire.py`, `test_web.py`.

**A part of the system I can explain in detail**
- How `investigate()` in `agent.py` passes tool requests from the model to Python and results back. The model decides the next step; Python only enforces the rules.

**Problems I hit and how I solved them**
- **Anthropic key rejected, then no OpenAI credits:** used a local Ollama model, then switched back to OpenAI once credits were added.
- **The small model claimed success after a tool failure:** the verifier caught it (`failure_honesty`); this is documented as a real failure case.

---

## Member 2: ShivaKumar Hassan Lokesh  NUID: 002058166

**Primary responsibilities:** data, tools, the report format, the verifier, scenario definitions, tests and documentation.

**Work completed**
| Date | What I did | Files | Evidence |
|---|---|---|---|
| 2026-11-17 | Fictional database: 12 orders designed to cover each problem type, including the carrier alerts (one matching, one decoy), ship-by dates, and the investigation date 2026-03-16 | `data/schema.sql`, `data/seed.sql`, `scagent/db.py` | `python -m scagent truth ORD-1001` |
| 2026-11-17 | The five read-only tools: order details, shipment status, inventory, alternative stock, carrier alerts | `scagent/tools.py` | `tests/test_tools.py` |
| 2026-11-17 | Tool registry, JSON schemas, argument validation and structured error codes (`INVALID_ARGUMENT`, `NOT_FOUND`, `TOOL_FAILURE`, …), plus simulated tool outages | `scagent/executor.py` | `tests/test_executor.py` |
| 2026-11-17 | Report format: issue types, cause categories, action catalog, report validation | `scagent/report.py` | `tests/test_agent_loop.py` (rejected reports) |
| 2026-11-17 | Verifier: checks every report against the database (IDs, dates, issue, cause, actions, honesty after a failure) | `scagent/verifier.py` | `tests/test_verifier.py` |
| 2026-11-17 | 13 test scenarios with acceptable answers, and the scoring (issue and cause accuracy, action recall and precision) | `scenarios/scenarios.json`, `scagent/scenarios.py` | `tests/test_scenario_definitions.py` |
| 2026-11-17–18 | README, demo script, work plan, results write-up | `README.md`, `docs/` | |

**Changes I made to the starter code, and why**
- Broadened the verifier's ID pattern after a live run wrote "SPH-5003" and it went unnoticed (regression test `test_mistyped_id_is_caught`).
- Allowed future dates in recommended actions (for example a follow-up date), which had caused a false failure.
- Renamed `NO_ACTION_MONITOR` to `NO_ACTION_NEEDED` after evaluation 1 showed the model misreading it as "keep monitoring" (6 of 7 failures).
- Accepted DELAYED_DELIVERY for ORD-1007 when the cause is MISSING_SHIPMENT_RECORD (documented in `docs/RESULTS.md`).

**Tests and scenarios I ran or wrote**
- `test_tools.py`, `test_executor.py`, `test_verifier.py`, `test_scenario_definitions.py`.
- The scenario definitions in `scenarios/scenarios.json`.

**A part of the system I can explain in detail**
- How `verifier.py` computes the correct answer from the database with plain SQL rules and compares the model's report against it, so results are not accepted only because the model claims success.

**Problems I hit and how I solved them**
- **Mistyped ID ("SPH-5003") passed the verifier:** fixed the pattern and added a regression test.
- **Scoring wording problems (the "monitor" action name, the meaning of "confirmed"):** fixed the wording without changing what is scored.

---

## Shared work
| Item | Who | Notes |
|---|---|---|
| Choosing the problem types and scenarios | both | Professor's advice: fictional data, 2–3 shipment problem types |
| Reviewing evaluation results | both | `docs/RESULTS.md` |
| README review | both | |
| Demo rehearsal | both | Follow `docs/DEMO.md` |
