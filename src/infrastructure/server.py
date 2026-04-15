"""
Puch AI Voice Server — FastAPI application wiring all components together.

Run with:
    python -m src.infrastructure.server

Or directly:
    uvicorn src.infrastructure.server:app --host 0.0.0.0 --port 8000 --reload

Environment variables (see .env.example):
    GEMINI_API_KEY           — Google Gemini API key (free tier)
    GOOGLE_APPLICATION_CREDENTIALS — path to Google Cloud service account JSON
    SAMPLE_RATE              — 8000 | 16000 | 24000 (default: 8000)
    PORT                     — server port (default: 8000)
    LOG_LEVEL                — DEBUG | INFO | WARNING (default: INFO)
    LOG_FORMAT               — text | JSON (default: text)

DEV / LOCAL TESTING (no API keys needed):
    DEV_MODE=true python -m src.infrastructure.server

    In DEV_MODE all three AI adapters are replaced with zero-credential stubs:
      StubSTTAdapter  → returns hardcoded transcript every 3 audio chunks
      StubLLMAdapter  → returns hardcoded response words
      StubTTSAdapter  → returns 440 Hz sine-wave PCM audio (real audio, no cloud)

    This lets you validate the full Exotel protocol + pipeline locally using
    scripts/sim_exotel.py without any Exotel KYC, Google Cloud, or Gemini key.

HYBRID MODE (real STT+TTS, stub LLM — for testing when Gemini quota exhausted):
    HYBRID_MODE=true python -m src.infrastructure.server

    In HYBRID_MODE:
      GoogleSTTAdapter  → real Google Cloud Speech-to-Text (tests buffering fix)
      StubLLMAdapter    → returns hardcoded response (bypasses Gemini quota)
      GoogleTTSAdapter  → real Google Cloud Text-to-Speech

    Use this to test the STT audio buffering fix with real phone calls when
    your Gemini free tier quota is exhausted.

POC SIMPLE LLM MODE (real STT+TTS, greeting once then non-streaming Gemini LLM):
    POC_SIMPLE_LLM_MODE=true python -m src.infrastructure.server

    In POC_SIMPLE_LLM_MODE:
      GoogleSTTAdapter           → real Google Cloud Speech-to-Text
      PoCGreetingThenLLMAdapter  → first greeting deterministic, then non-streaming Gemini
      GoogleTTSAdapter           → real Google Cloud Text-to-Speech

    This mode avoids Gemini streaming while still enabling live conversational replies.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
load_dotenv()  # Load .env file before anything reads os.environ


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


# Configure structured logging as early as possible (before any module-level loggers fire)
from src.infrastructure.logging_config import configure_logging, log_context  # noqa: E402
configure_logging()
logger = logging.getLogger(__name__)


def _initialize_runtime_tracing() -> None:
    """
    Initialize tracing based on selected runtime mode.

    Tracing is disabled in DEV_MODE and POC_SIMPLE_LLM_MODE.
    """
    dev_mode = _is_truthy(os.environ.get("DEV_MODE", "false"))
    poc_simple_mode = _is_truthy(os.environ.get("POC_SIMPLE_LLM_MODE", "false"))

    if dev_mode:
        logger.info("DEV_MODE enabled — OpenTelemetry tracing disabled")
        return
    if poc_simple_mode:
        logger.info("POC_SIMPLE_LLM_MODE enabled — OpenTelemetry tracing disabled")
        return

    from src.infrastructure.tracing import init_tracing  # noqa: E402
    init_tracing()


_initialize_runtime_tracing()

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from src.adapters.gemini_llm_adapter import GeminiLLMAdapter
from src.adapters.poc_greeting_then_llm_adapter import PoCGreetingThenLLMAdapter
from src.adapters.google_stt_adapter import GoogleSTTAdapter
from src.adapters.google_tts_adapter import GoogleTTSAdapter
from src.adapters.stub_stt_adapter import StubSTTAdapter
from src.adapters.stub_llm_adapter import StubLLMAdapter
from src.adapters.stub_tts_adapter import StubTTSAdapter
from src.adapters.in_memory_session_repository import InMemorySessionRepository
from src.adapters.webrtc_vad_adapter import WebRTCVADAdapter
from src.domain.services.audio_buffer_manager import AudioBufferManager
from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler
from src.infrastructure.exotel_caller_audio_adapter import ExotelCallerAudioAdapter
from src.infrastructure.rate_limiter import RateLimiter
from src.infrastructure.auth import AuthenticatorConfig
from src.use_cases.accept_call import AcceptCallUseCase
from src.use_cases.end_call import EndCallUseCase
from src.use_cases.generate_response import GenerateResponseUseCase
from src.use_cases.process_audio import ProcessAudioUseCase
from src.use_cases.reset_session import ResetSessionUseCase
from src.use_cases.stream_response import StreamResponseUseCase

logger = logging.getLogger(__name__)

# ── Shared singletons (created once at startup) ───────────────────────────────
_session_repo: InMemorySessionRepository
_ws_handler: ExotelWebSocketHandler
_rate_limiter: RateLimiter
_authenticator: AuthenticatorConfig

# ── Graceful shutdown tracking ──────────────────────────────────────────────────
_active_websockets: set = set()  # Track active WebSocket connections
_shutdown_event: asyncio.Event = asyncio.Event()  # Signals shutdown in progress


def _get_active_connection_count() -> int:
    """Return the current number of active WebSocket connections."""
    return len(_active_websockets)


async def _track_websocket(ws: Any) -> None:
    """Register a WebSocket connection during shutdown tracking."""
    _active_websockets.add(id(ws))


async def _untrack_websocket(ws: Any) -> None:
    """Unregister a WebSocket connection."""
    _active_websockets.discard(id(ws))


async def _drain_connections(timeout_seconds: int = 30) -> None:
    """
    Graceful connection draining during shutdown.
    
    - Signals all active connections to prepare for graceful close
    - Waits up to timeout_seconds for connections to complete
    - Forcefully closes remaining connections after timeout
    """
    logger.info(
        "🔴 Graceful shutdown initiated. Draining %d active WebSocket connection(s). "
        "Timeout: %ds", len(_active_websockets), timeout_seconds
    )
    _shutdown_event.set()
    
    try:
        # Wait for connections to close gracefully (with timeout)
        start_time = asyncio.get_event_loop().time()
        while _active_websockets and (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            await asyncio.sleep(0.5)
            remaining = len(_active_websockets)
            if remaining > 0:
                logger.debug("Waiting for %d connection(s) to close...", remaining)
    except Exception as e:
        logger.error("Error during connection draining: %s", e)
    
    if _active_websockets:
        logger.warning(
            "⏱️  Shutdown timeout exceeded. Force-closing %d remaining connection(s)",
            len(_active_websockets)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise all adapters and use cases on startup."""
    global _session_repo, _ws_handler, _rate_limiter, _authenticator

    dev_mode = _is_truthy(os.environ.get("DEV_MODE", "false"))
    poc_simple_mode = _is_truthy(os.environ.get("POC_SIMPLE_LLM_MODE", "false"))
    # HYBRID_MODE: real STT+TTS but stub LLM (for testing when Gemini quota exhausted)
    hybrid_mode = _is_truthy(os.environ.get("HYBRID_MODE", "false"))
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    sample_rate = int(os.environ.get("SAMPLE_RATE", "8000"))  # Exotel default is 8000 Hz
    language_code = os.environ.get("LANGUAGE_CODE", "en-US")
    tts_voice = os.environ.get("TTS_VOICE", "en-US-Neural2-F")

    # Rate limiting configuration
    ip_rate_limit = float(os.environ.get("RATE_LIMIT_IP", "100.0"))  # tokens/sec per IP
    stream_rate_limit = float(os.environ.get("RATE_LIMIT_STREAM", "50.0"))  # tokens/sec per stream
    rate_limit_config = os.environ.get("RATE_LIMIT_CONFIG", "config/rate-limits.yaml")
    
    # Initialize hierarchical rate limiter with config file
    _rate_limiter = RateLimiter(config_path=rate_limit_config)
    
    # Authentication configuration (IP whitelist + Bearer tokens)
    _authenticator = AuthenticatorConfig()
    
    # Connection draining configuration (load balancer coordination)
    max_connections = int(os.environ.get("MAX_CONNECTIONS_PER_INSTANCE", "200"))

    # VAD configuration
    vad_enabled = os.environ.get("VAD_ENABLED", "true").lower() in ("true", "1", "yes")
    # In DEV_MODE, disable VAD by default to keep stub STT behaviour deterministic.
    if dev_mode and "VAD_ENABLED" not in os.environ:
        vad_enabled = False
    vad_silence_threshold = int(os.environ.get("VAD_SILENCE_THRESHOLD_MS", "700"))
    # Default sensitivity: 0 in DEV_MODE (less aggressive for test tones), 2 in production
    default_sensitivity = "0" if dev_mode else "2"
    vad_sensitivity = int(os.environ.get("VAD_SENSITIVITY", default_sensitivity))
    logger.debug(f"VAD config: dev_mode={dev_mode}, default_sensitivity={default_sensitivity}, vad_sensitivity={vad_sensitivity}")
    max_buffer_duration = int(os.environ.get("MAX_SPEECH_BUFFER_SECONDS", "30"))
    default_min_transcribe = "0" if dev_mode else "900"
    min_transcribe_audio_ms = int(
        os.environ.get("MIN_TRANSCRIBE_AUDIO_MS", default_min_transcribe)
    )
    utterance_dedup_window_ms = int(os.environ.get("UTTERANCE_DEDUP_WINDOW_MS", "2000"))
    enable_thinking_indicator = _is_truthy(os.environ.get("ENABLE_THINKING_INDICATOR", "false"))

    if sum(int(flag) for flag in (dev_mode, poc_simple_mode, hybrid_mode)) > 1:
        logger.warning(
            "Multiple runtime modes enabled simultaneously. Priority order: DEV_MODE > POC_SIMPLE_LLM_MODE > HYBRID_MODE > PRODUCTION."
        )

    # ── Adapters ───────────────────────────────────────────────────────────────
    # STT/TTS/LLM providers are interchangeable — only this block changes when
    # swapping providers (Deepgram, Whisper, ElevenLabs, etc.).
    _session_repo = InMemorySessionRepository()

    if dev_mode:
        # Zero-credential stubs — full pipeline works with NO API keys.
        # Use DEV_MODE=true for local testing / Exotel simulator.
        logger.info(
            "🔧 DEV_MODE enabled — using stub adapters (no API keys required). "
            "StubSTT triggers once per utterance flush. StubTTS emits 440 Hz sine wave."
        )
        stt = StubSTTAdapter(
            transcript="Hello, can you hear me? This is a local test.",
            trigger_every=1,
        )
        llm = StubLLMAdapter(
            response=(
                "Hello! I am your AI voice assistant and I am working correctly. "
                "The full pipeline is operational."
            )
        )
        tts = StubTTSAdapter(sample_rate=sample_rate, duration_ms=400)
    elif poc_simple_mode:
        logger.info(
            "🔧 POC_SIMPLE_LLM_MODE enabled — first greeting deterministic, then non-streaming Gemini replies."
        )
        if not gemini_key:
            logger.warning(
                "GEMINI_API_KEY not set in POC_SIMPLE_LLM_MODE — post-greeting turns will use fallback canned response."
            )
        stt = GoogleSTTAdapter(language_code=language_code, sample_rate=sample_rate)
        llm = PoCGreetingThenLLMAdapter(
            api_key=gemini_key,
            model_name=os.environ.get("POC_SIMPLE_LLM_MODEL", "gemini-2.5-flash"),
            fallback_response=os.environ.get(
                "POC_SIMPLE_LLM_RESPONSE",
                (
                    "Hello! This is our PoC assistant. I can hear you and respond clearly. "
                    "Please tell me what you would like to test next."
                ),
            ),
            greeting_response=os.environ.get(
                "POC_SIMPLE_GREETING_RESPONSE",
                "Hi! Yes, I can hear you. The PoC mode is running correctly.",
            ),
        )
        tts = GoogleTTSAdapter(
            language_code=language_code,
            voice_name=tts_voice,
            sample_rate=sample_rate,
        )
    elif hybrid_mode:
        # Real STT+TTS but stub LLM — useful when Gemini quota exhausted.
        # Use HYBRID_MODE=true to test STT buffering fix with real Google APIs.
        logger.info(
            "🔧 HYBRID_MODE enabled — real Google STT+TTS, stub LLM. "
            "Use this to test STT audio buffering when Gemini quota is exhausted."
        )
        stt = GoogleSTTAdapter(language_code=language_code, sample_rate=sample_rate)
        llm = StubLLMAdapter(
            response=(
                "Thank you for calling. I heard you clearly. "
                "This is a hybrid test with real speech recognition but simulated AI response."
            )
        )
        tts = GoogleTTSAdapter(
            language_code=language_code,
            voice_name=tts_voice,
            sample_rate=sample_rate,
        )
    else:
        # Production adapters — require valid credentials in environment.
        if not gemini_key:
            logger.warning("GEMINI_API_KEY not set — LLM responses will fail at call time")
        llm = GeminiLLMAdapter(api_key=gemini_key)
        stt = GoogleSTTAdapter(language_code=language_code, sample_rate=sample_rate)
        tts = GoogleTTSAdapter(
            language_code=language_code,
            voice_name=tts_voice,
            sample_rate=sample_rate,
        )

    # CallerAudioAdapter: sends TTS audio back over the active WebSocket
    audio_out = ExotelCallerAudioAdapter()

    # ── VAD & Buffer Manager ──────────────────────────────────────────────────
    buffer_manager = None
    if vad_enabled:
        try:
            vad = WebRTCVADAdapter(sensitivity=vad_sensitivity)
            buffer_manager = AudioBufferManager(
                vad=vad,
                silence_threshold_ms=vad_silence_threshold,
                max_buffer_duration_seconds=max_buffer_duration
            )
            logger.info(
                "✅ VAD enabled: sensitivity=%d, silence_threshold=%dms, max_buffer=%ds",
                vad_sensitivity, vad_silence_threshold, max_buffer_duration
            )
        except Exception as e:
            logger.error("Failed to initialize VAD: %s. Continuing without VAD.", e)
            buffer_manager = None
    else:
        logger.info("VAD disabled — processing every audio chunk (may cause excessive LLM calls)")

    # ── Use cases ──────────────────────────────────────────────────────────────
    accept_uc = AcceptCallUseCase(session_repo=_session_repo)
    reset_uc = ResetSessionUseCase(session_repo=_session_repo)
    generate_uc = GenerateResponseUseCase(
        session_repo=_session_repo,
        llm=llm,
        degraded_response_text=os.environ.get(
            "LLM_DEGRADED_RESPONSE_TEXT",
            "I am facing a temporary delay right now. Please try again in a moment.",
        ),
    )
    stream_uc = StreamResponseUseCase(
        session_repo=_session_repo, tts=tts, audio_out=audio_out
    )
    process_uc = ProcessAudioUseCase(
        session_repo=_session_repo,
        stt=stt,
        buffer_manager=buffer_manager,  # NEW: Inject buffer manager
        generate_response=generate_uc,
        stream_response=stream_uc,
        min_transcribe_audio_ms=min_transcribe_audio_ms,
        dedup_window_ms=utterance_dedup_window_ms,
    )
    end_uc = EndCallUseCase(session_repo=_session_repo)

    _ws_handler = ExotelWebSocketHandler(
        accept_call=accept_uc,
        process_audio=process_uc,
        end_call=end_uc,
        session_repo=_session_repo,
        sample_rate=sample_rate,
        audio_adapter=audio_out,
        reset_session=reset_uc,
        stt=stt,
        buffer_manager=buffer_manager,
    )

    mode_label = (
        "DEV (stubs)"
        if dev_mode
        else (
            "POC_SIMPLE (real STT+TTS)"
            if poc_simple_mode
            else ("HYBRID (real STT+TTS)" if hybrid_mode else "PRODUCTION")
        )
    )
    vad_status = "enabled" if vad_enabled else "disabled"
    logger.info(
        "✅ Puch AI Voice Server ready — mode=%s sample_rate=%dHz VAD=%s",
        mode_label, sample_rate, vad_status
    )
    
    # Log VAD metrics on startup if enabled
    if buffer_manager:
        logger.info(
            "   📊 VAD config: sensitivity=%d, silence=%dms, max_buffer=%ds",
            vad_sensitivity, vad_silence_threshold, max_buffer_duration
        )
        logger.info(
            "   🧠 Utterance gate: min_transcribe=%dms dedup_window=%dms",
            min_transcribe_audio_ms,
            utterance_dedup_window_ms,
        )
    logger.info("   🔔 Thinking indicator: %s", "enabled" if enable_thinking_indicator else "disabled")
    
    yield
    
    # Graceful shutdown: drain connections with timeout
    graceful_shutdown_timeout = int(os.environ.get("GRACEFUL_SHUTDOWN_TIMEOUT_S", "30"))
    await _drain_connections(timeout_seconds=graceful_shutdown_timeout)
    
    # Log final metrics on shutdown
    logger.info("Server shutting down. Active sessions: %d", len(_session_repo))
    if buffer_manager and _session_repo:
        # Log aggregated buffer metrics
        logger.info("VAD Buffer Metrics Summary:")
        for stream_id in list(_session_repo._sessions.keys()) if hasattr(_session_repo, '_sessions') else []:
            metrics = buffer_manager.get_metrics(stream_id)
            sent_segments = audio_out.get_sent_segment_count(stream_id) if hasattr(audio_out, "get_sent_segment_count") else 0
            logger.info(
                "  Stream %s: buffered=%d flushes=%d flushed_chunks=%d flushed_audio_s=%.2f sent_segments=%d state=%s",
                stream_id[:8], metrics['chunks_buffered'], 
                metrics['flushes_count'],
                metrics.get('chunks_flushed_total', 0),
                metrics.get('audio_seconds_flushed_total', 0.0),
                sent_segments,
                metrics['state']
            )
    
    logger.info("✅ Server shutdown complete")


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


