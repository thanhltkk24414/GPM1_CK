from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict, deque
from datetime import date

METRICS = ("obi3", "spread_bps", "volume")


def data_quality_report(
    conn: sqlite3.Connection, trading_date: date, window: int = 30, min_periods: int = 15
) -> dict:
    """Data quality summary for one trading day.

    - snapshots_by_session_flag: book_snapshot counts per session flag (None = flag unknown).
    - parse_errors: number of PARSE_ERROR rows in collector_events.
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
    return {"snapshots_by_session_flag": by_flag, "parse_errors": parse_errors, "zero_std_ratio": ratio}
