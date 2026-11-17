from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict, deque
from datetime import date

from liquidity_lens import config

METRICS = ("obi3", "spread_bps", "volume")


def data_quality_report(
    conn: sqlite3.Connection, trading_date: date, window: int = 30, min_periods: int = 15
) -> dict:
    """Data quality summary for one trading day.

    - snapshots_by_session_flag: book_snapshot counts per session flag (None = flag unknown).
    - parse_errors: number of PARSE_ERROR rows in collector_events.
    - excluded_opening_trades: {symbol: {trades, volume}} of trades inside config.OPENING_MATCH_WINDOW, kept in trade_tick
      but left out of minute-bar volume.
    - snapshots_without_ref: snapshots of symbols that have no market_ref for the day (OUT_OF_BAND is skipped for them).
    - zero_std_ratio: {symbol: {metric: share of evaluated z-score windows with std == 0}}, rebuilt
      from metrics_1m with the same rule as rolling_zscore (prior non-None values, same symbol and
      AM/PM group). Metrics with no evaluated window are omitted.
    """
    day = trading_date.isoformat() + "%"
    by_flag = {
        r["session_flag"]: r["n"]
        for r in conn.execute(
            "SELECT session_flag, COUNT(*) AS n FROM book_snapshot WHERE ts LIKE ? GROUP BY session_flag", (day,)
        )
    }
    parse_errors = conn.execute(
        "SELECT COUNT(*) FROM collector_events WHERE event = 'PARSE_ERROR' AND ts LIKE ?", (day,)
    ).fetchone()[0]

    evaluated: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    zero: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    history: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=window))
    rows = conn.execute("SELECT * FROM metrics_1m WHERE minute LIKE ? ORDER BY symbol, minute", (day,))
    for r in rows:
        hour = int(r["minute"][11:13])
        for m in METRICS:
            hist = history[(r["symbol"], m, "AM" if hour < 12 else "PM")]
            x = r[m]
            if x is not None and len(hist) >= max(min_periods, 2):
                evaluated[r["symbol"]][m] += 1
                if statistics.stdev(hist) == 0:
                    zero[r["symbol"]][m] += 1
            if x is not None:
                hist.append(x)

    ratio = {
        sym: {m: zero[sym][m] / n for m, n in per.items() if n}
        for sym, per in evaluated.items()
    }
    without_ref = conn.execute(
        "SELECT COUNT(*) FROM book_snapshot b WHERE b.ts LIKE ? AND NOT EXISTS "
        "(SELECT 1 FROM market_ref m WHERE m.symbol = b.symbol AND m.trading_date = ?)",
        (day, trading_date.isoformat()),
    ).fetchone()[0]
    start, end = config.OPENING_MATCH_WINDOW
    excluded = {
        r["symbol"]: {"trades": r["n"], "volume": r["q"]}
        for r in conn.execute(
            "SELECT symbol, COUNT(*) AS n, SUM(qty) AS q FROM trade_tick WHERE ts LIKE ? "
            "AND substr(ts, 12, 8) >= ? AND substr(ts, 12, 8) < ? GROUP BY symbol",
            (day, start.strftime("%H:%M:%S"), end.strftime("%H:%M:%S")),
        )
    }
    return {
        "snapshots_by_session_flag": by_flag, "parse_errors": parse_errors, "zero_std_ratio": ratio,
        "snapshots_without_ref": without_ref, "excluded_opening_trades": excluded,
    }
