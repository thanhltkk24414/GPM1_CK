"""SSI FastConnect WebSocket transport (DATA channel only).

Transport layer only: connect with the Bearer header, subscribe, answer heartbeat PINGs, reconnect with
backoff, subscribe again after every reconnect, log every connect/disconnect/heartbeat event, and hand each
raw frame to `on_frame`. Mapping a frame to a kind (quote, trade, ...) lives in `ssi/frames.py`.

Session rule: one active session per apiKey, so only the collector creates a StreamClient.
Never uses the TRADING channel (build_subscribe refuses order.*, portfolio.*, fco.* topics).
No token is ever logged: events carry status codes, frame sizes and error class names only.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Any, Callable, Sequence

from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from liquidity_lens import config
from liquidity_lens.ssi.auth import AuthError
from liquidity_lens.ssi.frames import DATA_KINDS, REJECTION_KEYWORDS, map_frame

DEFAULT_URL = "wss://stream.ssi.com.vn/ws/v3"
_FORBIDDEN_PREFIXES = ("order.", "portfolio.", "fco.")


def _check_topics(topics: Sequence[str]) -> list[str]:
    if not topics:
        raise ValueError("topics must not be empty")
    for t in topics:
        if t.lower().startswith(_FORBIDDEN_PREFIXES):
            raise ValueError(f"topic {t!r} belongs to the trading channel, which this project never uses")
    return list(topics)


def build_subscribe(topics: Sequence[str]) -> dict:
    return {"method": "SUBSCRIBE", "channel": "DATA", "topics": _check_topics(topics)}


MAX_TOPICS_PER_FRAME = 20
MAX_FRAME_BYTES = 4000  # frames must stay below this (the SDK documents a 4096-byte limit and keeps 4000)


def _frame_bytes(frame: dict) -> int:
    return len(json.dumps(frame).encode("utf-8"))


def build_subscribe_frames(
    topics: Sequence[str], max_topics: int = MAX_TOPICS_PER_FRAME, max_bytes: int = MAX_FRAME_BYTES
) -> list[dict]:
    """Split a SUBSCRIBE into several frames of at most `max_topics` topics and fewer than `max_bytes` bytes,
    keeping the topic order. A watchlist of 30 symbols is 91 topics, far too many for one frame."""
    topics = _check_topics(topics)
    frames: list[dict] = []
    current: list[str] = []
    for topic in topics:
        if _frame_bytes(build_subscribe([topic])) >= max_bytes:
            raise ValueError(f"topic is too long for one SUBSCRIBE frame ({len(topic)} characters)")
        candidate = current + [topic]
        if current and (len(candidate) > max_topics or _frame_bytes(build_subscribe(candidate)) >= max_bytes):
            frames.append(build_subscribe(current))
            candidate = [topic]
        current = candidate
    frames.append(build_subscribe(current))
    return frames


def build_unsubscribe(topics: Sequence[str]) -> dict:
    return {"method": "UNSUBSCRIBE", "channel": "DATA", "topics": _check_topics(topics)}


def pong_for(ping: dict) -> dict:
    # docs/ssi/04: the client answers a server PING with a PONG carrying the same time. [Kiểm tra] whether
    # the real server sends PING at all (no PING seen in 60 s on 2026-11-16, market closed).
    return {"method": "PONG", "channel": "HEARTBEAT", "time": ping.get("time")}


def default_connect(url: str, headers: dict):
    from websockets.asyncio.client import connect

    # ping_interval=None: SSI has its own application-level heartbeat; protocol pings are not used.
    return connect(url, additional_headers=headers, open_timeout=20, ping_interval=None)


class StreamClient:
    def __init__(
        self,
        *,
        url: str = DEFAULT_URL,
        topics: Sequence[str],
        authorization: Callable[[], str],
        on_frame: Callable[[str, datetime], None],
        on_event: Callable[[str, str | None], None],
        connect: Callable[[str, dict], Any] = default_connect,
        sleep: Callable[[float], Any] | None = None,
        rng: Callable[[], float] = random.random,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        backoff_base_s: float = 1.0,
        backoff_cap_s: float = 60.0,
        jitter: float = 0.2,
        stable_s: float = 30.0,
        silence_warn_s: float = 30.0,
        should_warn: Callable[[datetime], bool] | None = None,
        on_auth_failure: Callable[[], None] | None = None,
        redact: Callable[[str], str] | None = None,
        poll_s: float = 1.0,
    ) -> None:
        self.url, self.topics = url, _check_topics(topics)
        self.authorization, self.on_frame, self.on_event = authorization, on_frame, on_event
        self._connect, self._rng, self._mono = connect, rng, monotonic
        self._now = now or (lambda: datetime.now(config.TZ))
        self._sleep_fn = sleep
        self.backoff_base_s, self.backoff_cap_s, self.jitter = backoff_base_s, backoff_cap_s, jitter
        self.stable_s, self.silence_warn_s, self.poll_s = stable_s, silence_warn_s, poll_s
        self.should_warn = should_warn or (lambda now: True)
        self.on_auth_failure = on_auth_failure
        self._redact = redact or (lambda s: s)
        self.halted = False
        self._delivered = False  # did the current connection deliver at least one frame?
        self._stop: asyncio.Event | None = None

    # ------------------------------------------------------------------ helpers
    def _emit(self, event: str, detail: str | None = None) -> None:
        try:
            self.on_event(event, self._redact(detail) if detail is not None else None)
        except Exception:  # an event sink must never take the stream down
            pass

    async def _sleep(self, delay: float) -> None:
        if self._sleep_fn is not None:
            await self._sleep_fn(delay)
            return
        assert self._stop is not None
        try:
            await asyncio.wait_for(self._stop.wait(), delay)
        except asyncio.TimeoutError:
            pass

    def _backoff(self, attempt: int, extra_floor: float = 0.0) -> float:
        delay = min(self.backoff_cap_s, self.backoff_base_s * (2 ** attempt))
        delay += delay * self.jitter * self._rng()
        return max(delay, extra_floor)

    # ------------------------------------------------------------------ main loop
    async def run(self, stop: asyncio.Event) -> None:
        self._stop = stop
        attempt = 0
        while not stop.is_set() and not self.halted:
            started = self._mono()
            connected, floor = False, 0.0
            self._delivered = False
            try:
                auth = await asyncio.to_thread(self.authorization)
                headers = {"Authorization": auth, "User-Agent": "liquidity-lens-collector"}
                async with self._connect(self.url, headers) as ws:
                    connected = True
                    self._emit("CONNECT", self.url)
                    frames = build_subscribe_frames(self.topics)  # again after every reconnect
                    for i, frame in enumerate(frames, 1):
                        text = json.dumps(frame)
                        await ws.send(text)
                        self._emit("SUBSCRIBE_SENT", json.dumps({
                            "frame": i, "frames": len(frames), "topics": len(frame["topics"]),
                            "bytes": len(text.encode("utf-8")),
                        }))
                    await self._listen(ws)
            except ConnectionClosed as e:
                code = e.rcvd.code if e.rcvd else None
                reason = e.rcvd.reason if e.rcvd else None
                self._emit("DISCONNECT", f"closed code={code} reason={reason!r}")
            except InvalidStatus as e:
                status = e.response.status_code
                self._emit("HANDSHAKE_REJECTED", f"HTTP {status}")
                if status in (401, 403) and self.on_auth_failure:
                    self.on_auth_failure()
                if status == 429:
                    floor = 30.0  # SDK docs: wait at least 30 s on 429
            except AuthError as e:
                self._emit("AUTH_ERROR", str(e))
            except (OSError, asyncio.TimeoutError, WebSocketException) as e:
                self._emit("DISCONNECT" if connected else "CONNECT_FAILED", f"{type(e).__name__}: {e}")
            if stop.is_set() or self.halted:
                break
            if self._delivered or self._mono() - started >= self.stable_s:
                attempt = 0
            delay = self._backoff(attempt, floor)
            attempt += 1
            self._emit("RECONNECT_WAIT", f"{delay:.1f}s")
            await self._sleep(delay)
        self._emit("STOPPED", "halted" if self.halted else None)

    async def _listen(self, ws) -> None:
        """Receive until stopped, halted or the connection drops (raises)."""
        assert self._stop is not None
        last, warned = self._mono(), False
        while not self._stop.is_set():
            try:
                msg = await asyncio.wait_for(ws.recv(), self.poll_s)
            except asyncio.TimeoutError:
                if not self.should_warn(self._now()):
                    last, warned = self._mono(), False  # outside trading hours silence is normal
                elif not warned and self._mono() - last >= self.silence_warn_s:
                    warned = True
                    self._emit("SILENCE_WARNING", f"no frame for {self.silence_warn_s:g}s during trading hours; connection kept")
                continue
            raw = msg if isinstance(msg, str) else msg.decode("utf-8", "replace")
            last, warned = self._mono(), False
            self._delivered = True
            received_at = self._now()
            kind, obj = map_frame(raw)
            if kind == "heartbeat":
                self._emit("HEARTBEAT", "in " + raw[:500])
                if isinstance(obj, dict) and obj.get("method") == "PING":
                    pong = json.dumps(pong_for(obj))
                    await ws.send(pong)
                    self._emit("HEARTBEAT", "out " + pong)
                continue
            if kind not in DATA_KINDS and any(k in raw.lower() for k in REJECTION_KEYWORDS):
                self._emit("REJECTED_OTP_OR_PERMISSION", f"stopping, not retrying and not trying OTP; frame: {raw[:200]}")
                self.halted = True
                return
            try:
                self.on_frame(raw, received_at)
            except Exception as e:
                self._emit("FRAME_HANDLER_ERROR", f"{type(e).__name__}: {e}")
