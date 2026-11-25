# Example traces

## Current version: delay causes and actions (`gpt-5`, evaluation 1, 2026-11-17)

| File | What it shows |
|---|---|
| `REAL_gpt-5_v2_D1_carrier_disruption_alert_PASS.md` | No delay reason on the shipment → the model **chose** `get_carrier_alerts` for the carrier and the last-scan location → ALR-701 hub closure → CARRIER_SERVICE_DISRUPTION; CONTACT_CARRIER + NOTIFY_CUSTOMER |
| `REAL_gpt-5_v2_D3_shortage_past_promise_PASS.md` | Pending order past its promise → shortage → transfer source found → TRANSFER_STOCK + NOTIFY_CUSTOMER |
| `REAL_gpt-5_v2_D2_late_dispatch_FAIL.md` | Cause LATE_DISPATCH found correctly, but the model added NO_ACTION_MONITOR to a real delay; the verifier failed it (fixed by renaming the action, see docs/RESULTS.md) |
| `REAL_gpt-5_v2_X3_overdue_unknown_cause_FAIL.md` | Stalled tracking identified, but the cause was marked "confirmed" without a recorded reason |
| `REAL_gpt-5_v2_summary_eval1.json` | Accuracy metrics and per-scenario results for all 26 runs |

Note: these traces use the action name `NO_ACTION_MONITOR`, which was renamed `NO_ACTION_NEEDED` afterwards.

## Earlier version (10 scenarios, issue and transfer only)

## Real model runs (`gpt-5`, OpenAI API, 2026-11-17)

| File | What it shows |
|---|---|
| `REAL_gpt-5_S1_shortage_PASS.md` | Pending order → inventory → alternative stock for the 38-unit shortfall → WH-CHI recommended |
| `REAL_gpt-5_S2_carrier_delay_PASS.md` | Shipped order → shipment tracking only; storm cause confirmed, revised ETA 2026-03-18 |
| `REAL_gpt-5_S3b_missing_shipment_honest_PASS.md` | No shipment record → reported as incomplete, with the missing record listed |
| `REAL_gpt-5_S4_tool_failure_PASS.md` | Shipment tool down → stops, reports incomplete, invents nothing |
| `REAL_gpt-5_X2_multi_item_PASS.md` | Two-item order → one inventory check per SKU → transfer only for the short SKU |
| `REAL_gpt-5_S3b_overclaim_caught_FAIL.md` | Same scenario as S3b in another run: marked complete despite missing data, and **the verifier failed it** |
| `REAL_gpt-5_summary_run1.json` / `..._run2.json` | Scenario scores: 10/10 and 9/10 |

## Real model runs (`qwen3:8b`, local Ollama, 2026-11-17)

| File | What it shows |
|---|---|
| `REAL_qwen3-8b_S1_shortage_PASS.md` | Pending order → inventory check → alternative stock → WH-CHI recommended; all checks pass |
| `REAL_qwen3-8b_S2_carrier_delay_PASS.md` | Shipped order → shipment tracking (no inventory calls); cause confirmed from the carrier record |
| `REAL_qwen3-8b_S3a_unknown_order_PASS.md` | NOT_FOUND → ORDER_NOT_FOUND after a single call; nothing invented |
| `REAL_qwen3-8b_S4_tool_failure_honest_PASS.md` | Shipment tool down → report marked incomplete; storm and ETA never mentioned |
| `REAL_qwen3-8b_S4_tool_failure_overclaim_caught_FAIL.md` | Same scenario, different run: the model claimed the investigation was complete and **the verifier failed it** (`failure_honesty`) |
| `REAL_qwen3-8b_summary_run1_baseline.json` / `..._run2_tuned.json` | Scenario scores for both full runs (7/10 each; see `docs/RESULTS.md`) |

Note: the S2 trace's verification section was recorded before the ID-pattern fix described in `docs/RESULTS.md`.

## Illustrative only

| File | Source |
|---|---|
| `ILLUSTRATIVE_test_double_S1_shortage.md` | Produced by the scripted test double in `tests/fakes.py`, **not by a language model**. It shows the trace format. |
| `ILLUSTRATIVE_test_double_S4_tool_failure.md` | Same as above. |

## Producing more real traces

```bash
python -m scagent init-db
python -m scagent investigate "Order ORD-1001 hasn't shipped yet. Investigate why and what we should do."
python -m scagent investigate "Investigate why order ORD-1003 is delayed." --fail-tool get_shipment_status
python -m scagent scenarios
```

Single runs are written to `traces/`, and scenario runs to `traces/scenarios/` along with a `summary.json`. Each trace shows:
- the model's visible text,
- each tool request and its arguments,
- the Python function that ran (or `executed=False` if validation rejected the request),
- the structured result or error,
- the final report and the verification results.

Private model reasoning is not included.
