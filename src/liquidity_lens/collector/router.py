"""Raw WebSocket frame -> Pipeline. Frames we cannot map are logged (type and length only), never raised."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Iterable

from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.ssi.frames import DATA_KINDS, describe_unknown, map_frame


class FrameRouter:
    def __init__(self, pipeline: Pipeline, watchlist: Iterable[str] | None = None) -> None:
        self.pipeline = pipeline
        self.watchlist = {s.upper() for s in watchlist} if watchlist is not None else None
        self.counts: Counter[str] = Counter()
        self.dropped = 0

    def __call__(self, raw: str, received_at: datetime) -> None:
        kind, payload = map_frame(raw)
        if kind in DATA_KINDS:
            self._data(kind, payload, received_at)
        elif kind == "subscribe_ack":
            self.pipeline.log_event(
                "SUBSCRIBE_ACK", json.dumps({k: payload.get(k) for k in ("method", "status", "message")}, ensure_ascii=False),
                received_at,
            )
        elif kind == "list_subscription":
            self.pipeline.log_event("LIST_SUBSCRIPTION", json.dumps(payload, ensure_ascii=False), received_at)
        elif kind == "heartbeat":
            pass  # logged by the transport layer
        else:
            self.counts["unknown"] += 1
            self.pipeline.log_event("UNKNOWN_FRAME", json.dumps(describe_unknown(raw)), received_at)

    def _data(self, kind: str, payload: dict, received_at: datetime) -> None:
        symbol = payload.get("s")
        if symbol is not None and self.watchlist is not None and str(symbol).upper() not in self.watchlist:
            self.dropped += 1
            return
        if kind == "market_ref" and payload.get("b") != "HOSE":
            # [Kiểm tra] CONTINUOUS_WINDOWS and the watchlist are only valid for HOSE symbols.
            self.dropped += 1
            self.pipeline.log_event("NON_HOSE_SYMBOL", json.dumps({"symbol": symbol, "board": payload.get("b")}), received_at)
            return
        self.pipeline.handle(kind, payload, received_at)
        self.counts[kind] += 1
