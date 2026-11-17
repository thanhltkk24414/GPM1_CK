"""Analysis layer: effective session flag from the session_flag table by board, per-board report, connection gaps."""
import sqlite3
from datetime import date, datetime

import pytest

from liquidity_lens.analytics.materialize import materialize_metrics
from liquidity_lens.analytics.sessions import BoardFlagTimeline
from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.config import TZ
from liquidity_lens.data.store import init_db
from liquidity_lens.data.symbol_board import save_symbol_board

DAY = date(2026, 11, 17)
MAPPING = {"AAA": "HOSE", "HHH": "HNX", "UUU": "UPCOM"}   # INVENTED symbols, not claims about real listings


def _iso(h, m, s=0):
    return f"2026-11-17T{h:02d}:{m:02d}:{s:02d}.000+07:00"


def _quote(symbol, ts):
    qty = str(100 + int(ts[11:13]) * 100 + int(ts[14:16]))      # differs between times: identical snapshots are de-duplicated
    return {"s": symbol, "t": ts, "bids": [["20850", qty], ["20800", "200"], ["20750", "300"]],
            "asks": [["20950", "100"], ["21000", "200"], ["21050", "300"]]}


def _flag(board, flag, ts):
    return {"b": board, "t": ts, "f": flag}


def _at(h, m, s=0):
    return datetime(2026, 11, 17, h, m, s, 500000, tzinfo=TZ)


def _db(tmp_path, mapping=MAPPING):
    """A database written by the UNCHANGED collector pipeline: it stamps every snapshot with the HOSE flag."""
    conn = init_db(tmp_path / "t.db")
    if mapping is not None:
        save_symbol_board(conn, mapping)
    return conn, Pipeline(conn, today=DAY)


def _bars(conn):
    materialize_metrics(conn, DAY, window=10, min_periods=5)
    return {(r["symbol"], r["minute"][11:16]): r["volume"] for r in conn.execute("SELECT symbol, minute, volume FROM metrics_1m")}


# ------------------------------------------------------------------------------- timeline
def test_timeline_returns_the_last_flag_at_or_before_ts_per_board():
    rows = [("HNX", _iso(11, 30), "BREAK"), ("HNX", _iso(13, 0), "LO"), ("HOSE", _iso(9, 15), "LO"),
            ("HNX", _iso(14, 45), "C"), ("HNX", _iso(14, 45), "C")]
    tl = BoardFlagTimeline(rows)
    assert tl.flag_at("HNX", _iso(11, 29, 59)) is None                       # before the first flag of that board
    assert tl.flag_at("HNX", _iso(11, 30)) == "BREAK"                        # the flag applies from its own second
    assert tl.flag_at("HNX", _iso(12, 59, 59)) == "BREAK"
    assert tl.flag_at("HNX", _iso(13, 0, 1)) == "LO"
    assert tl.flag_at("HNX", _iso(15, 0)) == "C"
    assert tl.flag_at("HOSE", _iso(11, 40)) == "LO"                          # boards are independent
    assert tl.flag_at("UPCOM", _iso(11, 40)) is None and tl.flag_at(None, _iso(11, 40)) is None


def test_timeline_loads_only_the_given_day_and_keeps_the_last_row_on_a_tie(tmp_path):
    conn, p = _db(tmp_path)
    p.handle("market_flag", _flag("HNX", "BREAK", "2026/11/16 11:30:00"), _at(11, 30))   # yesterday: must be ignored
    p.handle("market_flag", _flag("HNX", "LO", "2026/11/17 13:00:00"), _at(13, 0))
    p.handle("market_flag", _flag("HNX", "ATC", "2026/11/17 13:00:00"), _at(13, 0))        # same ts: the later row wins
    conn.commit()
    tl = BoardFlagTimeline.load(conn, DAY)
    assert tl.flag_at("HNX", _iso(12, 0)) is None
    assert tl.flag_at("HNX", _iso(13, 0, 30)) == "ATC"


