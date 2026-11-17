from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from liquidity_lens.collector.pipeline import Pipeline


def replay_jsonl(pipeline: Pipeline, path: str | Path) -> int:
    """Feed a JSONL file of {"received_at", "kind", "payload"} lines through the pipeline."""
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            pipeline.handle(rec["kind"], rec["payload"], datetime.fromisoformat(rec["received_at"]))
            n += 1
    return n


def replay_capture(handler: Callable[[str, datetime], None], path: str | Path) -> int:
    """Feed a raw WebSocket capture (as written by scripts/smoke_test.py) to `handler(raw, received_at)`.

    The first line is a label/metadata record; only inbound frames ("direction": "in") are replayed, in order.
    Returns the number of frames replayed.
    """
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("direction") != "in":
                continue
            handler(rec["raw"], datetime.fromisoformat(rec["received_at"]))
            n += 1
    return n
