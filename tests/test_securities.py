import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from liquidity_lens.config import TZ
from liquidity_lens.ssi.auth import TokenManager
from liquidity_lens.ssi.securities import SECURITIES_PATH, describe_structure, fetch_securities_raw

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=TZ)

# Every response below is INVENTED to exercise the generic structure reader. The real response shape of
# securitiesByBoard is unknown until it is observed, so none of these names is a claim about the real API.


def test_describe_top_level_list():
    info = describe_structure([{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5, "b": 6}, {"a": 7, "b": 8}])
    assert info["type"] == "list"
    ((path, lst),) = info["lists"].items()
    assert path == "$" and lst["count"] == 4 and lst["item_fields"] == ["a", "b"]
    assert lst["samples"] == [{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5, "b": 6}]


def test_describe_dict_with_nested_list_reports_every_list_without_choosing():
    obj = {"x": 1, "wrapper": {"rows": [{"k": "v"}], "other": [{"z": 1}, {"z": 2}]}, "meta": {"n": 3}}
    info = describe_structure(obj)
    assert info["type"] == "dict" and info["top_level_keys"] == ["x", "wrapper", "meta"]
    assert set(info["lists"]) == {"wrapper.rows", "wrapper.other"}
    assert info["lists"]["wrapper.other"]["count"] == 2


def test_describe_without_lists_and_with_scalar_items():
    assert describe_structure({"a": 1})["lists"] == {}
    info = describe_structure({"names": ["p", "q"], "empty": []})
    assert info["lists"]["names"]["item_fields"] is None and info["lists"]["names"]["count"] == 2
    assert info["lists"]["empty"]["count"] == 0 and info["lists"]["empty"]["samples"] == []


class FakeHttp:
    def __init__(self, text, status=200):
        self.calls, self.text, self.status = [], text, status

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if url.endswith("/auth/token"):
            exp = int((NOW + timedelta(hours=1)).timestamp())
            return 200, {}, json.dumps({"tokenType": "Bearer", "accessToken": "ACCESS-TOKEN-XYZ",
                                        "refreshToken": "REFRESH-TOKEN-XYZ", "expiresAt": exp, "refreshExpiresAt": exp})
        return self.status, {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "19"}, self.text


def test_fetch_is_a_get_with_board_param_bearer_header_and_no_body():
    http = FakeHttp("[]")
    mgr = TokenManager("KEY", "SECRET", http, clock=lambda: NOW)
    status, headers, text = fetch_securities_raw("hose", mgr.authorization, http)
    method, url, hdrs, body = http.calls[-1]
    assert (method, body) == ("GET", None)
    assert url == "https://api.ssi.com.vn" + SECURITIES_PATH + "?board=HOSE"
    assert hdrs["Authorization"] == "Bearer ACCESS-TOKEN-XYZ"
    assert (status, text) == (200, "[]")


def test_fetch_rejects_a_board_that_is_not_a_plain_code():
    with pytest.raises(ValueError):
        fetch_securities_raw("../etc", lambda: "Bearer x", FakeHttp("[]"))


def _load_script():
    spec = importlib.util.spec_from_file_location("list_securities", ROOT / "scripts" / "list_securities.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RAW = '[{"alpha": "AAA", "beta": 1}, {"alpha": "BBB", "beta": 2},\n {"alpha": "CCC", "beta": 3}, {"alpha": "DDD", "beta": 4}]'


def test_script_saves_raw_response_unchanged_and_prints_structure_only(tmp_path, capsys):
    mod = _load_script()
    http = FakeHttp(RAW)
    mgr = TokenManager("KEY", "SECRET", http, clock=lambda: NOW)
    rc = mod.run("HOSE", tmp_path, mgr, http)
    out = capsys.readouterr().out
    assert rc == 0
    assert (tmp_path / "securities_HOSE.json").read_text(encoding="utf-8") == RAW       # byte-for-byte, not re-serialised
    assert "HTTP 200" in out and "4 item(s)" in out and "alpha" in out and "beta" in out
    assert out.count('"AAA"') == 1 and '"DDD"' not in out                               # exactly 3 samples
    assert "ACCESS-TOKEN-XYZ" not in out and "REFRESH-TOKEN-XYZ" not in out and "SECRET" not in out
    assert "symbol field" not in out.lower()                                           # the script never names the code field
    urls = [c[1] for c in http.calls]
    assert [u.split("?")[0].split(".vn")[1] for u in urls] == ["/api/v3/auth/token", SECURITIES_PATH]


def test_script_non_json_response_is_saved_and_reported(tmp_path, capsys):
    mod = _load_script()
    http = FakeHttp("<html>oops</html>", status=502)
    mgr = TokenManager("KEY", "SECRET", http, clock=lambda: NOW)
    assert mod.run("HOSE", tmp_path, mgr, http) == 1
    assert (tmp_path / "securities_HOSE.json").read_text(encoding="utf-8") == "<html>oops</html>"
    assert "HTTP 502" in capsys.readouterr().out


def test_script_can_print_vietnamese_on_a_cp1252_console(monkeypatch):
    import io
    import sys

    mod = _load_script()
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")   # what a default Windows console gives
    monkeypatch.setattr(sys, "stdout", console)
    mod.force_utf8_stdout()
    print("Ngân hàng Thương mại Cổ phần Á Châu")                          # would raise UnicodeEncodeError on cp1252
    sys.stdout.flush()
    assert "Á Châu".encode("utf-8") in raw.getvalue()
