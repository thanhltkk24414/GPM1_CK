"""SSI FastConnect token handling. Read-only market-data tokens only.

The token request carries apiKey and apiSecret and nothing else: no otp, no transactionId.
Tokens live in memory only. They are never written to disk, logged or included in exception messages.
Only the collector holds a token (one active session per apiKey); the dashboard never calls auth.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from liquidity_lens import config
from liquidity_lens.ssi.redact import mask

BASE_URL = "https://api.ssi.com.vn"
TOKEN_PATH = "/api/v3/auth/token"
REFRESH_PATH = "/api/v3/auth/refresh"

# http(method, url, headers, body) -> (status, response_headers, response_text)
HttpFn = Callable[[str, str, dict, "dict | None"], "tuple[int, dict, str]"]


class AuthError(Exception):
    """Authentication failed. The message never contains credentials or tokens."""


def urllib_http(method: str, url: str, headers: dict, body: dict | None) -> tuple[int, dict, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers.items()), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read().decode("utf-8", "replace")


def normalize_epoch(value: int) -> datetime:
    """10 digits = seconds, 13 digits = milliseconds (the real server sends seconds; docs say ms)."""
    n = int(value)
    digits = len(str(abs(n)))
    if digits == 10:
        seconds = n
    elif digits == 13:
        seconds = n / 1000
    else:
        raise ValueError(f"unexpected epoch length ({digits} digits)")
    return datetime.fromtimestamp(seconds, tz=config.TZ)


@dataclass(frozen=True)
class TokenSet:
    token_type: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: datetime

    def __repr__(self) -> str:  # never show tokens
        return f"TokenSet(expires_at={self.expires_at.isoformat()})"


_HEADERS = {"Content-Type": "application/json", "User-Agent": "liquidity-lens-collector"}


def _post(path: str, body: dict, http: HttpFn, secrets: list[str], base_url: str) -> TokenSet:
    status, _, text = http("POST", base_url + path, dict(_HEADERS), body)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if status != 200 or not isinstance(data, dict):
        raise AuthError(f"{path} failed: HTTP {status}: {mask(text, secrets)[:300]}")
    needed = ("tokenType", "accessToken", "refreshToken", "expiresAt", "refreshExpiresAt")
    missing = [k for k in needed if k not in data]
    if missing:
        raise AuthError(f"{path}: response lacks fields {missing}; fields received: {sorted(data)}")
    secrets.extend([data["accessToken"], data["refreshToken"]])
    return TokenSet(
        token_type=data["tokenType"],
        access_token=data["accessToken"],
        refresh_token=data["refreshToken"],
        expires_at=normalize_epoch(data["expiresAt"]),
        refresh_expires_at=normalize_epoch(data["refreshExpiresAt"]),
    )


def request_token(api_key: str, api_secret: str, http: HttpFn = urllib_http, base_url: str = BASE_URL) -> TokenSet:
    return _post(TOKEN_PATH, {"apiKey": api_key, "apiSecret": api_secret}, http, [api_key, api_secret], base_url)


def refresh_token(refresh: str, http: HttpFn = urllib_http, base_url: str = BASE_URL) -> TokenSet:
    return _post(REFRESH_PATH, {"refreshToken": refresh}, http, [refresh], base_url)


def needs_refresh(t: TokenSet, now: datetime, margin_s: int = 300) -> bool:
    return now >= t.expires_at - timedelta(seconds=margin_s)


class TokenManager:
    """Keeps the current token in memory and refreshes it before expiry.

    A used refresh token is discarded at once: reusing it makes the server revoke every session of the key.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        http: HttpFn = urllib_http,
        clock: Callable[[], datetime] | None = None,
        margin_s: int = 300,
        base_url: str = BASE_URL,
    ) -> None:
        self._api_key, self._api_secret = api_key, api_secret
        self._http, self._base_url, self._margin_s = http, base_url, margin_s
        self._clock = clock or (lambda: datetime.now(config.TZ))
        self._token: TokenSet | None = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "TokenManager(<redacted>)"

    def secrets(self) -> list[str]:
        """Values that must be masked in any text: key, secret and current tokens."""
        out = [self._api_key, self._api_secret]
        if self._token:
            out += [self._token.access_token, self._token.refresh_token]
        return out

    def invalidate(self) -> None:
        """Forget the token (for example after a 401): the next call logs in again."""
        with self._lock:
            self._token = None

    def authorization(self) -> str:
        """Value for the `Authorization` header, e.g. 'Bearer <token>'. Safe to call from a worker thread."""
        with self._lock:
            now = self._clock()
            t = self._token
            if t is not None and needs_refresh(t, now, self._margin_s):
                t = self._try_refresh(t, now)
            if t is None:
                t = request_token(self._api_key, self._api_secret, self._http, self._base_url)
            self._token = t
            return f"{t.token_type} {t.access_token}"

    def _try_refresh(self, t: TokenSet, now: datetime) -> TokenSet | None:
        if now >= t.refresh_expires_at - timedelta(seconds=self._margin_s):
            return None
        self._token = None  # the old refresh token must never be used twice
        try:
            return refresh_token(t.refresh_token, self._http, self._base_url)
        except AuthError:
            return None
