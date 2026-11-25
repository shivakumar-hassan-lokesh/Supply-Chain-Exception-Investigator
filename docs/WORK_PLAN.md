# Suggested four-week work plan (two people)

The code base already provides a working skeleton. The plan focuses on understanding it, running it for real, hardening it, and producing evidence. Swap roles if you prefer, but record who actually did what in `CONTRIBUTIONS.md`.

- **Member A**, data and tools: `data/`, `tools.py`, `executor.py`, `test_tools.py`, `test_executor.py`.
- **Member B**, agent and evaluation: `agent.py`, `providers/`, `verifier.py`, `scenarios`, `test_agent_loop.py`, `test_verifier.py`.

| Week | Member A | Member B | Shared milestone |
|---|---|---|---|
| **1. Understand and run** | Read the schema and seed data; explain each order's design. Run `python -m scagent tool ...` for every order. Add one new fictional order and its expected facts. | Get API access; run `investigate` on ORD-1001 and ORD-1003. Read `agent.py` line by line and explain the loop to A. | Both can run the agent and explain the architecture diagram. **First real traces saved.** |
| **2. Tools and validation** | Review the validation rules; add tests for any gaps you find. Review the tool descriptions, since these drive model decisions. | Run `python -m scagent scenarios`. Record failures and tune the **system prompt and tool descriptions** (not the code) until scenarios pass. Keep notes on what changed and why. | Scenario pass rate recorded (for example, "7/10, then 10/10 after prompt fix X"). |
| **3. Reliability** | Add one extra failure case (for example, a SKU with no inventory row, or a second simulated outage). | Run the full scenario set 3 times; record the pass rate per scenario. Try a second model or provider through `LLM_PROVIDER` / `LLM_MODEL` and compare. | `RUN_LIVE=1 pytest -m live` passing; real traces copied into `traces/examples/REAL_*`. |
| **4. Demo and docs** | Update the README limitations and the dataset description. Practice demo parts 1 and 2. | Practice demo parts 3 to 5; prepare answers to the likely questions in `DEMO.md`. | Full rehearsal with `./demo.sh`. `CONTRIBUTIONS.md` completed by both. Submit. |

## Definition of done (maps to the rubric)
- [ ] The real model passes the 5 required scenarios, with traces saved (**Working agent, 30**)
- [ ] Traces show different tool sequences for different orders (**Agentic behavior, 20**)
- [ ] Offline tests pass; live scenario pass rate reported; at least one failure case demonstrated (**Testing, 20**)
- [ ] Demo rehearsed; both members can explain every file (**Demo, 15**)
- [ ] README instructions verified on a clean machine (**Code and docs, 10**)
- [ ] `CONTRIBUTIONS.md` completed honestly (**Individual, 5**)
