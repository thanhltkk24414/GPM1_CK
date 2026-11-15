from __future__ import annotations

from liquidity_lens.data.normalize import MarketRef
from liquidity_lens.finance.orderbook import BookSnapshot

_UNUSABLE = frozenset({"CROSSED", "BID_ORDER", "ASK_ORDER", "OUT_OF_BAND", "BAD_QTY"})


def quality_flags(
    book: BookSnapshot, ref: MarketRef | None = None, tick: int | None = None
) -> frozenset[str]:
    flags: set[str] = set()
    if not book.bids:
        flags.add("EMPTY_BID")
    if not book.asks:
        flags.add("EMPTY_ASK")
    if book.bids and book.asks and book.bids[0].price >= book.asks[0].price:
        flags.add("CROSSED")
    bid_prices = [lv.price for lv in book.bids]
    ask_prices = [lv.price for lv in book.asks]
    if any(a <= b for a, b in zip(bid_prices, bid_prices[1:])):
        flags.add("BID_ORDER")
    if any(a >= b for a, b in zip(ask_prices, ask_prices[1:])):
        flags.add("ASK_ORDER")
    levels = book.bids + book.asks
    if ref is not None and any(not (ref.floor <= lv.price <= ref.ceiling) for lv in levels):
        flags.add("OUT_OF_BAND")
    if tick and any(lv.price % tick != 0 for lv in levels):
        flags.add("OFF_TICK")
    if any(lv.qty <= 0 for lv in levels):
        flags.add("BAD_QTY")
    return frozenset(flags)


def is_usable(flags: frozenset[str]) -> bool:
    return not (flags & _UNUSABLE)
