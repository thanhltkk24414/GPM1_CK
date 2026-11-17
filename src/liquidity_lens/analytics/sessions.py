"""Session flag of a board at a given time, rebuilt from the `session_flag` table.

The collector stamps book_snapshot.session_flag with the HOSE flag for every symbol, which is wrong for HNX and UPCOM
symbols. The analysis layer therefore ignores that column and looks up the flag of the symbol's OWN board here.
"""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import date, time
from typing import Iterable

from liquidity_lens import config


class BoardFlagTimeline:
    """Flag changes per board for one trading day. Timestamps are the ISO-8601 strings stored by the collector
    (fixed '+07:00' offset and millisecond precision), so plain string comparison orders them correctly."""

    def __init__(self, rows: Iterable[tuple[str, str, str]]) -> None:
        by_board: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for board, ts, flag in rows:
            by_board[board].append((ts, flag))
        self._ts: dict[str, list[str]] = {}
        self._flag: dict[str, list[str]] = {}
        for board, items in by_board.items():
            items.sort(key=lambda x: x[0])  # stable: rows with the same ts keep their order, the last one wins
            self._ts[board] = [t for t, _ in items]
            self._flag[board] = [f for _, f in items]

    @classmethod
    def load(cls, conn: sqlite3.Connection, trading_date: date) -> "BoardFlagTimeline":
        """Rows of that day only: a flag from an earlier day says nothing about today."""
        cur = conn.execute(
            "SELECT board, ts, flag FROM session_flag WHERE ts LIKE ? ORDER BY ts, rowid", (trading_date.isoformat() + "%",)
        )
        return cls((r[0], r[1], r[2]) for r in cur)

    def flag_at(self, board: str | None, ts_iso: str) -> str | None:
        """The last flag of `board` at or before `ts_iso`; None before the board's first flag of the day or for an
        unknown board (the caller then uses the fallback schedule, or nothing)."""
        if board is None or board not in self._ts:
            return None
        i = bisect_right(self._ts[board], ts_iso) - 1
        return self._flag[board][i] if i >= 0 else None


def fallback_phase(board: str | None, t: time) -> str | None:
    """Phase of `board` at local time `t` from the fallback schedule (config.CONTINUOUS_WINDOWS_BY_BOARD and
    config.AUCTION_WINDOWS_BY_BOARD): the continuous flag name, an auction name (ATO, ATC, PLO), or None. An unknown board
    (None) gets nothing: no guess."""
    if board is None:
        return None
    if any(start <= t < end for start, end in config.CONTINUOUS_WINDOWS_BY_BOARD.get(board, ())):
        return min(config.CONTINUOUS_FLAGS)
    for phase, windows in config.AUCTION_WINDOWS_BY_BOARD.get(board, {}).items():
        if any(start <= t < end for start, end in windows):
            return phase
    return None
