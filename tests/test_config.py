def test_defaults():
    from zoneinfo import ZoneInfo
    from liquidity_lens import config
    assert config.TZ == ZoneInfo("Asia/Ho_Chi_Minh")
    assert config.QUOTE_PRICE_MULTIPLIER == 1000
    assert config.DB_PATH.as_posix().endswith("data/liquidity_lens.db")
    assert config.CONTINUOUS_FLAGS == frozenset({"LO"})
