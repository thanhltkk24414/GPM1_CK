def test_defaults():
    from zoneinfo import ZoneInfo
    from liquidity_lens import config
    assert config.TZ == ZoneInfo("Asia/Ho_Chi_Minh")
    assert config.QUOTE_PRICE_MULTIPLIER == 1  # prices are already in dong (observed 2026-11-17)
    assert config.DB_PATH.as_posix().endswith("data/liquidity_lens.db")
    assert config.CONTINUOUS_FLAGS == frozenset({"LO"})
