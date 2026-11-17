import asyncio
import json
from datetime import datetime

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.http11 import Response

from liquidity_lens.config import TZ
from liquidity_lens.ssi.stream import StreamClient, build_subscribe, build_unsubscribe, pong_for

# Frames below are DOC SAMPLE-style (docs/ssi/04, 05) or shapes observed on 2026-11-16, not market data.
PING = {"method": "PING", "channel": "HEARTBEAT", "time": "16-11-2026 09-00-05"}
QUOTE = {"s": "SSI", "t": "2026/07/29 09:15:32", "bids": [["45450", "3200"]], "asks": [["45500", "2800"]]}
TOPICS = ["quote.SSI", "trade.SSI", "market.SSI", "market.flag"]


def test_build_subscribe_exact_and_rejects_non_data_topics():
    assert build_subscribe(["quote.SSI"]) == {"method": "SUBSCRIBE", "channel": "DATA", "topics": ["quote.SSI"]}
    assert build_unsubscribe(["quote.SSI"])["method"] == "UNSUBSCRIBE"
    for bad in ("order.0001", "portfolio.1", "fco.x"):
        with pytest.raises(ValueError):
            build_subscribe([bad])
    with pytest.raises(ValueError):
        build_subscribe([])


def test_pong_for_echoes_time():
    assert pong_for(PING) == {"method": "PONG", "channel": "HEARTBEAT", "time": "16-11-2026 09-00-05"}


class FakeWS:
    """Delivers `script` items in order (str = frame, Exception = raise), then waits forever."""

    def __init__(self, script):
        self.script, self.sent = list(script), []

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        await asyncio.sleep(3600)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Harness:
    def __init__(self, connections, **kw):
        self.connections = list(connections)
        self.headers, self.frames, self.events, self.sleeps = [], [], [], []
        self.stop = asyncio.Event()
        self.invalidated = 0

        def connect(url, headers):
            self.headers.append(headers)
            item = self.connections.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        async def sleep(delay):
            self.sleeps.append(delay)
            await asyncio.sleep(0)

        self.client = StreamClient(
            url="wss://example.invalid/ws/v3", topics=TOPICS,
            authorization=lambda: "Bearer TESTTOKEN",
            on_frame=lambda raw, ts: self.frames.append(raw),
            on_event=lambda event, detail: self.events.append((event, detail)),
            connect=connect, sleep=sleep, rng=lambda: 0.0,
            now=lambda: datetime(2026, 11, 17, 9, 30, tzinfo=TZ),
            on_auth_failure=self._invalidate, poll_s=0.01, **kw,
        )

    def _invalidate(self):
        self.invalidated += 1

    async def run(self, until, timeout=3.0):
        task = asyncio.create_task(self.client.run(self.stop))

        async def waiter():
            while not until():
                await asyncio.sleep(0.005)
            self.stop.set()

        w = asyncio.create_task(waiter())
        await asyncio.wait_for(task, timeout)
        w.cancel()

    def names(self):
        return [e for e, _ in self.events]


def _closed():
    return ConnectionClosed(None, None)


def test_connect_with_bearer_header_subscribe_and_forward_frames():
    ws = FakeWS([json.dumps(QUOTE)])
    h = Harness([ws])
    asyncio.run(h.run(lambda: len(h.frames) == 1))
    assert h.headers[0]["Authorization"] == "Bearer TESTTOKEN"
    assert ws.sent[0] == build_subscribe(TOPICS)
    assert h.frames == [json.dumps(QUOTE)]
    assert h.names()[:2] == ["CONNECT", "SUBSCRIBE_SENT"]


def test_pong_sent_and_heartbeats_logged_both_ways():
    ws = FakeWS([json.dumps(PING)])
    h = Harness([ws])
    asyncio.run(h.run(lambda: len(ws.sent) >= 2))
    assert ws.sent[1] == pong_for(PING)
    hb = [d for e, d in h.events if e == "HEARTBEAT"]
    assert len(hb) == 2 and hb[0].startswith("in ") and hb[1].startswith("out ")
    assert h.frames == []  # heartbeat is handled by the transport, not forwarded


