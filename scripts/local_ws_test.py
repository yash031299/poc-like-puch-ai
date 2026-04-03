#!/usr/bin/env python3
"""
Local WebSocket test client — simulates Exotel AgentStream for manual testing.

Usage:
    # First start the server:
    python -m src.infrastructure.server

    # Then in another terminal run this script:
    python scripts/local_ws_test.py

    # Or test with specific settings:
    python scripts/local_ws_test.py --stream-id my-test-stream --sample-rate 8000
"""

import argparse
import asyncio
import base64
import json
import time
import sys

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets")
    sys.exit(1)


def _pcm_silence(ms: int = 100, sample_rate: int = 8000) -> bytes:
    """Generate silent PCM16LE audio of given duration."""
    num_samples = int(sample_rate * ms / 1000)
    return b"\x00\x00" * num_samples  # 2 bytes per 16-bit sample


def _pad_to_multiple(data: bytes, multiple: int = 320) -> bytes:
    remainder = len(data) % multiple
    if remainder:
        data += b"\x00" * (multiple - remainder)
    return data


async def simulate_call(
    url: str,
    stream_id: str,
    sample_rate: int = 8000,
    num_chunks: int = 5,
    chunk_ms: int = 100,
):
    print(f"Connecting to {url} ...")

    async with websockets.connect(url) as ws:
        print("Connected ✅")

        # 1. Start event (as Exotel sends)
        start_msg = {
            "event": "start",
            "sequence_number": "1",
            "stream_sid": stream_id,
            "start": {
                "stream_sid": stream_id,
                "call_sid": f"call-{stream_id}",
                "account_sid": "test-account",
                "from": "+91XXXXXXXXXX",
                "to": "+1800XXXXXXX",
                "custom_parameters": {},
                "media_format": {
                    "encoding": "base64",
                    "sample_rate": str(sample_rate),
                    "bit_rate": "128kbps",
                },
            },
        }
        await ws.send(json.dumps(start_msg))
        print(f"→ Sent: start (stream_sid={stream_id})")

        # 2. Media chunks (silence — no real speech, but exercises the pipeline)
        for i in range(1, num_chunks + 1):
            audio = _pad_to_multiple(_pcm_silence(chunk_ms, sample_rate))
            payload = base64.b64encode(audio).decode()
            media_msg = {
                "event": "media",
                "sequence_number": str(i + 1),
                "stream_sid": stream_id,
                "media": {
                    "chunk": str(i),
                    "timestamp": str(i * chunk_ms),
                    "payload": payload,
                },
            }
            await ws.send(json.dumps(media_msg))
            print(f"→ Sent: media chunk={i} ({len(audio)} bytes, {chunk_ms}ms)")
            await asyncio.sleep(chunk_ms / 1000)

        # 3. Listen for audio responses from server
        print("\nListening for server responses (3 seconds)...")
        try:
            async with asyncio.timeout(3.0):
                async for message in ws:
                    data = json.loads(message)
                    event = data.get("event", "unknown")
                    if event == "media":
                        payload = data.get("media", {}).get("payload", "")
                        audio_bytes = base64.b64decode(payload) if payload else b""
                        print(f"← Received: media ({len(audio_bytes)} bytes audio)")
                    elif event == "mark":
                        print(f"← Received: mark name={data.get('mark', {}).get('name')}")
                    else:
                        print(f"← Received: {event}")
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            pass

        # 4. Stop event
        stop_msg = {
            "event": "stop",
            "sequence_number": str(num_chunks + 2),
            "stream_sid": stream_id,
            "stop": {
                "call_sid": f"call-{stream_id}",
                "account_sid": "test-account",
                "reason": "callended",
            },
        }
        await ws.send(json.dumps(stop_msg))
        print(f"→ Sent: stop")

    print("\n✅ Test call completed")


def main():
    parser = argparse.ArgumentParser(description="Simulate an Exotel AgentStream call")
    parser.add_argument("--url", default="ws://localhost:8000/stream", help="WebSocket URL")
    parser.add_argument("--stream-id", default=f"test-{int(time.time())}", help="Stream ID")
    parser.add_argument("--sample-rate", type=int, default=8000, choices=[8000, 16000, 24000])
    parser.add_argument("--chunks", type=int, default=5, help="Number of audio chunks to send")
    parser.add_argument("--chunk-ms", type=int, default=100, help="Chunk duration in ms")
    args = parser.parse_args()

    sep = "&" if "?" in args.url else "?"
    ws_url = f"{args.url}{sep}sample-rate={args.sample_rate}"

    print("=" * 50)
    print("Puch AI Local WebSocket Test")
    print("=" * 50)
    print(f"URL:         {ws_url}")
    print(f"Stream ID:   {args.stream_id}")
    print(f"Sample Rate: {args.sample_rate} Hz")
    print(f"Chunks:      {args.chunks} × {args.chunk_ms}ms")
    print("=" * 50)

    asyncio.run(simulate_call(
        url=ws_url,
        stream_id=args.stream_id,
        sample_rate=args.sample_rate,
        num_chunks=args.chunks,
        chunk_ms=args.chunk_ms,
    ))


if __name__ == "__main__":
    main()
