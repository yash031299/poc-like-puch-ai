#!/usr/bin/env bash
# run_local_validation.sh
# ──────────────────────────────────────────────────────────────────────────────
# One-command end-to-end local validation for Puch AI Voice Server.
#
# Starts the server in DEV_MODE (zero credentials), waits for it to be ready,
# runs the full Exotel AgentStream simulator, then cleanly shuts the server.
#
# Usage:
#   chmod +x scripts/run_local_validation.sh
#   ./scripts/run_local_validation.sh
#
# Options (env vars):
#   PORT=8000          Server port (default: 8000)
#   SAMPLE_RATE=8000   Audio sample rate (default: 8000)
#   LOG_LEVEL=WARNING  Reduce server noise in output (default: WARNING)
#
# Exit codes:
#   0  — All assertions passed  🎉
#   1  — One or more assertions failed  💥
#   2  — Server failed to start
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PORT="${PORT:-8000}"
SAMPLE_RATE="${SAMPLE_RATE:-8000}"
LOG_LEVEL="${LOG_LEVEL:-WARNING}"

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
echo -e "${YELLOW}  Puch AI — Local End-to-End Validation${RESET}"
echo -e "${YELLOW}════════════════════════════════════════════════════════${RESET}"
echo ""
echo "  Project : $PROJECT_DIR"
echo "  Port    : $PORT"
echo "  Mode    : DEV_MODE=true (zero credentials)"
echo ""

# ── Start server ──────────────────────────────────────────────────────────────
echo "▶  Starting server (DEV_MODE) ..."
cd "$PROJECT_DIR"
DEV_MODE=true VAD_ENABLED=false LOG_LEVEL="$LOG_LEVEL" PORT="$PORT" SAMPLE_RATE="$SAMPLE_RATE" \
  "$PYTHON" -m src.infrastructure.server &
SERVER_PID=$!

# ── Wait for server to be healthy ─────────────────────────────────────────────
MAX_WAIT=20
READY=0
for i in $(seq 1 $MAX_WAIT); do
  sleep 1
  if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
    echo -e "  ${GREEN}✅ Server ready (took ${i}s)${RESET}"
    READY=1
    break
  fi
done

if [[ "$READY" -eq 0 ]]; then
  echo -e "  ${RED}❌ Server did not start within ${MAX_WAIT}s${RESET}"
  kill "$SERVER_PID" 2>/dev/null || true
  exit 2
fi

echo ""

# ── Run simulator ─────────────────────────────────────────────────────────────
SIM_EXIT=0
"$PYTHON" "$SCRIPT_DIR/sim_exotel.py" --port "$PORT" --sample-rate "$SAMPLE_RATE" || SIM_EXIT=$?

# ── Shut server down ──────────────────────────────────────────────────────────
echo ""
echo "▶  Stopping server (PID $SERVER_PID) ..."
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
echo "   Server stopped."
echo ""

# ── Final result ──────────────────────────────────────────────────────────────
if [[ "$SIM_EXIT" -eq 0 ]]; then
  echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
  echo -e "${GREEN}  🎉 VALIDATION PASSED — all scenarios green!${RESET}"
  echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
else
  echo -e "${RED}════════════════════════════════════════════════════════${RESET}"
  echo -e "${RED}  💥 VALIDATION FAILED — check output above${RESET}"
  echo -e "${RED}════════════════════════════════════════════════════════${RESET}"
fi
echo ""
exit "$SIM_EXIT"