@app.get("/cost-metrics")
async def get_cost_metrics() -> JSONResponse:
    """Get current cost metrics and budget status."""
    if not hasattr(app.state, 'cost_tracker'):
        return JSONResponse(
            status_code=503,
            content={"error": "Cost tracker not initialized"},
        )
    
    tracker = app.state.cost_tracker
    breakdown = tracker.get_cost_breakdown()
    
    return JSONResponse(
        status_code=200,
        content={
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "daily": {
                "cost": round(breakdown["total"], 6),
                "budget": tracker.daily_budget_usd,
                "remaining": round(breakdown["remaining_budget"], 6),
                "percentage": round(breakdown["budget_percentage"], 2),
                "exceeded": tracker.is_budget_exceeded(),
            },
            "monthly": {
                "cost": round(breakdown["monthly_total"], 6),
                "budget": tracker.monthly_budget_usd,
                "remaining": round(breakdown["monthly_remaining"], 6),
                "percentage": round(breakdown["monthly_percentage"], 2),
                "exceeded": tracker.is_monthly_budget_exceeded(),
            },
            "providers": {
                "google_stt": round(breakdown["google_stt"], 6),
                "google_tts": round(breakdown["google_tts"], 6),
                "gemini": round(breakdown["gemini"], 6),
                "openai": round(breakdown["openai"], 6),
            },
        },
    )


