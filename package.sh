#!/usr/bin/env bash
# Build a zip of the project that is SAFE TO SHARE with classmates or graders.
#
#   ./package.sh      -> dist/supply-chain-agent-YYYYMMDD.zip
#
# Leaves out: .env (your API key and access code), .venv, the generated database,
# caches, and run traces (except traces/examples). Recipients run ./start.sh.
set -euo pipefail
cd "$(dirname "$0")"
NAME="supply-chain-agent"
OUT="dist/${NAME}-$(date +%Y%m%d).zip"
mkdir -p dist
rm -f "$OUT"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/$NAME"
# Copy everything, then delete what must not be shared.
tar --exclude='./.env' --exclude='./.venv' --exclude='./dist' --exclude='./.pytest_cache' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='./data/*.db' --exclude='.DS_Store' \
    -cf - . | tar -xf - -C "$STAGE/$NAME"
find "$STAGE/$NAME/traces" -mindepth 1 -maxdepth 1 ! -name examples -exec rm -rf {} +

# Safety net: refuse to build if anything that looks like a secret slipped in:
# an API-key-shaped string in any file, or a filled-in key/code in any .env-style file.
secrets_found() {
  grep -rIlE 'sk-[A-Za-z0-9_-]{20,}' "$STAGE/$NAME"
  find "$STAGE/$NAME" -name '.env*' -type f -exec grep -lE '^(OPENAI_API_KEY|ANTHROPIC_API_KEY|WEB_ACCESS_CODE)=.+' {} +
}
if [ -e "$STAGE/$NAME/.env" ] || [ -n "$(secrets_found 2>/dev/null)" ]; then
  echo "ERROR: a file that looks like it contains a secret was found; package not created:" >&2
  secrets_found >&2 || true
  exit 1
fi

(cd "$STAGE" && zip -qr - "$NAME") > "$OUT"
echo "Created $OUT ($(du -h "$OUT" | cut -f1)). It contains no .env, keys, or virtual environment."
echo "Recipients unzip it and run ./start.sh (macOS/Linux) or start.bat (Windows)."
