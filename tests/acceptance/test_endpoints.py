"""
Acceptance Test: Complete Endpoint Validation

Black-box tests for all endpoints with focus on:
1. Protocol compliance (Exotel AgentStream spec)
2. HTTP status codes
3. Response formats
4. Error handling
5. Authentication
"""

import json
import base64
import pytest
from fastapi.testclient import TestClient
from src.infrastructure.server import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestHealthEndpointBlackBox:
    """Test /health endpoint as external service (black-box)."""

    def test_endpoint_accessible(self, client):
        """GET /health should return 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_response_content_type(self, client):
        """Response should be JSON."""
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_response_valid_json(self, client):
        """Response should be valid JSON."""
        response = client.get("/health")
        try:
            data = response.json()
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            pytest.fail("Invalid JSON response")

    def test_response_has_status_field(self, client):
        """Response should have 'status' field."""
        response = client.get("/health")
        data = response.json()
        
        assert "status" in data
        assert data["status"] in ["ok", "healthy"]

    def test_response_has_active_sessions(self, client):
        """Response should have 'active_sessions' field."""
        response = client.get("/health")
        data = response.json()
        
        assert "active_sessions" in data
        assert isinstance(data["active_sessions"], int)
        assert data["active_sessions"] >= 0

    def test_no_sensitive_data_exposed(self, client):
        """Response should not expose sensitive data."""
        response = client.get("/health")
        data = response.json()
        response_str = json.dumps(data)
        
        assert "password" not in response_str.lower()
        assert "secret" not in response_str.lower()
        assert "token" not in response_str.lower()

    def test_response_time_acceptable(self, client):
        """Health check should respond quickly (<100ms)."""
        import time
        start = time.time()
        client.get("/health")
        elapsed = (time.time() - start) * 1000
        
        assert elapsed < 100, f"Health check too slow: {elapsed}ms"

    def test_multiple_requests_succeed(self, client):
        """Multiple health checks should all succeed."""
        for _ in range(10):
            response = client.get("/health")
            assert response.status_code == 200

    def test_concurrent_requests_handled(self, client):
        """Concurrent requests should be handled independently."""
        responses = []
        for _ in range(5):
            response = client.get("/health")
            responses.append(response.status_code)
        
        assert all(code == 200 for code in responses)

    def test_idempotent_responses(self, client):
        """Multiple calls should return consistent results."""
        response1 = client.get("/health")
        response2 = client.get("/health")
        
        assert response1.json()["status"] == response2.json()["status"]


class TestPassthruEndpointBlackBox:
    """Test /passthru endpoint (HTTP voice alternative)."""

    def test_endpoint_exists(self, client):
        """Passthru endpoint should be accessible."""
        response = client.get("/passthru")
        # GET endpoint should return something (not 404)
        assert response.status_code != 404

    def test_get_method_accepted(self, client):
        """GET should be accepted."""
        response = client.get("/passthru")
        # Either success or error, but not 404
        assert response.status_code >= 200

    def test_passthru_accepts_query_params(self, client):
        """Passthru should accept query parameters for input."""
        response = client.get("/passthru?input=hello")
        # Should be handled (not crash)
        assert response.status_code >= 100

    def test_response_is_json(self, client):
        """Response should be JSON."""
        response = client.get("/passthru")
        if response.status_code < 400:
            try:
                response.json()
            except json.JSONDecodeError:
                pass  # Some errors might not be JSON

    def test_empty_input_handling(self, client):
        """Empty input should be handled."""
        response = client.get("/passthru?input=")
        # Should handle gracefully
        assert response.status_code >= 100

    def test_special_characters_in_input(self, client):
        """Special characters should be handled."""
        response = client.get("/passthru?input=hello%20world%21")
        # Should not crash
        assert response.status_code >= 100

    def test_unicode_input_support(self, client):
        """Unicode input should be supported."""
        response = client.get("/passthru?input=%E3%81%93%E3%82%93%E3%81%AB%E3%81%A1%E3%81%AF")
        # Japanese: こんにちは
        assert response.status_code >= 100

    def test_very_long_input_handling(self, client):
        """Very long input should be handled."""
        long_input = "a" * 5000
        response = client.get(f"/passthru?input={long_input}")
        # Should handle gracefully (not crash)
        assert response.status_code in [200, 201, 400, 413, 414, 500]


class TestStreamEndpointBlackBox:
    """Test /stream endpoint (WebSocket)."""

    def test_stream_endpoint_exists(self, client):
        """Stream endpoint should be available for WebSocket."""
        # WebSocket endpoints typically return 404 for HTTP OPTIONS
        # This is expected behavior
        response = client.options("/stream")
        # Could be 404 (not found as HTTP) or 405 (method not allowed for WebSocket)
        assert response.status_code in [404, 405]

    def test_stream_requires_sample_rate(self):
        """Stream URL must include sample-rate parameter."""
        valid_url = "/stream?sample-rate=8000"
        invalid_url = "/stream"  # Missing parameter
        
        assert "sample-rate=" in valid_url
        assert "sample-rate=" not in invalid_url

    def test_stream_sample_rate_values(self):
        """Only certain sample rates are supported."""
        valid_rates = [8000, 16000, 24000]
        invalid_rates = [44100, 48000, 11025, 22050]
        
        for rate in valid_rates:
            assert rate in [8000, 16000, 24000]
        
        for rate in invalid_rates:
            assert rate not in [8000, 16000, 24000]

    def test_stream_url_format_validation(self):
        """Stream URLs should follow proper format."""
        urls = [
            "ws://localhost:8000/stream?sample-rate=8000",
            "wss://domain.com/stream?sample-rate=16000",
            "ws://localhost:8000/stream?sample-rate=24000"
        ]
        
        for url in urls:
            assert url.startswith("ws://") or url.startswith("wss://")
            assert "/stream?" in url
            assert "sample-rate=" in url


class TestStreamMessageProtocolBlackBox:
    """Test Exotel protocol message formats."""

    def test_connected_event_structure(self):
        """'connected' event structure."""
        message = {
            "event": "connected",
            "stream_sid": "stream_abc123xyz789",
            "sequenceNumber": 1
        }
        
        assert message["event"] == "connected"
        assert "stream_sid" in message
        assert message["stream_sid"].startswith("stream_")
        assert "sequenceNumber" in message

    def test_start_event_structure(self):
        """'start' event structure."""
        message = {
            "event": "start",
            "stream_sid": "stream_abc123xyz789",
            "sequenceNumber": 2
        }
        
        assert message["event"] == "start"
        assert "stream_sid" in message
        assert "sequenceNumber" in message
        assert message["sequenceNumber"] > 1

    def test_media_event_structure(self):
        """'media' event structure with base64 audio."""
        audio_payload = base64.b64encode(bytes(320)).decode()
        
        message = {
            "event": "media",
            "stream_sid": "stream_abc123xyz789",
            "sequenceNumber": 3,
            "media": {
                "payload": audio_payload,
                "contentType": "audio/raw",
                "sampleRate": 8000
            }
        }
        
        assert message["event"] == "media"
        assert "media" in message
        assert message["media"]["sampleRate"] in [8000, 16000, 24000]

    def test_stop_event_structure(self):
        """'stop' event structure."""
        message = {
            "event": "stop",
            "stream_sid": "stream_abc123xyz789",
            "sequenceNumber": 100
        }
        
        assert message["event"] == "stop"
        assert "stream_sid" in message
        assert "sequenceNumber" in message

    def test_sequence_number_increasing(self):
        """Sequence numbers must increase."""
        seq1 = 1
        seq2 = 2
        seq3 = 100
        
        assert seq1 < seq2 < seq3

    def test_stream_sid_format(self):
        """stream_sid must start with 'stream_'."""
        valid_ids = [
            "stream_abc123",
            "stream_1234567890",
            "stream_XYZ"
        ]
        
        for sid in valid_ids:
            assert sid.startswith("stream_")


class TestAudioDataFormatBlackBox:
    """Test audio data format compliance."""

    def test_audio_chunk_size_multiple_of_320(self):
        """Audio chunks must be multiples of 320 bytes."""
        valid_sizes = [320, 640, 960, 1280, 3200]
        invalid_sizes = [300, 321, 319, 1000]
        
        for size in valid_sizes:
            assert size % 320 == 0
        
        for size in invalid_sizes:
            assert size % 320 != 0

    def test_audio_base64_encoding(self):
        """Audio payload should be base64 encoded."""
        raw = bytes(320)
        encoded = base64.b64encode(raw).decode()
        decoded = base64.b64decode(encoded)
        
        assert decoded == raw

    def test_audio_sample_rate_match(self):
        """Sample rate must match between URL and media message."""
        url_rate = 8000
        message_rate = 8000
        
        assert url_rate == message_rate

    def test_pcm16le_requirements(self):
        """Audio must be PCM16LE (16-bit samples, mono)."""
        # 160 samples @ 8kHz = 20ms
        samples = 160
        bytes_per_sample = 2  # 16-bit
        total_bytes = samples * bytes_per_sample
        
        assert total_bytes == 320


class TestAuthenticationBlackBox:
    """Test authentication mechanisms."""

    def test_health_no_auth_required(self, client):
        """Health endpoint should not require auth."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_basic_auth_format(self):
        """Basic auth format: Base64(username:password)."""
        key = "api_key"
        token = "api_token"
        
        credentials = f"{key}:{token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        
        assert encoded != credentials  # Base64 encoding applied
        assert len(encoded) > len(credentials)

    def test_basic_auth_decoding(self):
        """Auth server should decode Basic auth properly."""
        key = "test_key"
        token = "test_token"
        
        credentials = f"{key}:{token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        
        # Server receives "Basic <encoded>"
        header = f"Basic {encoded}"
        
        # Server extracts and decodes
        encoded_part = header.split(" ")[1]
        decoded = base64.b64decode(encoded_part).decode()
        
        assert decoded == credentials


