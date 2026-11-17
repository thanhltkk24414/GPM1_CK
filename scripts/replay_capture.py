"""Replay a raw WebSocket capture into a fresh SQLite DB, materialize 1-minute metrics and print a quality report.

    python scripts/replay_capture.py data/smoke/ws_20261117T090521.jsonl --date 2026-11-17 --db data/replay_test.db

Offline only: no network, no token. The DB is deleted and rebuilt on every run (it is derived data, kept out of git).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from liquidity_lens.analytics.materialize import materialize_metrics
from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.collector.replay import replay_capture
from liquidity_lens.collector.router import FrameRouter
from liquidity_lens.data.report import data_quality_report
from liquidity_lens.data.store import init_db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("capture", help="JSONL capture written by scripts/smoke_test.py")
    ap.add_argument("--date", required=True, help="trading date YYYY-MM-DD")
    ap.add_argument("--db", default="data/replay_test.db")
    ap.add_argument("--symbols", default="VIC,HPG,FPT", help="watchlist (HOSE symbols)")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--min-periods", type=int, default=15)
    args = ap.parse_args(argv)

    day = date.fromisoformat(args.date)
    db = Path(args.db)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    conn = init_db(db)
    router = FrameRouter(Pipeline(conn, today=day, batch=True, commit_every=1000), watchlist=args.symbols.split(","))
    n = replay_capture(router, args.capture)
    router.pipeline.flush()
    print(f"replayed {n} inbound frames; router counts={dict(router.counts)} dropped={router.dropped}")

    bars, alerts = materialize_metrics(conn, day, window=args.window, min_periods=args.min_periods)
    print(f"materialized {bars} minute bars, {alerts} alerts")
    rep = data_quality_report(conn, day, window=args.window, min_periods=args.min_periods)
    print("data_quality_report:", json.dumps(rep, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
