"""Password hashing and signed tokens — standard library only.

* Passwords: scrypt with a per-user random salt.
* Tokens: base64url(JSON payload) + HMAC-SHA256 signature, with expiry.
  Deliberately simple and dependency-free for Phase 2; a production
  deployment can swap in any standard scheme without touching call-sites.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from .models import User

_TOKEN_TTL_SECONDS = 24 * 3600


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _sign(payload_b64: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()


def create_token(user: User, secret: str, ttl_seconds: int = _TOKEN_TTL_SECONDS) -> str:
    payload = json.dumps(
        {"sub": str(user.id), "role": user.role.value, "exp": int(time.time()) + ttl_seconds},
        separators=(",", ":"),
    ).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{payload_b64}.{_sign(payload_b64, secret)}"


def decode_token(token: str, secret: str) -> dict | None:
    """Return the payload if the signature and expiry are valid, else None."""
    try:
        payload_b64, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(_sign(payload_b64, secret), signature):
            return None
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
