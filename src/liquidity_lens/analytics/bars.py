from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from typing import Callable, Mapping, Sequence

from liquidity_lens.config import CONTINUOUS_FLAGS, OPENING_MATCH_WINDOW
from liquidity_lens.data.normalize import MarketRef, TradeTick
from liquidity_lens.data.quality import is_usable, quality_flags
from liquidity_lens.finance import metrics
from liquidity_lens.finance.orderbook import BookSnapshot


@dataclass
class MinuteBar:
    symbol: str
    minute: datetime
    spread_abs: int | None
    spread_bps: float | None
    spread_ticks: float | None
    obi1: float | None
    obi3: float | None
    depth_bid3: int
    depth_ask3: int
    depth_val_bid3: int
    depth_val_ask3: int
    volume: int


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def to_minute_bars(
    books: Sequence[tuple[BookSnapshot, str | None]],
    trades: Sequence[TradeTick],
    tick: int | None = None,
    continuous_flags: frozenset[str] = CONTINUOUS_FLAGS,
    refs: Mapping[str, MarketRef] | None = None,
    tick_for: Callable[[str, int], int] | None = None,
    opening_window: tuple[time, time] | None = OPENING_MATCH_WINDOW,
    symbol_board: Mapping[str, str] | None = None,
) -> list[MinuteBar]:
    """Last usable continuous-session snapshot per (symbol, minute); no forward fill.

    Trades inside `opening_window` (the opening auction match) do not add to `volume`; pass None to count them.
    With `symbol_board` given, that exclusion applies to HOSE symbols only (HNX and UPCOM have no opening auction);
    without it every symbol is treated as HOSE, as before.
    """
    def tick_of(book: BookSnapshot) -> int | None:
        first = (book.bids or book.asks or (None,))[0]
        if tick_for is not None and first is not None:
            return tick_for(book.symbol, first.price)
        return tick

    last: dict[tuple[str, datetime], tuple[BookSnapshot, int | None]] = {}
    for book, flag in sorted(books, key=lambda p: p[0].ts):
        if flag not in continuous_flags:
            continue
        book_tick = tick_of(book)
        ref = refs.get(book.symbol) if refs else None
        if not is_usable(quality_flags(book, ref=ref, tick=book_tick)):
            continue
        last[(book.symbol, _minute(book.ts))] = (book, book_tick)

    volume: dict[tuple[str, datetime], int] = defaultdict(int)
    for t in trades:
        is_hose = symbol_board is None or symbol_board.get(t.symbol) == "HOSE"
        if is_hose and opening_window is not None and opening_window[0] <= t.ts.time() < opening_window[1]:
            continue  # opening auction match: kept in trade_tick, not part of continuous-trading volume
        volume[(t.symbol, _minute(t.ts))] += t.qty

    bars = []
    for (symbol, minute), (b, b_tick) in sorted(last.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        bars.append(
            MinuteBar(
                symbol=symbol,
                minute=minute,
                spread_abs=metrics.spread_abs(b),
                spread_bps=metrics.spread_bps(b),
                spread_ticks=metrics.spread_ticks(b, b_tick) if b_tick else None,
                obi1=metrics.obi(b, 1),
                obi3=metrics.obi(b, 3),
                depth_bid3=metrics.depth_qty(b, "bid", 3),
                depth_ask3=metrics.depth_qty(b, "ask", 3),
                depth_val_bid3=metrics.depth_value(b, "bid", 3),
                depth_val_ask3=metrics.depth_value(b, "ask", 3),
                volume=volume.get((symbol, minute), 0),
            )
        )
    return bars
