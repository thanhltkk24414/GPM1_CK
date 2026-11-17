"""Three-board support: symbol -> board mapping, CSV watchlist, per-board session flags and windows."""
import asyncio
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from liquidity_lens.collector.main import Collector, load_watchlist, load_watchlist_boards, resolve_watchlist
from liquidity_lens.config import TZ
from liquidity_lens.data.store import init_db
from liquidity_lens.watchlist import build_watchlist_csv, read_watchlist_csv
from tests.test_stream import FakeWS

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 11, 17)

# Symbols below are INVENTED test data (not a claim about which board a real symbol is on).
BY_BOARD = {"HOSE": ["BBB", "AAA"], "HNX": ["HHH"], "UPCOM": ["UUU"]}


# ------------------------------------------------------------------------------- CSV format
def test_build_csv_orders_by_board_then_symbol_and_has_comment_and_header():
    text = build_watchlist_csv(BY_BOARD, DAY)
    lines = text.splitlines()
    assert lines[0].startswith("#") and "4 symbols" in lines[0] and "2026-11-17" in lines[0]
    assert lines[1] == "symbol,board"
    assert lines[2:] == ["AAA,HOSE", "BBB,HOSE", "HHH,HNX", "UUU,UPCOM"]


def test_csv_round_trip_and_comments_blank_lines_are_ignored():
    text = build_watchlist_csv(BY_BOARD, DAY)
    assert read_watchlist_csv(text) == {"AAA": "HOSE", "BBB": "HOSE", "HHH": "HNX", "UUU": "UPCOM"}
    assert read_watchlist_csv("# c\n\nsymbol,board\n\naaa , hose \n") == {"AAA": "HOSE"}


def test_build_csv_stops_on_a_symbol_listed_on_two_boards():
    with pytest.raises(ValueError) as e:
        build_watchlist_csv({"HOSE": ["AAA"], "HNX": ["AAA", "HHH"]}, DAY)
    assert "AAA" in str(e.value)


@pytest.mark.parametrize("text", [
    "AAA,HOSE\n",                                   # no header
    "symbol,board\nAAA,NYSE\n",                     # unknown board
    "symbol,board\nAAA,HOSE\nAAA,HNX\n",            # duplicate symbol
    "symbol,board\nbad symbol,HOSE\n",              # bad symbol
    "symbol,board\nAAA\n",                          # missing column
])
def test_read_csv_rejects_malformed_input(text):
    with pytest.raises(ValueError):
        read_watchlist_csv(text)


def test_build_csv_rejects_unknown_board():
    with pytest.raises(ValueError):
        build_watchlist_csv({"NYSE": ["AAA"]}, DAY)


# ------------------------------------------------------------------------------- collector loaders
def test_txt_watchlist_is_treated_as_hose_and_csv_gives_the_mapping(tmp_path):
    txt = tmp_path / "w.txt"
    txt.write_text("# c\nAAA\nBBB\n", encoding="utf-8")
    assert load_watchlist_boards(txt) == {"AAA": "HOSE", "BBB": "HOSE"}
    csv = tmp_path / "w.csv"
    csv.write_text(build_watchlist_csv(BY_BOARD, DAY), encoding="utf-8")
    assert load_watchlist_boards(csv) == {"AAA": "HOSE", "BBB": "HOSE", "HHH": "HNX", "UUU": "UPCOM"}
    assert load_watchlist(csv) == ["AAA", "BBB", "HHH", "UUU"]           # same function, symbols only
    assert load_watchlist(txt) == ["AAA", "BBB"]                          # old .txt behaviour unchanged
    assert resolve_watchlist(str(csv)) == ["AAA", "BBB", "HHH", "UUU"]
    assert resolve_watchlist(None) == ["VIC", "HPG", "FPT"]


def test_repo_files_hose_hnx_upcom_have_no_symbol_on_two_boards():
    by = {b: load_watchlist(ROOT / f"{b.lower()}_all.txt") for b in ("HOSE", "HNX", "UPCOM")}
    text = build_watchlist_csv(by, DAY)                                   # raises if a symbol is on two boards
    mapping = read_watchlist_csv(text)
    assert len(mapping) == sum(len(v) for v in by.values())


# ------------------------------------------------------------------------------- symbol_board table
def test_symbol_board_table_is_created_and_existing_tables_are_left_alone(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)                                           # a database from before this change
    old.execute("CREATE TABLE trade_tick (symbol TEXT, ts TEXT, price INTEGER, qty INTEGER, side TEXT, "
                "total_vol INTEGER, received_at TEXT)")
    old.execute("INSERT INTO trade_tick VALUES ('AAA', 't', 1, 2, 'B', 3, 'r')")
    old.commit()
    old.close()
    conn = init_db(path)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(symbol_board)")]
    assert cols == ["symbol", "board"]
    assert conn.execute("SELECT COUNT(*) FROM trade_tick").fetchone()[0] == 1   # data untouched
    init_db(path)                                                         # idempotent


def test_collector_writes_the_mapping_to_symbol_board(tmp_path):
    conn = init_db(tmp_path / "t.db")
    mapping = {"AAA": "HOSE", "HHH": "HNX", "UUU": "UPCOM"}
    c = Collector(conn, list(mapping), authorization=lambda: "Bearer x", connect=lambda url, h: FakeWS([]),
                  symbol_board=mapping, flush_interval_s=3600, now=lambda: datetime(2026, 11, 17, 9, 0, tzinfo=TZ))

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(c.run(stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 3)

    asyncio.run(go())
    rows = dict(sqlite3.connect(tmp_path / "t.db").execute("SELECT symbol, board FROM symbol_board").fetchall())
    assert rows == mapping


# ------------------------------------------------------------------------------- build script
def _script(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "build_watchlist.py"), *args],
                          capture_output=True, text=True, timeout=60)


