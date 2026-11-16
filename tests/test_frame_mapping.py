import json
from datetime import datetime

from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.collector.router import FrameRouter
from liquidity_lens.data.store import init_db
from liquidity_lens.ssi.frames import map_frame
from tests.fixtures.ssi_doc_samples import MARKET_FLAG, MARKET_REF, QUOTE, RECEIVED, TRADE

# DOC SAMPLE payloads. [Kiểm tra] The wrapper below is HYPOTHETICAL: the real envelope of data frames
# is unknown until a frame is captured during trading hours.
ENVELOPED = {"channel": "DATA", "topic": "quote.SSI", "data": QUOTE}
ACK = {"method": "SUBSCRIBE", "channel": "DATA", "status": "ok", "message": "Subscribed to 10 topic(s)"}  # observed 2026-11-16
LIST = {"trading": "", "data": "quote.VIC;market.flag"}  # observed 2026-11-16


def test_map_bare_payloads():
    assert map_frame(json.dumps(QUOTE))[0] == "quote"
    assert map_frame(json.dumps(TRADE))[0] == "trade"
    assert map_frame(json.dumps(MARKET_REF))[0] == "market_ref"
    assert map_frame(json.dumps(MARKET_FLAG))[0] == "market_flag"


def test_map_finds_payload_inside_wrapper():
    kind, payload = map_frame(json.dumps(ENVELOPED))
    assert kind == "quote" and payload == QUOTE


def test_map_control_and_heartbeat_frames():
    assert map_frame(json.dumps(ACK))[0] == "subscribe_ack"
    assert map_frame(json.dumps(LIST))[0] == "list_subscription"
    assert map_frame(json.dumps({"method": "PING", "channel": "HEARTBEAT", "time": "x"}))[0] == "heartbeat"


def test_oddlot_and_unknown_are_not_quotes():
    oddlot = dict(QUOTE, p="45.50", q="80")  # oddlot has p and q next to bids/asks
    assert map_frame(json.dumps(oddlot))[0] == "unknown"
    assert map_frame(json.dumps({"code": 1, "msg": "x"}))[0] == "unknown"
    assert map_frame("not json")[0] == "non_json"


def _setup(tmp_path, watchlist=None):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn, today=datetime(2026, 7, 29).date())
    return conn, FrameRouter(p, watchlist=watchlist)


def _events(conn):
    return [(r["event"], r["detail"]) for r in conn.execute("SELECT event, detail FROM collector_events ORDER BY id")]


def test_router_feeds_pipeline_and_counts(tmp_path):
    conn, router = _setup(tmp_path)
    router(json.dumps(MARKET_REF), RECEIVED)
    router(json.dumps(MARKET_FLAG), RECEIVED)
    router(json.dumps(ENVELOPED), RECEIVED)
    router(json.dumps(TRADE), RECEIVED)
    assert conn.execute("SELECT COUNT(*) FROM book_snapshot").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM trade_tick").fetchone()[0] == 1
    assert conn.execute("SELECT session_flag FROM book_snapshot").fetchone()[0] == "ATO"
    assert router.counts == {"market_ref": 1, "market_flag": 1, "quote": 1, "trade": 1}


def test_unknown_frame_logged_with_type_and_length_only(tmp_path):
    conn, router = _setup(tmp_path)
    frame = json.dumps({"code": 1, "msg": "SENSITIVE-LOOKING TEXT"})
    router(frame, RECEIVED)
    ((event, detail),) = _events(conn)
    assert event == "UNKNOWN_FRAME"
    d = json.loads(detail)
    assert d == {"type": "other:code,msg", "length": len(frame)}
    assert "SENSITIVE" not in detail
    router("not json", RECEIVED)
    assert json.loads(_events(conn)[1][1]) == {"type": "non_json", "length": 8}


def test_control_frames_are_logged_not_unknown(tmp_path):
    conn, router = _setup(tmp_path)
    router(json.dumps(ACK), RECEIVED)
    router(json.dumps(LIST), RECEIVED)
    assert [e for e, _ in _events(conn)] == ["SUBSCRIBE_ACK", "LIST_SUBSCRIPTION"]
    assert "Subscribed to 10" in _events(conn)[0][1]


def test_watchlist_filters_symbols_and_warns_on_non_hose(tmp_path):
    conn, router = _setup(tmp_path, watchlist={"SSI"})
    router(json.dumps(dict(TRADE, s="ZZZ")), RECEIVED)           # not in watchlist: dropped
    assert conn.execute("SELECT COUNT(*) FROM trade_tick").fetchone()[0] == 0
    router(json.dumps(dict(MARKET_REF, b="HNX")), RECEIVED)      # watchlist symbol but not HOSE
    assert conn.execute("SELECT COUNT(*) FROM market_ref").fetchone()[0] == 0
    assert _events(conn)[-1][0] == "NON_HOSE_SYMBOL"
    assert router.dropped == 2
