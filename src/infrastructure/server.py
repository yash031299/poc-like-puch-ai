"""
Puch AI Voice Server — FastAPI application wiring all components together.

Run with:
    python -m src.infrastructure.server

Or directly:
    uvicorn src.infrastructure.server:app --host 0.0.0.0 --port 8000 --reload

Environment variables required (see .env.example):
    GEMINI_API_KEY           — Google Gemini API key (free tier)
    GOOGLE_APPLICATION_CREDENTIALS — path to Google Cloud service account JSON
    SAMPLE_RATE              — 8000 | 16000 | 24000 (default: 16000)
    PORT                     — server port (default: 8000)
    LOG_LEVEL                — DEBUG | INFO | WARNING (default: INFO)
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()  # Load .env file before anything reads os.environ

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from src.adapters.gemini_llm_adapter import GeminiLLMAdapter
from src.adapters.google_stt_adapter import GoogleSTTAdapter
from src.adapters.google_tts_adapter import GoogleTTSAdapter
from src.adapters.in_memory_session_repository import InMemorySessionRepository
from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler
from src.infrastructure.exotel_caller_audio_adapter import ExotelCallerAudioAdapter
from src.use_cases.accept_call import AcceptCallUseCase
from src.use_cases.end_call import EndCallUseCase
from src.use_cases.generate_response import GenerateResponseUseCase
from src.use_cases.process_audio import ProcessAudioUseCase
from src.use_cases.reset_session import ResetSessionUseCase
from src.use_cases.stream_response import StreamResponseUseCase

# ── Logging ───────────────────────────────────────────────────────────────────
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Shared singletons (created once at startup) ───────────────────────────────
_session_repo: InMemorySessionRepository
_ws_handler: ExotelWebSocketHandler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise all adapters and use cases on startup."""
    global _session_repo, _ws_handler

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    sample_rate = int(os.environ.get("SAMPLE_RATE", "8000"))  # Exotel default is 8000 Hz
    language_code = os.environ.get("LANGUAGE_CODE", "en-US")
    tts_voice = os.environ.get("TTS_VOICE", "en-US-Neural2-F")

    if not gemini_key:
        logger.warning("GEMINI_API_KEY not set — LLM responses will fail")

    # ── Adapters ───────────────────────────────────────────────────────────────
    # STT/TTS providers are interchangeable — swap the adapter classes here
    # to use Deepgram, Whisper, ElevenLabs, etc. without touching use cases.
    # Future: read STT_PROVIDER / TTS_PROVIDER env vars to select at runtime.
    _session_repo = InMemorySessionRepository()

    llm = GeminiLLMAdapter(api_key=gemini_key)
    stt = GoogleSTTAdapter(language_code=language_code)
    tts = GoogleTTSAdapter(
        language_code=language_code,
        voice_name=tts_voice,
        sample_rate=sample_rate,
    )

    # CallerAudioAdapter is per-connection; factory injected into use case layer
    audio_out = ExotelCallerAudioAdapter()

    # ── Use cases ──────────────────────────────────────────────────────────────
    accept_uc = AcceptCallUseCase(session_repo=_session_repo)
    reset_uc = ResetSessionUseCase(session_repo=_session_repo)
    generate_uc = GenerateResponseUseCase(session_repo=_session_repo, llm=llm)
    stream_uc = StreamResponseUseCase(
        session_repo=_session_repo, tts=tts, audio_out=audio_out
    )

    process_uc = ProcessAudioUseCase(
        session_repo=_session_repo,
        stt=stt,
        generate_response=generate_uc,
        stream_response=stream_uc,
    )
    end_uc = EndCallUseCase(session_repo=_session_repo)

    _ws_handler = ExotelWebSocketHandler(
        accept_call=accept_uc,
        process_audio=process_uc,
        end_call=end_uc,
        sample_rate=sample_rate,
        audio_adapter=audio_out,
        reset_session=reset_uc,
    )

    logger.info("✅ Puch AI Voice Server ready (sample_rate=%dHz)", sample_rate)
    yield
    logger.info("Server shutting down. Active sessions: %d", len(_session_repo))


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Puch AI Voice Server",
    description="Exotel AgentStream → AI pipeline",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> JSONResponse:
    """Health check endpoint for load balancers and smoke tests."""
    active = len(_session_repo) if "_session_repo" in globals() else 0
    return JSONResponse({"status": "ok", "active_sessions": active})


@app.get("/passthru")
async def passthru(request: Request) -> JSONResponse:
    """
    Exotel Passthru Applet endpoint.

    Exotel calls this HTTP GET after the VoiceBot stream ends, passing:
      Stream[StreamSID], Stream[Status], Stream[Duration],
      Stream[RecordingUrl], Stream[DisconnectedBy], Stream[Error]

    Place the Passthru Applet immediately after the VoiceBot Applet in
    your Exotel flow and point it to: https://<your-host>/passthru

    Returns 200 to allow Exotel to proceed to the next applet.
    """
    params = dict(request.query_params)
    stream_sid = params.get("Stream[StreamSID]", params.get("StreamSID", "unknown"))
    status = params.get("Stream[Status]", params.get("Status", "unknown"))
    duration = params.get("Stream[Duration]", params.get("Duration", "0"))
    disconnected_by = params.get("Stream[DisconnectedBy]", params.get("DisconnectedBy", "NA"))
    recording_url = params.get("Stream[RecordingUrl]", params.get("RecordingUrl", ""))
    error = params.get("Stream[Error]", params.get("Error", ""))

    if error:
        logger.error(
            "Stream ended with error: stream=%s status=%s error=%s disconnected_by=%s",
            stream_sid, status, error, disconnected_by,
        )
    else:
        logger.info(
            "Stream completed: stream=%s status=%s duration=%ss disconnected_by=%s recording=%s",
            stream_sid, status, duration, disconnected_by, recording_url or "none",
        )

    return JSONResponse({"status": "ok"})


@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket) -> None:
    """
    Primary Exotel AgentStream WebSocket endpoint.

    URL: wss://<host>/stream?sample-rate=8000
    Exotel connects here when a call is routed to your VoiceBot Applet.

    Exotel will disconnect if the server doesn't respond within 10 seconds.
    One automatic retry on handshake failure.
    """
    # Per-connection sample-rate override from Exotel query params
    qs_rate = websocket.query_params.get("sample-rate")
    if qs_rate and qs_rate.isdigit():
        _ws_handler._sample_rate = int(qs_rate)

    try:
        await _ws_handler.handle(websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected cleanly (Exotel closed connection)")
    except Exception as exc:
        logger.error("Unexpected WebSocket error: %s", exc, exc_info=True)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler — log unexpected errors and return 500."""
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "src.infrastructure.server:app",
        host="0.0.0.0",
        port=port,
        log_level=log_level.lower(),
        reload=os.environ.get("RELOAD", "false").lower() == "true",
    )
