"""Signed answers: each business has an Ed25519 key pair, so an AI assistant can verify that an
offer or booking really came from that business and wasn't changed on the way.

The public key is published (get_business_info); the private key stays encrypted at rest."""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from .. import db, vault

VALID_FOR = timedelta(minutes=15)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def ensure_key(business_id: str) -> str:
    """The business's public key, creating the key pair the first time."""
    with db.session() as conn:
        b = conn.execute("SELECT public_key, signing_key_enc FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if b["public_key"] and b["signing_key_enc"]:
            return b["public_key"]
        key = Ed25519PrivateKey.generate()
        private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        public = _b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        conn.execute("UPDATE businesses SET public_key = ?, signing_key_enc = ? WHERE id = ?", (public, vault.encrypt(_b64(private)), business_id))
        return public


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def sign(business_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_key(business_id)
    with db.session() as conn:
        b = conn.execute("SELECT public_key, signing_key_enc FROM businesses WHERE id = ?", (business_id,)).fetchone()
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(vault.decrypt(b["signing_key_enc"])))
    now = datetime.now(timezone.utc)
    signed = {**payload, "issued_at": now.isoformat(timespec="seconds"), "valid_until": (now + VALID_FOR).isoformat(timespec="seconds")}
    return {
        "payload": signed,
        "signature": _b64(key.sign(canonical(signed))),
        "public_key": b["public_key"],
        "algorithm": "Ed25519 over the payload as compact JSON with sorted keys",
    }


def verify(signed: dict[str, Any]) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(signed["public_key"]))
        key.verify(base64.b64decode(signed["signature"]), canonical(signed["payload"]))
        return True
    except (InvalidSignature, KeyError, ValueError):
        return False
