#!/usr/bin/env bash
# One-step launcher for the Supply Chain Exception Investigator website (macOS / Linux).
#
#   ./start.sh            first run: sets everything up, asks for your API key, opens the site
#                         later runs: just starts the site
#
# Environment overrides: PORT=8001 ./start.sh   NO_BROWSER=1 ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Python 3.10+ ------------------------------------------------------------
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 &&
     "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and run ./start.sh again."

# 2. Virtual environment (re-created if missing or broken, e.g. after moving the folder)
if ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  say "Creating a private Python environment in .venv (first run only)..."
  rm -rf .venv
  "$PY" -m venv .venv
fi
VPY=.venv/bin/python

# 3. Dependencies --------------------------------------------------------------
if ! "$VPY" -c 'import flask, openai, anthropic, dotenv' >/dev/null 2>&1; then
  say "Installing dependencies (first run only, about a minute)..."
  "$VPY" -m pip install --quiet --upgrade pip
  "$VPY" -m pip install --quiet -r requirements.txt
fi

# 4. Configuration (.env) ------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  if [ -t 0 ]; then
    say "First-time setup: which AI model should the agent use?"
    echo "  1) OpenAI (needs an OpenAI API key with credits)"
    echo "  2) Anthropic Claude (needs an Anthropic API key)"
    echo "  3) Local model via Ollama (free, needs Ollama installed with a tool-calling model)"
    read -r -p "Choose 1, 2 or 3 [1]: " choice || choice=""
    choice="${choice:-1}"
    key=""
    if [ "$choice" != "3" ]; then
      read -r -s -p "Paste your API key (typing is hidden), then press Enter: " key || key=""; echo
      [ -n "$key" ] || echo "No key entered. You can add it to .env later and restart."
    fi
    # Written by Python from environment variables so the key never appears in a command line.
    CHOICE="$choice" KEY="$key" "$VPY" - <<'EOF'
import os, re, pathlib
p = pathlib.Path(".env"); s = p.read_text()
def put(name, value):
    global s
    line = f"{name}={value}"
    s, n = re.subn(rf"^#?\s*{name}=.*$", lambda m: line, s, count=1, flags=re.M)
    if not n:
        s += f"\n{line}\n"
choice, key = os.environ["CHOICE"], os.environ["KEY"].strip()
if choice == "2":
    put("LLM_PROVIDER", "anthropic"); put("ANTHROPIC_API_KEY", key)
elif choice == "3":
    put("LLM_PROVIDER", "openai"); put("LLM_MODEL", "qwen3:8b")
    put("OPENAI_BASE_URL", "http://localhost:11434/v1")
else:
    put("LLM_PROVIDER", "openai"); put("OPENAI_API_KEY", key)
p.write_text(s)
print("Saved your settings to .env (keep this file private; it is never shared by package.sh).")
EOF
  else
    say "Created .env from .env.example. Add your API key to .env, then run ./start.sh again."
  fi
fi

# 5. Database ------------------------------------------------------------------
[ -f data/supply_chain.db ] || "$VPY" -m scagent init-db >/dev/null

# 6. Free port + start ---------------------------------------------------------
PORT="$("$VPY" - "${PORT:-8000}" <<'EOF'
import socket, sys
start = int(sys.argv[1])
for port in range(start, start + 20):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port)); print(port); break
        except OSError:
            continue
else:
    print(start)
EOF
)"
OPEN_FLAG="--open"; [ -n "${NO_BROWSER:-}" ] && OPEN_FLAG=""
exec "$VPY" -m scagent web --port "$PORT" $OPEN_FLAG
