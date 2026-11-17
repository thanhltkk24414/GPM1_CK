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


def test_refs_exclude_out_of_band_snapshot():
    from datetime import date

    from liquidity_lens.data.normalize import MarketRef

    refs = {"SSI": MarketRef("SSI", "HOSE", date(2026, 7, 29), 45400, 42100, 45300)}  # asks above ceiling
    books = [(_at(9, 15, 30), "LO")]
    assert to_minute_bars(books, [], refs=refs) == []
    assert len(to_minute_bars(books, [])) == 1


def test_tick_for_flags_off_tick_is_not_fatal_but_used():
    seen = []

    def tick_for(symbol, price):
        seen.append((symbol, price))
        return 50

    bars = to_minute_bars([(_at(9, 15, 30), "LO")], [], tick_for=tick_for)
    assert seen and bars[0].spread_ticks == 1.0


def _tick(h, m, s, us, qty, symbol="SSI"):
    ts = datetime(2026, 7, 29, h, m, s, us, tzinfo=TZ)
    return TradeTick(symbol, ts, 45500, qty, "B", 0, ts)


def test_opening_match_trades_are_excluded_from_volume():
    # Real data (2026-11-17): the opening auction match is stamped 09:15:00.005; continuous trading starts after.
    trades = [
        _tick(9, 14, 59, 999000, 7),     # before the window: counted (belongs to the 09:14 minute, no bar anyway)
        _tick(9, 15, 0, 5000, 1000),     # opening match: excluded
        _tick(9, 15, 0, 438000, 100),    # still inside [09:15:00, 09:15:01): excluded
        _tick(9, 15, 0, 999999, 10),     # last microsecond of the window: excluded
        _tick(9, 15, 1, 0, 50),          # first instant after the window: counted
        _tick(9, 15, 30, 0, 25),
    ]
    bars = to_minute_bars([(_at(9, 15, 40), "LO")], trades)
    assert bars[0].volume == 75


def test_opening_window_can_be_disabled_and_applies_only_to_that_window():
    trades = [_tick(9, 15, 0, 5000, 1000), _tick(13, 0, 0, 5000, 40)]
    assert to_minute_bars([(_at(9, 15, 40), "LO")], trades, opening_window=None)[0].volume == 1000
    # 13:00:00 has no opening auction on HOSE: a trade in that second is NOT excluded
    assert to_minute_bars([(_at(13, 0, 30), "LO")], trades)[0].volume == 40
