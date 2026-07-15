"""Fernet symmetric encryption for user-stored secrets (FRA-93).

The per-user API key stored in ``user_llm_configs.encrypted_api_key`` is
encrypted at rest using a Fernet token derived from ``settings.secret_key``.
The key never appears in API responses or logs.

If ``SECRET_KEY`` is empty (local dev default), a deterministic throwaway key
is generated from the JWT secret so the feature still works without extra
configuration — production deployments **must** set a proper ``SECRET_KEY``.
"""

from __future__ import annotations

import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Return a Fernet instance, deriving a key if SECRET_KEY is unset."""
    key = settings.secret_key
    if not key:
        import base64

        raw = hashlib.sha256(settings.jwt_secret.encode()).digest()
        key = base64.urlsafe_b64encode(raw).decode()
        logger.warning(
            "SECRET_KEY not set — using derived key (dev mode). "
            "Set SECRET_KEY in production for per-user API key encryption."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


_fernet: Fernet | None = None


def _fernet_instance() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _get_fernet()
    return _fernet


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key and return the Fernet token as a string."""
    token: str = _fernet_instance().encrypt(plaintext.encode()).decode()
    return token


def decrypt_api_key(token: str) -> str:
    """Decrypt a Fernet token back to the plaintext API key.

    Raises :class:`InvalidToken` if the token is tampered or was encrypted
    with a different key.
    """
    plaintext: str = _fernet_instance().decrypt(token.encode()).decode()
    return plaintext


def mask_api_key(key: str) -> str:
    """Return ``••••••••last4`` for display. Empty key → empty string."""
    if not key or len(key) < 4:
        return ""
    return f"••••••••{key[-4:]}"


__all__ = [
    "InvalidToken",
    "decrypt_api_key",
    "encrypt_api_key",
    "mask_api_key",
]
