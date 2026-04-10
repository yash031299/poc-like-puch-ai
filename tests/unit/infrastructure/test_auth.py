"""Tests for authentication (IP whitelist + Bearer tokens)."""

import asyncio
import json
import pytest


class FakeWebSocket:
    """Mock WebSocket with query params for testing auth."""

    def __init__(self, messages: list, query_params: dict = None):
        self._in = list(messages)
        self.sent = []
        self.closed = False
        self.accepted = False
        self.closed_code = None
        self.closed_reason = None
        self.client = type('obj', (object,), {'host': '127.0.0.1'})()
        self.query_params = query_params or {}

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if self._in:
            return self._in.pop(0)
        raise RuntimeError("No more messages")

    async def send_text(self, data: str):
        self.sent.append(json.loads(data))

    async def close(self, code=None, reason=None):
        self.closed = True
        self.closed_code = code
        self.closed_reason = reason


class FakeAcceptCall:
    def __init__(self):
        self.called_with = None

    async def execute(self, **kwargs):
        self.called_with = kwargs


class FakeAuth:
    """Mock authenticator for testing."""

    def __init__(self, valid_tokens=None, valid_ips=None):
        self.valid_tokens = valid_tokens or {}
        self.valid_ips = valid_ips or set()

    def is_ip_whitelisted(self, ip: str) -> bool:
        return ip in self.valid_ips or len(self.valid_ips) == 0

    def is_token_valid(self, token: str) -> bool:
        return token in self.valid_tokens or len(self.valid_tokens) == 0


class TestIPWhitelistAuth:
    """Tests for IP whitelist authentication."""

    @pytest.mark.asyncio
    async def test_auth_allows_whitelisted_ip(self):
        """Auth allows requests from whitelisted IP."""
        auth = FakeAuth(valid_ips={'192.168.1.1'})
        assert auth.is_ip_whitelisted('192.168.1.1') is True

    @pytest.mark.asyncio
    async def test_auth_rejects_non_whitelisted_ip(self):
        """Auth rejects requests from non-whitelisted IP."""
        auth = FakeAuth(valid_ips={'192.168.1.1'})
        assert auth.is_ip_whitelisted('10.0.0.1') is False

    @pytest.mark.asyncio
    async def test_auth_allows_all_ips_when_empty_whitelist(self):
        """Auth allows all IPs when whitelist is empty."""
        auth = FakeAuth(valid_ips=set())
        assert auth.is_ip_whitelisted('192.168.1.1') is True
        assert auth.is_ip_whitelisted('10.0.0.1') is True


class TestBearerTokenAuth:
    """Tests for Bearer token authentication."""

    @pytest.mark.asyncio
    async def test_auth_allows_valid_token(self):
        """Auth allows requests with valid Bearer token."""
        auth = FakeAuth(valid_tokens={'secret-key-123'})
        assert auth.is_token_valid('secret-key-123') is True

    @pytest.mark.asyncio
    async def test_auth_rejects_invalid_token(self):
        """Auth rejects requests with invalid Bearer token."""
        auth = FakeAuth(valid_tokens={'secret-key-123'})
        assert auth.is_token_valid('wrong-token') is False

    @pytest.mark.asyncio
    async def test_auth_allows_all_tokens_when_empty(self):
        """Auth allows all tokens when token list is empty."""
        auth = FakeAuth(valid_tokens=set())
        assert auth.is_token_valid('any-token') is True
        assert auth.is_token_valid('another-token') is True


class TestCombinedAuth:
    """Tests for combined IP + Bearer token authentication."""

    @pytest.mark.asyncio
    async def test_auth_allows_valid_ip_or_token(self):
        """Auth allows if either IP is whitelisted OR token is valid."""
        auth = FakeAuth(
            valid_ips={'192.168.1.1'},
            valid_tokens={'secret-key-123'}
        )
        # Valid IP should pass
        assert auth.is_ip_whitelisted('192.168.1.1') is True
        # Valid token should pass
        assert auth.is_token_valid('secret-key-123') is True
        # Invalid IP and token should fail
        assert auth.is_ip_whitelisted('10.0.0.1') is False
        assert auth.is_token_valid('wrong-token') is False

    @pytest.mark.asyncio
    async def test_auth_no_whitelist_requires_token(self):
        """When no IP whitelist, token authentication is required."""
        auth = FakeAuth(valid_tokens={'secret-key-123'})
        # Any IP is allowed (no whitelist), but token is still required
        assert auth.is_ip_whitelisted('192.168.1.1') is True
        assert auth.is_token_valid('secret-key-123') is True
        assert auth.is_token_valid('wrong-token') is False

    @pytest.mark.asyncio
    async def test_auth_no_tokens_requires_whitelist(self):
        """When no tokens configured, IP whitelist is required."""
        auth = FakeAuth(valid_ips={'192.168.1.1'})
        # Any token is allowed, but IP must be whitelisted
        assert auth.is_ip_whitelisted('192.168.1.1') is True
        assert auth.is_ip_whitelisted('10.0.0.1') is False
        assert auth.is_token_valid('any-token') is True


def test_extract_bearer_token_from_headers():
    """Extract Bearer token from Authorization header."""
    from src.infrastructure.auth import extract_bearer_token

    # Valid Bearer token
    token = extract_bearer_token("Bearer secret-key-123")
    assert token == "secret-key-123"

    # Missing Bearer prefix
    token = extract_bearer_token("secret-key-123")
    assert token is None

    # Empty string
    token = extract_bearer_token("")
    assert token is None

    # Whitespace handling
    token = extract_bearer_token("Bearer  secret-key-123")
    assert token == "secret-key-123"

    # Multiple words (only first word after Bearer)
    token = extract_bearer_token("Bearer secret-key-123 extra")
    assert token == "secret-key-123"


def test_extract_bearer_token_case_insensitive():
    """Bearer token extraction is case-insensitive."""
    from src.infrastructure.auth import extract_bearer_token

    token = extract_bearer_token("bearer secret-key-123")
    assert token == "secret-key-123"

    token = extract_bearer_token("BEARER secret-key-123")
    assert token == "secret-key-123"

    token = extract_bearer_token("BeArEr secret-key-123")
    assert token == "secret-key-123"
