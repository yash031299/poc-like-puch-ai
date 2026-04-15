"""Tests for scripts/sim_exotel_live.py helper message builders."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path


def _load_module():
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "sim_exotel_live.py"
    )
    spec = importlib.util.spec_from_file_location("sim_exotel_live", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_start_event_shape():
    mod = _load_module()
    msg = mod.build_start_event("stream-1", 8000)
    assert msg["event"] == "start"
    assert msg["stream_sid"] == "stream-1"
    assert msg["start"]["stream_sid"] == "stream-1"
    assert msg["start"]["media_format"]["sample_rate"] == "8000"


def test_build_media_event_contains_base64_payload():
    mod = _load_module()
    payload = bytes(640)
    msg = mod.build_media_event("stream-1", 2, 1, 20, payload)
    assert msg["event"] == "media"
    assert msg["media"]["chunk"] == "1"
    assert msg["media"]["timestamp"] == "20"
    decoded = base64.b64decode(msg["media"]["payload"])
    assert decoded == payload


def test_to_320_multiple_pads_bytes():
    mod = _load_module()
    data = bytes(321)
    padded = mod.to_320_multiple(data)
    assert len(padded) % 320 == 0
    assert padded.startswith(data)


def test_safe_queue_put_latest_accepts_when_available():
    """safe_queue_put_latest should put payload when queue has space."""
    import asyncio

    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=3)
    payload1 = b"frame1"
    payload2 = b"frame2"

    # Import the helper function
    mod = _load_module()
    safe_queue_put_latest = mod.safe_queue_put_latest

    # First put should succeed
    safe_queue_put_latest(q, payload1)
    assert q.qsize() == 1

    # Second put should also succeed (queue has space)
    safe_queue_put_latest(q, payload2)
    assert q.qsize() == 2

    # Verify order
    assert q.get_nowait() == payload1
    assert q.get_nowait() == payload2


def test_safe_queue_put_latest_drops_oldest_on_full():
    """safe_queue_put_latest should drop oldest item when queue is full."""
    import asyncio

    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
    payload1 = b"frame1"
    payload2 = b"frame2"
    payload3 = b"frame3"

    mod = _load_module()
    safe_queue_put_latest = mod.safe_queue_put_latest

    # Fill queue
    safe_queue_put_latest(q, payload1)
    safe_queue_put_latest(q, payload2)
    assert q.qsize() == 2

    # Queue is full; add new item (drops oldest, adds newest)
    safe_queue_put_latest(q, payload3)
    assert q.qsize() == 2

    # Should have payload2 and payload3 (payload1 was dropped)
    assert q.get_nowait() == payload2
    assert q.get_nowait() == payload3
