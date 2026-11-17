"""Structure tests on REAL SAMPLE frames (SSI WebSocket 2026-11-17). Not market data."""
import json
from datetime import datetime

import pytest

from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.collector.router import FrameRouter
from liquidity_lens.config import TZ
from liquidity_lens.data.store import init_db
from liquidity_lens.ssi.frames import map_frame
from tests.fixtures import real_ws_samples as R

RECEIVED = datetime(2026, 11, 17, 9, 20, 0, 500000, tzinfo=TZ)


def test_real_frames_map_to_expected_kinds():
    assert map_frame(R.SUBSCRIBE_ACK)[0] == "subscribe_ack"
    assert map_frame(R.LIST_SUBSCRIPTION_REPLY)[0] == "list_subscription"
    for q in (R.QUOTE_HPG, R.QUOTE_HPG_LATER, R.QUOTE_FPT, R.QUOTE_VIC):
        assert map_frame(q)[0] == "quote"
    assert map_frame(R.TRADE_FPT_MS)[0] == "trade" and map_frame(R.TRADE_HPG)[0] == "trade"
    kind, payload = map_frame(R.MARKET_FLAG_UPPER)
    assert kind == "market_flag" and payload == {"b": "HOSE", "t": "2026/11/17 09:15:00", "f": "LO"}


def test_mapped_payload_is_the_data_object_of_the_envelope():
    kind, payload = map_frame(R.QUOTE_HPG)
    assert kind == "quote" and payload == json.loads(R.QUOTE_HPG)["data"]


@pytest.mark.parametrize("topic", ["quote.HPG", "QUOTE.HPG", "Quote.hpg"])
def test_topic_is_case_insensitive(topic):
    frame = json.loads(R.QUOTE_HPG)
    frame["topic"] = topic
    assert map_frame(json.dumps(frame))[0] == "quote"


@pytest.mark.parametrize("topic", ["market.FLAG", "market.flag", "MARKET.Flag"])
def test_market_flag_topic_any_case(topic):
    frame = json.loads(R.MARKET_FLAG_UPPER)
    frame["topic"] = topic
    assert map_frame(json.dumps(frame))[0] == "market_flag"


def test_topic_decides_kind_and_unsubscribed_topics_are_unknown():
    frame = json.loads(R.TRADE_HPG)
    frame["topic"] = "trade.index.VN30"            # an index tick, not a stock trade
    assert map_frame(json.dumps(frame))[0] == "unknown"
    frame["topic"] = "oddlot.HPG"
    assert map_frame(json.dumps(frame))[0] == "unknown"
    frame = json.loads(R.QUOTE_HPG)
    frame["data"].pop("bids")                      # topic says quote but the payload is not a quote
    assert map_frame(json.dumps(frame))[0] == "unknown"


def _setup(tmp_path):
    conn = init_db(tmp_path / "t.db")
    return conn, FrameRouter(Pipeline(conn, today=datetime(2026, 11, 17).date()), watchlist={"HPG", "FPT", "VIC"})


def test_router_stores_real_frames(tmp_path):
    conn, router = _setup(tmp_path)
    for raw in R.ALL_FRAMES:
        router(raw, RECEIVED)
    assert router.counts["quote"] == 4 and router.counts["trade"] == 2 and router.counts["market_flag"] == 1
    assert "unknown" not in router.counts
    rows = conn.execute("SELECT symbol, bid_p1, bid_q1, ask_p1, n_bids, n_asks, session_flag FROM book_snapshot ORDER BY rowid").fetchall()
    assert len(rows) == 4
    hpg = rows[0]
    assert (hpg["symbol"], hpg["bid_p1"], hpg["bid_q1"], hpg["ask_p1"]) == ("HPG", 20850, 179700, 20950)
    assert all((r["n_bids"], r["n_asks"]) == (3, 3) for r in rows)   # padding levels are not counted
    trade = conn.execute("SELECT symbol, price, ts FROM trade_tick WHERE symbol='FPT'").fetchone()
    assert trade["price"] == 49400 and ".005" in trade["ts"]
    assert conn.execute("SELECT board, flag FROM session_flag").fetchone()[:] == ("HOSE", "LO")
    assert conn.execute("SELECT COUNT(*) FROM collector_events WHERE event='PARSE_ERROR'").fetchone()[0] == 0
    events = {r[0] for r in conn.execute("SELECT event FROM collector_events")}
    assert {"SUBSCRIBE_ACK", "LIST_SUBSCRIPTION"} <= events


def test_replay_capture_feeds_only_inbound_frames(tmp_path):
    from liquidity_lens.collector.replay import replay_capture

    cap = tmp_path / "cap.jsonl"
    lines = [{"label": "REAL SAMPLE, SSI WebSocket 2026-11-17 (test capture)", "url": "x"},
             {"received_at": "2026-11-17T09:05:22.000+07:00", "direction": "out", "raw": '{"method":"SUBSCRIBE"}'}]
    lines += [{"received_at": f"2026-11-17T09:15:0{i}.100+07:00", "direction": "in", "raw": raw}
              for i, raw in enumerate(R.ALL_FRAMES)]
    cap.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    seen = []
    n = replay_capture(lambda raw, ts: seen.append((raw, ts)), cap)
    assert n == len(R.ALL_FRAMES) == len(seen)
    assert seen[0][0] == R.SUBSCRIBE_ACK and seen[0][1].isoformat().startswith("2026-11-17T09:15:00.100")
