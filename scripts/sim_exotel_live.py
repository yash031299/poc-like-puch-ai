#!/usr/bin/env python3
"""
sim_exotel_live.py — Live Exotel-like simulator using microphone + speaker.

Runs a local websocket call loop against `/stream`:
connected -> start -> media* ... and plays server media back to speakers.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import queue
import signal
import time
import uuid
from dataclasses import dataclass

import websockets

def build_connected_event() -> dict:
    return {"event": "connected"}


def build_start_event(stream_sid: str, sample_rate: int) -> dict:
    return {
        "event": "start",
        "sequence_number": "1",
        "stream_sid": stream_sid,
        "start": {
            "stream_sid": stream_sid,
            "call_sid": f"live-{stream_sid[:8]}",
            "account_sid": "local-simulator",
            "from": "+910000000001",
            "to": "+911800000000",
            "custom_parameters": {"simulator": "live-mic"},
            "media_format": {
                "encoding": "base64",
                "sample_rate": str(sample_rate),
                "bit_rate": "128kbps",
            },
        },
    }


def build_media_event(
    stream_sid: str,
    sequence_number: int,
    chunk_number: int,
    timestamp_ms: int,
    audio_bytes: bytes,
) -> dict:
    return {
        "event": "media",
        "sequence_number": str(sequence_number),
        "stream_sid": stream_sid,
        "media": {
            "chunk": str(chunk_number),
            "timestamp": str(timestamp_ms),
            "payload": base64.b64encode(audio_bytes).decode("ascii"),
        },
    }


def build_stop_event(stream_sid: str, sequence_number: int) -> dict:
    return {
        "event": "stop",
        "sequence_number": str(sequence_number),
        "stream_sid": stream_sid,
        "stop": {
            "call_sid": f"live-{stream_sid[:8]}",
            "account_sid": "local-simulator",
            "reason": "callended",
        },
    }


def to_320_multiple(data: bytes) -> bytes:
    rem = len(data) % 320
    if rem:
        data += b"\x00" * (320 - rem)
    return data


def safe_queue_put_latest(q: asyncio.Queue[bytes], payload: bytes) -> None:
    """
    Push payload into asyncio queue without raising callback exceptions.

    If queue is full, drop oldest item and keep latest audio frame to preserve
    real-time behavior.
    """
    try:
        q.put_nowait(payload)
        return
    except asyncio.QueueFull:
        pass

    try:
        _ = q.get_nowait()
    except asyncio.QueueEmpty:
        return

    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        # Another producer filled queue in between; skip frame.
        return


@dataclass
class LiveConfig:
    ws_url: str
    sample_rate: int
    frame_ms: int


class PlaybackBuffer:
    def __init__(self) -> None:
        self.q: queue.Queue[bytes] = queue.Queue(maxsize=256)
        self.pending = bytearray()

    def push(self, data: bytes) -> None:
        try:
            self.q.put_nowait(data)
        except queue.Full:
            # Drop oldest frame to keep playback real-time.
            _ = self.q.get_nowait()
            self.q.put_nowait(data)

    def pull(self, bytes_needed: int) -> bytes:
        while len(self.pending) < bytes_needed:
            try:
                self.pending.extend(self.q.get_nowait())
            except queue.Empty:
                break
        out = bytes(self.pending[:bytes_needed])
        del self.pending[:bytes_needed]
        if len(out) < bytes_needed:
            out += b"\x00" * (bytes_needed - len(out))
        return out


async def run_live_session(cfg: LiveConfig) -> None:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise SystemExit(
            "sounddevice is required. Install dependencies and retry: pip install sounddevice"
        ) from exc

    stream_sid = f"live-{uuid.uuid4().hex[:12]}"
    frame_bytes = int(cfg.sample_rate * (cfg.frame_ms / 1000.0) * 2)
    if frame_bytes <= 0:
        raise ValueError("Invalid frame configuration")
    frame_bytes = ((frame_bytes + 319) // 320) * 320

    mic_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)
    playback = PlaybackBuffer()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def on_input(indata, frames, _time_info, status) -> None:
        if status:
            print(f"[mic] status={status}")
        payload = bytes(indata)
        payload = to_320_multiple(payload)
        loop.call_soon_threadsafe(safe_queue_put_latest, mic_q, payload)

    def on_output(outdata, frames, _time_info, status) -> None:
        if status:
            print(f"[spk] status={status}")
        need = frames * 2
        outdata[:] = playback.pull(need)

    async with websockets.connect(cfg.ws_url, max_size=2_000_000) as ws:
        print(f"Connected to {cfg.ws_url} stream_sid={stream_sid}")
        await ws.send(json.dumps(build_connected_event()))
        await ws.send(json.dumps(build_start_event(stream_sid, cfg.sample_rate)))

        started = time.monotonic()
        seq = 2
        chunk = 1

        async def sender() -> None:
            nonlocal seq, chunk
            while not stop_event.is_set():
                audio = await mic_q.get()
                ts_ms = int((time.monotonic() - started) * 1000)
                event = build_media_event(stream_sid, seq, chunk, ts_ms, audio)
                await ws.send(json.dumps(event))
                seq += 1
                chunk += 1

        async def receiver() -> None:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("event") != "media":
                    continue
                payload = msg.get("media", {}).get("payload", "")
                if not payload:
                    continue
                try:
                    audio = base64.b64decode(payload)
                except Exception:
                    continue
                playback.push(audio)

        def handle_sigint() -> None:
            if not stop_event.is_set():
                print("\nStopping...")
                stop_event.set()

        try:
            loop.add_signal_handler(signal.SIGINT, handle_sigint)
        except NotImplementedError:
            # Windows event loop may not support add_signal_handler.
            pass

        with sd.RawInputStream(
            samplerate=cfg.sample_rate,
            blocksize=frame_bytes // 2,
            channels=1,
            dtype="int16",
            callback=on_input,
        ), sd.RawOutputStream(
            samplerate=cfg.sample_rate,
            blocksize=frame_bytes // 2,
            channels=1,
            dtype="int16",
            callback=on_output,
        ):
            sender_task = asyncio.create_task(sender())
            receiver_task = asyncio.create_task(receiver())
            await stop_event.wait()
            sender_task.cancel()
            receiver_task.cancel()
            await asyncio.gather(sender_task, receiver_task, return_exceptions=True)

        await ws.send(json.dumps(build_stop_event(stream_sid, seq)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live Exotel-like simulator with microphone input and speaker playback"
    )
    parser.add_argument(
        "--ws-url",
        default="ws://localhost:8000/stream?sample-rate=8000",
        help="Websocket URL of server /stream endpoint",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=8000,
        choices=[8000, 16000, 24000],
        help="Audio sample rate",
    )
    parser.add_argument(
        "--frame-ms",
        type=int,
        default=20,
        choices=[20, 40, 60, 80, 100],
        help="Microphone frame size in ms",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = LiveConfig(ws_url=args.ws_url, sample_rate=args.sample_rate, frame_ms=args.frame_ms)
    asyncio.run(run_live_session(cfg))


if __name__ == "__main__":
    main()
