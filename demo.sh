#!/usr/bin/env bash
# Demonstration script (about 5 minutes). Requires an API key in .env.
# Usage: ./demo.sh        (press Enter between parts)
set -u
cd "$(dirname "$0")"
PY="${PYTHON:-python}"
pause() { echo; read -r -p "---- press Enter to continue ----" _; echo; }

echo "== 0. Reset the fictional database =="
$PY -m scagent init-db
pause

echo "== 1. SUCCESS: inventory shortage with an alternative warehouse (ORD-1001) =="
$PY -m scagent investigate "Order ORD-1001 hasn't shipped yet. Investigate why and what we should do."
pause

echo "== 2. Check the agent against the raw data, without the model =="
$PY -m scagent tool check_inventory '{"sku": "SKU-202", "warehouse_id": "WH-BOS"}'
$PY -m scagent tool find_alternative_stock '{"sku": "SKU-202", "required_quantity": 38, "exclude_warehouse_id": "WH-BOS"}'
$PY -m scagent truth ORD-1001
pause

echo "== 3. DIFFERENT PATH: delayed shipment with a documented carrier delay (ORD-1003) =="
$PY -m scagent investigate "Investigate why order ORD-1003 is delayed."
pause

echo "== 4. FAILURE: the shipment-tracking tool is down (same order) =="
$PY -m scagent investigate "Investigate why order ORD-1003 is delayed." --fail-tool get_shipment_status
pause

echo "== 5. MISSING INFORMATION: order that does not exist =="
$PY -m scagent investigate "Investigate order ORD-9999. The customer says it never arrived."
echo
echo "Demo complete. Traces are in ./traces/"
