import asyncio
import json
import sqlite3
from datetime import datetime

import pytest

from liquidity_lens.collector.main import Collector, build_topics, load_watchlist, prepare_connection
from liquidity_lens.config import TZ
from liquidity_lens.data.store import init_db
from tests.fixtures.ssi_doc_samples import MARKET_FLAG, MARKET_REF, QUOTE, TRADE
from tests.test_stream import FakeWS

# All frames are DOC SAMPLE payloads (docs/ssi/05) or control frames observed on 2026-11-16: not market data.
LO = dict(MARKET_FLAG, t="2026/07/29 09:15:00", f="LO")
ACK = {"method": "SUBSCRIBE", "channel": "DATA", "status": "ok", "message": "Subscribed to 4 topic(s)"}
FRAMES = [json.dumps(f) for f in (ACK, MARKET_REF, LO, QUOTE, TRADE)]


def _count(path, table):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _make(tmp_path, frames, **kw):
    path = tmp_path / "t.db"
    conn = init_db(path)
    prepare_connection(conn)
    ws = FakeWS(frames)
    c = Collector(
        conn, ["SSI"], authorization=lambda: "Bearer TESTTOKEN", connect=lambda url, headers: ws,
        now=lambda: datetime(2026, 7, 29, 9, 20, tzinfo=TZ), **kw,
    )
    return path, conn, c


async def _run_until(c, cond, then=None, timeout=3.0):
    stop = asyncio.Event()
    task = asyncio.create_task(c.run(stop))
    for _ in range(int(timeout / 0.01)):
        if cond():
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("condition not reached")
    if then:
        then()
    stop.set()
    await asyncio.wait_for(task, 3)


def test_prepare_connection_sets_synchronous_normal(tmp_path):
    conn = init_db(tmp_path / "t.db")
    prepare_connection(conn)
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_load_watchlist_and_topics(tmp_path):
    f = tmp_path / "wl.txt"
    f.write_text("# HOSE only\nvic\n\nHPG  # liquid\nFPT\n", encoding="utf-8")
    assert load_watchlist(f) == ["VIC", "HPG", "FPT"]
    assert build_topics(["VIC"]) == ["quote.VIC", "trade.VIC", "market.VIC", "market.flag"]
    f.write_text("VIC\nbad symbol!\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_watchlist(f)


def test_writes_are_batched_until_flush_then_visible(tmp_path):
    path, conn, c = _make(tmp_path, FRAMES, flush_interval_s=3600, commit_every=1000)
    seen = {}

    def check():
        seen["before"] = _count(path, "raw_message")

    asyncio.run(_run_until(c, lambda: c.router.counts["trade"] == 1, then=check))
    assert seen["before"] == 0                       # nothing committed yet (batching)
    assert _count(path, "raw_message") == 4          # market_ref, market_flag, quote, trade (ack is an event, not raw)
    assert _count(path, "book_snapshot") == 1 and _count(path, "trade_tick") == 1


def test_commit_after_n_messages(tmp_path):
    path, conn, c = _make(tmp_path, FRAMES, flush_interval_s=3600, commit_every=3)
    seen = {}
    asyncio.run(_run_until(c, lambda: c.router.counts["trade"] == 1, then=lambda: seen.update(n=_count(path, "raw_message"))))
    assert seen["n"] == 3                            # committed at the 3rd message; the 4th is still pending


def test_timer_flush(tmp_path):
    path, conn, c = _make(tmp_path, FRAMES, flush_interval_s=0.05, commit_every=1000)
    seen = {}

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(c.run(stop))
        while c.router.counts["trade"] != 1:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)
        seen["n"] = _count(path, "raw_message")
        stop.set()
        await task

    asyncio.run(go())
    assert seen["n"] == 4


