# PoC Like Puch AI

AI-powered phone conversation system using Exotel AgentStream with **Voice Activity Detection (VAD)** for intelligent buffering.

**Flow:** Caller dials Exotel number → Exotel WebSocket → Our server → **VAD buffering** → STT → Gemini LLM → TTS → Audio back to caller

## ✨ NEW: Voice Activity Detection (VAD)

**Problem Solved:** Previous implementation processed every 10-40ms audio chunk immediately, causing **dozens of LLM API calls per second** during active speech.

**Solution:** VAD + intelligent buffering reduces LLM calls by **90%+** by:
- Detecting when user is speaking vs silence
- Accumulating audio chunks while user speaks
- Flushing complete utterances only after 700ms of silence
- Processing once per complete sentence instead of every chunk

### Interaction State Transitions

Session interaction state now follows:
- `listening` → waiting for caller input
- `thinking` → STT/LLM pipeline in progress
- `speaking` → TTS segments being streamed to caller

This state machine is used to keep turn-taking behavior explicit and observable.

### VAD Configuration

Edit `.env` to tune VAD behavior:

```bash
# Enable/disable VAD (default: true)
VAD_ENABLED=true

# Silence threshold before flushing buffer (default: 700ms)
# Lower = more responsive but may cut off speech
# Higher = safer but slower response
VAD_SILENCE_THRESHOLD_MS=700

# VAD sensitivity (0-3, default: 2)
# 0 = Only very clear speech (fewest false positives)
# 2 = Recommended for telephony with background noise
# 3 = Most sensitive (may trigger on ambient noise)
VAD_SENSITIVITY=2

# Maximum buffer duration (default: 30s)
# Prevents memory overflow during long monologues
MAX_SPEECH_BUFFER_SECONDS=30
```

**Recommended Settings:**
- **High quality line:** `VAD_SENSITIVITY=1`, `VAD_SILENCE_THRESHOLD_MS=500`
- **Noisy environment:** `VAD_SENSITIVITY=2`, `VAD_SILENCE_THRESHOLD_MS=800`
- **Very responsive:** `VAD_SILENCE_THRESHOLD_MS=500` (may cut off longer pauses)
- **Conservative:** `VAD_SILENCE_THRESHOLD_MS=1000` (waits longer, safer)

## Quick Start (PoC Demo)

### Step 1 — Get API Keys

**Gemini API key (free):**
1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click "Get API key" → Create key
3. Copy it

