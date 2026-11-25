# Live results (real model runs)

# Current version: delay causes, recommended actions, accuracy metrics

This version adds cause categories, a catalog of recommended actions, a carrier-alerts tool, ship-by dates, and three delay-cause scenarios (13 scenarios in total). Each scenario is scored against the database's own answer for **issue, cause and actions**.

## Evaluation 1: `gpt-5`, 13 scenarios × 2 runs (2026-11-17)

Command: `python -m scagent scenarios --repeat 2`. Summary file: `traces/examples/REAL_gpt-5_v2_summary_eval1.json`. Full traces are in `traces/eval_gpt-5_v2_run1/`.

| Metric | Result |
|---|---|
| Issue identification | **100%** (26/26) |
| Cause accuracy | **100%** (26/26) |
| Action recall | **100%** (every required action recommended) |
| Action precision | 92% |
| Evidence grounding (verifier PASS) | 77% |
| **Scenario pass rate** | **73%** (19/26) |

| Scenario | Passed | Scenario | Passed |
|---|---|---|---|
| S1 shortage, alternative exists | 2/2 | X1 shortage, no single source | 2/2 |
| S2 delay, carrier reason | 0/2 | X2 multi-item shortage | 2/2 |
| S3a unknown order | 2/2 | X3 overdue, stalled tracking | 0/2 |
| S3b missing shipment record | 2/2 | X4 pending but fine | 2/2 |
| S4 tool failure | 2/2 | **D1** carrier disruption (alert) | 1/2 |
| S5 no exception | 2/2 | **D2** late warehouse dispatch | 0/2 |
| | | **D3** shortage past promise | 2/2 |

**What the model got right:**
- **Every cause was right, in all 26 runs.** That includes the two causes that can only be found by digging. For ORD-1010, GPT-5 called `get_carrier_alerts` on its own for the carrier and the location of the last scan, and found ALR-701. For ORD-1011, it compared the dispatch date with the ship-by date. It never blamed the old, unrelated Hartford alert.
- **Every required action was recommended**, with evidence: a stock transfer from the right warehouse, replenishment when no warehouse could cover the shortfall, contacting the carrier, notifying the customer, escalating late dispatches to the warehouse, and verifying an unknown order ID.

**Why runs failed:**
- **6 of the 7 failures had the same cause.** In delay cases the model added `NO_ACTION_MONITOR` on top of the correct actions, apparently meaning "keep monitoring". That action meant "no intervention needed", so `actions_supported_by_evidence` correctly failed it for a real problem. **The cause was our catalog naming**: putting "MONITOR" in the name of the "do nothing" action invited the misuse.
- **X3 (2 runs):** the model labelled the cause of stalled tracking "confirmed", although the reason behind the stall isn't in the data. The scenario expects "unknown" or "suspected".

**Changes made after evaluation 1 (wording only; scoring unchanged):**
| Problem | Change |
|---|---|
| "Do nothing" action misread as "monitor" | Renamed `NO_ACTION_MONITOR` to `NO_ACTION_NEEDED`, described as "only when there is no exception, never together with other actions". The prompt says monitoring belongs in an action's details. |
| "Confirmed" used for stalled tracking | The `cause_status` description now says that TRACKING_STALLED or UNKNOWN causes take `unknown` or `suspected` |

**Not yet measured:** a second evaluation after these wording changes. Run `python -m scagent scenarios --repeat 2` and add the results here.

**Definition change to note.** Previously, an order marked shipped with no shipment record (ORD-1007) had to be reported as MISSING_DATA. Now DELAYED_DELIVERY is also accepted when the order is past its promise date, provided the cause is MISSING_SHIPMENT_RECORD; the new cause field now carries the "record is missing" information. This was decided before evaluation 1 ran. It would also have turned the one earlier GPT-5 failure on that order into a pass.

---

# Earlier version: issue and transfer only (10 scenarios)

## Summary

| Model | Run 1 | Run 2 | Total |
|---|---|---|---|
| `gpt-5` (OpenAI API, default settings) | 10/10 | 9/10 | **19/20** |
| `qwen3:8b` (local Ollama) | 7/10 (baseline prompt) | 7/10 (tuned prompt) | 14/20 |

Both `gpt-5` runs used the tuned prompt described in Part B, unchanged. All runs used the same database, scenarios and verifier.

---

# Part A: `gpt-5` (hosted)

**Date of runs:** 2026-11-17. About 1.5 minutes per investigation. Full traces: `traces/scenarios_gpt-5_run1/`, `traces/scenarios_gpt-5_run2/`.

| Scenario | Run 1 | Run 2 | Tools called (both runs) |
|---|---|---|---|
| S1 shortage, alternative exists | PASS | PASS | order → inventory → alternative stock (searched for the 38-unit **shortfall**, excluding WH-BOS) |
| S2 delay, carrier reason | PASS | PASS | order → shipment |
| S3a unknown order | PASS | PASS | order only |
| S3b missing shipment record | PASS | **FAIL** | order → shipment |
| S4 tool failure | PASS | PASS | order → shipment (failed); stopped and reported incomplete |
| S5 no exception | PASS | PASS | order → shipment |
| X1 shortage, no single source | PASS | PASS | order → inventory → alternative stock; no transfer recommended |
| X2 multi-item shortage | PASS | PASS | order → inventory ×2 → alternative stock for SKU-303 only |
| X3 overdue, unknown cause | PASS | PASS | order → shipment |
| X4 pending but fine | PASS | PASS | order → inventory |

