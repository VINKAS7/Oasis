"""Encrypts AI provider API keys at rest. Keys go in through the admin panel and only ever
come out inside this process, on the way to the provider."""

from cryptography.fernet import Fernet, InvalidToken

from .config import SECRETS_KEY


class VaultError(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not SECRETS_KEY:
        raise VaultError("SECRETS_KEY is not set in backend/.env; run `npm run init-env` at the repo root")
    try:
        return Fernet(SECRETS_KEY.encode())
    except ValueError as exc:
        raise VaultError("SECRETS_KEY in backend/.env is not a valid Fernet key") from exc


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise VaultError("A stored API key could not be decrypted (SECRETS_KEY changed?). Re-enter it in the admin panel.") from exc


def hint(secret: str) -> str:
    return secret[-4:] if len(secret) >= 8 else ""
