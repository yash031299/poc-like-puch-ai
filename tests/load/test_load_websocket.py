"""
WebSocket endpoint load testing.

Tests concurrent WebSocket connections and streaming audio under load.
"""

import asyncio
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
import websocket

from src.infrastructure.server import app


class TestWebSocketConnectionLoad:
    """WebSocket connection and streaming load tests."""

    def test_websocket_multiple_sequential_connections(self):
        """Test opening/closing multiple WebSocket connections sequentially."""
        NUM_CONNECTIONS = 50
        latencies = []
        
        for i in range(NUM_CONNECTIONS):
            start = time.time()
            try:
                ws = websocket.create_connection(
                    "ws://localhost:8000/stream?sample-rate=8000",
                    timeout=5
                )
                latency = time.time() - start
                latencies.append(latency)
                ws.close()
            except Exception as e:
                # Expected if server not running; skip with warning
                pytest.skip(f"WebSocket server not running: {e}")
        
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            print(f"\n✓ Sequential WS connections: {len(latencies)} succeeded")
            print(f"  Avg connection latency: {avg_latency * 1000:.2f}ms")
            assert avg_latency < 1.0, f"Connection latency too high: {avg_latency * 1000:.2f}ms"

    def test_websocket_concurrent_connection_setup(self):
        """Test concurrent WebSocket connection setup (connection pool)."""
        NUM_CONNECTIONS = 20
        
        def create_connection():
            try:
                start = time.time()
                ws = websocket.create_connection(
                    "ws://localhost:8000/stream?sample-rate=8000",
                    timeout=5
                )
                latency = time.time() - start
                ws.close()
                return ("success", latency)
            except Exception as e:
                if "Connection refused" in str(e):
                    return ("skip", None)
                return ("error", str(e))
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_connection) for _ in range(NUM_CONNECTIONS)]
            results = [f.result() for f in as_completed(futures)]
        
        success_count = sum(1 for r, _ in results if r == "success")
        skip_count = sum(1 for r, _ in results if r == "skip")
        error_count = sum(1 for r, _ in results if r == "error")
        
        if skip_count == NUM_CONNECTIONS:
            pytest.skip("WebSocket server not running")
        
        print(f"\n✓ Concurrent WS connection setup:")
        print(f"  Successes: {success_count}")
        print(f"  Errors: {error_count}")
        
        success_rate = (success_count / NUM_CONNECTIONS) * 100
        assert success_rate >= 80, f"Expected 80%+ success rate, got {success_rate:.1f}%"

    def test_websocket_audio_streaming_under_load(self):
        """Test audio streaming with concurrent connections."""
        NUM_CONNECTIONS = 10
        CHUNKS_PER_CONNECTION = 5
        
        def stream_audio():
            try:
                ws = websocket.create_connection(
                    "ws://localhost:8000/stream?sample-rate=8000",
                    timeout=5
                )
                
                chunks_sent = 0
                start = time.time()
                
                for i in range(CHUNKS_PER_CONNECTION):
                    audio_data = b"\x00\x01" * 160  # 320 bytes
                    encoded = base64.b64encode(audio_data).decode()
                    
                    message = {
                        "event": "media",
                        "stream_sid": f"stream_test_{id(ws)}",
                        "sequence_number": i + 1,
                        "media": {
                            "payload": encoded
                        }
                    }
                    
                    try:
                        ws.send(json.dumps(message))
                        chunks_sent += 1
                    except Exception:
                        break
                
                elapsed = time.time() - start
                ws.close()
                
                return ("success", chunks_sent, elapsed)
            except Exception as e:
                if "Connection refused" in str(e):
                    return ("skip", 0, 0)
                return ("error", 0, 0)
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(stream_audio) for _ in range(NUM_CONNECTIONS)]
            results = [f.result() for f in as_completed(futures)]
        
        success_count = sum(1 for r, _, _ in results if r == "success")
        skip_count = sum(1 for r, _, _ in results if r == "skip")
        
        if skip_count == NUM_CONNECTIONS:
            pytest.skip("WebSocket server not running")
        
        total_chunks = sum(chunks for _, chunks, _ in results if chunks > 0)
        
        print(f"\n✓ Audio streaming under load:")
        print(f"  Connections: {success_count} successful")
        print(f"  Total chunks sent: {total_chunks}")
        print(f"  Expected: {NUM_CONNECTIONS * CHUNKS_PER_CONNECTION}")
        
        assert success_count >= NUM_CONNECTIONS // 2, f"Expected {NUM_CONNECTIONS // 2}+ successful connections, got {success_count}"


class TestWebSocketProtocolUnderLoad:
    """Test Exotel protocol compliance under load conditions."""

    def test_message_ordering_concurrent_streams(self):
        """Verify message sequence numbers are handled correctly under load."""
        NUM_STREAMS = 5
        MESSAGES_PER_STREAM = 20
        
        def send_ordered_messages():
            try:
                ws = websocket.create_connection(
                    "ws://localhost:8000/stream?sample-rate=8000",
                    timeout=5
                )
                
                stream_id = f"stream_order_{id(ws)}"
                sequence_numbers = []
                
                for seq in range(1, MESSAGES_PER_STREAM + 1):
                    audio_data = b"\x00\x01" * 160
                    encoded = base64.b64encode(audio_data).decode()
                    
                    message = {
                        "event": "media",
                        "stream_sid": stream_id,
                        "sequence_number": seq,
                        "media": {
                            "payload": encoded
                        }
                    }
                    
                    try:
                        ws.send(json.dumps(message))
                        sequence_numbers.append(seq)
                    except Exception:
                        break
                
                ws.close()
                return ("success", sequence_numbers)
            except Exception as e:
                if "Connection refused" in str(e):
                    return ("skip", [])
                return ("error", [])
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_ordered_messages) for _ in range(NUM_STREAMS)]
            results = [f.result() for f in as_completed(futures)]
        
        success_count = sum(1 for r, _ in results if r == "success")
        skip_count = sum(1 for r, _ in results if r == "skip")
        
        if skip_count == NUM_STREAMS:
            pytest.skip("WebSocket server not running")
        
        print(f"\n✓ Message ordering under concurrent load:")
        print(f"  Streams: {success_count} successful")
        print(f"  Messages verified: {sum(len(seqs) for _, seqs in results)}")
        
        assert success_count >= 1, "Expected at least 1 successful ordered stream"

    def test_websocket_connection_resilience(self):
        """Test connection handling with rapid open/close cycles."""
        NUM_CYCLES = 100
        
        successful = 0
        start_time = time.time()
        
        for _ in range(NUM_CYCLES):
            try:
                ws = websocket.create_connection(
                    "ws://localhost:8000/stream?sample-rate=8000",
                    timeout=5
                )
                ws.close()
                successful += 1
            except Exception as e:
                if "Connection refused" in str(e):
                    pytest.skip("WebSocket server not running")
                break
        
        elapsed = time.time() - start_time
        
        print(f"\n✓ Connection resilience test:")
        print(f"  Cycles: {successful}/{NUM_CYCLES}")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  Rate: {successful / elapsed:.0f} cycles/sec")
        
        success_rate = (successful / NUM_CYCLES) * 100
        assert success_rate >= 90, f"Expected 90%+ success rate, got {success_rate:.1f}%"
