from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict, deque
from datetime import date
from typing import Sequence

from liquidity_lens import config

METRICS = ("obi3", "spread_bps", "volume")


def data_quality_report(
    conn: sqlite3.Connection, trading_date: date, window: int = 30, min_periods: int = 15
) -> dict:
    """Data quality summary for one trading day.

    - snapshots_by_session_flag: book_snapshot counts per session flag (None = flag unknown).
    - parse_errors: number of PARSE_ERROR rows in collector_events.
    - unknown_frames: number of UNKNOWN_FRAME events (frames the collector could not map).
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
    unknown_frames = conn.execute(
        "SELECT COUNT(*) FROM collector_events WHERE event = 'UNKNOWN_FRAME' AND ts LIKE ?", (day,)
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
    report = {
        "snapshots_by_session_flag": by_flag, "parse_errors": parse_errors, "zero_std_ratio": ratio,
        "snapshots_without_ref": without_ref, "excluded_opening_trades": excluded,
        "unknown_frames": unknown_frames,
    }
    report.update(_board_statistics(conn, day))
    return report


def _board_statistics(conn: sqlite3.Connection, day: str) -> dict:
    """Per-board numbers from the symbol_board mapping. Empty (keys absent) for a database without a mapping."""
    try:
        expected = {r["board"]: r["n"] for r in conn.execute("SELECT board, COUNT(*) AS n FROM symbol_board GROUP BY board")}
    except sqlite3.OperationalError:  # connection to a database that predates the table
        return {}
    if not expected:
        return {}
    by_board = {
        board: {"expected_symbols": n, "symbols_with_snapshots": 0, "snapshots_by_session_flag": {}}
        for board, n in expected.items()
    }
    for r in conn.execute(
        "SELECT m.board AS board, COUNT(DISTINCT b.symbol) AS n FROM book_snapshot b "
        "JOIN symbol_board m ON m.symbol = b.symbol WHERE b.ts LIKE ? GROUP BY m.board", (day,)
    ):
        by_board[r["board"]]["symbols_with_snapshots"] = r["n"]
    for r in conn.execute(
        "SELECT m.board AS board, b.session_flag AS flag, COUNT(*) AS n FROM book_snapshot b "
        "JOIN symbol_board m ON m.symbol = b.symbol WHERE b.ts LIKE ? GROUP BY m.board, b.session_flag", (day,)
    ):
        by_board[r["board"]]["snapshots_by_session_flag"][r["flag"]] = r["n"]
    unmapped = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT symbol) AS s FROM book_snapshot b WHERE b.ts LIKE ? "
        "AND NOT EXISTS (SELECT 1 FROM symbol_board m WHERE m.symbol = b.symbol)", (day,)
    ).fetchone()
    return {"by_board": by_board, "snapshots_unmapped": {"snapshots": unmapped["n"], "symbols": unmapped["s"]}}


def _table(headers: list[str], rows: list[list[str]], indent: str = "  ") -> list[str]:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)] if rows else [len(h) for h in headers]
    fmt = indent + "  ".join(f"{{:<{w}}}" for w in widths)
    return [fmt.format(*headers).rstrip(), *(fmt.format(*[str(x) for x in r]).rstrip() for r in rows)]


def format_report(
    trading_date: date, bars: int, alerts: int, report: dict, symbols: Sequence[str] | None = None
) -> str:
    """Plain-text tables for the output of materialize_metrics and data_quality_report."""
    keep = (lambda sym: True) if not symbols else (lambda sym: sym in {x.upper() for x in symbols})
    start, end = config.OPENING_MATCH_WINDOW
    lines = [f"Liquidity Lens, materialize {trading_date.isoformat()}", f"minute bars: {bars}   alerts: {alerts}", ""]

    lines.append("Snapshots by session flag")
    flags = sorted(report["snapshots_by_session_flag"].items(), key=lambda kv: (kv[0] is None, str(kv[0])))
    lines += _table(["flag", "snapshots"], [["(none)" if f is None else f, n] for f, n in flags])
    lines.append(f"Snapshots without market_ref: {report['snapshots_without_ref']}")
    lines.append("")
    if "by_board" in report:
        lines.append("By board (symbols expected from symbol_board; snapshots by stored session flag)")
        rows = []
        for board in config.BOARDS:
            if board not in report["by_board"]:
                continue
            b = report["by_board"][board]
            flags = sorted(b["snapshots_by_session_flag"].items(), key=lambda kv: (kv[0] is None, str(kv[0])))
            rows.append([board, b["expected_symbols"], b["symbols_with_snapshots"],
                         ", ".join(f"{'(none)' if f is None else f}: {n}" for f, n in flags) or "-"])
        lines += _table(["board", "expected", "with snapshots", "snapshots by flag"], rows)
        u = report["snapshots_unmapped"]
        lines.append(f"Symbols not in symbol_board: {u['snapshots']} snapshot(s) of {u['symbols']} symbol(s)")
        lines.append("")
    lines.append("Collector events")
    lines.append(f"  PARSE_ERROR: {report['parse_errors']}")
    lines.append(f"  UNKNOWN_FRAME: {report['unknown_frames']}")
    lines.append("")
    lines.append(f"Opening-match trades excluded from volume ({start:%H:%M:%S} to {end:%H:%M:%S}, kept in trade_tick)")
    rows = [[sym, v["trades"], v["volume"]] for sym, v in sorted(report["excluded_opening_trades"].items()) if keep(sym)]
    lines += _table(["symbol", "trades", "volume"], rows) if rows else ["  none"]
    lines.append("")
    lines.append("Z-score windows with zero standard deviation (share of evaluated windows)")
    rows = [
        [sym] + [f"{per[m]:.2f}" if m in per else "-" for m in ("obi3", "spread_bps", "volume")]
        for sym, per in sorted(report["zero_std_ratio"].items()) if keep(sym)
    ]
    lines += _table(["symbol", "obi3", "spread_bps", "volume"], rows) if rows else ["  none (not enough observations yet)"]
    return "\n".join(lines)
