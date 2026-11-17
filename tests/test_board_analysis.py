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
