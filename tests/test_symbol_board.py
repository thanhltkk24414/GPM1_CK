import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from liquidity_lens.data.symbol_board import build_mapping, ensure_table, load_symbol_board, save_symbol_board

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "load_symbol_board.py"

# Symbols are INVENTED test data, not claims about real listings.


def _legacy_db(path):
    """A database that predates the symbol_board table, with one row of data in an existing table."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trade_tick (symbol TEXT, ts TEXT, price INTEGER, qty INTEGER)")
    conn.execute("INSERT INTO trade_tick VALUES ('AAA', 't', 1, 2)")
    conn.commit()
    return conn


def test_ensure_table_only_adds_symbol_board_and_leaves_existing_data_alone(tmp_path):
    conn = _legacy_db(tmp_path / "a.db")
    ensure_table(conn)
    ensure_table(conn)                                                   # idempotent
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"trade_tick", "symbol_board"}
    assert conn.execute("SELECT COUNT(*) FROM trade_tick").fetchone()[0] == 1
    assert [r[1] for r in conn.execute("PRAGMA table_info(symbol_board)")] == ["symbol", "board"]


def test_save_and_load_round_trip_and_a_changed_board_is_replaced(tmp_path):
    conn = _legacy_db(tmp_path / "a.db")
    assert save_symbol_board(conn, {"AAA": "HOSE", "HHH": "HNX"}) == 2
    assert load_symbol_board(conn) == {"AAA": "HOSE", "HHH": "HNX"}
    save_symbol_board(conn, {"HHH": "UPCOM", "UUU": "UPCOM"})
    assert load_symbol_board(conn) == {"AAA": "HOSE", "HHH": "UPCOM", "UUU": "UPCOM"}


def test_load_returns_empty_when_the_table_does_not_exist(tmp_path):
    assert load_symbol_board(_legacy_db(tmp_path / "a.db")) == {}


def test_build_mapping_rejects_a_symbol_on_two_boards_and_unknown_boards_and_bad_symbols():
    assert build_mapping({"HOSE": ["AAA"], "HNX": ["HHH"], "UPCOM": []}) == {"AAA": "HOSE", "HHH": "HNX"}
    with pytest.raises(ValueError) as e:
        build_mapping({"HOSE": ["AAA"], "HNX": ["AAA"]})
    assert "AAA" in str(e.value)
    with pytest.raises(ValueError):
        build_mapping({"NYSE": ["AAA"]})
    with pytest.raises(ValueError):
        build_mapping({"HOSE": ["bad symbol"]})


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


def _files(tmp_path, hose="AAA\nBBB", hnx="HHH", upcom="UUU"):
    out = []
    for name, body in (("h.txt", hose), ("x.txt", hnx), ("u.txt", upcom)):
        (tmp_path / name).write_text("# comment\n" + body + "\n", encoding="utf-8")
        out.append(str(tmp_path / name))
    return ["--hose", out[0], "--hnx", out[1], "--upcom", out[2]]


def test_script_loads_the_three_files_and_touches_nothing_else(tmp_path):
    db = tmp_path / "a.db"
    _legacy_db(db).close()
    r = _run("--db", str(db), *_files(tmp_path))
    assert r.returncode == 0, r.stderr
    conn = sqlite3.connect(db)
    assert dict(conn.execute("SELECT symbol, board FROM symbol_board")) == {
        "AAA": "HOSE", "BBB": "HOSE", "HHH": "HNX", "UUU": "UPCOM"}
    assert {x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"trade_tick", "symbol_board"}
    assert conn.execute("SELECT COUNT(*) FROM trade_tick").fetchone()[0] == 1
    assert "HOSE 2" in r.stdout and "HNX 1" in r.stdout and "UPCOM 1" in r.stdout


def test_script_is_idempotent(tmp_path):
    db = tmp_path / "a.db"
    _legacy_db(db).close()
    args = ["--db", str(db), *_files(tmp_path)]
    assert _run(*args).returncode == 0 and _run(*args).returncode == 0
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM symbol_board").fetchone()[0] == 4


def test_script_stops_without_writing_on_a_symbol_in_two_files(tmp_path):
    db = tmp_path / "a.db"
    _legacy_db(db).close()
    r = _run("--db", str(db), *_files(tmp_path, hnx="AAA\nHHH"))
    assert r.returncode == 3 and "AAA" in r.stdout + r.stderr
    names = {x[0] for x in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "symbol_board" not in names


def test_script_never_creates_a_missing_database(tmp_path):
    missing = tmp_path / "nope.db"
    r = _run("--db", str(missing), *_files(tmp_path))
    assert r.returncode == 2 and "not found" in r.stderr and not missing.exists()


def test_script_works_on_the_real_symbol_files_in_the_repo(tmp_path):
    db = tmp_path / "a.db"
    _legacy_db(db).close()
    r = _run("--db", str(db))                                            # defaults: hose_all.txt, hnx_all.txt, upcom_all.txt
    assert r.returncode == 0, r.stderr
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM symbol_board").fetchone()[0]
    assert n == 1517
