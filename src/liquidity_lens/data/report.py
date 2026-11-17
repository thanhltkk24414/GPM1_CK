from __future__ import annotations

import sqlite3
import statistics
from collections import Counter, defaultdict, deque
from datetime import date, datetime, time
from typing import Sequence

from liquidity_lens import config
from liquidity_lens.analytics.sessions import BoardFlagTimeline, fallback_phase
from liquidity_lens.data.symbol_board import load_symbol_board

METRICS = ("obi3", "spread_bps", "volume")


def data_quality_report(
    conn: sqlite3.Connection, trading_date: date, window: int = 30, min_periods: int = 15
) -> dict:
    """Data quality summary for one trading day.

    - snapshots_by_session_flag: book_snapshot counts per STORED session flag column (None = unknown). That column holds
      the HOSE flag for every symbol, so it is wrong for HNX/UPCOM symbols: use by_board for the effective flags.
    - parse_errors: number of PARSE_ERROR rows in collector_events.
    - unknown_frames: number of UNKNOWN_FRAME events (frames the collector could not map).
    - excluded_opening_trades: {symbol: {trades, volume}} of trades inside config.OPENING_MATCH_WINDOW, kept in trade_tick
      but left out of minute-bar volume.
    - snapshots_without_ref: snapshots of symbols that have no market_ref for the day (OUT_OF_BAND is skipped for them).
    - zero_std_ratio: {symbol: {metric: share of evaluated z-score windows with std == 0}}, rebuilt
      from metrics_1m with the same rule as rolling_zscore (prior non-None values, same symbol and
      AM/PM group). Metrics with no evaluated window are omitted.
    Only when the symbol_board table has rows (see _board_statistics):
    - symbols_in_symbol_board, by_board, snapshots_unmapped.
    Only when the day has collector start/connect events:
    - connection_gaps: see connection_gaps().
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
    mapping = load_symbol_board(conn)
    if mapping:  # the opening auction (and its exclusion from volume) exists on HOSE only
        excluded = {s: v for s, v in excluded.items() if mapping.get(s) == "HOSE"}
    report = {
        "snapshots_by_session_flag": by_flag, "parse_errors": parse_errors, "zero_std_ratio": ratio,
        "snapshots_without_ref": without_ref, "excluded_opening_trades": excluded,
        "unknown_frames": unknown_frames,
    }
    report.update(_board_statistics(conn, trading_date))
    if _has_run_events(conn, day):
        report["connection_gaps"] = connection_gaps(conn, trading_date)
    return report


def _board_statistics(conn: sqlite3.Connection, trading_date: date) -> dict:
    """Per-board numbers. The session flag of a snapshot is the one of the symbol's OWN board at that time, read from the
    session_flag table; when the board has no flag yet that day the fallback schedule is used (counted separately).
    Empty (keys absent) for a database without a symbol_board mapping."""
    mapping = load_symbol_board(conn)
    if not mapping:
        return {}
    timeline = BoardFlagTimeline.load(conn, trading_date)
    expected = Counter(mapping.values())
    stats = {
        board: {"expected_symbols": n, "symbols_with_snapshots": 0, "snapshots": 0,
                "snapshots_by_effective_flag": Counter(), "snapshots_from_fallback": 0}
        for board, n in expected.items()
    }
    seen: dict[str, set[str]] = defaultdict(set)
    unmapped_n, unmapped_symbols = 0, set()
    for r in conn.execute("SELECT symbol, ts FROM book_snapshot WHERE ts LIKE ?", (trading_date.isoformat() + "%",)):
        symbol, ts = r[0], r[1]
        board = mapping.get(symbol)
        if board is None:
            unmapped_n += 1
            unmapped_symbols.add(symbol)
            continue
        flag = timeline.flag_at(board, ts)
        if flag is None:
            flag = fallback_phase(board, time.fromisoformat(ts[11:19]))
            stats[board]["snapshots_from_fallback"] += 1
        stats[board]["snapshots"] += 1
        stats[board]["snapshots_by_effective_flag"][flag] += 1
        seen[board].add(symbol)
    for board, s in stats.items():
        s["symbols_with_snapshots"] = len(seen[board])
        s["snapshots_by_effective_flag"] = dict(s["snapshots_by_effective_flag"])
    return {
        "symbols_in_symbol_board": len(mapping),
        "by_board": stats,
        "snapshots_unmapped": {"snapshots": unmapped_n, "symbols": len(unmapped_symbols)},
    }


_RUN_EVENTS = ("COLLECTOR_START", "CONNECT", "DISCONNECT", "CONNECT_FAILED", "SESSION_SUMMARY", "STOPPED")


def _has_run_events(conn: sqlite3.Connection, day_like: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM collector_events WHERE ts LIKE ? AND event IN ('COLLECTOR_START', 'CONNECT') LIMIT 1", (day_like,)
    ).fetchone() is not None


def _seconds(start: str, end: str | None) -> int | None:
    if end is None:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def _last_data_ts(conn: sqlite3.Connection, before: str) -> str | None:
    row = conn.execute("SELECT MAX(received_at) FROM raw_message WHERE received_at < ?", (before,)).fetchone()
    return row[0] if row else None


def connection_gaps(conn: sqlite3.Connection, trading_date: date) -> list[dict]:
    """Periods without a WebSocket connection, rebuilt from collector_events of that day.

    A connected period starts at CONNECT and ends at DISCONNECT, SESSION_SUMMARY/STOPPED (the collector was stopped) or a
    COLLECTOR_START of a new run that found the previous run still "connected" (it was killed without a summary; the gap
    then starts at the last sign of life, flagged start_is_estimate). Each gap is
    {start, end, seconds, cause, failed_attempts, last_error, start_is_estimate}; `last_error` is only the exception CLASS of the last
    CONNECT_FAILED, never its message. A gap still open at the end of the data has end = None, except a collector
    stop (SESSION_SUMMARY/STOPPED) with no later run, which is the normal end of the day and is not listed.
    """
    rows = conn.execute(
        f"SELECT ts, event, detail FROM collector_events WHERE ts LIKE ? AND event IN ({','.join('?' * len(_RUN_EVENTS))}) "
        "ORDER BY id", (trading_date.isoformat() + "%", *_RUN_EVENTS),
    ).fetchall()
    gaps: list[dict] = []
    gap: dict | None = None
    connected = False
    previous_ts: str | None = None
    last_connect: str | None = None

    def open_gap(start: str, cause: str, estimate: bool = False) -> dict:
        return {"start": start, "end": None, "seconds": None, "cause": cause, "failed_attempts": 0, "last_error": None,
                "start_is_estimate": estimate}

    for ts, event, detail in rows:
        if event == "COLLECTOR_START":
            if connected:  # the previous run never wrote a SESSION_SUMMARY
                # Real stop time unknown: use the last sign of life, the later of the last raw message and the last CONNECT
                # (a lunch break has no data although the connection is fine, so the last message alone would be too early).
                signs = [x for x in (_last_data_ts(conn, ts), last_connect) if x]
                gap = open_gap(max(signs) if signs else (previous_ts or ts), "restart_without_summary", estimate=True)
                connected = False
        elif event == "CONNECT":
            last_connect = ts
            if gap is not None:
                gap["end"], gap["seconds"] = ts, _seconds(gap["start"], ts)
                gaps.append(gap)
                gap = None
            connected = True
        elif event == "DISCONNECT" and connected:
            gap, connected = open_gap(ts, "disconnect"), False
        elif event in ("SESSION_SUMMARY", "STOPPED") and connected:
            gap, connected = open_gap(ts, "collector_stopped"), False
        elif event == "CONNECT_FAILED" and gap is not None:
            gap["failed_attempts"] += 1
            gap["last_error"] = (detail or "").split(":", 1)[0].strip() or None
        previous_ts = ts
    if gap is not None and gap["cause"] != "collector_stopped":
        gaps.append(gap)  # still disconnected at the end of the data; a normal stop at the end is not a gap
    return gaps


def _table(headers: list[str], rows: list[list[str]], indent: str = "  ") -> list[str]:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)] if rows else [len(h) for h in headers]
    fmt = indent + "  ".join(f"{{:<{w}}}" for w in widths)
    return [fmt.format(*headers).rstrip(), *(fmt.format(*[str(x) for x in r]).rstrip() for r in rows)]


def _flags_text(flags: dict) -> str:
    items = sorted(flags.items(), key=lambda kv: (kv[0] is None, str(kv[0])))
    return ", ".join(f"{'(none)' if f is None else f}: {n}" for f, n in items) or "-"


def format_report(
    trading_date: date, bars: int, alerts: int, report: dict, symbols: Sequence[str] | None = None
) -> str:
    """Plain-text tables for the output of materialize_metrics and data_quality_report."""
    keep = (lambda sym: True) if not symbols else (lambda sym: sym in {x.upper() for x in symbols})
    start, end = config.OPENING_MATCH_WINDOW
    lines = [f"Liquidity Lens, materialize {trading_date.isoformat()}", f"minute bars: {bars}   alerts: {alerts}", ""]

    if "by_board" in report:
        lines.append(f"By board (symbol_board has {report['symbols_in_symbol_board']} symbols; flag = the symbol's own "
                     "board flag from session_flag, fallback schedule when none yet)")
        rows = []
        for board in config.BOARDS:
            if board not in report["by_board"]:
                continue
            b = report["by_board"][board]
            rows.append([board, b["expected_symbols"], b["symbols_with_snapshots"], b["snapshots"],
                         b["snapshots_from_fallback"], _flags_text(b["snapshots_by_effective_flag"])])
        lines += _table(["board", "expected", "with snapshots", "snapshots", "from fallback", "snapshots by effective flag"], rows)
        u = report["snapshots_unmapped"]
        lines.append(f"Symbols not in symbol_board: {u['snapshots']} snapshot(s) of {u['symbols']} symbol(s)")
    else:
        lines.append("NOTE: symbol_board is empty or missing: every symbol is treated as HOSE. "
                     "Run scripts/load_symbol_board.py to load the boards.")
    lines.append("")

    lines.append("Snapshots by STORED session flag column (the collector writes the HOSE flag for every symbol: "
                 "not valid for HNX/UPCOM)")
    flags = sorted(report["snapshots_by_session_flag"].items(), key=lambda kv: (kv[0] is None, str(kv[0])))
    lines += _table(["flag", "snapshots"], [["(none)" if f is None else f, n] for f, n in flags])
    lines.append(f"Snapshots without market_ref: {report['snapshots_without_ref']}")
    lines.append("")

    if "connection_gaps" in report:
        gaps = report["connection_gaps"]
        lines.append(f"Connection gaps (from collector_events): {len(gaps)} gap(s)")
        rows = [[("~" if g["start_is_estimate"] else "") + g["start"][11:19], g["end"][11:19] if g["end"] else "still open",
                 "-" if g["seconds"] is None else g["seconds"], g["cause"], g["failed_attempts"], g["last_error"] or "-"]
                for g in gaps]
        lines += _table(["start", "end", "seconds", "cause", "failed attempts", "last error"], rows) if rows else ["  none"]
        lines.append("")

    lines.append("Collector events")
    lines.append(f"  PARSE_ERROR: {report['parse_errors']}")
    lines.append(f"  UNKNOWN_FRAME: {report['unknown_frames']}")
    lines.append("")
    lines.append(f"Opening-match trades excluded from volume ({start:%H:%M:%S} to {end:%H:%M:%S}, kept in trade_tick; HOSE only)")
    rows = [[sym, v["trades"], v["volume"]] for sym, v in sorted(report["excluded_opening_trades"].items()) if keep(sym)]
    lines += _table(["symbol", "trades", "volume"], rows) if rows else ["  none"]
    lines.append("")
    lines.append("Z-score windows with zero standard deviation (share of evaluated windows)")
    items = [(sym, per) for sym, per in sorted(report["zero_std_ratio"].items()) if keep(sym)]
    limit = 30
    truncated = len(items) > limit and not symbols
    if truncated:  # a whole market is too long to read: show the most affected symbols
        items = sorted(items, key=lambda kv: (-max(kv[1].values(), default=0), kv[0]))[:limit]
    rows = [[sym] + [f"{per[m]:.2f}" if m in per else "-" for m in ("obi3", "spread_bps", "volume")] for sym, per in items]
    lines += _table(["symbol", "obi3", "spread_bps", "volume"], rows) if rows else ["  none (not enough observations yet)"]
    if truncated:
        lines.append(f"  showing the {limit} symbols with the highest share, out of {len(report['zero_std_ratio'])} symbols "
                     "(use --symbols for others)")
    return "\n".join(lines)
