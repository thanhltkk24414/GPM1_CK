from liquidity_lens.finance.zscore import rolling_zscore


def test_basic():
    assert rolling_zscore([1, 2, 3, 4, 5], window=3, min_periods=3) == [None, None, None, 2.0, 2.0]


def test_zero_variance_returns_none():  # Review Focus 2
    assert rolling_zscore([5, 5, 5, 5], 3, 3) == [None, None, None, None]


def test_groups_do_not_cross():
    out = rolling_zscore([1, 2, 3, 4, 1, 2, 3, 4], 3, 3, groups=list("AAAABBBB"))
    assert out[3] == 2.0 and out[4:7] == [None, None, None] and out[7] == 2.0


def test_none_values_skipped():
    assert rolling_zscore([1, 2, None, 3, 4], 3, 3)[4] is not None