def test_reconnect_resubscribes_and_logs_events():
    ws1 = FakeWS([json.dumps(QUOTE), _closed()])
    ws2 = FakeWS([json.dumps(QUOTE)])
    h = Harness([ws1, ws2])
    asyncio.run(h.run(lambda: len(h.frames) == 2))
    assert ws1.sent[0] == ws2.sent[0] == build_subscribe(TOPICS)
    names = h.names()
    assert names.index("DISCONNECT") < names.index("RECONNECT_WAIT") < len(names) - 1
    assert names.count("CONNECT") == 2 and names.count("SUBSCRIBE_SENT") == 2


def test_backoff_grows_and_resets_after_data():
    ws_ok = FakeWS([json.dumps(QUOTE), _closed()])
    h = Harness([OSError("down"), OSError("down"), OSError("down"), ws_ok, OSError("down"), FakeWS([json.dumps(QUOTE)])],
                backoff_base_s=1.0, backoff_cap_s=60.0)
    asyncio.run(h.run(lambda: len(h.frames) == 2))
    assert h.sleeps[:3] == [1.0, 2.0, 4.0]
    assert h.sleeps[3] == 1.0   # reset after a connection that delivered data
    assert h.sleeps[4] == 2.0   # and grows again from there


def test_backoff_is_capped():
    h = Harness([OSError("x")] * 8 + [FakeWS([json.dumps(QUOTE)])], backoff_base_s=1.0, backoff_cap_s=5.0)
    asyncio.run(h.run(lambda: len(h.frames) == 1))
    assert max(h.sleeps) == 5.0


def test_silence_warning_in_trading_hours_does_not_disconnect():
    h = Harness([FakeWS([])], silence_warn_s=0.03, should_warn=lambda now: True)
    asyncio.run(h.run(lambda: "SILENCE_WARNING" in h.names()))
    assert h.names().count("SILENCE_WARNING") == 1 and "DISCONNECT" not in h.names()


def test_no_silence_warning_outside_trading_hours():
    h2 = Harness([FakeWS([])], silence_warn_s=0.03, should_warn=lambda now: False)

    async def go():
        t = asyncio.create_task(h2.client.run(h2.stop))
        await asyncio.sleep(0.2)
        h2.stop.set()
        await t

    asyncio.run(go())
    assert "SILENCE_WARNING" not in h2.names()


def _status_error(code):
    return InvalidStatus(Response(code, "x", Headers(), b""))


def test_handshake_401_invalidates_token_and_retries():
    h = Harness([_status_error(401), FakeWS([json.dumps(QUOTE)])])
    asyncio.run(h.run(lambda: len(h.frames) == 1))
    assert h.invalidated == 1
    assert ("HANDSHAKE_REJECTED", "HTTP 401") in h.events


def test_http_429_waits_at_least_30_seconds():
    h = Harness([_status_error(429), FakeWS([json.dumps(QUOTE)])], backoff_base_s=1.0)
    asyncio.run(h.run(lambda: len(h.frames) == 1))
    assert h.sleeps[0] >= 30


def test_otp_or_permission_refusal_halts_without_retry():
    ws = FakeWS([json.dumps({"code": 401, "msg": "OTP required for this channel"})])
    h = Harness([ws])
    asyncio.run(h.run(lambda: h.client.halted, timeout=2))
    assert h.client.halted and "REJECTED_OTP_OR_PERMISSION" in h.names()
    assert "RECONNECT_WAIT" not in h.names()


