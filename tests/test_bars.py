from dataclasses import replace
from datetime import datetime

from liquidity_lens.analytics.bars import to_minute_bars
from liquidity_lens.data.normalize import TradeTick
from liquidity_lens.finance.orderbook import Level
from tests.fixtures.ssi_doc_samples import BOOK, TZ


def _at(h, m, s, book=BOOK):
    return replace(book, ts=datetime(2026, 7, 29, h, m, s, tzinfo=TZ))


def _trade(h, m, s, qty, symbol="SSI"):
    ts = datetime(2026, 7, 29, h, m, s, tzinfo=TZ)
    return TradeTick(symbol, ts, 45500, qty, "B", 0, ts)


def test_auction_and_lunch_excluded():  # Review Focus 3
    other = replace(BOOK, bids=(Level(45400, 100),), asks=(Level(45500, 300),))
    books = [
        (_at(9, 0, 10), "ATO"),
        (_at(9, 15, 5), "LO"),
        (_at(9, 15, 40, other), "LO"),
        (_at(12, 0, 0), None),
    ]
    bars = to_minute_bars(books, [])
    assert len(bars) == 1
    assert bars[0].minute == datetime(2026, 7, 29, 9, 15, tzinfo=TZ)
    assert bars[0].spread_abs == 100  # data of 09:15:40, the last snapshot in the minute
    assert bars[0].depth_bid3 == 100


def test_unusable_snapshot_skipped():
    crossed = replace(BOOK, bids=(Level(45500, 100),), asks=(Level(45450, 100),))
    assert to_minute_bars([(_at(9, 15, 5, crossed), "LO")], []) == []


def test_volume_sums_trades_in_minute():
    trades = [_trade(9, 15, 1, 100), _trade(9, 15, 59, 250), _trade(9, 16, 0, 999), _trade(9, 15, 30, 7, "ACB")]
    bars = to_minute_bars([(_at(9, 15, 30), "LO")], trades)
    assert bars[0].volume == 350


def test_no_forward_fill():
    books = [(_at(9, 15, 30), "LO"), (_at(9, 18, 30), "LO")]
    assert len(to_minute_bars(books, [])) == 2
