"""Combined watchlist file: CSV with a `symbol,board` header (one row per symbol)."""
from __future__ import annotations

import re
from datetime import date
from typing import Mapping, Sequence

from liquidity_lens import config

HEADER = "symbol,board"
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def build_watchlist_csv(by_board: Mapping[str, Sequence[str]], when: date) -> str:
    """CSV text: one comment line, the header, then rows ordered by board (HOSE, HNX, UPCOM) and symbol.

    Raises ValueError, building nothing, for an unknown board, a bad symbol, or a symbol listed on two boards
    (it is never decided silently which board wins).
    """
    unknown = [b for b in by_board if b not in config.BOARDS]
    if unknown:
        raise ValueError(f"unknown board(s) {unknown}; expected {list(config.BOARDS)}")
    seen: dict[str, str] = {}
    twice: dict[str, list[str]] = {}
    for board in config.BOARDS:
        for sym in by_board.get(board, ()):
            if not _SYMBOL_RE.match(sym):
                raise ValueError(f"invalid symbol {sym!r} on {board}")
            if sym in seen and seen[sym] != board:
                twice.setdefault(sym, [seen[sym]]).append(board)
            seen.setdefault(sym, board)
    if twice:
        raise ValueError("symbol(s) listed on more than one board: "
                         + ", ".join(f"{s} ({'/'.join(b)})" for s, b in sorted(twice.items())))
    rows = [(b, s) for b in config.BOARDS for s in sorted(set(by_board.get(b, ())))]
    counts = ", ".join(f"{b} {sum(1 for x, _ in rows if x == b)}" for b in config.BOARDS)
    header = f"# combined watchlist; built {when.isoformat()}; {len(rows)} symbols ({counts})"
    return "\n".join([header, HEADER, *(f"{s},{b}" for b, s in rows)]) + "\n"


def read_watchlist_csv(text: str) -> dict[str, str]:
    """Parse the CSV into {symbol: board}, keeping file order. Comment (#) and blank lines are skipped."""
    mapping: dict[str, str] = {}
    header_seen = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split(",")]
        if not header_seen:
            if [c.lower() for c in cols] != HEADER.split(","):
                raise ValueError(f"line {lineno}: expected the header {HEADER!r}")
            header_seen = True
            continue
        if len(cols) != 2:
            raise ValueError(f"line {lineno}: expected 2 columns (symbol,board)")
        symbol, board = cols[0].upper(), cols[1].upper()
        if not _SYMBOL_RE.match(symbol):
            raise ValueError(f"line {lineno}: invalid symbol {symbol!r}")
        if board not in config.BOARDS:
            raise ValueError(f"line {lineno}: unknown board {board!r} for {symbol}")
        if symbol in mapping:
            raise ValueError(f"line {lineno}: duplicate symbol {symbol}")
        mapping[symbol] = board
    if not header_seen:
        raise ValueError(f"missing header {HEADER!r}")
    return mapping
