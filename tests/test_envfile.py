from pathlib import Path

import pytest

from liquidity_lens import envfile
from liquidity_lens.envfile import load_env, parse_env

ROOT = Path(__file__).resolve().parents[1]


def test_parse_skips_blank_and_comment_lines_and_strips():
    text = "\n# a comment\n  SSI_API_KEY =  abc123  \n   # indented comment\nOTHER=x\n"
    assert parse_env(text) == {"SSI_API_KEY": "abc123", "OTHER": "x"}


def test_parse_strips_matching_quotes_only():
    text = "A=\"double\"\nB='single'\nC=\"mismatch'\nD=\"\"\nE=pa\"ss\nF=with#hash\n"
    assert parse_env(text) == {"A": "double", "B": "single", "C": "\"mismatch'", "D": "", "E": 'pa"ss', "F": "with#hash"}


def test_parse_accepts_export_prefix_and_ignores_bad_lines():
    text = "export KEY1=v1\nthis line has no equals\n=novalue_key\n1BAD=x\nKEY2=a=b\n"
    assert parse_env(text) == {"KEY1": "v1", "KEY2": "a=b"}


def test_load_env_sets_variables_and_reports_names_only(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comment\nLL_TEST_KEY = \"secret-value\"\nLL_TEST_SECRET='s2'\n", encoding="utf-8")
    monkeypatch.delenv("LL_TEST_KEY", raising=False)
    monkeypatch.delenv("LL_TEST_SECRET", raising=False)
    loaded = load_env(f)
    import os

    assert sorted(loaded) == ["LL_TEST_KEY", "LL_TEST_SECRET"]
    assert os.environ["LL_TEST_KEY"] == "secret-value" and os.environ["LL_TEST_SECRET"] == "s2"
    assert "secret-value" not in repr(loaded)
    monkeypatch.delenv("LL_TEST_KEY")
    monkeypatch.delenv("LL_TEST_SECRET")


def test_existing_environment_variable_is_not_overwritten(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("LL_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("LL_TEST_KEY", "from-shell")
    assert load_env(f) == []
    import os

    assert os.environ["LL_TEST_KEY"] == "from-shell"


def test_empty_existing_variable_is_filled(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("LL_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("LL_TEST_KEY", "")
    assert load_env(f) == ["LL_TEST_KEY"]
    import os

    assert os.environ["LL_TEST_KEY"] == "from-file"
    monkeypatch.delenv("LL_TEST_KEY")


def test_missing_file_is_not_an_error(tmp_path):
    assert load_env(tmp_path / "does-not-exist.env") == []


def test_utf8_bom_is_handled(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_bytes(b"\xef\xbb\xbfLL_TEST_KEY=bom-ok\r\n")  # Windows PowerShell writes a BOM and CRLF
    monkeypatch.delenv("LL_TEST_KEY", raising=False)
    assert load_env(f) == ["LL_TEST_KEY"]
    import os

    assert os.environ["LL_TEST_KEY"] == "bom-ok"
    monkeypatch.delenv("LL_TEST_KEY")


def test_default_path_is_project_root():
    assert envfile.DEFAULT_ENV_PATH == ROOT / ".env"


def test_env_example_has_no_values():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assignments = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    assert assignments, ".env.example should list the variable names"
    for ln in assignments:
        name, sep, value = ln.partition("=")
        assert sep == "=" and name.strip(), f"malformed line: {name!r}"
        assert value.strip() == "", f"{name.strip()} must have no value in .env.example"


def test_collector_main_missing_keys_reports_names_without_values(tmp_path, monkeypatch, capsys):
    from liquidity_lens.collector import main as collector_main

    monkeypatch.setattr(envfile, "DEFAULT_ENV_PATH", tmp_path / "no.env")
    monkeypatch.delenv("SSI_API_KEY", raising=False)
    monkeypatch.delenv("SSI_API_SECRET", raising=False)
    assert collector_main.main(["--db", str(tmp_path / "t.db")]) == 2
    err = capsys.readouterr().err
    assert "SSI_API_KEY" in err and "SSI_API_SECRET" in err


def test_collector_main_reads_dotenv_before_checking_keys(tmp_path, monkeypatch, capsys):
    from liquidity_lens.collector import main as collector_main

    f = tmp_path / ".env"
    f.write_text("SSI_API_KEY=KEYFROMFILE\nSSI_API_SECRET=SECRETFROMFILE\n", encoding="utf-8")
    monkeypatch.setattr(envfile, "DEFAULT_ENV_PATH", f)
    monkeypatch.delenv("SSI_API_KEY", raising=False)
    monkeypatch.delenv("SSI_API_SECRET", raising=False)
    wl = tmp_path / "wl.txt"
    wl.write_text("bad symbol!\n", encoding="utf-8")
    with pytest.raises(ValueError):  # got past the key check (so .env was read) and failed on the watchlist
        collector_main.main(["--db", str(tmp_path / "t.db"), "--symbols", str(wl)])
    out = capsys.readouterr()
    assert "KEYFROMFILE" not in out.out + out.err and "SECRETFROMFILE" not in out.out + out.err
    monkeypatch.delenv("SSI_API_KEY", raising=False)
    monkeypatch.delenv("SSI_API_SECRET", raising=False)
