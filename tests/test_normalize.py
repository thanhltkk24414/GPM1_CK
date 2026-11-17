from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from liquidity_lens import config

from liquidity_lens.data.normalize import (
    parse_market_ref,
    parse_quote,
    parse_session_flag,
    parse_trade,
)
from liquidity_lens.finance.orderbook import Level
from tests.fixtures.ssi_doc_samples import (
    MARKET_FLAG,
    MARKET_REF,
    MARKET_REF_DOC_ORIGINAL,
    QUOTE,
    QUOTE_DOC_ORIGINAL,
    RECEIVED,
    TRADE,
)


def test_quote_prices_scaled_to_vnd():  # Review Focus 4
    b = parse_quote(QUOTE, RECEIVED)
    assert b.bids[0] == Level(45450, 3200) and b.asks[0] == Level(45500, 2800)
    assert len(b.bids) == 5 and b.symbol == "SSI"
    assert b.ts == datetime(2026, 7, 29, 9, 15, 32, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


def test_trade_price_not_scaled():
    t = parse_trade(TRADE, RECEIVED)
    assert (t.price, t.qty, t.side, t.total_vol) == (45500, 1000, "B", 1_250_000)


def test_market_ref():
    r = parse_market_ref(MARKET_REF)
    assert (r.ceiling, r.floor, r.ref, r.board) == (48500, 42100, 45300, "HOSE")


def test_session_flag():
    assert parse_session_flag(MARKET_FLAG).flag == "ATO"


def test_multiplier_is_applied_explicitly():
    # The documentation sample (45.45) is in thousands of dong; an explicit multiplier still converts it.
    assert parse_quote(QUOTE_DOC_ORIGINAL, RECEIVED, price_multiplier=1000).bids[0].price == 45450
    assert parse_market_ref(MARKET_REF_DOC_ORIGINAL, price_multiplier=1000).ceiling == 48500


def test_default_multiplier_is_one_and_fractional_dong_is_rejected():
    assert config.QUOTE_PRICE_MULTIPLIER == 1
    # With the default multiplier a documentation-style price (45.45) is not a whole number of dong:
    # fail loudly (it becomes a PARSE_ERROR upstream) instead of silently truncating to 45.
    with pytest.raises(ValueError):
        parse_quote(QUOTE_DOC_ORIGINAL, RECEIVED)


def _padded(real_bids, real_asks, total=10):
    pad = [["0", "0"]] * (total - 0)
    return {
        "s": "HPG", "t": "2026/11/17 09:15:00",
        "bids": (real_bids + pad)[:total], "asks": (real_asks + pad)[:total],
    }


def test_padding_levels_are_dropped():
    # Shape observed on 2026-11-17: always 10 levels per side, only the first 3 are real, the rest are ["0","0"].
    p = _padded([["20850", "179700"], ["20800", "280400"], ["20750", "63500"]],
                [["20950", "3700"], ["21000", "6700"], ["21050", "21700"]])
    b = parse_quote(p, RECEIVED)
    assert [lv.price for lv in b.bids] == [20850, 20800, 20750]
    assert [lv.price for lv in b.asks] == [20950, 21000, 21050]
    assert len(b.bids) == 3 and len(b.asks) == 3


def test_all_padding_side_is_empty():
    b = parse_quote(_padded([["20850", "100"]], []), RECEIVED)
    assert len(b.bids) == 1 and b.asks == ()


def test_zero_price_or_zero_quantity_levels_are_dropped():
    p = {"s": "HPG", "t": "2026/11/17 09:15:00", "bids": [["20850", "100"], ["20800", "0"], ["0", "50"]], "asks": []}
    assert [lv.price for lv in parse_quote(p, RECEIVED).bids] == [20850]


def test_one_sided_book_from_padding_gives_none_metrics():
    from liquidity_lens.finance.metrics import obi, spread_abs

    b = parse_quote(_padded([["20850", "100"]], []), RECEIVED)
    assert spread_abs(b) is None and obi(b, 3) is None


def test_trade_time_with_milliseconds():
    # Observed 2026-11-17: trade.t has milliseconds ("09:15:00.005"), quote.t does not.
    from liquidity_lens.data.normalize import parse_vn_time

    t = parse_vn_time("2026/11/17 09:15:00.005")
    assert (t.second, t.microsecond) == (0, 5000) and t.utcoffset().total_seconds() == 7 * 3600
    assert parse_vn_time("2026/11/17 09:15:00").microsecond == 0
    trade = dict(TRADE, t="2026/11/17 09:15:00.005")
    assert parse_trade(trade, RECEIVED).ts.microsecond == 5000
