"""Collector: SSI WebSocket -> raw frames -> Pipeline -> SQLite, for the whole trading session.

    python -m liquidity_lens.collector.main [--symbols FILE] [--db PATH] [--duration SECONDS]

Reads SSI_API_KEY and SSI_API_SECRET from the environment. This is the ONLY process that holds a token or
opens the WebSocket (one active session per apiKey); the dashboard only reads SQLite.
Writes are batched (commit about every second or every 200 messages). Ctrl+C flushes and exits cleanly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

from liquidity_lens import config
from liquidity_lens.envfile import load_env
from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.collector.router import FrameRouter
from liquidity_lens.data.store import init_db
from liquidity_lens.ssi.auth import BASE_URL, TokenManager
from liquidity_lens.ssi.redact import mask
from liquidity_lens.ssi.stream import DEFAULT_URL, StreamClient, default_connect
from liquidity_lens.watchlist import read_watchlist_csv

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def load_watchlist_boards(path: str | Path) -> dict[str, str]:
    """{symbol: board}. A .csv file (`symbol,board`) carries the boards; a .txt file is a plain list, all HOSE."""
    if Path(path).suffix.lower() == ".csv":
        mapping = read_watchlist_csv(Path(path).read_text(encoding="utf-8-sig"))
        if not mapping:
            raise ValueError("watchlist is empty")
        return mapping
    return {sym: "HOSE" for sym in load_watchlist(path)}


def load_watchlist(path: str | Path) -> list[str]:
    """One symbol per line; '#' starts a comment. A .csv file (`symbol,board`) is read through
    load_watchlist_boards and only its symbols are returned."""
    if Path(path).suffix.lower() == ".csv":
        return list(load_watchlist_boards(path))
    out: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        sym = line.split("#", 1)[0].strip().upper()
        if not sym:
            continue
        if not _SYMBOL_RE.match(sym):
            raise ValueError(f"invalid symbol in watchlist: {sym!r}")
        if sym not in out:
            out.append(sym)
    if not out:
        raise ValueError("watchlist is empty")
    return out


def resolve_watchlist(path: str | Path | None) -> list[str]:
    """--symbols FILE when given, otherwise config.DEFAULT_WATCHLIST (VIC, HPG, FPT)."""
    return load_watchlist(path) if path else list(config.DEFAULT_WATCHLIST)


def build_topics(symbols: Sequence[str]) -> list[str]:
    # No market.<symbol>: the server never sent a frame for it (observed 2026-11-17), so it only cost topics.
    # market.flag (session flag, all boards) is subscribed once.
    return [f"{kind}.{s}" for s in symbols for kind in ("quote", "trade")] + ["market.flag"]


def prepare_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA synchronous=NORMAL")  # WAL + NORMAL: durable enough for a collector, much faster commits
    conn.execute("PRAGMA busy_timeout=5000")


def is_trading_time(now: datetime) -> bool:
    """Used only to decide whether silence deserves a warning. [Kiểm tra] windows are the HOSE fallback ones."""
    if now.weekday() >= 5:
        return False
    t = now.time()
    return any(start <= t < end for start, end in config.CONTINUOUS_WINDOWS)


class Collector:
    def __init__(
        self,
        conn: sqlite3.Connection,
        symbols: Sequence[str],
        authorization: Callable[[], str],
        *,
        url: str = DEFAULT_URL,
        connect=default_connect,
        flush_interval_s: float = 1.0,
        commit_every: int = 200,
        silence_warn_s: float = 30.0,
        now: Callable[[], datetime] | None = None,
        redact: Callable[[str], str] | None = None,
        on_auth_failure: Callable[[], None] | None = None,
        symbol_board: Mapping[str, str] | None = None,
    ) -> None:
        self.symbols = list(symbols)
        self.symbol_board = dict(symbol_board) if symbol_board is not None else None
        self._now = now or (lambda: datetime.now(config.TZ))
        self.flush_interval_s = flush_interval_s
        self.pipeline = Pipeline(conn, today=self._now().date(), batch=True, commit_every=commit_every,
                                 symbol_board=symbol_board)
        self.router = FrameRouter(self.pipeline, watchlist=self.symbols)
        self.event_counts: Counter[str] = Counter()
        self._finished = False
        self.stream = StreamClient(
            url=url, topics=build_topics(self.symbols), authorization=authorization,
            on_frame=self.router, on_event=self._event, connect=connect, now=self._now,
            silence_warn_s=silence_warn_s, should_warn=is_trading_time,
            on_auth_failure=on_auth_failure, redact=redact,
        )

    def _event(self, event: str, detail: str | None = None) -> None:
        self.event_counts[event] += 1
        self.pipeline.log_event(event, detail, self._now())

    async def _flush_loop(self, stop: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), self.flush_interval_s)
                return
            except asyncio.TimeoutError:
                try:
                    self.pipeline.flush()
                except sqlite3.Error as e:
                    self.event_counts["FLUSH_ERROR"] += 1
                    print(f"flush failed: {type(e).__name__}: {e}", file=sys.stderr)

    def _save_symbol_board(self) -> None:
        """Remember the board of each watchlist symbol (table symbol_board, added by init_db, never altered)."""
        if self.symbol_board is None:
            return
        conn = self.pipeline.conn
        conn.executemany("INSERT OR REPLACE INTO symbol_board (symbol, board) VALUES (?, ?)", sorted(self.symbol_board.items()))
        conn.commit()

    async def run(self, stop: asyncio.Event) -> None:
        self._save_symbol_board()
        self._event("COLLECTOR_START", json.dumps({"symbols": self.symbols}))
        stream_task = asyncio.create_task(self.stream.run(stop))
        flusher = asyncio.create_task(self._flush_loop(stop))
        try:
            await stream_task
        finally:  # also runs when the task is cancelled (Ctrl+C)
            stop.set()
            for t in (stream_task, flusher):
                t.cancel()
            await asyncio.gather(stream_task, flusher, return_exceptions=True)
            self.finish()

    def finish(self) -> None:
        """Write the session summary and commit everything. Safe to call more than once."""
        if self._finished:
            return
        self._finished = True
        summary = {
            "frames": dict(self.router.counts), "dropped": self.router.dropped,
            "events": dict(self.event_counts),
        }
        self.pipeline.log_event("SESSION_SUMMARY", json.dumps(summary), self._now())
        self.pipeline.flush()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Liquidity Lens collector (read-only SSI market data)")
    ap.add_argument("--symbols", help="watchlist file, one HOSE symbol per line (default: config.DEFAULT_WATCHLIST)")
    ap.add_argument("--db", default=str(config.DB_PATH), help="SQLite path (default: config.DB_PATH)")
    ap.add_argument("--duration", type=float, help="stop after this many seconds (tests/ops); default: run until Ctrl+C")
    ap.add_argument("--flush-interval", type=float, default=1.0)
    ap.add_argument("--commit-every", type=int, default=200)
    ap.add_argument("--base-url", default=BASE_URL, help="override only for local fake-server tests")
    ap.add_argument("--ws-url", default=DEFAULT_URL, help="override only for local fake-server tests")
    args = ap.parse_args(argv)

    load_env()  # project-root .env; variables already set in the shell win
    key, secret = os.environ.get("SSI_API_KEY", ""), os.environ.get("SSI_API_SECRET", "")
    missing = [n for n, v in (("SSI_API_KEY", key), ("SSI_API_SECRET", secret)) if not v]
    if missing:
        print(f"ERROR: missing environment variable(s): {', '.join(missing)} (see .env.example)", file=sys.stderr)
        return 2
    symbol_board = load_watchlist_boards(args.symbols) if args.symbols else {s: "HOSE" for s in config.DEFAULT_WATCHLIST}
    symbols = list(symbol_board)

    conn = init_db(args.db)
    prepare_connection(conn)
    manager = TokenManager(key, secret, base_url=args.base_url)
    collector = Collector(
        conn, symbols, manager.authorization, url=args.ws_url,
        flush_interval_s=args.flush_interval, commit_every=args.commit_every,
        redact=lambda s: mask(s, manager.secrets()), on_auth_failure=manager.invalidate,
        symbol_board=symbol_board,
    )

    async def amain() -> None:
        stop = asyncio.Event()
        if args.duration:
            asyncio.get_running_loop().call_later(args.duration, stop.set)
        await collector.run(stop)

    print(f"collector: {len(symbols)} symbol(s) {symbols}, db={args.db}; Ctrl+C to stop")
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    finally:
        collector.finish()
        conn.close()
    print(f"collector stopped: frames={dict(collector.router.counts)} dropped={collector.router.dropped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