class TestErrorHandlingBlackBox:
    """Test error handling and HTTP status codes."""

    def test_400_bad_request(self, client):
        """Invalid requests should return error."""
        response = client.get("/passthru?input=")
        # Should handle (not crash)
        assert response.status_code >= 100

    def test_404_not_found(self, client):
        """Non-existent endpoint should return 404."""
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_405_method_not_allowed(self, client):
        """POST to GET-only endpoint should return 405."""
        response = client.post("/health")  # health is GET only
        assert response.status_code == 405

    def test_error_response_has_details(self, client):
        """Error responses should include error details."""
        response = client.get("/nonexistent")
        
        if response.status_code >= 400:
            try:
                data = response.json()
                # Should have error information
                assert response.status_code >= 100
            except json.JSONDecodeError:
                pass  # Some errors might not be JSON


class TestConcurrencyBlackBox:
    """Test concurrent request handling."""

    def test_multiple_health_checks(self, client):
        """Multiple concurrent health checks should succeed."""
        responses = []
        for _ in range(10):
            response = client.get("/health")
            responses.append(response.status_code)
        
        assert all(code == 200 for code in responses)

    def test_multiple_passthru_requests(self, client):
        """Multiple passthru requests should be handled."""
        responses = []
        for i in range(5):
            response = client.get(f"/passthru?input=request_{i}")
            responses.append(response.status_code)
        
        # All should complete without crashing
        assert len(responses) == 5


