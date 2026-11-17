"""Build the combined watchlist CSV (`symbol,board`) from the per-board symbol files.

    python scripts/build_watchlist.py [--hose hose_all.txt] [--hnx hnx_all.txt] [--upcom upcom_all.txt]
                                      [--out watchlist_all.csv]

Offline. Stops, writing nothing, if a symbol appears on two boards (it never guesses which board is right).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from liquidity_lens import config
from liquidity_lens.collector.main import load_watchlist
from liquidity_lens.watchlist import build_watchlist_csv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hose", default="hose_all.txt")
    ap.add_argument("--hnx", default="hnx_all.txt")
    ap.add_argument("--upcom", default="upcom_all.txt")
    ap.add_argument("--out", default="watchlist_all.csv")
    args = ap.parse_args(argv)
    try:
        by_board = {"HOSE": load_watchlist(args.hose), "HNX": load_watchlist(args.hnx), "UPCOM": load_watchlist(args.upcom)}
        text = build_watchlist_csv(by_board, datetime.now(config.TZ).date())
    except (OSError, ValueError) as e:
        print(f"STOP, no file written: {e}")
        return 3
    Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    total = len(text.splitlines()) - 2
    print(f"wrote {total} symbols to {args.out}: " + ", ".join(f"{b} {len(v)}" for b, v in by_board.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
