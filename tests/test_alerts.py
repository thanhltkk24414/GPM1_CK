from datetime import datetime

from liquidity_lens.analytics.alerts import calibrate_threshold, detect_alerts, score_bars
from liquidity_lens.analytics.bars import MinuteBar
from tests.fixtures.ssi_doc_samples import TZ

MINUTE = datetime(2026, 7, 29, 9, 30, tzinfo=TZ)


def test_calibrate_threshold():
    assert calibrate_threshold(list(range(101)), 0.99) == 99.0


def test_alert_severity():
    a = detect_alerts("SSI", MINUTE, {"obi3": 0.5}, {"obi3": 2.5}, watch=2, alert=3)
    assert [x.severity for x in a] == ["WATCH"]
    b = detect_alerts("SSI", MINUTE, {"obi3": -0.5}, {"obi3": -3.2}, watch=2, alert=3)
    assert [x.severity for x in b] == ["ALERT"]


def test_none_z_no_alert():
    assert detect_alerts("SSI", MINUTE, {"obi3": 0.5}, {"obi3": None}, watch=2, alert=3) == []


def test_message_wording():
    (a,) = detect_alerts("SSI", MINUTE, {"obi3": 0.5}, {"obi3": 3.5}, watch=2, alert=3)
    assert "bất thường thống kê" in a.message and "thao túng" not in a.message


def _bar(h, m, obi3):
    return MinuteBar("SSI", datetime(2026, 7, 29, h, m, tzinfo=TZ), 50, 10.0, 1.0, 0.1, obi3,
                     100, 100, 1, 1, 10)


def test_score_bars_resets_between_am_pm():  # Review Focus 3
    am = [_bar(10, i, 0.1 * (i % 3) + 0.01 * i) for i in range(6)]
    pm = [_bar(13, 0, 0.9), _bar(13, 1, 0.2)]
    out = score_bars(am + pm, window=5, min_periods=3)
    assert out[5]["obi3"] is not None  # morning has enough history
    assert out[6]["obi3"] is None      # first afternoon bar: history reset
    assert out[7]["obi3"] is None      # still below min_periods in the afternoon group
