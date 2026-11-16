import json

from liquidity_lens.ssi.frames import FrameStats
from liquidity_lens.ssi.redact import MASK
from tests.fixtures.ssi_doc_samples import MARKET_FLAG, MARKET_REF, QUOTE, TRADE

# DOC SAMPLE payloads. The envelope below is HYPOTHETICAL (the real envelope is still [Kiểm tra]),
# it only checks that classification looks inside wrapper objects.
PING = {"method": "PING", "channel": "HEARTBEAT", "time": "16-11-2026 09-00-05"}


def _add(stats, obj, **kw):
    stats.add(json.dumps(obj), **kw)


def test_counts_by_kind_bare_and_wrapped():
    s = FrameStats()
    _add(s, QUOTE)
    _add(s, {"channel": "DATA", "data": QUOTE})
    _add(s, TRADE)
    _add(s, MARKET_REF)
    _add(s, MARKET_FLAG)
    _add(s, PING)
    s.add("not json at all")
    assert dict(s.counts) == {"quote": 2, "trade": 1, "market_ref": 1, "market_flag": 1, "heartbeat": 1, "non_json": 1}
    assert s.total == 7


def test_quote_levels_and_session_flags():
    s = FrameStats()
    _add(s, QUOTE)
    _add(s, {"s": "X", "t": "2026/07/29 09:15:33", "bids": [["1", "1"]], "asks": []})
    _add(s, MARKET_FLAG)
    _add(s, {"b": "HNX", "t": "2026/07/29 09:15:00", "f": "LO"})
    assert dict(s.quote_levels) == {(5, 5): 1, (1, 0): 1}
    assert dict(s.session_flags) == {("HOSE", "ATO"): 1, ("HNX", "LO"): 1}


def test_heartbeat_frames_kept_with_direction():
    s = FrameStats()
    _add(s, PING)
    _add(s, dict(PING, method="PONG"), direction="out")
    assert len(s.heartbeats) == 2
    assert s.heartbeats[0][0] == "in" and s.heartbeats[1][0] == "out"


def test_samples_are_capped_and_masked():
    s = FrameStats(secrets=["SECRETTOKEN"], max_samples=2)
    for i in range(5):
        _add(s, {"s": "SSI", "p": "1", "q": "1", "v": "1", "note": "SECRETTOKEN"})
    assert len(s.samples["trade"]) == 2
    assert all("SECRETTOKEN" not in x and MASK in x for x in s.samples["trade"])


def test_rejection_keywords_detected():
    s = FrameStats()
    _add(s, {"code": 401, "msg": "OTP required"})
    _add(s, {"msg": "Permission denied for topic"})
    _add(s, QUOTE)
    assert len(s.rejections) == 2


def test_report_never_contains_secret():
    s = FrameStats(secrets=["SECRETTOKEN"])
    _add(s, {"accessToken": "SECRETTOKEN", "x": 1})
    assert "SECRETTOKEN" not in s.report()
