from dataclasses import replace

import pytest

from liquidity_lens.finance.metrics import (
    buy_slippage,
    depth_qty,
    depth_value,
    mid_price,
    obi,
    spread_abs,
    spread_bps,
    spread_ticks,
)
from tests.fixtures.ssi_doc_samples import BOOK


def test_spread_and_mid():
    assert mid_price(BOOK) == 45475.0
    assert spread_abs(BOOK) == 50
    assert spread_bps(BOOK) == pytest.approx(10.99505, abs=1e-4)
    assert spread_ticks(BOOK, tick=50) == 1.0


def test_obi():
    assert obi(BOOK, 1) == pytest.approx(400 / 6000)
    assert obi(BOOK, 3) == pytest.approx(600 / 17200)


def test_depth():
    assert depth_qty(BOOK, "bid", 3) == 8900 and depth_qty(BOOK, "ask", 3) == 8300
    assert depth_value(BOOK, "bid", 3) == 404_010_000
    assert depth_value(BOOK, "ask", 3) == 378_105_000


def test_buy_slippage_within_depth():
    r = buy_slippage(BOOK, 4000)
    assert r.filled and r.avg_price == 45515.0
    assert r.slippage_bps == pytest.approx(8.79604, abs=1e-4)


def test_buy_slippage_exceeds_visible_depth():
    r = buy_slippage(BOOK, 20000)
    assert (r.filled, r.avg_price, r.slippage_bps) == (False, None, None)


def test_one_sided_book_returns_none():  # Review Focus 1
    b = replace(BOOK, asks=())
    assert spread_abs(b) is None and spread_bps(b) is None and obi(b, 3) is None
    assert mid_price(b) is None