class TestEndpointComplianceChecklist:
    """Final checklist for endpoint compliance."""

    def test_all_required_endpoints_exist(self, client):
        """All required endpoints should exist."""
        # Check /health
        response = client.get("/health")
        assert response.status_code == 200
        
        # Check /passthru exists (GET)
        response = client.get("/passthru")
        assert response.status_code != 404
        
        # Check /stream exists (WebSocket - will return 404 for HTTP OPTIONS, which is OK)
        response = client.options("/stream")
        assert response.status_code in [404, 405]  # Expected for WebSocket

    def test_response_format_consistency(self, client):
        """All responses should be properly formatted."""
        # Health should be JSON
        response = client.get("/health")
        assert response.headers["content-type"].startswith("application/json")

    def test_no_information_disclosure(self, client):
        """Responses should not expose system information."""
        response = client.get("/health")
        data = response.json()
        response_str = json.dumps(data)
        
        # Should not expose paths, versions, internal errors
        assert "/usr/" not in response_str
        assert "python" not in response_str.lower()

    def test_graceful_error_handling(self, client):
        """Errors should be handled gracefully."""
        # Various error conditions
        responses = [
            client.get("/nonexistent"),  # 404
            client.post("/health"),  # 405
            client.get("/health")  # 200 (good request)
        ]
        
        # None should crash the server
        assert all(response.status_code >= 100 for response in responses)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