**Google Cloud credentials (for STT + TTS):**
1. Go to [GCP Console](https://console.cloud.google.com) → Create project
2. Enable: Cloud Speech-to-Text API + Cloud Text-to-Speech API
3. IAM → Service Accounts → Create → Download JSON key
4. Note the file path

> ⚠️ **PoC shortcut:** You can run with just `GEMINI_API_KEY` first. STT/TTS will fail at call time (not at startup), but the server will start and you can test the WebSocket connection.

### Step 2 — Set Up

```bash
cd poc-like-puch-ai
cp .env.example .env
# Edit .env with your keys
```

Minimum `.env` to start:
```
GEMINI_API_KEY=your-key-here
SAMPLE_RATE=8000
```

### Step 3 — Install and Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run the server
python -m src.infrastructure.server
# or: uvicorn src.infrastructure.server:app --host 0.0.0.0 --port 8000
```

Verify it works:
```bash
curl http://localhost:8000/health
# {"status": "ok", "active_sessions": 0}
```

### Step 4 — Expose with ngrok (for Exotel)

Exotel needs a public HTTPS URL.

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
# Copy the https URL, e.g.: https://abc123.ngrok-free.app
```

Your endpoints will be:
- WebSocket: `wss://abc123.ngrok-free.app/stream`
- Passthru: `https://abc123.ngrok-free.app/passthru`

### Step 5 — Configure Exotel

1. Log in to your [Exotel Dashboard](https://app.exotel.com)
2. Go to **App Bazaar** → **Create App**
3. Add a **VoiceBot Applet**:
   - URL: `wss://abc123.ngrok-free.app/stream?sample-rate=8000`
   - Sample Rate: 8000 Hz (default)
   - Authentication: IP Whitelist (for PoC) or Basic Auth
4. Add a **Passthru Applet** immediately after VoiceBot:
   - URL: `https://abc123.ngrok-free.app/passthru`
   - Mode: Async
5. Assign the app to your Exotel phone number
6. Call the number!

### Step 6 — Watch the Logs

```
✅ Puch AI Voice Server ready (sample_rate=8000Hz)
INFO: Exotel connection established
INFO: Call accepted: stream=<sid> caller=+91XXXXXXXXXX
INFO: Stream completed: stream=<sid> status=completed duration=28s
```

---

## Architecture

**Hexagonal Architecture (Ports & Adapters)**

```
Exotel WebSocket
       ↓
ExotelWebSocketHandler (Infrastructure)
       ↓
Use Cases: AcceptCall → ProcessAudio → GenerateResponse → StreamResponse → EndCall
       ↓              ↑              ↑                   ↑
   Domain      SpeechToTextPort  LanguageModelPort  TextToSpeechPort
                     ↓                 ↓                  ↓
               GoogleSTTAdapter  GeminiLLMAdapter  GoogleTTSAdapter
                    (swap any time — only change the adapter)
```

**Swapping providers:** To use Deepgram instead of Google STT, write `DeepgramSTTAdapter(SpeechToTextPort)` and change one line in `server.py`. No business logic changes needed.

## Project Structure

```
poc-like-puch-ai/
├── src/
│   ├── domain/              # Pure Python, zero dependencies
│   │   ├── entities/
│   │   ├── value_objects/
│   │   └── aggregates/
│   ├── use_cases/           # Application business rules
│   ├── ports/               # Interface definitions (ABCs)
│   ├── adapters/            # STT/LLM/TTS implementations
│   └── infrastructure/      # FastAPI server + WebSocket handler
├── tests/
│   ├── unit/                # Domain, use case, adapter tests (Fakes)
│   ├── integration/         # Gherkin scenario tests
│   └── smoke/               # Server startup tests
├── features/                # Gherkin feature files (BDD specs)
└── docs/                    # Domain definitions
```

## Design Principles

- **Hexagonal / Clean Architecture** — domain has zero external dependencies
- **SOLID** — all providers are injected via abstract ports
- **TDD** — every change: Red → Green → Refactor
- **Fakes not Mocks** — tests use Fake implementations, never mocks

## Running Tests

```bash
pytest                  # all 151+ tests
pytest --cov            # with coverage report
pytest tests/unit/      # unit tests only
pytest tests/smoke/     # startup smoke tests
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | **Required.** Google Gemini API key |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Path to GCP service account JSON (for STT/TTS) |
| `SAMPLE_RATE` | `8000` | Audio sample rate: 8000, 16000, or 24000 Hz |
| `LANGUAGE_CODE` | `en-US` | BCP-47 language code |
| `TTS_VOICE` | `en-US-Neural2-F` | Google TTS voice name |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `VAD_ENABLED` | `true` | Enable VAD-based utterance buffering |
| `VAD_SILENCE_THRESHOLD_MS` | `700` | Silence threshold before utterance flush |
| `VAD_SENSITIVITY` | `2` | WebRTC VAD sensitivity (0-3) |
| `MAX_SPEECH_BUFFER_SECONDS` | `30` | Max buffered speech duration before forced flush |
| `ENABLE_THINKING_INDICATOR` | `false` | Toggle thinking-indicator mode |

### Validation Snapshot

- Full suite: **269 passed**
- Coverage: **84%**

## Exotel Protocol Reference

| Direction | Events |
|-----------|--------|
| Exotel → Server | `connected`, `start`, `media`, `dtmf`, `mark`, `stop`, `clear` |
| Server → Exotel | `media` (audio), `mark` (playback tracking), `clear` (flush buffer) |

**Audio format:** PCM 16-bit little-endian, mono, base64-encoded  
**Chunk size:** multiples of 320 bytes; recommended 3200 bytes (100ms)  
**Timeout:** Exotel disconnects if server doesn't respond within 10 seconds

## References

- [Exotel AgentStream Documentation](https://docs.exotel.com/exotel-agentstream/agentstream)
- [google-genai SDK](https://github.com/google-gemini/generative-ai-python)
- [Clean Architecture by Uncle Bob](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)

## License

MIT
