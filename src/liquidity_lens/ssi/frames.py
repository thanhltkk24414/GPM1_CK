"""Statistics over raw WebSocket frames, used by the smoke test.

Classification looks at the documented payload fields (docs/ssi/05), wherever they sit inside the frame,
because the real envelope of a data frame is still [Kiểm tra]. Everything printed is masked first.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable, Iterator

from liquidity_lens.ssi.redact import mask

REJECTION_KEYWORDS = ("otp", "permission", "forbidden", "unauthori", "denied")
HEARTBEAT_METHODS = {"PING", "PONG", "PING_PONG"}


def _dicts(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _dicts(v)


def classify(obj: Any) -> str:
    dicts = list(_dicts(obj))
    if any(d.get("channel") == "HEARTBEAT" or d.get("method") in HEARTBEAT_METHODS for d in dicts):
        return "heartbeat"
    if any("bids" in d and "asks" in d for d in dicts):
        return "quote"
    if any({"b", "f", "t"} <= d.keys() for d in dicts):
        return "market_flag"
    if any({"ce", "fl", "ref"} <= d.keys() for d in dicts):
        return "market_ref"
    if any({"s", "p", "q", "v"} <= d.keys() for d in dicts):
        return "trade"
    if isinstance(obj, dict):
        return "other:" + ",".join(sorted(obj))
    return "other"


class FrameStats:
    def __init__(self, secrets: Iterable[str | None] = (), max_samples: int = 2) -> None:
        self.secrets = [s for s in secrets if s]
        self.max_samples = max_samples
        self.counts: Counter[str] = Counter()
        self.total = 0
        self.samples: dict[str, list[str]] = {}
        self.session_flags: Counter[tuple[str, str]] = Counter()
        self.quote_levels: Counter[tuple[int, int]] = Counter()
        self.heartbeats: list[tuple[str, str]] = []  # (direction, masked raw)
        self.rejections: list[str] = []  # masked raw frames that look like an auth/permission refusal

    def add_secret(self, secret: str | None) -> None:
        if secret:
            self.secrets.append(secret)

    def mask_frame(self, raw: str) -> str:
        """Raw frame text with credentials hidden. Unchanged (byte for byte) when nothing needed hiding."""
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return mask(raw, self.secrets)
        masked = mask(obj, self.secrets)
        return raw if masked == obj else json.dumps(masked, ensure_ascii=False)

    def add(self, raw: str, direction: str = "in") -> str:
        """Record one frame. Returns its kind. Outbound frames only feed the heartbeat list."""
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = None
        kind = classify(obj) if obj is not None else "non_json"
        masked = self.mask_frame(raw)

        if kind == "heartbeat":
            self.heartbeats.append((direction, masked))
        if direction != "in":
            return kind

        self.total += 1
        self.counts[kind] += 1
        bucket = self.samples.setdefault(kind, [])
        if len(bucket) < self.max_samples:
            bucket.append(masked[:600])
        low = raw.lower()
        if any(k in low for k in REJECTION_KEYWORDS):
            self.rejections.append(masked[:600])
        for d in _dicts(obj):
            if "bids" in d and "asks" in d and isinstance(d["bids"], list) and isinstance(d["asks"], list):
                self.quote_levels[(len(d["bids"]), len(d["asks"]))] += 1
            if {"b", "f", "t"} <= d.keys():
                self.session_flags[(str(d["b"]), str(d["f"]))] += 1
        return kind

    def report(self) -> str:
        lines = [f"frames received: {self.total}"]
        lines.append(f"by kind: {dict(self.counts) or '-'}")
        lines.append(f"quote levels (bids, asks) -> count: {dict(self.quote_levels) or '-'}")
        lines.append(f"session flags seen (board, flag) -> count: {dict(self.session_flags) or '-'}")
        lines.append(f"HEARTBEAT frames: {len(self.heartbeats)}")
        for direction, masked in self.heartbeats[:6]:
            lines.append(f"  [{direction}] {masked[:200]}")
        if self.rejections:
            lines.append(f"POSSIBLE REJECTION frames: {len(self.rejections)}")
            for m in self.rejections[:3]:
                lines.append(f"  {m[:300]}")
        for kind, items in self.samples.items():
            for i, m in enumerate(items, 1):
                lines.append(f"sample {kind} #{i}: {m}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------
# Frame -> kind mapping for Pipeline.handle.
# [Xác nhận bằng thực nghiệm 2026-11-17] Data frames look like {"channel":"DATA","topic":"quote.HPG","data":{...}}
# and the session-flag topic is "market.FLAG" (upper case). Topics are therefore matched case-insensitively, and
# the topic decides the kind. Frames without a topic envelope fall back to the payload shapes of docs/ssi/05.
# ---------------------------------------------------------------------------------------------------
DATA_KINDS = ("quote", "trade", "market_ref", "market_flag")

_REQUIRED_KEYS = {
    "quote": {"s", "t", "bids", "asks"},
    "trade": {"s", "t", "p", "q", "v", "si"},
    "market_ref": {"s", "b", "t", "ce", "fl", "ref"},
    "market_flag": {"b", "t", "f"},
}


def _kind_from_topic(topic: str) -> str:
    head, _, rest = topic.strip().lower().partition(".")
    if head == "quote":
        return "quote"
    if head == "trade":
        return "unknown" if rest.startswith("index") else "trade"  # trade.index.* are index ticks
    if head == "market":
        return "market_flag" if rest == "flag" else "market_ref"
    return "unknown"  # room, put, oddlot, indexsummary, ...: not subscribed by this project


def map_frame(raw: str) -> tuple[str, Any]:
    """Return (kind, payload). kind is one of quote, trade, market_ref, market_flag (payload = the data
    dict), heartbeat / subscribe_ack / list_subscription (payload = the whole frame), unknown or non_json."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return "non_json", None
    dicts = list(_dicts(obj))
    if any(d.get("channel") == "HEARTBEAT" or d.get("method") in HEARTBEAT_METHODS for d in dicts):
        return "heartbeat", obj
    if isinstance(obj, dict):
        if obj.get("method") in ("SUBSCRIBE", "UNSUBSCRIBE") and "status" in obj:
            return "subscribe_ack", obj
        if set(obj) == {"trading", "data"}:
            return "list_subscription", obj
        if isinstance(obj.get("topic"), str) and isinstance(obj.get("data"), dict):
            kind = _kind_from_topic(obj["topic"])
            if kind != "unknown" and _REQUIRED_KEYS[kind] <= obj["data"].keys():
                if kind == "quote" and "p" in obj["data"]:  # oddlot-like payload on a quote topic
                    return "unknown", None
                return kind, obj["data"]
            return "unknown", None
    for d in dicts:  # no known envelope: payload shapes from the documentation, outermost first
        keys = d.keys()
        if _REQUIRED_KEYS["quote"] <= keys and "p" not in keys:  # "p" next to bids/asks = oddlot
            return "quote", d
        if _REQUIRED_KEYS["market_flag"] <= keys and "s" not in keys:
            return "market_flag", d
        if _REQUIRED_KEYS["market_ref"] <= keys:
            return "market_ref", d
        if _REQUIRED_KEYS["trade"] <= keys:
            return "trade", d
    return "unknown", None


def describe_unknown(raw: str) -> dict:
    """Type and length of a frame we could not map. Never the content."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "non_json", "length": len(raw)}
    return {"type": classify(obj), "length": len(raw)}
