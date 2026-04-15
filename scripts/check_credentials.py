#!/usr/bin/env python3
"""
check_credentials.py
────────────────────────────────────────────────────────────────────────────
Validates all three production credentials used by Puch AI Voice Server:

  1. GOOGLE_APPLICATION_CREDENTIALS  — service account JSON file (STT + TTS)
  2. Google Cloud Speech-to-Text      — recognise a 1-second silence clip
  3. Google Cloud Text-to-Speech      — synthesise "hello"
  4. GEMINI_API_KEY                   — generate one response token

Run directly:
    python scripts/check_credentials.py

Or via the shell wrapper:
    ./scripts/validate_production_credentials.sh

Exit codes:
    0  — all checks passed  ✅
    1  — one or more checks failed  ❌
"""

from __future__ import annotations

import json
import math
import os
import struct
import sys
from pathlib import Path

# ── Load .env before reading os.environ ──────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    # For this validator, prefer repo .env over any stale shell-exported values.
    load_dotenv(_env_path, override=True)
except ImportError:
    pass  # dotenv not installed — rely on environment variables already being set


# ── ANSI colours ──────────────────────────────────────────────────────────────
_GREEN  = "\033[0;32m"
_RED    = "\033[0;31m"
_YELLOW = "\033[0;33m"
_CYAN   = "\033[0;36m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  {_CYAN}{detail}{_RESET}" if detail else ""
    print(f"  {_GREEN}✅ PASS{_RESET}  {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f"\n          {_RED}{detail}{_RESET}" if detail else ""
    print(f"  {_RED}❌ FAIL{_RESET}  {label}{suffix}")


def _heading(title: str) -> None:
    print(f"\n{_BOLD}{_YELLOW}{'─' * 60}{_RESET}")
    print(f"{_BOLD}{title}{_RESET}")
    print(f"{_BOLD}{_YELLOW}{'─' * 60}{_RESET}")


def _pcm16_silence(duration_ms: int = 1000, sample_rate: int = 8000) -> bytes:
    """Return PCM16LE mono silence (all zeros), padded to 320-byte multiple."""
    n_samples = int(sample_rate * duration_ms / 1000)
    data = struct.pack(f"<{n_samples}h", *([0] * n_samples))
    remainder = len(data) % 320
    if remainder:
        data += b"\x00" * (320 - remainder)
    return data


def _pcm16_sine(duration_ms: int = 1000, sample_rate: int = 8000, freq: float = 440.0) -> bytes:
    """Return PCM16LE mono sine wave (440 Hz), padded to 320-byte multiple."""
    n_samples = int(sample_rate * duration_ms / 1000)
    amplitude = int(0.3 * 32767)
    samples = [
        int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
        for i in range(n_samples)
    ]
    data = struct.pack(f"<{n_samples}h", *samples)
    remainder = len(data) % 320
    if remainder:
        data += b"\x00" * (320 - remainder)
    return data


# ── Check 1: Google credentials file ─────────────────────────────────────────

def check_gcp_credentials_file() -> bool:
    """Verify GOOGLE_APPLICATION_CREDENTIALS points to a readable JSON file."""
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds_path:
        _fail(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "Environment variable is not set. Add it to .env",
        )
        return False

    path = Path(creds_path)
    if not path.exists():
        _fail(
            "GOOGLE_APPLICATION_CREDENTIALS",
            f"File not found: {creds_path}",
        )
        return False

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        _fail("GOOGLE_APPLICATION_CREDENTIALS", f"Cannot read/parse JSON: {exc}")
        return False

    project = data.get("project_id", "<unknown>")
    email   = data.get("client_email", "<unknown>")
    _ok(
        "GOOGLE_APPLICATION_CREDENTIALS",
        f"project={project}  client={email}",
    )
    return True


# ── Check 2: Google Cloud STT ─────────────────────────────────────────────────

def check_google_stt() -> bool:
    """
    Send 1 second of 440 Hz PCM16 to Google STT.

    We expect a successful API round-trip (even if the transcript is empty —
    a silence/tone clip will legitimately return no words). Any exception
    means credentials or API access are broken.
    """
    sample_rate = int(os.environ.get("SAMPLE_RATE", "8000"))
    try:
        from google.cloud import speech
        client = speech.SpeechClient()

        audio_bytes = _pcm16_sine(duration_ms=1000, sample_rate=sample_rate)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=os.environ.get("LANGUAGE_CODE", "en-US"),
        )
        audio = speech.RecognitionAudio(content=audio_bytes)
        response = client.recognize(config=config, audio=audio)
        n_results = len(response.results)
        _ok(
            "Google Cloud STT",
            f"API call succeeded — {n_results} result(s) returned (0 is normal for a tone)",
        )
        return True
    except ImportError:
        _fail(
            "Google Cloud STT",
            "google-cloud-speech not installed. Run: pip install google-cloud-speech",
        )
        return False
    except Exception as exc:
        _fail("Google Cloud STT", str(exc))
        return False