# ------------------------------------------------------------------------------- materialize uses the timeline
def test_materialize_ignores_the_stored_session_flag_column_and_uses_each_boards_own_flag(tmp_path):
    conn, p = _db(tmp_path)
    p.handle("market_flag", _flag("HOSE", "LO", "2026/11/17 09:15:00"), _at(9, 15))
    p.handle("market_flag", _flag("HNX", "BREAK", "2026/11/17 11:30:00"), _at(11, 30))
    p.handle("market_flag", _flag("HNX", "LO", "2026/11/17 13:00:00"), _at(13, 0))
    for sym in ("AAA", "HHH"):
        p.handle("quote", _quote(sym, "2026/11/17 11:40:00"), _at(11, 40))
        p.handle("quote", _quote(sym, "2026/11/17 13:10:00"), _at(13, 10))
    conn.commit()
    stored = {r[0] for r in conn.execute("SELECT session_flag FROM book_snapshot WHERE symbol='HHH'")}
    assert stored == {"LO"}                       # the collector wrote the HOSE flag on an HNX symbol: this is the bug
    keys = set(_bars(conn))
    assert ("HHH", "11:40") not in keys           # HNX was in BREAK although the stored column says LO
    assert ("HHH", "13:10") in keys               # HNX flag LO from 13:00
    assert ("AAA", "11:40") in keys               # HOSE has no BREAK flag in this data: its own flag is still LO


def test_materialize_uses_the_board_fallback_schedule_before_the_first_flag(tmp_path):
    conn, p = _db(tmp_path)
    for sym in MAPPING:                            # no session flag was received at all
        p.handle("quote", _quote(sym, "2026/11/17 09:05:00"), _at(9, 5))
        p.handle("quote", _quote(sym, "2026/11/17 14:50:00"), _at(14, 50))
    keys = set(_bars(conn))
    assert ("HHH", "09:05") in keys and ("UUU", "09:05") in keys and ("AAA", "09:05") not in keys   # HOSE: ATO
    assert ("UUU", "14:50") in keys and ("HHH", "14:50") not in keys and ("AAA", "14:50") not in keys


@pytest.mark.parametrize("flag", ["BREAK", "ATC", "C"])
def test_observed_non_continuous_flags_exclude_snapshots(tmp_path, flag):
    conn, p = _db(tmp_path)
    p.handle("market_flag", _flag("HNX", flag, "2026/11/17 10:00:00"), _at(10, 0))
    p.handle("quote", _quote("HHH", "2026/11/17 10:05:00"), _at(10, 5))
    assert ("HHH", "10:05") not in _bars(conn)


def test_symbol_not_in_the_mapping_gets_no_bar_and_no_guess(tmp_path):
    conn, p = _db(tmp_path)
    p.handle("market_flag", _flag("HOSE", "LO", "2026/11/17 09:15:00"), _at(9, 15))
    p.handle("quote", _quote("ZZZ", "2026/11/17 10:00:00"), _at(10, 0))
    p.handle("quote", _quote("AAA", "2026/11/17 10:00:00"), _at(10, 0))
    keys = set(_bars(conn))
    assert ("AAA", "10:00") in keys and ("ZZZ", "10:00") not in keys


def test_database_without_a_mapping_treats_every_symbol_as_hose_like_before(tmp_path):
    conn, p = _db(tmp_path, mapping=None)
    p.handle("market_flag", _flag("HOSE", "LO", "2026/11/17 09:15:00"), _at(9, 15))
    p.handle("quote", _quote("ZZZ", "2026/11/17 10:00:00"), _at(10, 0))
    assert ("ZZZ", "10:00") in _bars(conn)


