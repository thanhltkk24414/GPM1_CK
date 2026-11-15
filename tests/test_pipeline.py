import copy
import json
from datetime import datetime
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
    crossed["bids"][0][0] = "45.60"
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

