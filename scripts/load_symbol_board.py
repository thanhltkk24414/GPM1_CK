"""Load the symbol -> board mapping into the `symbol_board` table from hose_all.txt, hnx_all.txt and upcom_all.txt.

    python scripts/load_symbol_board.py [--db data/liquidity_lens.db] [--hose F] [--hnx F] [--upcom F]

Adds the table with CREATE TABLE IF NOT EXISTS and writes only that table: no other table is created or altered, so it
is safe on a database that already holds collected data. Never creates a missing database. Stops, writing nothing, if
a symbol is listed on two boards. Re-running is safe (rows are replaced, nothing is deleted).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from liquidity_lens import config
from liquidity_lens.collector.main import load_watchlist
from liquidity_lens.data.symbol_board import build_mapping, save_symbol_board

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--hose", default=str(ROOT / "hose_all.txt"))
    ap.add_argument("--hnx", default=str(ROOT / "hnx_all.txt"))
    ap.add_argument("--upcom", default=str(ROOT / "upcom_all.txt"))
    args = ap.parse_args(argv)

    if not Path(args.db).is_file():
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2
    try:
        by_board = {"HOSE": load_watchlist(args.hose), "HNX": load_watchlist(args.hnx), "UPCOM": load_watchlist(args.upcom)}
        mapping = build_mapping(by_board)
    except (OSError, ValueError) as e:
        print(f"STOP, nothing written: {e}")
        return 3
    conn = sqlite3.connect(args.db, timeout=30)  # plain connection: init_db would run the DDL of every table
    try:
        n = save_symbol_board(conn, mapping)
    finally:
        conn.close()
    print(f"wrote {n} rows to symbol_board in {args.db}: " + ", ".join(f"{b} {len(v)}" for b, v in by_board.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
