"""Authenticated encryption for GitHub OAuth tokens at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenCryptoError(RuntimeError):
    """Raised when token encryption is not configured or data is invalid."""


def _fernet(key: str) -> Fernet:
    value = key.strip()
    if not value:
        raise TokenCryptoError("GitHub token encryption is not configured on the server.")
    try:
        return Fernet(value.encode("ascii"))
    except Exception as error:
        raise TokenCryptoError("GitHub token encryption key is invalid.") from error


def encrypt_token(token: str, key: str) -> str:
    if not token or len(token) > 4096:
        raise TokenCryptoError("GitHub token is invalid.")
    return "v1:" + _fernet(key).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(value: str, key: str) -> str:
    """Decrypt current rows; reject legacy plaintext instead of leaking it."""
    if not value.startswith("v1:"):
        raise TokenCryptoError("Stored GitHub credentials need to be reconnected.")
    try:
        token = _fernet(key).decrypt(value[3:].encode("ascii"), ttl=None).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as error:
        raise TokenCryptoError("Stored GitHub credentials could not be decrypted. Reconnect GitHub.") from error
    if not token:
        raise TokenCryptoError("Stored GitHub credentials are invalid. Reconnect GitHub.")
    return token
