from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence

from liquidity_lens.analytics.bars import MinuteBar
from liquidity_lens.finance.zscore import rolling_zscore

METRICS = ("obi3", "spread_bps", "volume")


def score_bars(
    bars: Sequence[MinuteBar], window: int = 30, min_periods: int = 15
) -> list[dict[str, float | None]]:
    """Rolling z-score per metric. Groups: (symbol, date, AM/PM), so history never crosses lunch or days."""
    groups = [(b.symbol, b.minute.date(), "AM" if b.minute.hour < 12 else "PM") for b in bars]
    per_metric = {
        m: rolling_zscore([getattr(b, m) for b in bars], window, min_periods, groups) for m in METRICS
    }
    return [{m: per_metric[m][i] for m in METRICS} for i in range(len(bars))]


@dataclass
class Alert:
    symbol: str
    minute: datetime
    metric: str
    value: float
    z: float
    severity: Literal["WATCH", "ALERT"]
    message: str


def detect_alerts(
    symbol: str,
    minute: datetime,
    values: Mapping[str, float | None],
    zscores: Mapping[str, float | None],
    watch: float,
    alert: float,
) -> list[Alert]:
    out: list[Alert] = []
    for metric, z in zscores.items():
        value = values.get(metric)
        if z is None or value is None:
            continue
        if abs(z) >= alert:
            severity = "ALERT"
        elif abs(z) >= watch:
            severity = "WATCH"
        else:
            continue
        message = (
            f"{symbol} {minute:%H:%M}: {metric} = {value:.4g} (z = {z:+.2f}), "
            f"bất thường thống kê so với {metric} gần đây của chính mã này."
        )
        out.append(Alert(symbol, minute, metric, value, z, severity, message))
    return out


def calibrate_threshold(abs_z: Sequence[float], percentile: float) -> float:
    """Linear-interpolation percentile (percentile in [0, 1])."""
    if not abs_z:
        raise ValueError("abs_z is empty")
    if not 0 <= percentile <= 1:
        raise ValueError("percentile must be in [0, 1]")
    xs = sorted(abs_z)
    pos = percentile * (len(xs) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
