from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Level:
    price: int  # VND
    qty: int


@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    ts: datetime
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    received_at: datetime | None = None
