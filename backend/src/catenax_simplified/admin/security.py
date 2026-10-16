"""Admin passwords, sessions and the encryption of secrets entered in the UI.

One deployment secret (CXS_SECRET_KEY) is stretched into separate keys per purpose, so a session
signature can never be replayed as a ciphertext and the other way round.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque

from cryptography.fernet import Fernet, InvalidToken

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1


def hash_password(password: str) -> str:
    """``scrypt:N:r:p:salt:hash`` (base64), the format of CXS_ADMIN_PASSWORD_HASH. No ``$``, so
    Docker Compose and shells take it as it is."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=2**26
    )
    salt_text, digest_text = base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}:{salt_text}:{digest_text}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split(":")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=2**26,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def derive_key(secret_key: str, purpose: str) -> bytes:
    return hmac.new(secret_key.encode(), purpose.encode(), hashlib.sha256).digest()


class SecretBox:
    """Encrypts the secrets stored in the database (Fernet: AES-128-CBC with HMAC-SHA256)."""

    def __init__(self, secret_key: str):
        self._fernet = Fernet(base64.urlsafe_b64encode(derive_key(secret_key, "config-secrets")))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        """``None`` if the value was encrypted with another CXS_SECRET_KEY."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            return None


class AdminAuth:
    """The single admin account: password check with a lockout, and signed session tokens."""

    MAX_FAILURES = 5
    LOCKOUT_SECONDS = 15 * 60

    def __init__(self, username: str, password_hash: str, secret_key: str, session_hours: int):
        self.username = username
        self._password_hash = password_hash
        self._key = derive_key(secret_key, "admin-session")
        self._lifetime = session_hours * 3600
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def locked_out(self, client: str) -> bool:
        with self._lock:
            recent = self._recent(client)
            return len(recent) >= self.MAX_FAILURES

    def _recent(self, client: str) -> deque[float]:
        recent = self._failures.setdefault(client, deque())
        while recent and recent[0] < time.monotonic() - self.LOCKOUT_SECONDS:
            recent.popleft()
        return recent

    def login(self, client: str, username: str, password: str) -> str | None:
        """A session token, or ``None`` for wrong credentials (counted towards the lockout)."""
        # Always verify, so a wrong username takes as long as a wrong password.
        valid = verify_password(password, self._password_hash)
        if valid and hmac.compare_digest(username.encode(), self.username.encode()):
            with self._lock:
                self._failures.pop(client, None)
            return self._token()
        with self._lock:
            self._recent(client).append(time.monotonic())
        return None

    def _token(self) -> str:
        payload = json.dumps({"u": self.username, "exp": int(time.time()) + self._lifetime})
        body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        return f"{body}.{self._sign(body)}"

    def _sign(self, body: str) -> str:
        mac = hmac.new(self._key, body.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    def user(self, token: str | None) -> str | None:
        """The signed-in admin of a session token, if it is valid and not expired."""
        if not token or "." not in token:
            return None
        body, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign(body)):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if payload.get("exp", 0) < time.time() or payload.get("u") != self.username:
            return None
        return payload["u"]
