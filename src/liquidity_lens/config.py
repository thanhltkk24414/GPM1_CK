import os
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Prices in quote/market/put messages are scaled by this factor to get VND (assumption, verify with real data).
QUOTE_PRICE_MULTIPLIER = 1000

DB_PATH = Path(os.environ.get("LL_DB_PATH", "data/liquidity_lens.db"))

# Session flags treated as continuous matching (assumption: "LO", verify with real data).
CONTINUOUS_FLAGS = frozenset({"LO"})

# Fallback continuous-matching windows (local time), used only when a snapshot has no session flag.
# [Kiểm tra] not in the SSI docs read so far: confirm per board with real data (docs/design.md).
CONTINUOUS_WINDOWS = (
    (time(9, 15), time(11, 30)),
    (time(13, 0), time(14, 30)),
)

# Default watchlist for the collector. [Kiểm tra] HOSE symbols only: the fallback session windows are HOSE's.
DEFAULT_WATCHLIST = ("VIC", "HPG", "FPT")
