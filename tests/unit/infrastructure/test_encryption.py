"""
Unit tests for encryption module.
"""

import pytest
import base64
from src.infrastructure.encryption import EncryptionManager


class TestEncryptionManager:
    """Test encryption manager functionality."""

    @pytest.fixture
    def encryption_manager(self):
        """Create encryption manager instance."""
        return EncryptionManager(master_key="test-master-key-12345")

    def test_initialization(self, encryption_manager):
        """Test encryption manager initialization."""
        assert encryption_manager.master_key == "test-master-key-12345"
        assert encryption_manager.key_rotation_days == 90
        assert encryption_manager.encryption_enabled is True

    def test_encrypt_decrypt_roundtrip(self, encryption_manager):
        """Test encrypt/decrypt roundtrip."""
        plaintext = "This is sensitive data"
        encrypted = encryption_manager.encrypt(plaintext)

        assert encrypted != plaintext
        assert isinstance(encrypted, str)

        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_multiple_times(self, encryption_manager):
        """Test encryption produces different ciphertexts."""
        plaintext = "Same data"
        encrypted1 = encryption_manager.encrypt(plaintext)
        encrypted2 = encryption_manager.encrypt(plaintext)

        # Different IVs produce different ciphertexts
        assert encrypted1 != encrypted2

        # But both decrypt to same plaintext
        assert encryption_manager.decrypt(encrypted1) == plaintext
        assert encryption_manager.decrypt(encrypted2) == plaintext

    def test_encrypt_empty_string(self, encryption_manager):
        """Test encrypting empty string."""
        plaintext = ""
        encrypted = encryption_manager.encrypt(plaintext)

        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_large_data(self, encryption_manager):
        """Test encrypting large data."""
        plaintext = "x" * 100000
        encrypted = encryption_manager.encrypt(plaintext)

        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_special_characters(self, encryption_manager):
        """Test encrypting special characters."""
        plaintext = "Special chars: !@#$%^&*()_+-=[]{}|;:,.<>?"
        encrypted = encryption_manager.encrypt(plaintext)

        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_unicode(self, encryption_manager):
        """Test encrypting unicode text."""
        plaintext = "Unicode: 你好世界 🌍 مرحبا"
        encrypted = encryption_manager.encrypt(plaintext)

        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_decrypt_invalid_ciphertext(self, encryption_manager):
        """Test decrypting invalid ciphertext."""
        invalid_ciphertext = base64.b64encode(b"invalid").decode()
        decrypted = encryption_manager.decrypt(invalid_ciphertext)

        # Should return original on error
        assert isinstance(decrypted, str)

    def test_encryption_disabled(self):
        """Test encryption with disabled flag."""
        manager = EncryptionManager(master_key="key")
        manager.encryption_enabled = False

        plaintext = "Data"
        encrypted = manager.encrypt(plaintext)

        # Should return plaintext when disabled
        assert encrypted == plaintext

    def test_hash_password(self, encryption_manager):
        """Test password hashing."""
        password = "MySecurePassword123!"
        hashed = encryption_manager.hash_password(password)

        assert hashed != password
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_verify_password_correct(self, encryption_manager):
        """Test password verification with correct password."""
        password = "MySecurePassword123!"
        hashed = encryption_manager.hash_password(password)

        verified = encryption_manager.verify_password(password, hashed)
        assert verified is True

    def test_verify_password_incorrect(self, encryption_manager):
        """Test password verification with incorrect password."""
        password = "MySecurePassword123!"
        hashed = encryption_manager.hash_password(password)

        verified = encryption_manager.verify_password("WrongPassword", hashed)
        assert verified is False

    def test_verify_password_empty(self, encryption_manager):
        """Test password verification with empty password."""
        password = ""
        hashed = encryption_manager.hash_password(password)

        verified = encryption_manager.verify_password(password, hashed)
        assert verified is True

    def test_hash_password_different_hashes(self, encryption_manager):
        """Test that same password produces different hashes."""
        password = "SecurePassword"
        hash1 = encryption_manager.hash_password(password)
        hash2 = encryption_manager.hash_password(password)

        # Different salts produce different hashes
        assert hash1 != hash2

        # But both verify correctly
        assert encryption_manager.verify_password(password, hash1) is True
        assert encryption_manager.verify_password(password, hash2) is True

    def test_get_key_rotation_status(self, encryption_manager):
        """Test getting key rotation status."""
        status = encryption_manager.get_key_rotation_status()

        assert "encryption_enabled" in status
        assert "key_rotation_interval_days" in status
        assert "algorithm" in status
        assert status["encryption_enabled"] is True
        assert status["key_rotation_interval_days"] == 90
        assert status["algorithm"] == "AES-256-CBC"

    def test_derive_key_consistency(self, encryption_manager):
        """Test key derivation is consistent."""
        salt = b"test-salt-1234567"
        key1 = encryption_manager._derive_key(salt)
        key2 = encryption_manager._derive_key(salt)

        assert key1 == key2
        assert len(key1) == 32  # AES-256 needs 32-byte key

    def test_derive_key_different_salts(self, encryption_manager):
        """Test different salts produce different keys."""
        salt1 = b"salt-1"
        salt2 = b"salt-2"

        key1 = encryption_manager._derive_key(salt1)
        key2 = encryption_manager._derive_key(salt2)

        assert key1 != key2
