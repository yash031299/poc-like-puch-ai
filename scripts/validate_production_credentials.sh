#!/usr/bin/env bash
# validate_production_credentials.sh
# ──────────────────────────────────────────────────────────────────────────────
# Validates all production credentials then starts the server in PRODUCTION
# mode and confirms it is healthy.
#
# This is the production equivalent of run_local_validation.sh.
# run_local_validation.sh  → uses DEV_MODE stubs (zero credentials)
# THIS script              → uses real credentials from .env
#
# Usage:
#   chmod +x scripts/validate_production_credentials.sh
#   ./scripts/validate_production_credentials.sh
#
# Options (env vars):
#   PORT=8000          Server port (default: 8000)
#   SKIP_SERVER=true   Only run credential checks, skip server start (default: false)
#
# Exit codes:
#   0  — All checks passed + server healthy  ✅
#   1  — One or more credential checks failed  ❌
#   2  — Credentials passed but server failed to start  ❌
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PORT="${PORT:-8000}"
SKIP_SERVER="${SKIP_SERVER:-false}"

# Resolve script dir regardless of where you call it from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Use the project's own venv python
PYTHON="$PROJECT_DIR/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "❌  venv not found at $PROJECT_DIR/venv"
  echo "    Run: python3 -m venv venv && venv/bin/pip install -e '.[dev]'"
  exit 2
fi

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
RESET='\033[0m'

echo ""
echo -e "${YELLOW}════════════════════════════════════════════════════════${RESET}"
echo -e "${YELLOW}  Puch AI — Production Credential Validation${RESET}"
echo -e "${YELLOW}════════════════════════════════════════════════════════${RESET}"
echo ""
echo "  Project : $PROJECT_DIR"
echo "  Port    : $PORT"
echo "  Mode    : PRODUCTION (real credentials from .env)"
echo ""

# ── Step 1: Run credential checker ───────────────────────────────────────────
echo "▶  Running credential checks ..."
echo ""

CRED_EXIT=0
"$PYTHON" "$SCRIPT_DIR/check_credentials.py" || CRED_EXIT=$?

if [[ "$CRED_EXIT" -ne 0 ]]; then
  echo -e "${RED}════════════════════════════════════════════════════════${RESET}"
  echo -e "${RED}  💥 Credential checks FAILED — fix errors above${RESET}"
  echo -e "${RED}     before running the server in PRODUCTION mode.${RESET}"
  echo -e "${RED}════════════════════════════════════════════════════════${RESET}"
  echo ""
  exit 1
fi

echo -e "${GREEN}▶  All credential checks passed.${RESET}"
echo ""

if [[ "$SKIP_SERVER" == "true" ]]; then
  echo "  (SKIP_SERVER=true — skipping server start)"
  echo ""
  echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
  echo -e "${GREEN}  ✅ Credential validation complete (server skipped)${RESET}"
  echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
  echo ""
  exit 0
fi

# ── Step 2: Start server in PRODUCTION mode ───────────────────────────────────
echo "▶  Starting server in PRODUCTION mode ..."
cd "$PROJECT_DIR"

# Load .env so the server gets all credentials (dotenv in the server also loads
# .env, but exporting here ensures subshell env vars are available immediately)
if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$PROJECT_DIR/.env"
  set +a
fi

PORT="$PORT" "$PYTHON" -m src.infrastructure.server &
SERVER_PID=$!

# ── Step 3: Wait for server to be healthy ─────────────────────────────────────
MAX_WAIT=20
READY=0
for i in $(seq 1 $MAX_WAIT); do
  sleep 1
  if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
    RESPONSE=$(curl -s "http://localhost:$PORT/health")
    echo -e "  ${GREEN}✅ Server ready (took ${i}s) — $RESPONSE${RESET}"
    READY=1
    break
  fi
done

if [[ "$READY" -eq 0 ]]; then
  echo -e "  ${RED}❌ Server did not become healthy within ${MAX_WAIT}s${RESET}"
  kill "$SERVER_PID" 2>/dev/null || true
  exit 2
fi

echo ""

# ── Step 4: Confirm /health active_sessions ───────────────────────────────────
HEALTH=$(curl -s "http://localhost:$PORT/health")
ACTIVE=$(echo "$HEALTH" | grep -o '"active_sessions":[0-9]*' | grep -o '[0-9]*' || echo "0")
echo "  Active sessions at startup: $ACTIVE (expected: 0)"
echo ""

# ── Step 5: Shut server down ──────────────────────────────────────────────────
echo "▶  Stopping server (PID $SERVER_PID) ..."
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
echo "   Server stopped."
echo ""

# ── Final result ──────────────────────────────────────────────────────────────
echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  🎉 PRODUCTION VALIDATION PASSED${RESET}"
echo -e "${GREEN}     All credentials verified + server started healthy.${RESET}"
echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
echo ""
exit 0