def test_clean_stop_writes_session_summary(tmp_path):
    path, conn, c = _make(tmp_path, FRAMES, flush_interval_s=3600)
    asyncio.run(_run_until(c, lambda: c.router.counts["trade"] == 1))
    c2 = sqlite3.connect(path)
    rows = {r[0]: r[1] for r in c2.execute("SELECT event, detail FROM collector_events")}
    for ev in ("COLLECTOR_START", "CONNECT", "SUBSCRIBE_SENT", "SUBSCRIBE_ACK", "SESSION_SUMMARY", "STOPPED"):
        assert ev in rows, ev
    summary = json.loads(rows["SESSION_SUMMARY"])
    assert summary["frames"]["quote"] == 1 and summary["frames"]["trade"] == 1
    assert "TESTTOKEN" not in json.dumps(rows)


def test_cancellation_flushes_and_summarises(tmp_path):
    path, conn, c = _make(tmp_path, FRAMES, flush_interval_s=3600, commit_every=1000)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(c.run(stop))
        while c.router.counts["trade"] != 1:
            await asyncio.sleep(0.01)
        task.cancel()                                 # what Ctrl+C does to the main task
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert _count(path, "raw_message") == 4
    assert _count(path, "collector_events") >= 1
    c2 = sqlite3.connect(path)
    assert c2.execute("SELECT COUNT(*) FROM collector_events WHERE event='SESSION_SUMMARY'").fetchone()[0] == 1


def test_silence_warning_only_in_trading_hours():
    from liquidity_lens.collector.main import is_trading_time

    assert is_trading_time(datetime(2026, 11, 17, 10, 0, tzinfo=TZ)) is True      # Tuesday morning
    assert is_trading_time(datetime(2026, 11, 17, 12, 0, tzinfo=TZ)) is False     # lunch break
    assert is_trading_time(datetime(2026, 11, 15, 10, 0, tzinfo=TZ)) is False     # Sunday


WATCHLIST_EXPECTED = ("ACB BID BSR CTG FPT GAS GVR HDB HPG LPB MBB MCH MSN MWG SAB SHB SSB SSI STB TCB "
                      "TCX VCB VHM VIB VIC VJC VNM VPB VPL VRE").split()  # HOSE price board, 2026-11-17


def test_repo_watchlist_file_has_the_30_symbols():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    symbols = load_watchlist(root / "watchlist.txt")
    assert symbols == WATCHLIST_EXPECTED and len(symbols) == 30
    assert len(build_topics(symbols)) == 91


def test_resolve_watchlist_defaults_to_three_symbols_without_symbols_option():
    from liquidity_lens import config
    from liquidity_lens.collector.main import resolve_watchlist

    assert resolve_watchlist(None) == ["VIC", "HPG", "FPT"] == list(config.DEFAULT_WATCHLIST)
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    assert resolve_watchlist(str(root / "watchlist.txt")) == WATCHLIST_EXPECTED


def test_each_subscribe_frame_gets_its_own_server_response_event(tmp_path):
    acks = [json.dumps({"method": "SUBSCRIBE", "channel": "DATA", "status": "ok",
                        "message": f"Subscribed to {n} topic(s)"}) for n in (20, 20, 20, 20, 11)]
    path, conn, c = _make(tmp_path, acks, flush_interval_s=3600)
    asyncio.run(_run_until(c, lambda: conn.execute(
        "SELECT COUNT(*) FROM collector_events WHERE event='SUBSCRIBE_ACK'").fetchone()[0] == 5))
    rows = [json.loads(r[0]) for r in sqlite3.connect(path).execute(
        "SELECT detail FROM collector_events WHERE event='SUBSCRIBE_ACK' ORDER BY id")]
    assert [r["message"] for r in rows] == [f"Subscribed to {n} topic(s)" for n in (20, 20, 20, 20, 11)]
    assert all(r["status"] == "ok" for r in rows)


def test_hose_all_file_is_loadable_and_well_formed():
    import re

    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    symbols = load_watchlist(root / "hose_all.txt")
    assert symbols == sorted(set(symbols)) and len(symbols) > 0
    assert all(re.fullmatch(r"[A-Z0-9]{3}", s) for s in symbols)
    assert {"ACB", "FPT", "HPG", "VIC"} <= set(symbols)
    assert not {"AMY", "BMJ", "ATP"} & set(symbols)            # stockType is null for these: excluded by decision