def test_build_script_writes_the_csv(tmp_path):
    for name, syms in (("h.txt", "AAA\nBBB"), ("x.txt", "HHH"), ("u.txt", "UUU")):
        (tmp_path / name).write_text("# c\n" + syms + "\n", encoding="utf-8")
    out = tmp_path / "all.csv"
    r = _script("--hose", str(tmp_path / "h.txt"), "--hnx", str(tmp_path / "x.txt"),
                "--upcom", str(tmp_path / "u.txt"), "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert read_watchlist_csv(out.read_text(encoding="utf-8")) == {
        "AAA": "HOSE", "BBB": "HOSE", "HHH": "HNX", "UUU": "UPCOM"}
    assert "4 symbols" in r.stdout


def test_build_script_stops_and_writes_nothing_on_a_symbol_in_two_files(tmp_path):
    (tmp_path / "h.txt").write_text("AAA\n", encoding="utf-8")
    (tmp_path / "x.txt").write_text("AAA\nHHH\n", encoding="utf-8")
    (tmp_path / "u.txt").write_text("UUU\n", encoding="utf-8")
    out = tmp_path / "all.csv"
    r = _script("--hose", str(tmp_path / "h.txt"), "--hnx", str(tmp_path / "x.txt"),
                "--upcom", str(tmp_path / "u.txt"), "--out", str(out))
    assert r.returncode == 3 and "AAA" in r.stdout + r.stderr and not out.exists()


# ------------------------------------------------------------------------------- per-board session flag
def _quote(symbol, ts="2026/11/17 09:30:00"):
    # DOC SAMPLE structure (docs/ssi/05) with the symbol replaced; prices in dong.
    return {"s": symbol, "t": ts, "bids": [["20850", "100"], ["20800", "200"], ["20750", "300"]],
            "asks": [["20950", "100"], ["21000", "200"], ["21050", "300"]]}


def _flag(board, flag, ts="2026/11/17 09:15:00"):
    return {"b": board, "t": ts, "f": flag}


RECV = datetime(2026, 11, 17, 9, 30, 0, 500000, tzinfo=TZ)
MAPPING = {"AAA": "HOSE", "HHH": "HNX", "UUU": "UPCOM"}


def _flags_of(conn):
    return {r["symbol"]: r["session_flag"] for r in conn.execute("SELECT symbol, session_flag FROM book_snapshot")}


def test_each_symbol_gets_the_flag_of_its_own_board(tmp_path):
    from liquidity_lens.collector.pipeline import Pipeline

    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn, today=DAY, symbol_board=MAPPING)
    p.handle("market_flag", _flag("HOSE", "LO"), RECV)
    p.handle("market_flag", _flag("HNX", "BREAK"), RECV)
    p.handle("market_flag", _flag("UPCOM", "LO"), RECV)
    for s in MAPPING:
        p.handle("quote", _quote(s), RECV)
    assert _flags_of(conn) == {"AAA": "LO", "HHH": "BREAK", "UUU": "LO"}


def test_symbol_missing_from_the_mapping_keeps_flag_none_not_the_default_board(tmp_path):
    from liquidity_lens.collector.pipeline import Pipeline

    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn, today=DAY, symbol_board=MAPPING)
    p.handle("market_flag", _flag("HOSE", "LO"), RECV)
    p.handle("quote", _quote("ZZZ"), RECV)                  # not in the mapping: no guess, even though HOSE has a flag
    assert _flags_of(conn) == {"ZZZ": None}


def test_without_a_mapping_the_old_default_board_behaviour_is_unchanged(tmp_path):
    from liquidity_lens.collector.pipeline import Pipeline

    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn, today=DAY)
    p.handle("market_flag", _flag("HOSE", "LO"), RECV)
    p.handle("quote", _quote("ZZZ"), RECV)
    assert _flags_of(conn) == {"ZZZ": "LO"}


def test_flags_of_every_board_survive_a_restart(tmp_path):
    from liquidity_lens.collector.pipeline import Pipeline

    path = tmp_path / "t.db"
    first = Pipeline(init_db(path), today=DAY, symbol_board=MAPPING)
    first.handle("market_flag", _flag("HNX", "ATC", "2026/11/17 14:30:00"), RECV)
    first.handle("market_flag", _flag("UPCOM", "LO", "2026/11/17 09:00:00"), RECV)
    conn2 = init_db(path)
    second = Pipeline(conn2, today=DAY, symbol_board=MAPPING)
    second.handle("quote", _quote("HHH"), RECV)
    second.handle("quote", _quote("UUU"), RECV)
    assert _flags_of(conn2) == {"HHH": "ATC", "UUU": "LO"}


def test_collector_hands_its_mapping_to_the_pipeline(tmp_path):
    conn = init_db(tmp_path / "t.db")
    frames = [json.dumps({"channel": "DATA", "topic": "market.FLAG", "data": _flag("HNX", "LO", "2026/11/17 09:00:00")}),
              json.dumps({"channel": "DATA", "topic": "quote.HHH", "data": _quote("HHH")})]
    c = Collector(conn, list(MAPPING), authorization=lambda: "Bearer x", connect=lambda url, h: FakeWS(frames),
                  symbol_board=MAPPING, flush_interval_s=3600, now=lambda: datetime(2026, 11, 17, 9, 30, tzinfo=TZ))

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(c.run(stop))
        for _ in range(300):
            if c.router.counts["quote"] == 1:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, 3)

    asyncio.run(go())
    check = sqlite3.connect(tmp_path / "t.db")
    check.row_factory = sqlite3.Row
    assert _flags_of(check) == {"HHH": "LO"}
