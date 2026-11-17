from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Callable, Literal

from liquidity_lens import config
from liquidity_lens.data.normalize import (
    MarketRef,
    parse_market_ref,
    parse_quote,
    parse_session_flag,
    parse_trade,
)
from liquidity_lens.data.quality import quality_flags
from liquidity_lens.data.store import insert_many
from liquidity_lens.finance.orderbook import BookSnapshot

Kind = Literal["quote", "trade", "market_ref", "market_flag"]


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="milliseconds")


def _signature(book: BookSnapshot) -> tuple:
    return (book.bids, book.asks)


class Pipeline:
    """Raw message -> normalized rows in SQLite. Pure orchestration, no network."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        tick_for: Callable[[str, int], int] | None = None,
        today: date | None = None,
        batch: bool = False,
        commit_every: int = 200,
    ) -> None:
        """batch=True defers commits: the caller (collector) calls flush() on a timer, and handle() also commits
        every `commit_every` messages. batch=False commits every write (default; what the tests rely on)."""
        self.conn = conn
        self.batch, self.commit_every = batch, commit_every
        self._messages_since_commit = 0
        self.tick_for = tick_for
        self._refs: dict[str, MarketRef] = {}
        self._board_flag: dict[str, str] = {}
        self._last_sig: dict[str, tuple] = {}
        self._restore_state(today or datetime.now(config.TZ).date())

    def _restore_state(self, today: date) -> None:
        """Reload today's market_ref (if any) and each board's latest session flag (Asia/Ho_Chi_Minh date).

        Session flags are only sent when they change, so they must survive a restart even without market_ref.

        Data from earlier days is never restored: yesterday's price band or session flag must not
        be applied to today's snapshots.
        """
        day = today.isoformat()
        for r in self.conn.execute(
            "SELECT symbol, board, ceiling, floor, ref FROM market_ref WHERE trading_date = ?", (day,)
        ):
            self._refs[r["symbol"]] = MarketRef(r["symbol"], r["board"], today, r["ceiling"], r["floor"], r["ref"])
        for r in self.conn.execute(
            "SELECT board, flag FROM session_flag WHERE ts >= ? ORDER BY ts, rowid", (day,)
        ):
            self._board_flag[r["board"]] = r["flag"]  # later rows overwrite earlier ones

    def _insert(self, table: str, rows: list[dict]) -> None:
        insert_many(self.conn, table, rows, commit=not self.batch)

    def flush(self) -> None:
        """Commit pending batched writes (no-op when nothing is pending)."""
        self.conn.commit()
        self._messages_since_commit = 0

    def log_event(self, event: str, detail: str | None = None, ts: datetime | None = None) -> None:
        """Write one row to collector_events (timestamp defaults to now, Asia/Ho_Chi_Minh)."""
        self._insert(
            "collector_events",
            [{"ts": _iso(ts or datetime.now(config.TZ)), "event": event, "detail": detail}],
        )

    def handle(self, kind: Kind, payload: dict, received_at: datetime) -> None:
        try:
            self._handle(kind, payload, received_at)
        finally:
            if self.batch:
                self._messages_since_commit += 1
                if self._messages_since_commit >= self.commit_every:
                    self.flush()

    def _handle(self, kind: Kind, payload: dict, received_at: datetime) -> None:
        self._insert(
            "raw_message",
            [{"received_at": _iso(received_at), "kind": kind, "payload": json.dumps(payload, ensure_ascii=False)}],
        )
        handlers = {
            "quote": self._quote,
            "trade": self._trade,
            "market_ref": lambda payload, _received_at: self._market_ref(payload),
            "market_flag": lambda payload, _received_at: self._market_flag(payload),
        }
        if kind not in handlers:
            raise ValueError(f"unknown kind: {kind!r}")
        try:
            handlers[kind](payload, received_at)
        except Exception as exc:  # malformed message: log and keep the collector alive
            self._insert(
                "collector_events",
                [{
                    "ts": _iso(received_at),
                    "event": "PARSE_ERROR",
                    "detail": json.dumps({"kind": kind, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
                }],
            )

    def _quote(self, payload: dict, received_at: datetime) -> None:
        book = parse_quote(payload, received_at)
        sig = _signature(book)
        if self._last_sig.get(book.symbol) == sig:
            return  # identical to the previous snapshot of this symbol
        self._last_sig[book.symbol] = sig

        ref = self._refs.get(book.symbol)
        first = (book.bids or book.asks or (None,))[0]
        tick = self.tick_for(book.symbol, first.price) if self.tick_for and first else None
        flags = quality_flags(book, ref=ref, tick=tick)
        board = ref.board if ref else config.DEFAULT_BOARD  # no market_ref on the real feed: HOSE watchlist
        session_flag = self._board_flag.get(board)

        row: dict = {
            "symbol": book.symbol,
            "ts": _iso(book.ts),
            "received_at": _iso(received_at),
            "n_bids": len(book.bids),
            "n_asks": len(book.asks),
            "session_flag": session_flag,
            "flags": ",".join(sorted(flags)),
        }
        for i in range(3):
            bid = book.bids[i] if i < len(book.bids) else None
            ask = book.asks[i] if i < len(book.asks) else None
            row[f"bid_p{i + 1}"] = bid.price if bid else None
            row[f"bid_q{i + 1}"] = bid.qty if bid else None
            row[f"ask_p{i + 1}"] = ask.price if ask else None
            row[f"ask_q{i + 1}"] = ask.qty if ask else None
        self._insert("book_snapshot", [row])

    def _trade(self, payload: dict, received_at: datetime) -> None:
        t = parse_trade(payload, received_at)
        self._insert(
            "trade_tick",
            [{
                "symbol": t.symbol, "ts": _iso(t.ts), "price": t.price, "qty": t.qty,
                "side": t.side, "total_vol": t.total_vol, "received_at": _iso(t.received_at),
            }],
        )

    def _market_ref(self, payload: dict) -> None:
        r = parse_market_ref(payload)
        self._refs[r.symbol] = r
        # market_ref has a (trading_date, symbol) primary key; a repeated message replaces the row.
        self.conn.execute(
            "INSERT OR REPLACE INTO market_ref (trading_date, symbol, board, ceiling, floor, ref) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r.trading_date.isoformat(), r.symbol, r.board, r.ceiling, r.floor, r.ref),
        )
        if not self.batch:
            self.conn.commit()

    def _market_flag(self, payload: dict) -> None:
        f = parse_session_flag(payload)
        self._board_flag[f.board] = f.flag
        self._insert("session_flag", [{"board": f.board, "ts": _iso(f.ts), "flag": f.flag}])
