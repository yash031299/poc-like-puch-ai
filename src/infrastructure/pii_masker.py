"""
PII Masking module for protecting sensitive data in logs and exports.

Masks:
- Phone numbers: +91 XXXXXXXXXX → +91 XXXX XXXX XX
- Names: John Doe → J*** ***
- Email: john@example.com → j***@example.com
- Transcription (optional): full redaction or partial masking
- Account IDs and credentials
"""

import re
import logging
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class PIIMasker:
    """Masks PII in logs, audit trails, and exports."""

    def __init__(self, enable_transcription_mask: bool = False):
        """Initialize PII masker.
        
        Args:
            enable_transcription_mask: If True, mask transcription content
        """
        self.enable_transcription_mask = enable_transcription_mask
        self.sensitive_fields = {
            "phone_number",
            "caller_id",
            "phone",
            "number",
            "name",
            "full_name",
            "email",
            "transcript",
            "transcription",
            "password",
            "api_key",
            "token",
            "account_id",
        }

    def mask_phone_number(self, phone: str) -> str:
        """Mask phone number to +CC XXXX XXXX XX format.
        
        Examples:
            +919876543210 → +91 XXXX XXXX 10
            919876543210 → 91 XXXX XXXX 10
            
        Args:
            phone: Phone number to mask
            
        Returns:
            Masked phone number
        """
        if not phone:
            return phone

        # Remove all non-digit characters except +
        cleaned = re.sub(r"[^\d+]", "", phone)

        # Handle +CC format
        if cleaned.startswith("+"):
            cc = cleaned[1:3]  # Country code (2 digits)
            if len(cleaned) > 5:
                last_two = cleaned[-2:]
                return f"+{cc} XXXX XXXX {last_two}"
            return f"+{cc} XXXX XXXX XX"

        # Handle CCXXXXXXXXXX format
        if len(cleaned) >= 5:
            cc = cleaned[:2]
            last_two = cleaned[-2:]
            return f"{cc} XXXX XXXX {last_two}"

        return "XXXX XXXX XXXX"

    def mask_name(self, name: str) -> str:
        """Mask name to first letter + asterisks.
        
        Examples:
            John Doe → J*** ***
            Sarah Johnson → S*** J*****
            
        Args:
            name: Name to mask
            
        Returns:
            Masked name
        """
        if not name or len(name) < 2:
            return "X***"

        parts = name.split()
        masked_parts = []

        for part in parts:
            if len(part) >= 1:
                # First letter + asterisks
                masked = part[0] + "*" * (len(part) - 1)
                masked_parts.append(masked)

        return " ".join(masked_parts) if masked_parts else "X***"

    def mask_email(self, email: str) -> str:
        """Mask email address.
        
        Examples:
            john@example.com → j***@example.com
            
        Args:
            email: Email to mask
            
        Returns:
            Masked email
        """
        if not email or "@" not in email:
            return "***@***.com"

        local, domain = email.split("@", 1)
        if len(local) >= 1:
            masked_local = local[0] + "*" * (len(local) - 1)
        else:
            masked_local = "***"

        return f"{masked_local}@{domain}"

    def mask_transcription(self, text: str) -> str:
        """Mask transcription content.
        
        Args:
            text: Transcription to mask
            
        Returns:
            Masked text (full redaction if enabled)
        """
        if not self.enable_transcription_mask:
            return text

        # Full redaction
        return "[REDACTED AUDIO TRANSCRIPT]"

    def mask_api_key(self, key: str) -> str:
        """Mask API key/token.
        
        Examples:
            sk_test_abc123def456 → sk_test_***456
            
        Args:
            key: API key to mask
            
        Returns:
            Masked key
        """
        if not key or len(key) < 4:
            return "***"

        return key[:4] + "*" * (len(key) - 8) + key[-4:]

    def mask_field(self, field_name: str, value: str) -> str:
        """Mask field value based on field name.
        
        Args:
            field_name: Name of the field
            value: Value to mask
            
        Returns:
            Masked value
        """
        field_lower = field_name.lower()

        # Name fields (check before phone since "caller" could match "caller_name")
        if any(name_keyword in field_lower for name_keyword in ["name"]):
            return self.mask_name(value)

        # Phone number fields
        if any(phone_keyword in field_lower for phone_keyword in ["phone", "number", "caller", "dialed"]):
            return self.mask_phone_number(value)

        # Email fields
        if "email" in field_lower:
            return self.mask_email(value)

        # Transcription fields
        if any(transcript_keyword in field_lower for transcript_keyword in ["transcript", "transcription", "text"]):
            return self.mask_transcription(value)

        # API key/token fields
        if any(key_keyword in field_lower for key_keyword in ["api_key", "token", "secret", "password"]):
            return self.mask_api_key(value)

        return value

    def mask_dict(self, data: Dict, field_whitelist: Optional[List[str]] = None) -> Dict:
        """Mask PII in dictionary.
        
        Args:
            data: Dictionary to mask
            field_whitelist: Fields to mask (if None, mask all sensitive fields)
            
        Returns:
            Dictionary with masked values
        """
        if not isinstance(data, dict):
            return data

        masked = {}
        for key, value in data.items():
            # Check if field should be masked
            should_mask = False
            if field_whitelist is None:
                # Mask all sensitive fields by default
                should_mask = any(keyword in key.lower() for keyword in self.sensitive_fields)
            else:
                # Mask only whitelisted fields
                should_mask = key.lower() in [f.lower() for f in field_whitelist]

            if should_mask and isinstance(value, str):
                masked[key] = self.mask_field(key, value)
            else:
                masked[key] = value

        return masked

    def mask_string(self, text: str, patterns: Optional[List[tuple]] = None) -> str:
        """Mask PII in text using regex patterns.
        
        Args:
            text: Text to mask
            patterns: List of (pattern, replacement) tuples
                     If None, use default patterns
            
        Returns:
            Text with PII masked
        """
        if not text:
            return text

        if patterns is None:
            # Default patterns
            patterns = [
                # Phone numbers: +CC XXXXXXXXXX or CCXXXXXXXXXX
                (r"\+\d{2}\s*\d{3,4}\s*\d{3,4}\s*\d{2,4}", lambda m: self.mask_phone_number(m.group(0))),
                # Email addresses
                (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", lambda m: self.mask_email(m.group(0))),
                # API keys (sk_test_*, sk_live_*, etc.)
                (r"\b[a-z]{2,}_[a-z0-9]{32,}\b", lambda m: self.mask_api_key(m.group(0))),
            ]

        result = text
        for pattern, replacement in patterns:
            if callable(replacement):
                result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
            else:
                result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        return result

    def get_masking_config(self) -> dict:
        """Get current masking configuration.
        
        Returns:
            Dict with masking settings
        """
        return {
            "enable_transcription_mask": self.enable_transcription_mask,
            "sensitive_fields": list(self.sensitive_fields),
            "masking_rules": {
                "phone": "Mask to +CC XXXX XXXX XX",
                "name": "Mask to F*** L***",
                "email": "Mask to f***@domain.com",
                "api_key": "Mask to prefix***suffix",
            },
        }


# Global PII masker instance
_pii_masker: Optional[PIIMasker] = None


def get_pii_masker() -> PIIMasker:
    """Get or create global PII masker."""
    global _pii_masker
    if _pii_masker is None:
        enable_transcript_mask = os.getenv("MASK_TRANSCRIPTION", "false").lower() == "true"
        _pii_masker = PIIMasker(enable_transcription_mask=enable_transcript_mask)
    return _pii_masker


def mask_phone(phone: str) -> str:
    """Mask a phone number."""
    import os  # Import here to avoid circular dependency
    return get_pii_masker().mask_phone_number(phone)


def mask_pii(data: Dict) -> Dict:
    """Mask PII in a dictionary."""
    import os  # Import here to avoid circular dependency
    return get_pii_masker().mask_dict(data)
