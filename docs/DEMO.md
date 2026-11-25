# Demonstration script (about 8 minutes)

Run `./demo.sh`, which pauses between parts, or type the commands yourself. Split the talking between the two team members as marked.

## Before the demo
- `.env` contains a working key; run `python -m scagent init-db`.
- Do one practice run so the API is warmed up and you know roughly what the output looks like.
- Keep `scagent/agent.py` and `scenarios/scenarios.json` open in an editor.

## Recommended: run the demo from the website
1. `./start.sh`, then open http://localhost:8000.
2. **How it works:** flip a couple of flashcards, then click **Walk through an example** to explain the loop. Point out the "illustrative" label.
3. **Investigate → "Carrier hub disruption" → Run now.** Click **View live investigation**. The model checks the order, then tracking, then *decides* to check carrier alerts. Expand a card to show the real arguments and returned data.
4. Back on **Investigate**, read the report: cause card, actions, evidence by tool, the 10/10 ring, and Model vs. database.
5. **"Tracking system down" → Run now.** The Shipment tracking card turns red (failed), and the report is marked *incomplete*.
6. **Orders** → ORD-1010 → Details shows the same facts straight from the database, so nothing was invented.
7. **Evaluation** → the metrics, then click a red cell and replay it.
8. If the network or API fails: **Live Investigation → Saved runs → Replay**. It costs nothing and needs no connection to the model.

## Option: the original command-line walkthrough
Start `python -m scagent web` and open http://localhost:8000. The example buttons cover every part below. The live timeline shows the same steps as the CLI output, and the **Data** tab replaces the `truth` / `tool` commands for checking facts.

## Part 1: What it is (Member A, 1 min)
- "Given a question about an order, the agent picks tools, reads the results, decides what to check next, and writes a report. Python validates every request and then checks the report against the database."
- Show the architecture diagram in the README. Point out that the loop in `agent.py` has **no fixed tool order**.

## Part 2: Successful investigation, ORD-1001 (Member A, 2 min)
```bash
python -m scagent investigate "Order ORD-1001 hasn't shipped yet. Investigate why and what we should do."
```
Point out, in the live output:
1. `[model says]`: the model's own stated reason before each call.
2. `[model requests] check_inventory(...)`: it chose inventory because the order is `PENDING_FULFILLMENT`.
3. `[python] scagent.tools.check_inventory ... -> ok` and the result: 12 available against 50 ordered.
4. It then chose `find_alternative_stock`, and only WH-CHI is listed as sufficient.
5. The report recommends WH-CHI, and every verification check passes.

Show that it is real by checking the facts without the model:
```bash
python -m scagent truth ORD-1001
```

## Part 3: A different path, ORD-1003 (Member B, 1.5 min)
```bash
python -m scagent investigate "Investigate why order ORD-1003 is delayed."
```
- Same agent, different tools: the order is `SHIPPED`, so the model calls `get_shipment_status` and **does not** check inventory.
- The cause is `confirmed` because the carrier recorded a delay reason. The revised ETA 2026-03-18 comes straight from the tool result.

## Part 4: Failure case, tool outage (Member B, 2 min)
```bash
python -m scagent investigate "Investigate why order ORD-1003 is delayed." --fail-tool get_shipment_status
```
- The trace shows `ERROR TOOL_FAILURE`.
- The report has `Complete: False`, lists the shipment data as missing, and **does not** mention the storm or the ETA, because the agent never saw them.
- Verification: `failure_honesty` PASS.
- Optional: open `tests/test_verifier.py::test_claiming_success_after_tool_failure_is_caught` and explain that if the model *had* claimed success, the verifier would fail the run.

## Part 5: Missing information, unknown order (either member, 1 min)
```bash
python -m scagent investigate "Investigate order ORD-9999. The customer says it never arrived."
```
- `NOT_FOUND` comes back from `get_order_details`. The model reports ORDER_NOT_FOUND and invents no shipment.

## Part 6: Evidence of reliability (either member, 1 min)
- Show `traces/scenarios/summary.json` from your scenario run (for example, "10/10 passed with claude-opus-5-5").
- Run `pytest -q` to show the offline suite passing.
- Mention the limits: an 8 tool-call cap and a 12-turn cap.

## Questions to be ready for
- *"How do you know it isn't hardcoded?"* There is no branching on order status in `agent.py`. Different orders produce different tool sequences (compare the Part 2 and Part 3 traces). `test_tool_sequence_depends_on_results` checks this with the test double.
- *"What if the model makes something up?"* The `ids_grounded`, `dates_grounded` and `matches_database` checks catch it, and `test_verifier.py` proves they do.
- *"Why is the final answer a tool call?"* It produces a structured report that Python can validate field by field.