def test_frame_handler_error_is_logged_and_stream_continues():
    ws = FakeWS([json.dumps(QUOTE), json.dumps(QUOTE)])
    h = Harness([ws])
    calls = []

    def bad(raw, ts):
        calls.append(raw)
        if len(calls) == 1:
            raise RuntimeError("boom")

    h.client.on_frame = bad
    asyncio.run(h.run(lambda: len(calls) == 2))
    assert "FRAME_HANDLER_ERROR" in h.names()


def test_stop_event_ends_run_cleanly():
    h = Harness([FakeWS([])])
    asyncio.run(h.run(lambda: "SUBSCRIBE_SENT" in h.names()))
    assert "DISCONNECT" not in h.names() and h.names()[-1] == "STOPPED"


# ----------------------------------------------------------------------------- chunked SUBSCRIBE
VN30 = ("ACB BID BSR BVH CTG FPT GAS GVR HDB HPG MBB MSN MWG PLX POW SAB SSB SSI STB TCB TPB VCB VHM VIB VIC VJC "
        "VNM VPB VPL VRE").split()


def _topics_for(symbols):
    return [f"{k}.{s}" for s in symbols for k in ("quote", "trade", "market")] + ["market.flag"]


def test_subscribe_frames_split_30_symbols_into_frames_of_at_most_20_topics():
    from liquidity_lens.ssi.stream import MAX_FRAME_BYTES, MAX_TOPICS_PER_FRAME, build_subscribe_frames

    topics = _topics_for(VN30)
    assert len(topics) == 91
    frames = build_subscribe_frames(topics)
    assert [len(f["topics"]) for f in frames] == [20, 20, 20, 20, 11]
    assert all(f["method"] == "SUBSCRIBE" and f["channel"] == "DATA" for f in frames)
    assert all(len(json.dumps(f).encode()) < MAX_FRAME_BYTES == 4000 for f in frames)
    assert MAX_TOPICS_PER_FRAME == 20
    assert [t for f in frames for t in f["topics"]] == topics          # nothing lost, nothing reordered


def test_subscribe_frames_also_split_by_size():
    from liquidity_lens.ssi.stream import build_subscribe_frames

    long_topics = [f"quote.{'X' * 400}{i}" for i in range(20)]          # 20 topics but ~8 KB together
    frames = build_subscribe_frames(long_topics)
    assert len(frames) > 1
    assert all(len(json.dumps(f).encode()) < 4000 and len(f["topics"]) <= 20 for f in frames)
    assert [t for f in frames for t in f["topics"]] == long_topics


def test_subscribe_frames_reject_unusable_input():
    from liquidity_lens.ssi.stream import build_subscribe_frames

    with pytest.raises(ValueError):
        build_subscribe_frames([])
    with pytest.raises(ValueError):
        build_subscribe_frames(["order.1"])
    with pytest.raises(ValueError):
        build_subscribe_frames(["quote." + "X" * 5000])               # one topic alone exceeds the limit


def test_stream_sends_every_frame_and_logs_each_one_and_resubscribes_after_reconnect():
    import liquidity_lens.ssi.stream as stream_mod

    topics = _topics_for(VN30)
    ws1 = FakeWS([json.dumps(QUOTE), _closed()])
    ws2 = FakeWS([json.dumps(QUOTE)])
    h = Harness([ws1, ws2])
    h.client.topics = topics
    asyncio.run(h.run(lambda: len(h.frames) == 2))
    expected = stream_mod.build_subscribe_frames(topics)
    assert ws1.sent[:5] == expected and ws2.sent[:5] == expected
    sent_events = [json.loads(d) for e, d in h.events if e == "SUBSCRIBE_SENT"]
    assert len(sent_events) == 10                                      # 5 frames x 2 connections
    first = sent_events[:5]
    assert [x["frame"] for x in first] == [1, 2, 3, 4, 5] and all(x["frames"] == 5 for x in first)
    assert [x["topics"] for x in first] == [20, 20, 20, 20, 11]
    assert all(0 < x["bytes"] < 4000 for x in first)
