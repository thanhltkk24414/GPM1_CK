import os
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Prices in quote/market/put messages are scaled by this factor to get VND (assumption, verify with real data).
QUOTE_PRICE_MULTIPLIER = 1000

DB_PATH = Path(os.environ.get("LL_DB_PATH", "data/liquidity_lens.db"))

# Session flags treated as continuous matching (assumption: "LO", verify with real data).
CONTINUOUS_FLAGS = frozenset({"LO"})
