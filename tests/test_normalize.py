from datetime import datetime
from zoneinfo import ZoneInfo

from liquidity_lens.data.normalize import (
    parse_market_ref,
    parse_quote,
    parse_session_flag,
    parse_trade,
)
from liquidity_lens.finance.orderbook import Level
from tests.fixtures.ssi_doc_samples import MARKET_FLAG, MARKET_REF, QUOTE, RECEIVED, TRADE


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


def test_multiplier_is_applied():
    assert parse_quote(QUOTE, RECEIVED, price_multiplier=1).bids[0].price == 45
