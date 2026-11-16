import json
import os
from datetime import datetime, timedelta

import pytest

from liquidity_lens.config import TZ
from liquidity_lens.ssi.auth import (
    AuthError,
    TokenManager,
    TokenSet,
    needs_refresh,
    normalize_epoch,
    refresh_token,
    request_token,
)

# Fake responses below are DOC SAMPLE-style shapes (docs/ssi/02, 03), not real tokens.
NOW = datetime(2026, 11, 17, 9, 0, 0, tzinfo=TZ)


def _epoch(dt):
    return int(dt.timestamp())


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        status, payload = self.responses.pop(0)
        return status, {}, json.dumps(payload)


def _ok(access, refresh, expires_in=3600, refresh_in=28800):
    return 200, {"tokenType": "Bearer", "accessToken": access, "refreshToken": refresh,
                 "expiresAt": _epoch(NOW + timedelta(seconds=expires_in)),
                 "refreshExpiresAt": _epoch(NOW + timedelta(seconds=refresh_in))}


def test_normalize_epoch_seconds_and_milliseconds_agree():
    a, b = normalize_epoch(1779806203), normalize_epoch(1779806203000)
    assert a == b and a.tzinfo is not None and a.utcoffset() == timedelta(hours=7)


def test_normalize_epoch_rejects_other_lengths():
    with pytest.raises(ValueError):
        normalize_epoch(12345)


def test_token_body_has_no_otp():
    http = FakeHttp(_ok("A1", "R1"))
    t = request_token("KEY", "SECRET", http)
    method, url, _, body = http.calls[0]
    assert (method, url) == ("POST", "https://api.ssi.com.vn/api/v3/auth/token")
    assert set(body) == {"apiKey", "apiSecret"}
    assert (t.token_type, t.access_token, t.refresh_token) == ("Bearer", "A1", "R1")
    assert t.expires_at == NOW + timedelta(hours=1)


def test_refresh_body_has_only_refresh_token():
    http = FakeHttp(_ok("A2", "R2"))
    t = refresh_token("R1", http)
    method, url, _, body = http.calls[0]
    assert url.endswith("/api/v3/auth/refresh") and body == {"refreshToken": "R1"}
    assert t.access_token == "A2"


def test_needs_refresh_margin():
    t = TokenSet("Bearer", "A", "R", NOW + timedelta(seconds=200), NOW + timedelta(hours=8))
    assert needs_refresh(t, NOW, margin_s=300) is True
    assert needs_refresh(t, NOW, margin_s=100) is False


def test_error_does_not_leak_credentials():
    http = FakeHttp((400, {"code": 400, "msg": "bad key KEY123 secret SECRET456"}))
    with pytest.raises(AuthError) as e:
        request_token("KEY123", "SECRET456", http)
    assert "KEY123" not in str(e.value) and "SECRET456" not in str(e.value) and "400" in str(e.value)


def test_manager_caches_then_refreshes_with_newest_refresh_token():
    now = [NOW]
    http = FakeHttp(_ok("A1", "R1", expires_in=1000), _ok("A2", "R2", expires_in=3600), _ok("A3", "R3"))
    m = TokenManager("KEY", "SECRET", http, clock=lambda: now[0])
    assert m.authorization() == "Bearer A1"
    assert m.authorization() == "Bearer A1" and len(http.calls) == 1          # cached
    now[0] = NOW + timedelta(seconds=800)                                       # inside the 300 s margin
    assert m.authorization() == "Bearer A2"
    assert http.calls[1][3] == {"refreshToken": "R1"}
    now[0] = NOW + timedelta(seconds=800 + 3400)
    assert m.authorization() == "Bearer A3"
    assert http.calls[2][3] == {"refreshToken": "R2"}                           # never reuses the old one


def test_manager_falls_back_to_full_login_when_refresh_rejected():
    now = [NOW]
    http = FakeHttp(_ok("A1", "R1", expires_in=1000), (400, {"code": 401103, "msg": "revoked"}), _ok("A9", "R9"))
    m = TokenManager("KEY", "SECRET", http, clock=lambda: now[0])
    m.authorization()
    now[0] = NOW + timedelta(seconds=800)
    assert m.authorization() == "Bearer A9"
    assert set(http.calls[2][3]) == {"apiKey", "apiSecret"}


def test_invalidate_forces_new_login():
    http = FakeHttp(_ok("A1", "R1"), _ok("A2", "R2"))
    m = TokenManager("KEY", "SECRET", http, clock=lambda: NOW)
    m.authorization()
    m.invalidate()
    assert m.authorization() == "Bearer A2" and set(http.calls[1][3]) == {"apiKey", "apiSecret"}


def test_tokens_never_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    http = FakeHttp(_ok("A1", "R1", expires_in=1000), _ok("A2", "R2"))
    m = TokenManager("KEY", "SECRET", http, clock=lambda: NOW + timedelta(seconds=0))
    m.authorization()
    m._clock = lambda: NOW + timedelta(seconds=900)
    m.authorization()
    assert os.listdir(tmp_path) == []
    assert "A1" not in repr(m) and "R1" not in repr(m)
