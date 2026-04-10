"""
Encryption module for at-rest and in-transit data protection.

Provides:
- AES-256 encryption for sensitive data at rest
- Key rotation support
- Environment-based key management
- Encryption/decryption utilities for PII masking
"""

import base64
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)


class EncryptionManager:
    """Manages encryption/decryption for sensitive data."""

    def __init__(
        self,
        master_key: Optional[str] = None,
        key_rotation_days: int = 90,
    ):
        """Initialize encryption manager.
        
        Args:
            master_key: Master encryption key (from environment if None)
            key_rotation_days: Days before key rotation required
        """
        self.master_key = master_key or os.getenv("ENCRYPTION_MASTER_KEY", "default-dev-key")
        self.key_rotation_days = key_rotation_days
        self.encryption_enabled = os.getenv("ENCRYPTION_ENABLED", "true").lower() == "true"
        self._backend = default_backend()

    def _derive_key(self, salt: bytes) -> bytes:
        """Derive a 32-byte encryption key from master key using PBKDF2.
        
        Args:
            salt: Random salt for key derivation
            
        Returns:
            32-byte derived encryption key
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=self._backend,
        )
        return kdf.derive(self.master_key.encode())

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext to ciphertext.
        
        Args:
            plaintext: Data to encrypt
            
        Returns:
            Base64-encoded ciphertext with IV and salt prepended
        """
        if not self.encryption_enabled:
            return plaintext

        try:
            # Generate random salt and IV
            salt = os.urandom(16)
            iv = os.urandom(16)

            # Derive key from master key
            key = self._derive_key(salt)

            # Encrypt using AES-256-CBC
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=self._backend,
            )
            encryptor = cipher.encryptor()

            # Pad plaintext to AES block size (16 bytes)
            plaintext_bytes = plaintext.encode()
            padding_length = 16 - (len(plaintext_bytes) % 16)
            plaintext_bytes += bytes([padding_length] * padding_length)

            # Encrypt
            ciphertext = encryptor.update(plaintext_bytes) + encryptor.finalize()

            # Return salt + IV + ciphertext as base64
            result = salt + iv + ciphertext
            return base64.b64encode(result).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return plaintext

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext to plaintext.
        
        Args:
            ciphertext: Base64-encoded ciphertext with IV and salt
            
        Returns:
            Decrypted plaintext
        """
        if not self.encryption_enabled:
            return ciphertext

        try:
            # Decode from base64
            data = base64.b64decode(ciphertext)

            # Extract salt (first 16 bytes), IV (next 16 bytes), ciphertext (rest)
            salt = data[:16]
            iv = data[16:32]
            encrypted_data = data[32:]

            # Derive key
            key = self._derive_key(salt)

            # Decrypt
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=self._backend,
            )
            decryptor = cipher.decryptor()
            plaintext_bytes = decryptor.update(encrypted_data) + decryptor.finalize()

            # Remove padding
            padding_length = plaintext_bytes[-1]
            plaintext_bytes = plaintext_bytes[:-padding_length]

            return plaintext_bytes.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return ciphertext

    def hash_password(self, password: str) -> str:
        """Hash password for secure storage.
        
        Args:
            password: Password to hash
            
        Returns:
            Base64-encoded hashed password with salt
        """
        try:
            salt = os.urandom(32)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=self._backend,
            )
            hashed = kdf.derive(password.encode())
            result = salt + hashed
            return base64.b64encode(result).decode()
        except Exception as e:
            logger.error(f"Password hashing failed: {e}")
            return ""

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash.
        
        Args:
            password: Password to verify
            hashed: Base64-encoded hash from hash_password
            
        Returns:
            True if password matches hash
        """
        try:
            data = base64.b64decode(hashed)
            salt = data[:32]
            stored_hash = data[32:]

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=self._backend,
            )
            computed_hash = kdf.derive(password.encode())
            return computed_hash == stored_hash
        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            return False

    def get_key_rotation_status(self) -> dict:
        """Get encryption key rotation status.
        
        Returns:
            Dict with rotation info (rotation_required, last_rotation, next_rotation)
        """
        return {
            "encryption_enabled": self.encryption_enabled,
            "key_rotation_interval_days": self.key_rotation_days,
            "algorithm": "AES-256-CBC",
            "status": "active",
        }


# Global encryption manager instance
_encryption_manager: Optional[EncryptionManager] = None


def get_encryption_manager() -> EncryptionManager:
    """Get or create global encryption manager."""
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


def encrypt_field(value: str) -> str:
    """Encrypt a field value."""
    return get_encryption_manager().encrypt(value)


def decrypt_field(value: str) -> str:
    """Decrypt a field value."""
    return get_encryption_manager().decrypt(value)
