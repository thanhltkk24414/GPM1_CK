import copy
import json
from datetime import date, datetime
from pathlib import Path

from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.collector.replay import replay_jsonl
from liquidity_lens.data.store import init_db
from tests.fixtures.ssi_doc_samples import MARKET_FLAG, MARKET_REF, QUOTE, RECEIVED, TRADE

SAMPLE = Path(__file__).parent / "fixtures" / "replay_sample.jsonl"


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_raw_always_stored_dedupe_snapshots(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    changed = copy.deepcopy(QUOTE)
    changed["bids"][0][1] = "3300"
    for payload in (QUOTE, copy.deepcopy(QUOTE), changed):
        p.handle("quote", payload, RECEIVED)
    assert _count(conn, "raw_message") == 3
    assert _count(conn, "book_snapshot") == 2


def test_session_flag_attached(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    p.handle("market_ref", MARKET_REF, RECEIVED)
    p.handle("market_flag", MARKET_FLAG, RECEIVED)
    p.handle("quote", QUOTE, RECEIVED)
    row = conn.execute("SELECT session_flag FROM book_snapshot").fetchone()
    assert row["session_flag"] == "ATO"
    assert _count(conn, "market_ref") == 1 and _count(conn, "session_flag") == 1


def test_flags_recorded(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    crossed = copy.deepcopy(QUOTE)
    crossed["bids"][0][0] = "45600"
    p.handle("quote", crossed, RECEIVED)
    row = conn.execute("SELECT flags, bid_p1, n_bids, n_asks FROM book_snapshot").fetchone()
    assert "CROSSED" in row["flags"].split(",")
    assert (row["bid_p1"], row["n_bids"], row["n_asks"]) == (45600, 5, 5)


def test_trade_stored(tmp_path):
    conn = init_db(tmp_path / "t.db")
    Pipeline(conn).handle("trade", TRADE, RECEIVED)
    row = conn.execute("SELECT price, qty, side, ts FROM trade_tick").fetchone()
    assert (row["price"], row["qty"], row["side"]) == (45500, 1000, "B")
    assert row["ts"].endswith("+07:00")


def test_replay_counts_lines(tmp_path):
    conn = init_db(tmp_path / "t.db")
    n = replay_jsonl(Pipeline(conn), SAMPLE)
    assert n == 4
    assert _count(conn, "raw_message") == 4
    assert conn.execute("SELECT session_flag FROM book_snapshot").fetchone()[0] == "ATO"
    assert json.loads(conn.execute("SELECT payload FROM raw_message").fetchone()[0])


def test_parse_error_logged_and_processing_continues(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    bad = copy.deepcopy(QUOTE)
    bad["bids"][0][0] = "abc"
    p.handle("quote", bad, RECEIVED)  # must not raise
    assert _count(conn, "raw_message") == 1
    assert _count(conn, "book_snapshot") == 0
    rows = conn.execute("SELECT event, detail FROM collector_events").fetchall()
    assert len(rows) == 1 and rows[0]["event"] == "PARSE_ERROR"
    assert "quote" in rows[0]["detail"]
    p.handle("quote", QUOTE, RECEIVED)  # later messages still processed
    assert _count(conn, "book_snapshot") == 1



def test_new_pipeline_restores_state_from_db(tmp_path):
    path = tmp_path / "t.db"
    conn = init_db(path)
    first = Pipeline(conn)
    first.handle("market_ref", MARKET_REF, RECEIVED)
    first.handle("market_flag", MARKET_FLAG, RECEIVED)
    conn2 = init_db(path)
    second = Pipeline(conn2, today=date(2026, 7, 29))
    second.handle("quote", QUOTE, RECEIVED)
    assert conn2.execute("SELECT session_flag FROM book_snapshot").fetchone()[0] == "ATO"


def test_restore_skips_data_from_previous_day(tmp_path):
    path = tmp_path / "t.db"
    conn = init_db(path)
    first = Pipeline(conn)
    first.handle("market_ref", MARKET_REF, RECEIVED)
    first.handle("market_flag", MARKET_FLAG, RECEIVED)
    second = Pipeline(init_db(path), today=date(2026, 7, 30))  # the stored data is from "yesterday"
    assert second._refs == {} and second._board_flag == {}


def test_restore_defaults_to_today_in_vn_timezone(tmp_path):
    conn = init_db(tmp_path / "t.db")
    first = Pipeline(conn)
    first.handle("market_ref", MARKET_REF, RECEIVED)  # 2026-07-29 is long past
    assert Pipeline(conn)._refs == {}


def test_session_flag_attached_without_market_ref_using_default_board(tmp_path):
    # Real feed (2026-11-17): market.<symbol> never arrives, so there is no market_ref; the flag of the default
    # board (HOSE, watchlist = HOSE symbols only) must still reach the snapshots.
    from liquidity_lens import config

    assert config.DEFAULT_BOARD == "HOSE"
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    p.handle("market_flag", dict(MARKET_FLAG, f="LO"), RECEIVED)
    p.handle("quote", QUOTE, RECEIVED)
    assert conn.execute("SELECT session_flag FROM book_snapshot").fetchone()[0] == "LO"


def test_other_board_flags_do_not_leak_into_hose_symbols(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    p.handle("market_flag", dict(MARKET_FLAG, b="HNX", f="ATC"), RECEIVED)
    p.handle("quote", QUOTE, RECEIVED)
    assert conn.execute("SELECT session_flag FROM book_snapshot").fetchone()[0] is None


def test_out_of_band_check_skipped_without_market_ref(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    wild = copy.deepcopy(QUOTE)
    wild["asks"][0][0] = "999999"          # absurd price, but there is no ceiling to compare with
    p.handle("quote", wild, RECEIVED)
    assert "OUT_OF_BAND" not in conn.execute("SELECT flags FROM book_snapshot").fetchone()[0]


def test_restore_session_flag_without_market_ref(tmp_path):
    path = tmp_path / "t.db"
    first = Pipeline(init_db(path))
    first.handle("market_flag", dict(MARKET_FLAG, t="2026/07/29 09:15:00", f="LO"), RECEIVED)
    conn2 = init_db(path)
    second = Pipeline(conn2, today=date(2026, 7, 29))
    second.handle("quote", QUOTE, RECEIVED)
    assert conn2.execute("SELECT session_flag FROM book_snapshot").fetchone()[0] == "LO"
