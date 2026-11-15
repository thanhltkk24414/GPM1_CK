from dataclasses import replace
from datetime import date

from liquidity_lens.data.normalize import MarketRef
from liquidity_lens.data.quality import is_usable, quality_flags
from liquidity_lens.finance.orderbook import Level
from tests.fixtures.ssi_doc_samples import BOOK


def _ref(ceiling=48500, floor=42100):
    return MarketRef("SSI", "HOSE", date(2026, 7, 29), ceiling, floor, 45300)


def test_clean_book_has_no_flags():
    assert quality_flags(BOOK) == frozenset()


def test_crossed_book():  # Review Focus 5
    b = replace(BOOK, bids=(Level(45500, 100),), asks=(Level(45450, 100),))
    f = quality_flags(b)
    assert "CROSSED" in f and not is_usable(f)


def test_bid_order():
    b = replace(BOOK, bids=(Level(45400, 100), Level(45450, 100)))
    f = quality_flags(b)
    assert "BID_ORDER" in f and not is_usable(f)


def test_ask_order():
    b = replace(BOOK, asks=(Level(45550, 100), Level(45500, 100)))
    f = quality_flags(b)
    assert "ASK_ORDER" in f and not is_usable(f)


def test_out_of_band():
    f = quality_flags(BOOK, ref=_ref(ceiling=45400))
    assert "OUT_OF_BAND" in f and not is_usable(f)


def test_off_tick():
    assert "OFF_TICK" in quality_flags(BOOK, tick=100)


def test_bad_qty():
    b = replace(BOOK, bids=(Level(45450, 0),))
    f = quality_flags(b)
    assert "BAD_QTY" in f and not is_usable(f)


def test_empty_side_is_usable_but_flagged():
    f = quality_flags(replace(BOOK, asks=()))
    assert f == frozenset({"EMPTY_ASK"}) and is_usable(f)
