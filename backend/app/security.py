"""Password hashing and signed user tokens — standard library only.

Passwords are stored as `scrypt$n$r$p$salt$hash` using `hashlib.scrypt`. That is a
deliberately slow, memory-hard KDF and it ships with Python, so there is no bcrypt/argon2
dependency to install on a free host.

Tokens are stateless: `expires.user_id.signature`, signed with HMAC-SHA256. The server
keeps no session table. Deactivating an account still takes effect immediately because
every authenticated request loads the user and checks `is_active`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid

# scrypt cost: 16 MiB of memory per hash, ~50 ms on a small VM. Enough to make offline
# guessing expensive without making sign-in feel slow.
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P,
                            dklen=_DKLEN)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$", 5)
        if scheme != "scrypt":
            return False
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        salt = base64.urlsafe_b64decode(pad(salt_b64))
        expected = base64.urlsafe_b64decode(pad(hash_b64))
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r),
                                p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_user_id() -> str:
    return "usr_" + uuid.uuid4().hex[:16]


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_user_token(secret: str, user_id: str, ttl_s: int) -> dict:
    expires = int(time.time()) + ttl_s
    payload = f"{expires}.{user_id}"
    return {"token": f"{payload}.{_sign(payload, secret)}", "expires_at": expires}


def read_user_token(token: str, secret: str) -> dict | None:
    """Return `{user_id, expires_at}` for a valid token, else None."""
    if not token or token.count(".") != 2:
        return None
    expires, user_id, signature = token.split(".", 2)
    if not expires.isdigit() or not user_id.startswith("usr_"):
        return None
    if not hmac.compare_digest(signature, _sign(f"{expires}.{user_id}", secret)):
        return None
    if int(expires) <= time.time():
        return None
    return {"user_id": user_id, "expires_at": int(expires)}
