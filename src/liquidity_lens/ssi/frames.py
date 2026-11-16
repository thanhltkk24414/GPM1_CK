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
