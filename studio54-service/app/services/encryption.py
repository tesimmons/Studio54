"""
Encryption Service for Studio54
Provides Fernet symmetric encryption for sensitive data (API keys, passwords)
"""
from cryptography.fernet import Fernet
from typing import Optional
import os


class EncryptionService:
    """
    Encryption service using Fernet (symmetric encryption)

    Uses AES-128 in CBC mode with HMAC authentication.
    Master key is stored in STUDIO54_ENCRYPTION_KEY environment variable.
    """

    def __init__(self, master_key: Optional[str] = None):
        """
        Initialize encryption service

        Args:
            master_key: Base64-encoded Fernet key. If None, uses STUDIO54_ENCRYPTION_KEY env var

        Raises:
            ValueError: If master key is not provided or invalid
        """
        key = master_key or os.getenv("STUDIO54_ENCRYPTION_KEY")

        if not key:
            raise ValueError(
                "Encryption key not configured. "
                "Set STUDIO54_ENCRYPTION_KEY environment variable. "
                "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

        try:
            self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as e:
            raise ValueError(f"Invalid encryption key: {str(e)}")

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string

        Args:
            plaintext: String to encrypt (e.g., API key, password)

        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ""

        try:
            encrypted_bytes = self.cipher.encrypt(plaintext.encode('utf-8'))
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Encryption failed: {str(e)}")

    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt encrypted string

        Args:
            encrypted: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails (invalid key, corrupted data)
        """
        if not encrypted:
            return ""

        try:
            decrypted_bytes = self.cipher.decrypt(encrypted.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Decryption failed: {str(e)}")

    def encrypt_optional(self, plaintext: Optional[str]) -> Optional[str]:
        """Encrypt optional string (handles None)"""
        if plaintext is None:
            return None
        return self.encrypt(plaintext)

    def decrypt_optional(self, encrypted: Optional[str]) -> Optional[str]:
        """Decrypt optional string (handles None)"""
        if encrypted is None:
            return None
        return self.decrypt(encrypted)

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet encryption key

        Returns:
            Base64-encoded key string

        Note:
            Save this key securely! Loss of key = loss of encrypted data.
        """
        return Fernet.generate_key().decode('utf-8')


# Global encryption service instance (singleton)
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """
    Get global encryption service instance (singleton pattern)

    Returns:
        EncryptionService instance
    """
    global _encryption_service

    if _encryption_service is None:
        _encryption_service = EncryptionService()

    return _encryption_service
