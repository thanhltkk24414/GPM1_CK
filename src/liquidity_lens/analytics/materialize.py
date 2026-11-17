from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from datetime import date, datetime
from typing import Callable, Sequence

from liquidity_lens import config
from liquidity_lens.analytics.alerts import METRICS, detect_alerts, score_bars
from liquidity_lens.analytics.bars import MinuteBar, to_minute_bars
from liquidity_lens.analytics.sessions import BoardFlagTimeline, fallback_phase
from liquidity_lens.data.normalize import MarketRef, TradeTick
from liquidity_lens.data.symbol_board import load_symbol_board  # noqa: F401  (also exported from here)
from liquidity_lens.finance.orderbook import BookSnapshot, Level


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(config.TZ)


def effective_flag(flag: str | None, ts: datetime, board: str | None = "HOSE") -> str | None:
    """Session flag as stored; when unknown (None), the phase of `board` at that time from the fallback schedule
    (config.CONTINUOUS_WINDOWS_BY_BOARD, config.AUCTION_WINDOWS_BY_BOARD). board=None means the board is unknown:
    no fallback, no guess. The default board is HOSE, which keeps the behaviour of databases without a mapping."""
    if flag is not None:
        return flag
    return fallback_phase(board, ts.time())


def _book_from_row(r: sqlite3.Row) -> BookSnapshot:
    def levels(side: str, n: int) -> tuple[Level, ...]:
        return tuple(Level(r[f"{side}_p{i}"], r[f"{side}_q{i}"]) for i in range(1, min(n, 3) + 1))

    return BookSnapshot(
        symbol=r["symbol"], ts=_ts(r["ts"]),
        bids=levels("bid", r["n_bids"]), asks=levels("ask", r["n_asks"]),
        received_at=_ts(r["received_at"]),
    )


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def materialize_metrics(
    conn: sqlite3.Connection,
    trading_date: date,
    symbols: Sequence[str] | None = None,
    tick_for: Callable[[str, int], int] | None = None,
    window: int = 30,
    min_periods: int = 15,
    watch: float = 2.0,
    alert: float = 3.0,
) -> tuple[int, int]:
    """Rebuild metrics_1m and alerts for one trading day from the raw tables.

    Idempotent: rows of that day (and of `symbols`, if given) are deleted and rewritten in one
    transaction. They are derived data, recomputable from book_snapshot/trade_tick.
    Returns (number of bars, number of alerts).
    """
    day = trading_date.isoformat()
    sym_clause, sym_args = "", ()
    if symbols:
        sym_clause = f" AND symbol IN ({','.join('?' * len(symbols))})"
        sym_args = tuple(symbols)

    mapping = load_symbol_board(conn)  # empty: legacy database, every symbol is treated as HOSE
    timeline = BoardFlagTimeline.load(conn, trading_date)  # flags of each board; book_snapshot.session_flag is NOT used
    books = [
        (b, effective_flag(timeline.flag_at(board, r["ts"]), b.ts, board))
        for r in conn.execute(
            f"SELECT * FROM book_snapshot WHERE ts LIKE ?{sym_clause} ORDER BY ts, rowid", (day + "%", *sym_args)
        )
        for b in (_book_from_row(r),)
        for board in (mapping.get(b.symbol) if mapping else "HOSE",)  # unknown symbol: no board, no flag, no guess
    ]
    trades = [
        TradeTick(r["symbol"], _ts(r["ts"]), r["price"], r["qty"], r["side"], r["total_vol"], _ts(r["received_at"]))
        for r in conn.execute(
            f"SELECT * FROM trade_tick WHERE ts LIKE ?{sym_clause} ORDER BY ts", (day + "%", *sym_args)
        )
    ]
    refs = {
        r["symbol"]: MarketRef(r["symbol"], r["board"], trading_date, r["ceiling"], r["floor"], r["ref"])
        for r in conn.execute(f"SELECT * FROM market_ref WHERE trading_date = ?{sym_clause}", (day, *sym_args))
    }

    bars: list[MinuteBar] = to_minute_bars(
        books, trades, refs=refs, tick_for=tick_for, symbol_board=mapping or None
    )
    scores = score_bars(bars, window=window, min_periods=min_periods)

    seen: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=window))
    metric_rows, alert_rows = [], []
    for bar, z in zip(bars, scores):
        group = (bar.symbol, bar.minute.date(), "AM" if bar.minute.hour < 12 else "PM")
        hist = seen[group]
        n_obs = len(hist)  # prior non-None obi3 observations available to this bar's window
        if bar.obi3 is not None:
            hist.append(bar.obi3)
        metric_rows.append({
            "symbol": bar.symbol, "minute": _iso(bar.minute),
            "spread_abs": bar.spread_abs, "spread_bps": bar.spread_bps, "spread_ticks": bar.spread_ticks,
            "obi1": bar.obi1, "obi3": bar.obi3,
            "depth_bid3": bar.depth_bid3, "depth_ask3": bar.depth_ask3,
            "depth_val_bid3": bar.depth_val_bid3, "depth_val_ask3": bar.depth_val_ask3,
            "volume": bar.volume,
            "z_obi3": z["obi3"], "z_spread_bps": z["spread_bps"], "z_volume": z["volume"],
            "n_obs": n_obs,
        })
        values = {m: getattr(bar, m) for m in METRICS}
        for a in detect_alerts(bar.symbol, bar.minute, values, z, watch, alert):
            alert_rows.append({
                "symbol": a.symbol, "minute": _iso(a.minute), "metric": a.metric,
                "value": a.value, "z": a.z, "severity": a.severity, "message": a.message,
            })

    def insert(table: str, rows: list[dict]) -> None:
        if rows:
            cols = list(rows[0])
            conn.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})", rows
            )

    with conn:  # one transaction: delete + rewrite, so a failure leaves the old rows intact
        conn.execute(f"DELETE FROM metrics_1m WHERE minute LIKE ?{sym_clause}", (day + "%", *sym_args))
        conn.execute(f"DELETE FROM alerts WHERE minute LIKE ?{sym_clause}", (day + "%", *sym_args))
        insert("metrics_1m", metric_rows)
        insert("alerts", alert_rows)
    return len(metric_rows), len(alert_rows)
