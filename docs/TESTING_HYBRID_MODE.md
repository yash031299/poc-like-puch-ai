# Testing Guide — STT Buffering Fix with HYBRID_MODE

## Problem You Hit

When you called in, the server received audio but you heard nothing back:
- ✅ Audio streaming worked (WebSocket connected, media frames received)
- ✅ Google Cloud STT credentials valid
- ✅ Google Cloud TTS credentials valid
- ❌ **Gemini API quota exhausted** (429 error)
- ❌ **STT was calling Google API on every 20ms chunk** (buffering bug — fixed)

## What Was Fixed

### 1. STT Audio Buffering (main bug)
Before: `GoogleSTTAdapter` called Google STT API on every 20ms audio chunk (320 bytes)
→ Google STT returned empty results (audio too short) → no transcript → no response

After: Accumulates audio until ≥1 second (16,000 bytes at 8kHz) before calling STT
→ Google STT gets enough audio to recognize speech → transcripts produced → pipeline works

### 2. Credential Validation Script
Created `scripts/check_credentials.py` to test all APIs independently:
```bash
./scripts/validate_production_credentials.sh
```

This caught your Gemini quota issue immediately instead of silent failures in logs.

---

## How to Test the Fix Right Now (Without Gemini Quota)

### Option 1: HYBRID_MODE (Recommended)
Tests the STT buffering fix with **real phone calls** while bypassing Gemini quota:

```bash
# Start server in HYBRID mode (real STT+TTS, stub LLM)
HYBRID_MODE=true LOG_LEVEL=DEBUG python -m src.infrastructure.server
```

**What happens when you call:**
1. You speak → Real Google STT transcribes (tests the buffering fix we implemented)
2. Stub LLM responds with: "Thank you for calling. I heard you clearly..."
3. Real Google TTS synthesizes → You hear actual TTS voice

You'll see in the DEBUG logs:
```
STT: sending 16000 bytes (1.00 s) for stream <id>
```
This proves the buffering fix is working (accumulating 1 second before calling STT).

### Option 2: DEV_MODE (Full Simulation)
Zero credentials needed — uses local sine-wave audio:
```bash
DEV_MODE=true python -m src.infrastructure.server
# Then run the simulator:
python scripts/sim_exotel.py
```

---

## When Gemini Quota Resets

Once your Gemini quota resets (check https://ai.dev/rate-limit):

```bash
# Full production with all real APIs:
python -m src.infrastructure.server
```

All three pipelines will work:
- Real Google STT (with buffering fix)
- Real Gemini LLM
- Real Google TTS

---

## Quick Checklist

- [x] STT buffering bug fixed (accumulates 1 second of audio)
- [x] Credential validator script created
- [x] HYBRID_MODE added for testing STT/TTS when Gemini quota exhausted
- [ ] Wait for Gemini quota reset OR upgrade to paid plan
- [ ] Test full pipeline with real Gemini once quota available

---

## Commands Summary

```bash
# Validate all credentials (including Gemini quota check):
./scripts/validate_production_credentials.sh

# Test STT buffering fix with real phone calls (no Gemini quota needed):
HYBRID_MODE=true LOG_LEVEL=DEBUG python -m src.infrastructure.server

# Full local test (no credentials):
./scripts/run_local_validation.sh

# Full production (requires Gemini quota):
python -m src.infrastructure.server
```

---

## What You'll Hear in HYBRID_MODE

**Before the fix:** Silence (STT never produced transcripts from 20ms chunks)
**After the fix:** Real TTS voice saying the stub response

This proves the STT buffering is working — Google STT is now receiving enough
audio to recognize speech, and the pipeline flows all the way to your ears.