def test_opening_match_exclusion_applies_to_hose_symbols_only(tmp_path):
    conn, p = _db(tmp_path)
    for s in ("AAA", "HHH"):
        p.handle("quote", _quote(s, "2026/11/17 09:15:30"), _at(9, 15, 30))
        p.handle("trade", {"s": s, "t": "2026/11/17 09:15:00.005", "p": "20850", "q": "1000", "a": "1", "si": "B",
                           "o": "1", "h": "1", "l": "1", "v": "1000"}, _at(9, 15, 0))
        p.handle("trade", {"s": s, "t": "2026/11/17 09:15:20", "p": "20850", "q": "50", "a": "1", "si": "B",
                           "o": "1", "h": "1", "l": "1", "v": "1050"}, _at(9, 15, 20))
    p.handle("market_flag", _flag("HOSE", "LO", "2026/11/17 09:15:00"), _at(9, 15))
    vol = _bars(conn)
    assert vol[("AAA", "09:15")] == 50            # HOSE: the 09:15:00.005 opening match is left out
    assert vol[("HHH", "09:15")] == 1050          # HNX is continuous from 09:00: a normal trade


# ------------------------------------------------------------------------------- per-board report (effective flags)
def test_report_by_board_counts_effective_flags_and_fallback(tmp_path):
    from liquidity_lens.data.report import data_quality_report

    conn, p = _db(tmp_path)
    p.handle("market_flag", _flag("HOSE", "LO", "2026/11/17 09:15:00"), _at(9, 15))
    p.handle("market_flag", _flag("HNX", "BREAK", "2026/11/17 11:30:00"), _at(11, 30))
    p.handle("market_flag", _flag("HNX", "LO", "2026/11/17 13:00:00"), _at(13, 0))
    p.handle("quote", _quote("AAA", "2026/11/17 09:20:00"), _at(9, 20))
    p.handle("quote", _quote("HHH", "2026/11/17 11:40:00"), _at(11, 40))
    p.handle("quote", _quote("HHH", "2026/11/17 13:10:00"), _at(13, 10))
    p.handle("quote", _quote("UUU", "2026/11/17 09:05:00"), _at(9, 5))        # UPCOM: no flag yet, fallback schedule
    p.handle("quote", _quote("ZZZ", "2026/11/17 09:20:00"), _at(9, 20))       # not in the mapping
    conn.commit()
    rep = data_quality_report(conn, DAY)
    assert rep["by_board"]["HOSE"] == {"expected_symbols": 1, "symbols_with_snapshots": 1, "snapshots": 1,
                                       "snapshots_by_effective_flag": {"LO": 1}, "snapshots_from_fallback": 0}
    assert rep["by_board"]["HNX"] == {"expected_symbols": 1, "symbols_with_snapshots": 1, "snapshots": 2,
                                      "snapshots_by_effective_flag": {"BREAK": 1, "LO": 1}, "snapshots_from_fallback": 0}
    assert rep["by_board"]["UPCOM"] == {"expected_symbols": 1, "symbols_with_snapshots": 1, "snapshots": 1,
                                        "snapshots_by_effective_flag": {"LO": 1}, "snapshots_from_fallback": 1}
    assert rep["snapshots_unmapped"] == {"snapshots": 1, "symbols": 1}
    assert rep["symbols_in_symbol_board"] == 3
    assert "snapshots_by_session_flag" in rep                                  # the old stored-column table is still there


def test_report_keeps_the_old_shape_without_a_mapping(tmp_path):
    from liquidity_lens.data.report import data_quality_report

    conn, p = _db(tmp_path, mapping=None)
    p.handle("quote", _quote("AAA", "2026/11/17 09:20:00"), _at(9, 20))
    rep = data_quality_report(conn, DAY)
    assert "by_board" not in rep and "snapshots_unmapped" not in rep and "connection_gaps" not in rep


# ------------------------------------------------------------------------------- connection gaps
def _events(conn, rows):
    conn.executemany("INSERT INTO collector_events (ts, event, detail) VALUES (?, ?, ?)",
                     [(_iso(*t), e, d) for t, e, d in rows])
    conn.commit()