@app.get("/cost-per-user/{user_id}")
async def get_user_costs(user_id: str) -> JSONResponse:
    """Get cost breakdown for a specific user."""
    if not hasattr(app.state, 'cost_tracker'):
        return JSONResponse(
            status_code=503,
            content={"error": "Cost tracker not initialized"},
        )
    
    tracker = app.state.cost_tracker
    user_costs = tracker.get_user_costs(user_id)
    
    return JSONResponse(
        status_code=200,
        content={
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "user_id": user_id,
            "daily_cost": round(user_costs["daily_cost"], 6),
            "call_count": user_costs["call_count"],
            "average_cost_per_call": round(user_costs["average_cost_per_call"], 6),
            "daily_limit": user_costs["budget_limit"],
            "limit_exceeded": user_costs["budget_exceeded"],
        },
    )


@app.get("/cache-metrics")
async def get_cache_metrics() -> JSONResponse:
    """Get semantic cache hit rate and metrics."""
    if not hasattr(app.state, 'semantic_cache'):
        return JSONResponse(
            status_code=503,
            content={"error": "Semantic cache not initialized"},
        )
    
    cache = app.state.semantic_cache
    metrics = cache.get_metrics()
    
    return JSONResponse(
        status_code=200,
        content={
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "hit_count": metrics["hit_count"],
            "miss_count": metrics["miss_count"],
            "total_requests": metrics["total_requests"],
            "hit_rate_percent": metrics["hit_rate_percent"],
            "average_hit_similarity": metrics["average_hit_similarity"],
            "configuration": {
                "threshold": metrics["threshold"],
                "ttl_seconds": metrics["ttl_seconds"],
                "max_entries": metrics["max_entries"],
            },
        },
    )


