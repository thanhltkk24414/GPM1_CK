import sqlite3

import pytest

from liquidity_lens.data.store import init_db, insert_many

EXPECTED = {
    "raw_message", "market_ref", "session_flag", "trade_tick",
    "book_snapshot", "metrics_1m", "alerts", "collector_events",
}


def test_tables_exist(tmp_path):
    conn = init_db(tmp_path / "t.db")
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED <= names


def test_wal_enabled(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_insert_many_and_second_connection_reads(tmp_path):
    path = tmp_path / "t.db"
    conn = init_db(path)
    rows = [
        {"symbol": "SSI", "ts": f"2026-07-29T09:15:{i % 60:02d}+07:00", "price": 45500, "qty": i + 1,
         "side": "B", "total_vol": i, "received_at": "2026-07-29T09:15:00.000+07:00"}
        for i in range(1000)
    ]
    assert insert_many(conn, "trade_tick", rows) == 1000
    other = sqlite3.connect(path)
    assert other.execute("SELECT COUNT(*) FROM trade_tick").fetchone()[0] == 1000


def test_unknown_table_rejected(tmp_path):
    conn = init_db(tmp_path / "t.db")
    with pytest.raises(ValueError):
        insert_many(conn, "nope; DROP TABLE alerts", [{"a": 1}])
