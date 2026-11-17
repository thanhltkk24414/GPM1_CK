"""symbol -> board mapping stored in the analysis table `symbol_board`.

The collector never writes this table: it is loaded by scripts/load_symbol_board.py and read by the analysis layer
(materialize, data quality report). It is added with CREATE TABLE IF NOT EXISTS, so existing tables are never altered.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Mapping, Sequence

from liquidity_lens import config

DDL = "CREATE TABLE IF NOT EXISTS symbol_board (symbol TEXT PRIMARY KEY, board TEXT NOT NULL)"
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(DDL)
    conn.commit()


def load_symbol_board(conn: sqlite3.Connection) -> dict[str, str]:
    """{symbol: board}; empty when the table does not exist yet (a database from before the mapping)."""
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT symbol, board FROM symbol_board")}
    except sqlite3.OperationalError:
        return {}


def save_symbol_board(conn: sqlite3.Connection, mapping: Mapping[str, str]) -> int:
    """Insert or update the given symbols (nothing is deleted). Returns the number of rows written."""
    ensure_table(conn)
    rows = sorted(mapping.items())
    with conn:
        conn.executemany("INSERT OR REPLACE INTO symbol_board (symbol, board) VALUES (?, ?)", rows)
    return len(rows)


def build_mapping(by_board: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """{symbol: board} from per-board symbol lists. Raises ValueError, without choosing, for an unknown board, a bad
    symbol, or a symbol listed on more than one board."""
    unknown = [b for b in by_board if b not in config.BOARDS]
    if unknown:
        raise ValueError(f"unknown board(s) {unknown}; expected {list(config.BOARDS)}")
    mapping: dict[str, str] = {}
    twice: dict[str, list[str]] = {}
    for board in config.BOARDS:
        for sym in by_board.get(board, ()):
            if not _SYMBOL_RE.match(sym):
                raise ValueError(f"invalid symbol {sym!r} on {board}")
            if sym in mapping and mapping[sym] != board:
                twice.setdefault(sym, [mapping[sym]]).append(board)
            mapping.setdefault(sym, board)
    if twice:
        raise ValueError("symbol(s) listed on more than one board: "
                         + ", ".join(f"{s} ({'/'.join(b)})" for s, b in sorted(twice.items())))
    return mapping