# ── Check 3: Google Cloud TTS ─────────────────────────────────────────────────

def check_google_tts() -> bool:
    """
    Synthesise the word "hello" using Google TTS.

    A successful call returns non-empty audio_content bytes.
    """
    sample_rate = int(os.environ.get("SAMPLE_RATE", "8000"))
    voice_name  = os.environ.get("TTS_VOICE", "en-US-Neural2-F")
    lang_code   = os.environ.get("LANGUAGE_CODE", "en-US")

    try:
        from google.cloud import texttospeech
        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(text="hello")
        voice = texttospeech.VoiceSelectionParams(
            language_code=lang_code,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
        )
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        n_bytes = len(response.audio_content)
        if n_bytes == 0:
            _fail("Google Cloud TTS", "Response returned 0 audio bytes")
            return False
        _ok(
            "Google Cloud TTS",
            f"Synthesised {n_bytes} bytes  voice={voice_name}",
        )
        return True
    except ImportError:
        _fail(
            "Google Cloud TTS",
            "google-cloud-texttospeech not installed. "
            "Run: pip install google-cloud-texttospeech",
        )
        return False
    except Exception as exc:
        _fail("Google Cloud TTS", str(exc))
        return False


# ── Check 4: Gemini API ───────────────────────────────────────────────────────

def check_gemini() -> bool:
    """
    Send a one-word prompt to Gemini and verify at least one text token is returned.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        _fail(
            "Gemini API",
            "GEMINI_API_KEY is not set. Add it to .env",
        )
        return False

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Reply with one word: hello",
        )
        text = response.text or ""
        if not text.strip():
            _fail("Gemini API", "Response returned empty text")
            return False
        _ok("Gemini API", f"Response: '{text.strip()[:60]}'")
        return True
    except ImportError:
        _fail(
            "Gemini API",
            "google-genai not installed. Run: pip install google-genai",
        )
        return False
    except Exception as exc:
        _fail("Gemini API", str(exc))
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print(f"{_BOLD}{_YELLOW}{'═' * 60}{_RESET}")
    print(f"{_BOLD}  Puch AI — Production Credential Checker{_RESET}")
    print(f"{_BOLD}{_YELLOW}{'═' * 60}{_RESET}")
    print()

    results = [
        ("GCP credentials file", check_gcp_credentials_file),
        ("Google Cloud STT",     check_google_stt),
        ("Google Cloud TTS",     check_google_tts),
        ("Gemini API",           check_gemini),
    ]

    passed = 0
    failed = 0

    for label, fn in results:
        _heading(f"Checking: {label}")
        try:
            ok = fn()
        except Exception as exc:
            _fail(label, f"Unexpected error: {exc}")
            ok = False
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print(f"{_BOLD}{_YELLOW}{'═' * 60}{_RESET}")
    if failed == 0:
        print(
            f"{_BOLD}{_GREEN}  🎉 All {passed} credential checks PASSED — "
            f"production mode is ready!{_RESET}"
        )
        print(f"{_BOLD}{_YELLOW}{'═' * 60}{_RESET}")
        print()
        return 0
    else:
        print(
            f"{_BOLD}{_RED}  💥 {failed} check(s) FAILED, {passed} passed.{_RESET}"
        )
        print(
            f"{_BOLD}{_RED}  Fix the issues above before running the server "
            f"in PRODUCTION mode.{_RESET}"
        )
        print(f"{_BOLD}{_YELLOW}{'═' * 60}{_RESET}")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
