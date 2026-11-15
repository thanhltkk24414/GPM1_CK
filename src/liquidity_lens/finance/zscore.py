from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque
from typing import Hashable, Sequence


def rolling_zscore(
    values: Sequence[float | None],
    window: int,
    min_periods: int,
    groups: Sequence[Hashable] | None = None,
) -> list[float | None]:
    """Z-score of values[i] against up to `window` non-None values that precede i in the same group.

    Returns None when fewer than `min_periods` prior values exist, when the sample std (ddof=1)
    is zero or not finite, or when values[i] is None.
    """
    if groups is not None and len(groups) != len(values):
        raise ValueError("groups must have the same length as values")
    history: dict[Hashable, deque[float]] = defaultdict(lambda: deque(maxlen=window))
    out: list[float | None] = []
    for i, x in enumerate(values):
        hist = history[None if groups is None else groups[i]]
        z: float | None = None
        if x is not None and len(hist) >= max(min_periods, 2):
            sd = statistics.stdev(hist)
            if sd > 0 and math.isfinite(sd):
                z = (x - statistics.fmean(hist)) / sd
        out.append(z)
        if x is not None:
            hist.append(x)
    return out