# The sequence of 2026-11-17 (rehearsal run), with the long detail strings shortened.
TODAY_EVENTS = [
    ((9, 55, 40), "COLLECTOR_START", "{}"), ((9, 55, 41), "CONNECT", "wss"),
    ((10, 40, 47), "SESSION_SUMMARY", "{}"),
    ((10, 55, 37), "COLLECTOR_START", "{}"), ((10, 55, 38), "CONNECT", "wss"),
    ((11, 49, 38), "DISCONNECT", "closed code=None reason=None"), ((11, 49, 38), "RECONNECT_WAIT", "1.0s"),
    ((11, 49, 39), "CONNECT_FAILED", "URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>"),
    ((11, 49, 42), "CONNECT_FAILED", "URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>"),
    ((11, 53, 1), "CONNECT_FAILED", "URLError: <urlopen error [Errno 11001] getaddrinfo failed>"),
    ((11, 54, 12), "CONNECT", "wss"),
    ((12, 42, 15), "COLLECTOR_START", "{}"),                      # the previous run never wrote SESSION_SUMMARY
    ((12, 42, 23), "CONNECT_FAILED", "ConnectionResetError: [WinError 64] The specified network name is no longer available"),
    ((12, 42, 25), "CONNECT", "wss"),
    ((12, 47, 12), "SESSION_SUMMARY", "{}"),
    ((12, 48, 43), "COLLECTOR_START", "{}"), ((12, 48, 46), "CONNECT", "wss"),
    ((15, 6, 19), "SESSION_SUMMARY", "{}"),
]


def test_connection_gaps_from_the_events_of_a_real_day(tmp_path):
    from liquidity_lens.data.report import connection_gaps

    conn, p = _db(tmp_path)
    p.handle("quote", _quote("AAA", "2026/11/17 12:41:30"), datetime(2026, 11, 17, 12, 41, 59, 250000, tzinfo=TZ))  # last data before the kill
    conn.commit()
    _events(conn, TODAY_EVENTS)
    gaps = connection_gaps(conn, DAY)
    assert [(g["cause"], g["start"][11:19], g["end"][11:19], g["seconds"], g["failed_attempts"]) for g in gaps] == [
        ("collector_stopped", "10:40:47", "10:55:38", 891, 0),
        ("disconnect", "11:49:38", "11:54:12", 274, 3),
        ("restart_without_summary", "12:41:59", "12:42:25", 26, 1),
        ("collector_stopped", "12:47:12", "12:48:46", 94, 0),
    ]
    assert gaps[1]["last_error"] == "URLError" and gaps[2]["last_error"] == "ConnectionResetError"
    assert gaps[0]["last_error"] is None
    assert "SSL" not in str(gaps)                                   # only the exception class, never the message


def test_a_gap_that_is_still_open_at_the_end_has_no_end(tmp_path):
    from liquidity_lens.data.report import connection_gaps

    conn, _ = _db(tmp_path)
    _events(conn, [((9, 0, 0), "COLLECTOR_START", "{}"), ((9, 0, 1), "CONNECT", "wss"),
                   ((10, 0, 0), "DISCONNECT", "closed code=1006 reason=''"), ((10, 0, 1), "CONNECT_FAILED", "OSError: x")])
    (gap,) = connection_gaps(conn, DAY)
    assert gap["cause"] == "disconnect" and gap["end"] is None and gap["seconds"] is None and gap["failed_attempts"] == 1


def test_no_gap_for_a_single_clean_run_and_events_of_other_days_are_ignored(tmp_path):
    from liquidity_lens.data.report import connection_gaps

    conn, _ = _db(tmp_path)
    _events(conn, [((9, 0, 0), "COLLECTOR_START", "{}"), ((9, 0, 1), "CONNECT", "wss"), ((15, 0, 0), "SESSION_SUMMARY", "{}")])
    conn.execute("INSERT INTO collector_events (ts, event, detail) VALUES ('2026-11-16T10:00:00.000+07:00', 'DISCONNECT', 'x')")
    conn.commit()
    assert connection_gaps(conn, DAY) == []


def test_report_includes_connection_gaps_and_prints_them(tmp_path):
    from liquidity_lens.data.report import data_quality_report, format_report

    conn, _ = _db(tmp_path)
    _events(conn, TODAY_EVENTS)
    rep = data_quality_report(conn, DAY)
    assert len(rep["connection_gaps"]) == 4
    text = format_report(DAY, 0, 0, rep)
    for needle in ("Connection gaps", "disconnect", "collector_stopped", "restart_without_summary", "11:49:38", "URLError",
                   "4 gap(s)"):
        assert needle in text, needle


