import os
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Prices in quote/trade/market messages are multiplied by this factor to get VND. Real frames observed on
# 2026-11-17 carry prices already in dong (HPG 20850, FPT 49400), so the factor is 1.
# (The docs show 45.45-style samples; that was an assumption of 1000, now replaced by observation.)
QUOTE_PRICE_MULTIPLIER = 1

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

# Board assumed for a watchlist symbol that has no market_ref. The real feed never sends market.<symbol>
# (observed 2026-11-17), so there is no per-symbol board; the watchlist is HOSE-only, which makes this safe.
DEFAULT_BOARD = "HOSE"

# Opening-auction match window: trades stamped inside [start, end) are the ATO match, not continuous trading.
# They stay in trade_tick but are excluded from the volume of a minute bar. Real data 2026-11-17: the match was
# stamped 09:15:00.005 for VIC, HPG, FPT, and the first continuous trades came at 09:15:01.649 or later.
# [Kiểm tra] HOSE only; one HPG trade at 09:15:00.438 (opening price) cannot be classified. Re-check per board.
OPENING_MATCH_WINDOW = (time(9, 15, 0), time(9, 15, 1))

# Boards the collector can handle.
BOARDS = ("HOSE", "HNX", "UPCOM")


# Fallback session schedule per board (local time), used only when a snapshot has no session flag.
# Source: HOSE and HNX trading regulations as looked up by the project owner. NOT observed in SSI data:
# the flag NAMES of every board other than HOSE "LO" (and "BREAK" at 11:30 on all boards) are [Kiểm tra].
CONTINUOUS_WINDOWS_BY_BOARD = {
    "HOSE": CONTINUOUS_WINDOWS,                                    # 09:15-11:30, 13:00-14:30 (unchanged)
    "HNX": ((time(9, 0), time(11, 30)), (time(13, 0), time(14, 30))),
    "UPCOM": ((time(9, 0), time(11, 30)), (time(13, 0), time(15, 0))),
}
AUCTION_WINDOWS_BY_BOARD = {                                       # phase name -> windows; never continuous
    "HOSE": {"ATO": ((time(9, 0), time(9, 15)),), "ATC": ((time(14, 30), time(14, 45)),)},
    "HNX": {"ATC": ((time(14, 30), time(14, 45)),), "PLO": ((time(14, 45), time(15, 0)),)},   # no ATO
    "UPCOM": {},                                                   # no ATO / ATC
}
