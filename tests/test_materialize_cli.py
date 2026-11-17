import subprocess
import sys
from datetime import datetime
from pathlib import Path

from liquidity_lens.config import TZ
from liquidity_lens.data.report import format_report
from tests.test_materialize import DAY, _db_with_series

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize.py"


def _run(*args, env=None):
    import os

    full_env = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=full_env, timeout=120)


REPORT = {
    "snapshots_by_session_flag": {"LO": 912, None: 369},
    "snapshots_without_ref": 1281,
    "parse_errors": 2,
    "unknown_frames": 5,
    "excluded_opening_trades": {"FPT": {"trades": 240, "volume": 106000}},
    "zero_std_ratio": {"FPT": {"obi3": 0.0, "spread_bps": 0.5, "volume": 1.0}},
}


def test_format_report_has_every_requested_section():
    text = format_report(DAY, 18, 3, REPORT)
    for needle in ("2026-07-29", "minute bars: 18", "alerts: 3", "LO", "912", "(none)", "369",
                   "without market_ref: 1281", "PARSE_ERROR: 2", "UNKNOWN_FRAME: 5",
                   "FPT", "240", "106000", "0.50", "1.00"):
        assert needle in text, needle


def test_format_report_filters_per_symbol_tables():
    text = format_report(DAY, 1, 0, REPORT, symbols=["HPG"])
    assert "FPT" not in text.split("Opening-match")[1]


def test_cli_materializes_and_prints_report(tmp_path):
    conn = _db_with_series(tmp_path)  # 12 minute bars of SSI on 2026-07-29 (DOC SAMPLE-shaped data)
    conn.close()
    r = _run("--db", str(tmp_path / "t.db"), "--date", "2026-07-29", "--window", "10", "--min-periods", "5")
    assert r.returncode == 0, r.stderr
    assert "minute bars: 12" in r.stdout and "alerts:" in r.stdout and "LO" in r.stdout
    assert "PARSE_ERROR: 0" in r.stdout and "UNKNOWN_FRAME: 0" in r.stdout


def test_cli_symbols_option_limits_materialization(tmp_path):
    conn = _db_with_series(tmp_path)
    conn.close()
    r = _run("--db", str(tmp_path / "t.db"), "--date", "2026-07-29", "--symbols", "HPG")
    assert r.returncode == 0, r.stderr
    assert "minute bars: 0" in r.stdout


def test_cli_default_date_is_today_in_vietnam_time(tmp_path):
    from liquidity_lens.data.store import init_db

    init_db(tmp_path / "t.db").close()
    r = _run("--db", str(tmp_path / "t.db"))
    assert r.returncode == 0, r.stderr
    assert datetime.now(TZ).date().isoformat() in r.stdout.splitlines()[0]


def test_cli_missing_db_is_an_error_and_creates_nothing(tmp_path):
    missing = tmp_path / "nope.db"
    r = _run("--db", str(missing), "--date", "2026-07-29")
    assert r.returncode == 2 and "not found" in r.stderr
    assert not missing.exists()


def test_cli_never_reads_or_prints_credentials(tmp_path):
    from liquidity_lens.data.store import init_db

    init_db(tmp_path / "t.db").close()
    r = _run("--db", str(tmp_path / "t.db"), "--date", "2026-07-29",
             env={"SSI_API_KEY": "KEYVALUE12345", "SSI_API_SECRET": "SECRETVALUE67890"})
    assert "KEYVALUE12345" not in r.stdout + r.stderr and "SECRETVALUE67890" not in r.stdout + r.stderr
    assert "SSI_API_KEY" not in SCRIPT.read_text(encoding="utf-8")
