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

# DOC SAMPLE: payloads copied from docs/ssi/05-websocket-sub-unsub-market-data.md.
RECEIVED = datetime(2026, 7, 29, 9, 15, 32, 120000, tzinfo=TZ)

QUOTE = {
    "s": "SSI",
    "t": "2026/07/29 09:15:32",
    "bids": [["45.45", "3200"], ["45.40", "1500"], ["45.35", "4200"], ["45.30", "2100"], ["45.25", "3300"]],
    "asks": [["45.50", "2800"], ["45.55", "1900"], ["45.60", "3600"], ["45.65", "2200"], ["45.70", "4100"]],
}

TRADE = {
    "s": "SSI", "t": "2026/07/29 09:15:32", "p": "45500", "q": "1000", "a": "45350",
    "si": "B", "o": "45000", "h": "45800", "l": "44900", "v": "1250000",
}

MARKET_REF = {"s": "SSI", "b": "HOSE", "t": "2026/07/29", "ce": "48.50", "fl": "42.10", "ref": "45.30"}

MARKET_FLAG = {"b": "HOSE", "t": "2026/07/29 09:00:00", "f": "ATO"}
