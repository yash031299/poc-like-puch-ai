"""
Unit tests for PII masker.
"""

import pytest
from src.infrastructure.pii_masker import PIIMasker


class TestPIIMasker:
    """Test PII masking functionality."""

    @pytest.fixture
    def masker(self):
        """Create PII masker instance."""
        return PIIMasker()

    def test_mask_phone_number_with_country_code(self, masker):
        """Test masking phone number with + prefix."""
        phone = "+919876543210"
        masked = masker.mask_phone_number(phone)

        assert masked == "+91 XXXX XXXX 10"

    def test_mask_phone_number_without_plus(self, masker):
        """Test masking phone number without + prefix."""
        phone = "919876543210"
        masked = masker.mask_phone_number(phone)

        assert masked == "91 XXXX XXXX 10"

    def test_mask_phone_number_with_spaces(self, masker):
        """Test masking phone number with spaces."""
        phone = "+91 9876 543210"
        masked = masker.mask_phone_number(phone)

        assert masked == "+91 XXXX XXXX 10"

    def test_mask_phone_number_short(self, masker):
        """Test masking short phone number."""
        phone = "+919876"
        masked = masker.mask_phone_number(phone)

        assert "XXXX" in masked

    def test_mask_phone_number_empty(self, masker):
        """Test masking empty phone number."""
        phone = ""
        masked = masker.mask_phone_number(phone)

        assert masked == ""

    def test_mask_name_full(self, masker):
        """Test masking full name."""
        name = "John Doe"
        masked = masker.mask_name(name)

        assert masked == "J*** D**"

    def test_mask_name_single(self, masker):
        """Test masking single name."""
        name = "John"
        masked = masker.mask_name(name)

        assert masked == "J***"

    def test_mask_name_three_parts(self, masker):
        """Test masking three-part name."""
        name = "John Michael Doe"
        masked = masker.mask_name(name)

        assert "J***" in masked
        assert "M*****" in masked
        assert "D**" in masked

    def test_mask_email_basic(self, masker):
        """Test masking email address."""
        email = "john@example.com"
        masked = masker.mask_email(email)

        assert masked == "j***@example.com"

    def test_mask_email_long_local(self, masker):
        """Test masking email with long local part."""
        email = "johndoe@example.com"
        masked = masker.mask_email(email)

        assert masked == "j******@example.com"

    def test_mask_email_no_at(self, masker):
        """Test masking invalid email."""
        email = "notanemail"
        masked = masker.mask_email(email)

        assert masked == "***@***.com"

    def test_mask_email_empty(self, masker):
        """Test masking empty email."""
        email = ""
        masked = masker.mask_email(email)

        assert masked == "***@***.com"

    def test_mask_api_key(self, masker):
        """Test masking API key."""
        key = "sk_test_4eC39HqLyjWDarhtT657"
        masked = masker.mask_api_key(key)

        assert masked.startswith("sk_t")
        assert masked.endswith("657")
        assert "*" in masked

    def test_mask_api_key_short(self, masker):
        """Test masking short API key."""
        key = "abc"
        masked = masker.mask_api_key(key)

        assert masked == "***"

    def test_mask_transcription_disabled(self, masker):
        """Test transcription masking disabled."""
        text = "This is a transcription"
        masked = masker.mask_transcription(text)

        assert masked == text

    def test_mask_transcription_enabled(self):
        """Test transcription masking enabled."""
        masker = PIIMasker(enable_transcription_mask=True)
        text = "This is a transcription"
        masked = masker.mask_transcription(text)

        assert masked == "[REDACTED AUDIO TRANSCRIPT]"

    def test_mask_field_phone(self, masker):
        """Test masking phone field."""
        masked = masker.mask_field("phone_number", "+919876543210")

        assert "XXXX" in masked

    def test_mask_field_name(self, masker):
        """Test masking name field."""
        masked = masker.mask_field("caller_name", "John Doe")

        assert "*" in masked

    def test_mask_field_email(self, masker):
        """Test masking email field."""
        masked = masker.mask_field("email", "john@example.com")

        assert "@" in masked
        assert "*" in masked

    def test_mask_field_api_key(self, masker):
        """Test masking API key field."""
        masked = masker.mask_field("api_key", "sk_test_4eC39HqLyjWDarhtT657")

        assert "*" in masked

    def test_mask_dict_basic(self, masker):
        """Test masking dictionary."""
        data = {
            "phone_number": "+919876543210",
            "name": "John Doe",
            "status": "active",
        }

        masked = masker.mask_dict(data)

        assert "XXXX" in masked["phone_number"]
        assert "***" in masked["name"]
        assert masked["status"] == "active"

    def test_mask_dict_with_whitelist(self, masker):
        """Test masking dictionary with field whitelist."""
        data = {
            "phone_number": "+919876543210",
            "name": "John Doe",
            "email": "john@example.com",
        }

        masked = masker.mask_dict(data, field_whitelist=["phone_number"])

        assert "XXXX" in masked["phone_number"]
        assert masked["name"] == "John Doe"  # Not masked
        assert masked["email"] == "john@example.com"  # Not masked

    def test_mask_string_phone_pattern(self, masker):
        """Test masking phone numbers in text."""
        text = "Call +919876543210 today"
        masked = masker.mask_string(text)

        assert "+91" in masked
        assert "9876543210" not in masked

    def test_mask_string_email_pattern(self, masker):
        """Test masking emails in text."""
        text = "Contact john@example.com for details"
        masked = masker.mask_string(text)

        assert "john@example.com" not in masked or "*" in masked

    def test_masking_config(self, masker):
        """Test getting masking configuration."""
        config = masker.get_masking_config()

        assert "enable_transcription_mask" in config
        assert "sensitive_fields" in config
        assert "masking_rules" in config
        assert config["enable_transcription_mask"] is False

    def test_masking_config_with_transcription(self):
        """Test masking config with transcription enabled."""
        masker = PIIMasker(enable_transcription_mask=True)
        config = masker.get_masking_config()

        assert config["enable_transcription_mask"] is True
