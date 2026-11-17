import copy
from datetime import date, datetime

from liquidity_lens import config
from liquidity_lens.analytics.materialize import materialize_metrics
from liquidity_lens.collector.pipeline import Pipeline
from liquidity_lens.data.store import init_db
from tests.fixtures.ssi_doc_samples import MARKET_FLAG, MARKET_REF, QUOTE, TZ

DAY = date(2026, 7, 29)


def _quote(h, m, s, bid_qty):
    q = copy.deepcopy(QUOTE)
    q["t"] = f"2026/07/29 {h:02d}:{m:02d}:{s:02d}"
    q["bids"][0][1] = str(bid_qty)
    return q


def _recv(h, m, s):
    return datetime(2026, 7, 29, h, m, s, 500000, tzinfo=TZ)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _db_with_series(tmp_path, spike=True):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)
    p.handle("market_ref", MARKET_REF, _recv(9, 0, 0))
    lo = copy.deepcopy(MARKET_FLAG)
    lo["t"], lo["f"] = "2026/07/29 09:15:00", "LO"
    p.handle("market_flag", lo, _recv(9, 15, 0))
    for i in range(12):
        qty = 3000 + 100 * (i % 4)
        if spike and i == 11:
            qty = 90000
        p.handle("quote", _quote(9, 20 + i, 10, qty), _recv(9, 20 + i, 10))
    return conn


def test_materialize_writes_metrics_and_alerts(tmp_path):
    conn = _db_with_series(tmp_path)
    n_bars, n_alerts = materialize_metrics(conn, DAY, window=10, min_periods=5)
    assert n_bars == 12 and _count(conn, "metrics_1m") == 12
    assert n_alerts >= 1 and _count(conn, "alerts") == n_alerts
    last = conn.execute("SELECT * FROM metrics_1m ORDER BY minute DESC LIMIT 1").fetchone()
    assert last["minute"].startswith("2026-07-29T09:31") and last["minute"].endswith("+07:00")
    assert last["z_obi3"] is not None and last["z_obi3"] > 3
    row = conn.execute("SELECT severity, message FROM alerts WHERE metric='obi3'").fetchone()
    assert row["severity"] == "ALERT" and "bất thường thống kê" in row["message"]


def test_materialize_twice_has_no_duplicates(tmp_path):
    conn = _db_with_series(tmp_path)
    first = materialize_metrics(conn, DAY, window=10, min_periods=5)
    second = materialize_metrics(conn, DAY, window=10, min_periods=5)
    assert first == second
    assert _count(conn, "metrics_1m") == 12 and _count(conn, "alerts") == first[1]


def test_none_session_flag_uses_fallback_windows(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn)  # no market_ref / market_flag: session_flag stays None
    p.handle("quote", _quote(9, 5, 10, 3000), _recv(9, 5, 10))    # outside CONTINUOUS_WINDOWS
    p.handle("quote", _quote(9, 20, 10, 3100), _recv(9, 20, 10))  # inside
    p.handle("quote", _quote(12, 0, 10, 3200), _recv(12, 0, 10))  # lunch break
    assert materialize_metrics(conn, DAY)[0] == 1
    assert config.CONTINUOUS_WINDOWS  # constant exists


def test_materialize_ignores_other_days(tmp_path):
    conn = _db_with_series(tmp_path)
    assert materialize_metrics(conn, date(2026, 7, 30)) == (0, 0)


def test_data_quality_report(tmp_path):
    from liquidity_lens.data.report import data_quality_report

    conn = _db_with_series(tmp_path)
    p = Pipeline(conn, today=DAY)
    p.handle("quote", {"s": "SSI", "t": "2026/07/29 09:50:00", "bids": [["x", "1"]], "asks": []}, _recv(9, 50, 0))
    p.handle("quote", _quote(9, 5, 10, 777), _recv(9, 5, 10))  # board flag is already LO, so this counts as LO
    conn.execute("INSERT INTO book_snapshot (symbol, ts, received_at, n_bids, n_asks, session_flag, flags) "
                 "VALUES ('SSI', '2026-07-29T09:06:00+07:00', '2026-07-29T09:06:00+07:00', 0, 0, NULL, '')")
    conn.commit()
    materialize_metrics(conn, DAY, window=10, min_periods=5)
    rep = data_quality_report(conn, DAY, window=10, min_periods=5)
    assert rep["snapshots_by_session_flag"]["LO"] == 13
    assert rep["snapshots_by_session_flag"][None] == 1
    assert rep["parse_errors"] == 1
    z = rep["zero_std_ratio"]["SSI"]
    assert z["spread_bps"] == 1.0          # constant spread: every evaluated window has std 0
    assert z["obi3"] == 0.0                # obi3 varies
    assert z["volume"] == 1.0              # no trades: volume is always 0


def test_data_quality_report_empty_day(tmp_path):
    from liquidity_lens.data.report import data_quality_report

    conn = init_db(tmp_path / "t.db")
    rep = data_quality_report(conn, DAY)
    assert rep == {"snapshots_by_session_flag": {}, "parse_errors": 0, "zero_std_ratio": {}, "snapshots_without_ref": 0}


def test_report_counts_snapshots_without_market_ref(tmp_path):
    from liquidity_lens.data.report import data_quality_report

    conn = init_db(tmp_path / "t.db")
    p = Pipeline(conn, today=DAY)
    p.handle("market_ref", MARKET_REF, _recv(9, 0, 0))                       # SSI has a reference
    p.handle("quote", _quote(9, 20, 10, 3000), _recv(9, 20, 10))             # SSI: with ref
    other = _quote(9, 21, 10, 3000)
    other["s"] = "HPG"
    p.handle("quote", other, _recv(9, 21, 10))                               # HPG: no market_ref
    p.handle("quote", dict(other, t="2026/07/29 09:22:10"), _recv(9, 22, 10))
    rep = data_quality_report(conn, DAY)
    assert rep["snapshots_without_ref"] == conn.execute(
        "SELECT COUNT(*) FROM book_snapshot WHERE symbol='HPG'").fetchone()[0]
