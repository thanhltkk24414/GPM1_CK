from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from liquidity_lens.config import CONTINUOUS_FLAGS
from liquidity_lens.data.normalize import TradeTick
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
) -> list[MinuteBar]:
    """Last usable continuous-session snapshot per (symbol, minute); no forward fill."""
    last: dict[tuple[str, datetime], BookSnapshot] = {}
    for book, flag in sorted(books, key=lambda p: p[0].ts):
        if flag not in continuous_flags or not is_usable(quality_flags(book, tick=tick)):
            continue
        last[(book.symbol, _minute(book.ts))] = book

    volume: dict[tuple[str, datetime], int] = defaultdict(int)
    for t in trades:
        volume[(t.symbol, _minute(t.ts))] += t.qty

    bars = []
    for (symbol, minute), b in sorted(last.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        bars.append(
            MinuteBar(
                symbol=symbol,
                minute=minute,
                spread_abs=metrics.spread_abs(b),
                spread_bps=metrics.spread_bps(b),
                spread_ticks=metrics.spread_ticks(b, tick) if tick else None,
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
