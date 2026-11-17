"""Compute 1-minute metrics and alerts for one trading day from the collector's SQLite DB, then print the data
quality report as tables.

    python scripts/materialize.py [--date YYYY-MM-DD] [--db data/liquidity_lens.db] [--symbols VIC,HPG,FPT]

Offline: reads and writes the local SQLite file only. It never reads credentials and never touches the network.
Safe to re-run: the day's metrics_1m and alerts rows are rebuilt each time.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from liquidity_lens import config
from liquidity_lens.analytics.materialize import materialize_metrics
from liquidity_lens.data.report import data_quality_report, format_report
from liquidity_lens.data.store import init_db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="trading date YYYY-MM-DD (default: today, Asia/Ho_Chi_Minh)")
    ap.add_argument("--db", default=str(config.DB_PATH), help="SQLite path (default: config.DB_PATH)")
    ap.add_argument("--symbols", help="comma-separated symbols to materialize (default: all)")
    ap.add_argument("--window", type=int, default=30, help="z-score window in minutes")
    ap.add_argument("--min-periods", type=int, default=15, help="minimum prior observations for a z-score")
    args = ap.parse_args(argv)

    try:
        day = date.fromisoformat(args.date) if args.date else datetime.now(config.TZ).date()
    except ValueError:
        print(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 2
    if not Path(args.db).is_file():
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)  # never create an empty DB by accident
        return 2
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None

    conn = init_db(args.db)
    try:
        bars, alerts = materialize_metrics(conn, day, symbols=symbols, window=args.window, min_periods=args.min_periods)
        report = data_quality_report(conn, day, window=args.window, min_periods=args.min_periods)
    finally:
        conn.close()
    print(format_report(day, bars, alerts, report, symbols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
