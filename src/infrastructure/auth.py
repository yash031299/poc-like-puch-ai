"""Authentication module — IP whitelist + Bearer token support."""

import logging
import os
from typing import Optional, Set

logger = logging.getLogger(__name__)


def extract_bearer_token(auth_header: str) -> Optional[str]:
    """
    Extract Bearer token from Authorization header.

    Args:
        auth_header: Authorization header value (e.g., "Bearer secret-token")

    Returns:
        Token string if valid Bearer header, None otherwise
    """
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) < 2:
        return None

    # Case-insensitive Bearer prefix check
    if parts[0].lower() != "bearer":
        return None

    return parts[1]


class AuthenticatorConfig:
    """Configuration for IP whitelist and Bearer token authentication."""

    def __init__(self):
        """Load auth config from environment variables."""
        # IP Whitelist: comma-separated list of IPs to allow
        whitelist_str = os.environ.get("IP_WHITELIST", "").strip()
        self.ip_whitelist: Set[str] = set()
        if whitelist_str:
            self.ip_whitelist = set(ip.strip() for ip in whitelist_str.split(",") if ip.strip())

        # Bearer tokens: comma-separated list of valid API tokens
        tokens_str = os.environ.get("EXOTEL_API_TOKEN", "").strip()
        self.api_tokens: Set[str] = set()
        if tokens_str:
            self.api_tokens = set(token.strip() for token in tokens_str.split(",") if token.strip())

        # Legacy API key (for backward compatibility)
        self.api_key = os.environ.get("EXOTEL_API_KEY", "").strip()

        logger.info(
            "Auth config: %d IPs whitelisted, %d tokens configured, "
            "legacy API key %s",
            len(self.ip_whitelist),
            len(self.api_tokens),
            "present" if self.api_key else "absent",
        )

    def is_ip_allowed(self, client_ip: str) -> bool:
        """
        Check if IP is allowed.

        Rules:
        - If whitelist is empty, all IPs are allowed
        - If whitelist has entries, IP must be in whitelist

        Args:
            client_ip: Client IP address

        Returns:
            True if IP is allowed
        """
        if not self.ip_whitelist:
            # No whitelist configured, allow all IPs
            return True
        return client_ip in self.ip_whitelist

    def is_token_valid(self, token: str) -> bool:
        """
        Check if Bearer token is valid.

        Rules:
        - If no tokens configured, all tokens are allowed
        - If tokens configured, token must match one of them

        Args:
            token: Bearer token to validate

        Returns:
            True if token is valid
        """
        if not self.api_tokens:
            # No tokens configured, allow all
            return True
        return token in self.api_tokens

    def can_authenticate(self, client_ip: str, auth_header: str = None) -> bool:
        """
        Check if client can be authenticated via IP or Bearer token.

        Rules:
        - If IP is whitelisted, authentication succeeds
        - If Bearer token is valid, authentication succeeds
        - Otherwise, authentication fails

        Args:
            client_ip: Client IP address
            auth_header: Optional Authorization header

        Returns:
            True if client is authenticated via IP or token
        """
        # Check IP whitelist first
        if self.is_ip_allowed(client_ip):
            logger.debug("IP authentication passed: %s", client_ip)
            return True

        # Check Bearer token
        if auth_header:
            token = extract_bearer_token(auth_header)
            if token and self.is_token_valid(token):
                logger.debug("Bearer token authentication passed")
                return True

        logger.warning("Authentication failed for IP: %s", client_ip)
        return False