@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket) -> None:
    """
    Primary Exotel AgentStream WebSocket endpoint.

    URL: wss://<host>/stream?sample-rate=8000
    Exotel connects here when a call is routed to your VoiceBot Applet.

    Exotel will disconnect if the server doesn't respond within 10 seconds.
    One automatic retry on handshake failure.
    """
    # Reject new connections during shutdown
    if _shutdown_event.is_set():
        logger.warning("Rejecting new WebSocket connection during shutdown")
        await websocket.close(code=1001, reason="Server shutting down")
        return
    
    # Per-connection sample-rate override from Exotel query params
    qs_rate = websocket.query_params.get("sample-rate")
    if qs_rate and qs_rate.isdigit():
        _ws_handler._sample_rate = int(qs_rate)

    # Correlation: client IP for early logging before stream_id is known
    client_ip = websocket.client.host if websocket.client else "unknown"
    with log_context(client_ip=client_ip):
        try:
            await _track_websocket(websocket)
            await _ws_handler.handle(websocket)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected cleanly (Exotel closed connection)")
        except Exception as exc:
            logger.error("Unexpected WebSocket error: %s", exc, exc_info=True)
        finally:
            await _untrack_websocket(websocket)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler — log unexpected errors and return 500."""
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    # Use uvloop for ~4x faster async I/O on Linux/macOS (ignored silently if unavailable)
    try:
        import uvloop  # type: ignore
        uvloop.install()
        logger.info("uvloop event loop installed")
    except ImportError:
        pass  # Falls back to default asyncio event loop

    port = int(os.environ.get("PORT", "8000"))
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    reload_enabled = os.environ.get("RELOAD", "false").lower() == "true"
    app_target = "src.infrastructure.server:app" if reload_enabled else app
    uvicorn.run(
        app_target,
        host="0.0.0.0",
        port=port,
        log_level=log_level_str.lower(),
        loop="uvloop",  # uvicorn will fall back to asyncio if unavailable
        reload=reload_enabled,
    )
