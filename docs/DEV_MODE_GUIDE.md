# DEV_MODE Troubleshooting & Quick Start Guide

## What is DEV_MODE?

DEV_MODE is a local development mode that requires **ZERO external credentials or services**. Perfect for testing without Google Cloud, Exotel account, or Redis.

### What DEV_MODE Provides (All Built-In Stubs)

- ✅ **StubSTT** — Returns fixed transcripts (no Google Cloud)
- ✅ **StubLLM** — Returns fixed responses (no Gemini API)
- ✅ **StubTTS** — Generates 440 Hz sine wave audio (no Google Cloud)
- ✅ **InMemorySessionRepository** — Stores state in memory (no Redis)
- ✅ Full Exotel WebSocket support
- ✅ Voice Activity Detection (VAD) with audio buffering

---

## How to Start

### Correct Command

```bash
cd poc-like-puch-ai
DEV_MODE=true python3 -m src.infrastructure.server
```

### What You Should See

```
🔧 DEV_MODE enabled — using stub adapters (no API keys required)
✅ VAD enabled: sensitivity=0, silence=700ms, max_buffer=30s
✅ Puch AI Voice Server ready — mode=DEV (stubs) sample_rate=8000Hz
INFO:     Application startup complete.
```

---

## Common Problems & Solutions

### Problem 1: Call Disconnects After 2 Seconds

**Cause (Most Likely):** Old code with VAD sensitivity=2

**Solution:**
```bash
# Get latest code
git pull origin main

# Kill old server if running
ps aux | grep "src.infrastructure.server" | grep -v grep
# kill <PID> from output

# Restart fresh
DEV_MODE=true python3 -m src.infrastructure.server

# Verify logs show "sensitivity=0" not "sensitivity=2"
```

### Problem 2: "address already in use" on port 8000

```bash
# Find what's using port 8000
lsof -i :8000

# Kill it (use the PID from above)
# kill <PID>

# Restart
DEV_MODE=true python3 -m src.infrastructure.server
```

### Problem 3: Google Credentials Error (NOT needed in DEV_MODE!)

**Cause:** Not in DEV_MODE or old code trying to initialize Google adapters

**Solution:**
```bash
# Verify DEV_MODE is set
echo $DEV_MODE  # Should output: true

# Restart with proper flag
DEV_MODE=true python3 -m src.infrastructure.server

# Check logs for "DEV_MODE enabled"
```

### Problem 4: Redis Errors (NOT needed in DEV_MODE!)

**Important:** Redis is completely optional in DEV_MODE.

**If you see Redis errors:**
- They're harmless in DEV_MODE (using InMemorySessionRepository by default)
- Ignore them
- Redis only needed if explicitly using RedisSessionRepository (not default)

### Problem 5: run_local_validation.sh Fails

```bash
# Create virtual environment
python3 -m venv venv

# Install dependencies
venv/bin/pip install -e .

# Run validation script
./scripts/run_local_validation.sh
```

---

## Test End-to-End Call Flow

### Option 1: Simulator (Recommended - Fastest)

```bash
# Terminal 1
DEV_MODE=true LOG_LEVEL=DEBUG python3 -m src.infrastructure.server

# Terminal 2 (wait for server to start)
python3 scripts/sim_exotel.py --port 8000 --sample-rate 8000

# Expected: "✅ VALIDATION PASSED — all scenarios green!"
```

### Option 2: One Command

```bash
./scripts/run_local_validation.sh
```

### Option 3: Real Exotel Call with ngrok

```bash
# Terminal 1: Start server
DEV_MODE=true python3 -m src.infrastructure.server

# Terminal 2: Expose publicly
ngrok http 8000
# Copy URL: https://abc123.ngrok-free.app

# Configure Exotel VoiceBot applet:
# WebSocket: wss://abc123.ngrok-free.app/stream?sample-rate=8000

# Call your Exotel VoiceBot number and speak
```

---

## How It Works (Simple Flow)

1. **Call connects** → Exotel sends WebSocket events
2. **Audio arrives** → VAD detects speech/silence
3. **Buffer fills** → After 700ms of speech, extract utterance
4. **StubSTT runs** → Returns fixed transcript ("hello", etc.)
5. **StubLLM runs** → Generates response ("I heard you. How can I help?")
6. **StubTTS runs** → Creates 440 Hz sine wave audio
7. **Response sent** → Audio streamed back to caller
8. **Call ends** → Exotel closes connection

---

## Quick Verification

```bash
# Is server running?
curl http://localhost:8000/health

# Response should be:
# {"status":"ok","active_sessions":0}
```

---

## Key Takeaways

✅ **DEV_MODE requires NO credentials, NO Redis, NO external services**

✅ **Use latest code** - Recent fixes for VAD sensitivity and OpenTelemetry

✅ **VAD sensitivity should be 0 in DEV_MODE** - If you see sensitivity=2, pull latest code

✅ **Ignore optional adapter errors** - Redis, Google, etc. not used in DEV_MODE

✅ **Run validation script to verify everything works** - One command tests full flow

---

## Environment Variable Reference

```bash
# Set these
DEV_MODE=true                  # Enable stub adapters
LOG_LEVEL=DEBUG                # Verbose logging

# Optional tuning
VAD_SENSITIVITY=0              # Speech detection aggressiveness (0=least, 3=most)
VAD_SILENCE_THRESHOLD_MS=700   # How long to wait after speech before flushing
SAMPLE_RATE=8000               # Audio sample rate

# DO NOT set in DEV_MODE (not needed)
GOOGLE_APPLICATION_CREDENTIALS  # Only for production
GEMINI_API_KEY                  # Only for production
```

---

## Recent Fixes Applied

### Fix 1: VAD Sensitivity
- Changed default VAD_SENSITIVITY from 2 → 0 in DEV_MODE
- Better detection of low-amplitude test signals
- Commit: 5843faf

### Fix 2: OpenTelemetry Overhead
- Disabled OpenTelemetry tracing initialization in DEV_MODE
- Removes repeated failed connection attempts to localhost:4317
- Reduces latency and overhead
- Commit: 8579f7e

**If you see old behavior (sensitivity=2 or OTEL errors), pull latest code:**
```bash
git pull origin main
```

---

## Troubleshooting Checklist

- [ ] Running `DEV_MODE=true python3 -m src.infrastructure.server`?
- [ ] Latest code? (`git pull origin main`)
- [ ] Server logs show "sensitivity=0"? (not sensitivity=2)
- [ ] Server logs show "OpenTelemetry tracing disabled"?
- [ ] Port 8000 free? (`lsof -i :8000`)
- [ ] Virtual environment set up? (`pip install -e .`)
- [ ] Tests pass? (`pytest tests/acceptance/`)
- [ ] Simulator works? (`python3 scripts/sim_exotel.py`)

---

## Getting Help

If you still have issues, provide:
1. **Full server logs** (from startup to error)
2. **Output of:** `DEV_MODE=true LOG_LEVEL=DEBUG python3 -m src.infrastructure.server 2>&1 | grep -i "error\|exception\|dev_mode\|sensitivity"`
3. **What you ran** (the exact command)
4. **What you expected** (what should happen)
5. **What actually happened** (error messages, call behavior)