**The one failure (S3b, run 2).** The report's wording was honest: the cause was "unknown", the shipment record was listed as missing, and an uncertainty said it couldn't confirm whether the order had been delivered. But the model marked `investigation_complete: true` with DELAYED_DELIVERY. `matches_database` failed it, because the database reference for an order with no shipment record is MISSING_DATA. Nothing was invented; the report was internally inconsistent. Trace: `traces/examples/REAL_gpt-5_S3b_overclaim_caught_FAIL.md`.

**Compared with `qwen3:8b`:**
- It never called inventory tools for shipped orders.
- It always stated a reason before each tool call.
- Its evidence quoted exact values every time.
- It never needed a report resubmission.
- Its recommendations used retrieved details (carrier name, tracking number) without inventing new ones.

---

# Part B: `qwen3:8b` (local)

**Model:** `qwen3:8b` (Q4_K_M) running locally in Ollama through its OpenAI-compatible API (`LLM_PROVIDER=openai`, `OPENAI_BASE_URL=http://localhost:11434/v1`).
**Date of runs:** 2026-11-17. **Investigation date:** 2026-03-16. **Hardware:** Apple Silicon Mac with 16 GB RAM, about 2 minutes per investigation.

Full traces: `traces/scenarios_baseline_qwen3-8b/` and `traces/scenarios_tuned_qwen3-8b/` (kept locally, outside git). A representative subset is copied to `traces/examples/REAL_*`.

## Pass rate

| Scenario | Run 1 (baseline prompt) | Run 2 (tuned prompt) |
|---|---|---|
| S1 shortage, alternative exists | PASS | PASS |
| S2 delay, carrier reason | PASS | FAIL: wrote ID "SPH-5003" (typo for SHP-5003) |
| S3a unknown order | PASS | PASS |
| S3b missing shipment record | FAIL: guessed DELAYED_DELIVERY from unrelated stock data and marked it complete | FAIL: recommended a stock transfer for an already-shipped order |
| S4 tool failure | PASS (honestly incomplete) | FAIL: claimed `investigation_complete: true` after the tool failure |
| S5 no exception | PASS | PASS |
| X1 shortage, no single source | FAIL: evidence listed tool names only, without the SKU | PASS |
| X2 multi-item shortage | PASS | PASS |
| X3 overdue, unknown cause | FAIL: evidence listed tool names only, without the shipment ID | PASS |
| X4 pending but fine | PASS | PASS |
| **Total** | **7/10** | **7/10** |

## What the runs show

1. **The model makes the tool choices.** Pending orders led to `check_inventory` and then `find_alternative_stock`. Shipped orders led to `get_shipment_status`. The unknown order stopped after one call. Multi-item ORD-1008 got one `check_inventory` per SKU. No code path decides this.
2. **The model never invented a problem** in the no-exception scenarios (S5, X4, in both runs). It never mentioned the storm or the revised ETA in S4 after the shipment tool failed.
3. **The verifier caught real model errors**, not only the synthetic ones in the unit tests:
   - claiming success after a tool failure (`failure_honesty`, S4 in run 2),
   - an unsupported transfer recommendation (`transfer_recommendation_supported`, S3b in run 2),
   - a conclusion that disagrees with the database (`matches_database`, S3b in run 1).
4. **Report validation helped.** The model often left out required fields (`uncertainties`, `recommended_source_warehouse`). Python rejected those reports, and the model resubmitted corrected ones in the same run.
5. **The small model is inconsistent.** The same prompt produced different failures in each run. It also kept calling inventory tools for shipped orders after the prompt said this was unnecessary, and it rarely wrote the requested one-sentence reason before each call.

## Changes made between runs (prompt and schema only, no loop logic)

| Problem seen in run 1 | Change |
|---|---|
| Evidence items were bare tool names | System prompt and `evidence` schema description now require quoted values, with an example |
| Guessing a cause when a record was missing | Prompt: report MISSING_DATA rather than guess from unrelated data |
| Unneeded inventory checks for shipped orders | Prompt: stock levels can't explain a late delivery once an order has shipped |
| Required fields left out of the report | `submit_report` description: all fields are required; use `[]` / `null` |
| (Run 1 S4 passed, but said "no delay reason was recorded" without having seen the shipment) | Prompt: never describe what a failed record would have contained. Added `"no delay reason"` to S4's `must_not_mention` |

Result: evidence quality clearly improved (X1 and X3 went from failing to passing), but the honesty failures moved to other scenarios instead of disappearing.

## Verifier gap found and fixed

In run 2, S2 wrote `SPH-5003`. The original ID pattern only recognized known prefixes, so `ids_grounded` did not flag it; only the scenario's `must_mention` check caught it. The pattern now matches any ID-shaped token, so the typo is caught. Re-checking the saved run-2 trace gives `ids_grounded: fail ['SPH-5003']`, and `tests/test_verifier.py::test_mistyped_id_is_caught` guards against regressions.

## Conclusions to present

- The loop, validation, limits and verification behave correctly with a real model, including when the model makes mistakes.
- A small 8B local model is enough to show adaptive tool use, but it is **not reliable** at the honesty rules. Our verifier, not the model, is what keeps unreliable answers from being accepted.
- A larger hosted model (`gpt-5`, Part A) fixed nearly all of these problems with the same prompt and code: 19/20 against 14/20. Its one failure was caught the same way.
