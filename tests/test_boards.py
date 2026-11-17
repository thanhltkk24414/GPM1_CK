"""Combined CSV watchlist, per-board fallback session windows and effective_flag. No collector code involved."""
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from liquidity_lens.collector.main import load_watchlist
from liquidity_lens.config import TZ
from liquidity_lens.watchlist import build_watchlist_csv, read_watchlist_csv

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


def test_repo_files_hose_hnx_upcom_have_no_symbol_on_two_boards():
    by = {b: load_watchlist(ROOT / f"{b.lower()}_all.txt") for b in ("HOSE", "HNX", "UPCOM")}
    text = build_watchlist_csv(by, DAY)                                   # raises if a symbol is on two boards
    mapping = read_watchlist_csv(text)
    assert len(mapping) == sum(len(v) for v in by.values())


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


# ------------------------------------------------------------------------------- fallback windows per board
def test_config_windows_per_board_match_the_agreed_schedule():
    from datetime import time as t

    from liquidity_lens import config

    cont, auc = config.CONTINUOUS_WINDOWS_BY_BOARD, config.AUCTION_WINDOWS_BY_BOARD
    assert cont["HOSE"] == ((t(9, 15), t(11, 30)), (t(13, 0), t(14, 30))) == config.CONTINUOUS_WINDOWS   # unchanged
    assert auc["HOSE"] == {"ATO": ((t(9, 0), t(9, 15)),), "ATC": ((t(14, 30), t(14, 45)),)}
    assert cont["HNX"] == ((t(9, 0), t(11, 30)), (t(13, 0), t(14, 30)))
    assert auc["HNX"] == {"ATC": ((t(14, 30), t(14, 45)),), "PLO": ((t(14, 45), t(15, 0)),)}       # no ATO
    assert cont["UPCOM"] == ((t(9, 0), t(11, 30)), (t(13, 0), t(15, 0)))
    assert auc["UPCOM"] == {}                                                                      # no ATO / ATC


@pytest.mark.parametrize("board, hhmm, expected", [
    ("HOSE", "09:05", "ATO"), ("HOSE", "09:15", "LO"), ("HOSE", "11:29", "LO"), ("HOSE", "11:30", None),
    ("HOSE", "12:00", None), ("HOSE", "13:00", "LO"), ("HOSE", "14:30", "ATC"), ("HOSE", "14:45", None),
    ("HNX", "09:00", "LO"), ("HNX", "09:05", "LO"), ("HNX", "11:30", None), ("HNX", "14:29", "LO"),
    ("HNX", "14:30", "ATC"), ("HNX", "14:45", "PLO"), ("HNX", "15:00", None),
    ("UPCOM", "09:00", "LO"), ("UPCOM", "14:45", "LO"), ("UPCOM", "14:59", "LO"), ("UPCOM", "15:00", None),
    ("UPCOM", "08:59", None),
])
def test_effective_flag_fallback_by_board(board, hhmm, expected):
    from liquidity_lens.analytics.materialize import effective_flag

    h, m = map(int, hhmm.split(":"))
    assert effective_flag(None, datetime(2026, 11, 17, h, m, 0, tzinfo=TZ), board) == expected


def test_effective_flag_keeps_a_given_flag_and_never_guesses_for_an_unknown_board():
    from liquidity_lens.analytics.materialize import effective_flag

    ts = datetime(2026, 11, 17, 10, 0, tzinfo=TZ)
    assert effective_flag("BREAK", ts, "HNX") == "BREAK"
    assert effective_flag(None, ts, None) is None                     # unknown board: no fallback
    assert effective_flag(None, ts) == "LO"                           # default board stays HOSE (old behaviour)
