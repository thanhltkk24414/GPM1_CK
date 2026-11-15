"""DOC SAMPLE: data derived from examples in the SSI FastConnect documentation (docs/ssi/).

This is NOT market data. Do not present it as such.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from liquidity_lens.finance.orderbook import BookSnapshot, Level

TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# DOC SAMPLE: derived from the SSI `quote` sample after multiplying prices by 1000 (top 3 levels).
BOOK = BookSnapshot(
    symbol="SSI",
    ts=datetime(2026, 7, 29, 9, 15, 32, tzinfo=TZ),
    bids=(Level(45450, 3200), Level(45400, 1500), Level(45350, 4200)),
    asks=(Level(45500, 2800), Level(45550, 1900), Level(45600, 3600)),
)