def test_format_report_prints_the_board_table_with_effective_flags():
    from liquidity_lens.data.report import format_report

    report = {
        "snapshots_by_session_flag": {"LO": 2}, "snapshots_without_ref": 2, "parse_errors": 0, "unknown_frames": 0,
        "excluded_opening_trades": {}, "zero_std_ratio": {}, "symbols_in_symbol_board": 1517,
        "by_board": {"HOSE": {"expected_symbols": 410, "symbols_with_snapshots": 399, "snapshots": 1005,
                              "snapshots_by_effective_flag": {"LO": 1000, None: 5}, "snapshots_from_fallback": 7},
                     "UPCOM": {"expected_symbols": 808, "symbols_with_snapshots": 0, "snapshots": 0,
                               "snapshots_by_effective_flag": {}, "snapshots_from_fallback": 0}},
        "snapshots_unmapped": {"snapshots": 7, "symbols": 2},
    }
    text = format_report(DAY, 0, 0, report)
    for needle in ("By board", "HOSE", "410", "399", "LO: 1000", "(none): 5", "UPCOM", "808", "1005",
                   "not in symbol_board: 7 snapshot(s) of 2 symbol(s)"):
        assert needle in text, needle


def test_format_report_warns_when_symbol_board_is_empty():
    from liquidity_lens.data.report import format_report

    report = {"snapshots_by_session_flag": {}, "snapshots_without_ref": 0, "parse_errors": 0, "unknown_frames": 0,
              "excluded_opening_trades": {}, "zero_std_ratio": {}}
    assert "symbol_board is empty" in format_report(DAY, 0, 0, report)


def test_restart_gap_starts_at_the_last_sign_of_life_not_at_the_start_of_the_lunch_break(tmp_path):
    from liquidity_lens.data.report import connection_gaps

    conn, p = _db(tmp_path)
    p.handle("quote", _quote("AAA", "2026/11/17 11:30:00"), datetime(2026, 11, 17, 11, 30, 0, tzinfo=TZ))   # last data: lunch starts
    conn.commit()
    _events(conn, [((9, 0, 0), "COLLECTOR_START", "{}"), ((11, 54, 12), "CONNECT", "wss"),
                   ((12, 42, 15), "COLLECTOR_START", "{}"), ((12, 42, 25), "CONNECT", "wss")])
    (gap,) = connection_gaps(conn, DAY)
    assert gap["cause"] == "restart_without_summary"
    assert gap["start"][11:19] == "11:54:12"                # the last CONNECT is later than the last data
    assert gap["start_is_estimate"] is True and gap["seconds"] == 2893


def test_exact_gaps_are_not_marked_as_estimates(tmp_path):
    from liquidity_lens.data.report import connection_gaps

    conn, _ = _db(tmp_path)
    _events(conn, [((9, 0, 1), "CONNECT", "wss"), ((10, 0, 0), "DISCONNECT", "x"), ((10, 1, 0), "CONNECT", "wss")])
    (gap,) = connection_gaps(conn, DAY)
    assert gap["start_is_estimate"] is False and gap["seconds"] == 60


def test_zero_std_table_is_limited_to_the_30_most_affected_symbols_when_there_are_many():
    from liquidity_lens.data.report import format_report

    zero = {f"S{i:03d}": {"obi3": 0.0, "spread_bps": i / 100, "volume": 0.0} for i in range(100)}
    report = {"snapshots_by_session_flag": {}, "snapshots_without_ref": 0, "parse_errors": 0, "unknown_frames": 0,
              "excluded_opening_trades": {}, "zero_std_ratio": zero}
    text = format_report(DAY, 0, 0, report)
    tail = text.split("Z-score windows")[1]
    assert "S099" in tail and "S070" in tail and "S069" not in tail                     # the top 30 by share
    assert "showing the 30 symbols with the highest share" in tail and "100 symbols" in tail
    assert "S069" in format_report(DAY, 0, 0, report, symbols=["S069"])                 # --symbols still reaches any symbol
