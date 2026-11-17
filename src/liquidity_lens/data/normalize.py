"""Parse SSI DATA-channel payloads into typed records. Prices become integer VND."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from liquidity_lens import config
from liquidity_lens.finance.orderbook import BookSnapshot, Level


def parse_vn_time(s: str) -> datetime:
    """Parse 'YYYY/MM/DD HH:mm:ss' (optionally '.fff' milliseconds, seen on trade frames) as Asia/Ho_Chi_Minh."""
    fmt = "%Y/%m/%d %H:%M:%S.%f" if "." in s else "%Y/%m/%d %H:%M:%S"
    return datetime.strptime(s, fmt).replace(tzinfo=config.TZ)


def _price(s: str, multiplier: int) -> int:
    """String price -> integer VND. Fails loudly on a fractional result instead of truncating it."""
    value = Decimal(s) * multiplier
    if value != value.to_integral_value():
        raise ValueError(f"price {s!r} x {multiplier} is not a whole number of VND")
    return int(value)


def parse_quote(
    payload: dict, received_at: datetime, price_multiplier: int = config.QUOTE_PRICE_MULTIPLIER
) -> BookSnapshot:
    def levels(raw) -> tuple[Level, ...]:
        # Real frames always carry 10 levels per side and pad the unused ones with ["0", "0"] (observed
        # 2026-11-17): keep only real levels, so len() is the number of real levels.
        parsed = ((_price(p, price_multiplier), int(q)) for p, q in raw)
        return tuple(Level(price, qty) for price, qty in parsed if price != 0 and qty != 0)

    return BookSnapshot(
        symbol=payload["s"],
        ts=parse_vn_time(payload["t"]),
        bids=levels(payload.get("bids") or []),
        asks=levels(payload.get("asks") or []),
        received_at=received_at,
    )


@dataclass
class TradeTick:
    symbol: str
    ts: datetime
    price: int
    qty: int
    side: str
    total_vol: int
    received_at: datetime


def parse_trade(payload: dict, received_at: datetime) -> TradeTick:
    # trade.p is already in VND: no multiplier.
    return TradeTick(
        symbol=payload["s"],
        ts=parse_vn_time(payload["t"]),
        price=int(Decimal(payload["p"])),
        qty=int(payload["q"]),
        side=payload.get("si", ""),
        total_vol=int(payload["v"]),
        received_at=received_at,
    )


@dataclass
class MarketRef:
    symbol: str
    board: str
    trading_date: date
    ceiling: int
    floor: int
    ref: int


def parse_market_ref(
    payload: dict, price_multiplier: int = config.QUOTE_PRICE_MULTIPLIER
) -> MarketRef:
    return MarketRef(
        symbol=payload["s"],
        board=payload["b"],
        trading_date=datetime.strptime(payload["t"], "%Y/%m/%d").date(),
        ceiling=_price(payload["ce"], price_multiplier),
        floor=_price(payload["fl"], price_multiplier),
        ref=_price(payload["ref"], price_multiplier),
    )


@dataclass
class SessionFlag:
    board: str
    ts: datetime
    flag: str


def parse_session_flag(payload: dict) -> SessionFlag:
    return SessionFlag(board=payload["b"], ts=parse_vn_time(payload["t"]), flag=payload["f"])
