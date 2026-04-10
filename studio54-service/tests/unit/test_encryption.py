"""
Tests for the encryption service.
"""
import pytest
from cryptography.fernet import Fernet

from app.services.encryption import EncryptionService


@pytest.fixture
def encryption_service():
    """Create encryption service with a known test key"""
    key = Fernet.generate_key().decode()
    return EncryptionService(master_key=key)


class TestEncryptDecrypt:
    def test_round_trip(self, encryption_service):
        plaintext = "my-secret-api-key-12345"
        encrypted = encryption_service.encrypt(plaintext)
        assert encrypted != plaintext
        assert encryption_service.decrypt(encrypted) == plaintext

    def test_empty_string(self, encryption_service):
        assert encryption_service.encrypt("") == ""
        assert encryption_service.decrypt("") == ""

    def test_unicode_round_trip(self, encryption_service):
        plaintext = "secret-with-unicode-\u00e9\u00e8\u00ea"
        encrypted = encryption_service.encrypt(plaintext)
        assert encryption_service.decrypt(encrypted) == plaintext


class TestEncryptOptional:
    def test_none_returns_none(self, encryption_service):
        assert encryption_service.encrypt_optional(None) is None

    def test_value_returns_encrypted(self, encryption_service):
        encrypted = encryption_service.encrypt_optional("secret")
        assert encrypted is not None
        assert encryption_service.decrypt(encrypted) == "secret"


class TestDecryptOptional:
    def test_none_returns_none(self, encryption_service):
        assert encryption_service.decrypt_optional(None) is None

    def test_value_returns_decrypted(self, encryption_service):
        encrypted = encryption_service.encrypt("secret")
        assert encryption_service.decrypt_optional(encrypted) == "secret"


class TestInvalidKey:
    def test_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("STUDIO54_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError, match="Encryption key not configured"):
            EncryptionService(master_key=None)

    def test_bad_key_raises(self):
        with pytest.raises(ValueError, match="Invalid encryption key"):
            EncryptionService(master_key="not-a-valid-fernet-key")

    def test_wrong_key_cannot_decrypt(self):
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        svc1 = EncryptionService(master_key=key1)
        svc2 = EncryptionService(master_key=key2)

        encrypted = svc1.encrypt("secret")
        with pytest.raises(ValueError, match="Decryption failed"):
            svc2.decrypt(encrypted)


class TestGenerateKey:
    def test_generates_valid_key(self):
        key = EncryptionService.generate_key()
        assert isinstance(key, str)
        # Should be usable as a Fernet key
        svc = EncryptionService(master_key=key)
        assert svc.decrypt(svc.encrypt("test")) == "test"
