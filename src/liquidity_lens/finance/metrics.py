"""Pure order book metrics. Only the visible levels are used, never the full book."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from liquidity_lens.finance.orderbook import BookSnapshot, Level


def _levels(b: BookSnapshot, side: Literal["bid", "ask"], k: int) -> tuple[Level, ...]:
    return (b.bids if side == "bid" else b.asks)[:k]


def mid_price(b: BookSnapshot) -> float | None:
    if not b.bids or not b.asks:
        return None
    return (b.bids[0].price + b.asks[0].price) / 2


def spread_abs(b: BookSnapshot) -> int | None:
    if not b.bids or not b.asks:
        return None
    return b.asks[0].price - b.bids[0].price


def spread_bps(b: BookSnapshot) -> float | None:
    mid = mid_price(b)
    spread = spread_abs(b)
    if mid is None or spread is None or mid == 0:
        return None
    return spread / mid * 10000


def spread_ticks(b: BookSnapshot, tick: int) -> float | None:
    spread = spread_abs(b)
    if spread is None or tick <= 0:
        return None
    return spread / tick


def depth_qty(b: BookSnapshot, side: Literal["bid", "ask"], k: int) -> int:
    return sum(lv.qty for lv in _levels(b, side, k))


def depth_value(b: BookSnapshot, side: Literal["bid", "ask"], k: int) -> int:
    return sum(lv.price * lv.qty for lv in _levels(b, side, k))


def obi(b: BookSnapshot, k: int) -> float | None:
    if not b.bids or not b.asks:
        return None
    bid_q = depth_qty(b, "bid", k)
    ask_q = depth_qty(b, "ask", k)
    total = bid_q + ask_q
    if total == 0:
        return None
    return (bid_q - ask_q) / total


@dataclass(frozen=True)
class SlippageResult:
    filled: bool
    avg_price: float | None
    slippage_bps: float | None


def buy_slippage(b: BookSnapshot, qty: int, k: int = 3) -> SlippageResult:
    """Walk the ask side for a buy of `qty`. No extrapolation beyond the visible k levels."""
    mid = mid_price(b)
    if qty <= 0 or mid is None or mid == 0:
        return SlippageResult(False, None, None)
    remaining = qty
    cost = 0
    for lv in _levels(b, "ask", k):
        take = min(remaining, lv.qty)
        cost += take * lv.price
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        return SlippageResult(False, None, None)
    avg = cost / qty
    return SlippageResult(True, avg, (avg - mid) / mid * 10000)
