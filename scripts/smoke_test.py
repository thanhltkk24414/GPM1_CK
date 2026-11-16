"""REST smoke test for SSI FastConnect (Task 10, REST part only; no WebSocket).

Steps: (1) POST /api/v3/auth/token with apiKey + apiSecret only (no otp, no transactionId),
(2) GET /api/v3/data/securitiesSummary for one HOSE symbol, (3) print a report, (4) save the masked
raw responses to data/smoke/.

Credentials come from the environment (SSI_API_KEY, SSI_API_SECRET). They, the access token and the
refresh token are never printed or written to disk. Read-only: this script never touches the Trading
API, order.*, fco.* or the TRADING channel.

Usage:  python scripts/smoke_test.py [--symbol SSI] [--days 7]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from liquidity_lens import config
from liquidity_lens.ssi.redact import mask

DEFAULT_BASE_URL = "https://api.ssi.com.vn"
TOKEN_PATH = "/api/v3/auth/token"
SUMMARY_PATH = "/api/v3/data/securitiesSummary"
OUT_DIR = Path("data/smoke")

# Field names taken verbatim from docs/ssi/02-auth-token.md and docs/ssi/06-data-securities-summary.md.
DOC_TOKEN_FIELDS = {"tokenType", "accessToken", "expiresAt", "refreshToken", "refreshExpiresAt"}
DOC_PAGE_FIELDS = {"pageSize", "pageIndex", "pagesCount", "itemsCount", "data"}
DOC_ITEM_FIELDS = {
    "symbol", "tradingDate", "priceChange", "priceChangePercentage", "open", "high", "low", "close",
    "average", "totalMatch", "totalMatchValue", "totalBuy", "totalTradeBuy", "totalSell", "totalTradeSell",
    "totalForeignBuy", "totalForeignBuyValue", "totalForeignSell", "totalForeignSellValue",
    "remainForeignRoom", "totalForeignRoom", "totalDeal", "totalDealValue", "openInterest", "settlementPrice",
}


class SmokeError(Exception):
    pass


def http(method: str, url: str, headers: dict[str, str], body: dict | None = None) -> tuple[int, dict[str, str], str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers.items()), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise SmokeError(f"network error: {e.reason}") from e


def rate_limit_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.upper().startswith("X-RATELIMIT-")}


def parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def epoch_unit(value) -> str:
    n = len(str(abs(int(value))))
    return {10: "seconds", 13: "milliseconds"}.get(n, "unknown")


def compare(name: str, got: set[str], documented: set[str]) -> None:
    missing, extra = sorted(documented - got), sorted(got - documented)
    print(f"  vs docs [{name}]: missing={missing or '-'} extra={extra or '-'}")


def _save(saved: dict, symbol: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(saved["fetched_at"]).strftime("%Y%m%dT%H%M%S")
    path = OUT_DIR / f"smoke_{symbol}_{stamp}.json"
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="SSI", help="HOSE symbol (default: SSI)")
    ap.add_argument("--days", type=int, default=7, help="look-back window in calendar days")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="override only for local fake-server tests")
    args = ap.parse_args(argv)

    key, secret = os.environ.get("SSI_API_KEY", ""), os.environ.get("SSI_API_SECRET", "")
    missing = [n for n, v in (("SSI_API_KEY", key), ("SSI_API_SECRET", secret)) if not v]
    if missing:
        print(f"ERROR: missing environment variable(s): {', '.join(missing)} (see .env.example)", file=sys.stderr)
        return 2

    fetched_at = datetime.now(config.TZ)
    secrets = [key, secret]
    saved: dict = {
        "label": f"REAL DATA from SSI FastConnect REST, fetched at {fetched_at.isoformat(timespec='seconds')} "
                 f"({config.TZ.key}). Credentials masked. Not a DOC SAMPLE.",
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
    }
    json_headers = {"Content-Type": "application/json", "User-Agent": "liquidity-lens-smoke-test"}
    base = args.base_url.rstrip("/")

    try:
        # 1. token: body has apiKey and apiSecret only.
        print(f"[1] POST {TOKEN_PATH}")
        status, hdrs, text = http("POST", base + TOKEN_PATH, json_headers, {"apiKey": key, "apiSecret": secret})
        body = parse_json(text)
        saved["auth"] = {
            "status": status, "ratelimit": rate_limit_headers(hdrs),
            "body": mask(body if body is not None else text, secrets),
        }
        print(f"  HTTP {status}")
        print(f"  X-RATELIMIT-*: {rate_limit_headers(hdrs) or 'none received'}")
        if status != 200 or not isinstance(body, dict):
            print(f"  response (masked): {json.dumps(saved['auth']['body'], ensure_ascii=False)}")
            _save(saved, args.symbol)
            return 1
        print(f"  fields: {sorted(body)}")
        compare("token", set(body), DOC_TOKEN_FIELDS)
        if "expiresAt" in body:
            print(f"  expiresAt digits: {len(str(body['expiresAt']))} -> {epoch_unit(body['expiresAt'])}")
        else:
            print("  expiresAt: absent")
        for name in ("accessToken", "refreshToken"):
            if body.get(name):
                secrets.append(body[name])
        if not body.get("accessToken") or not body.get("tokenType"):
            print("  STOP: accessToken or tokenType missing; docs do not say what to do. Ask the project owner.")
            _save(saved, args.symbol)
            return 1

        # 2. securitiesSummary: parameters exactly as in docs/ssi/06 (symbol, from, to; YYYY/MM/DD).
        today = fetched_at.date()
        params = {
            "symbol": args.symbol,
            "from": (today - timedelta(days=args.days)).strftime("%Y/%m/%d"),
            "to": today.strftime("%Y/%m/%d"),
        }
        url = f"{base}{SUMMARY_PATH}?{urllib.parse.urlencode(params)}"
        print(f"\n[2] GET {SUMMARY_PATH} {params}")
        auth_headers = dict(json_headers, Authorization=f"{body['tokenType']} {body['accessToken']}")
        status, hdrs, text = http("GET", url, auth_headers)
        body2 = parse_json(text)
        saved["securitiesSummary"] = {
            "request": {"method": "GET", "path": SUMMARY_PATH, "params": params},
            "status": status, "ratelimit": rate_limit_headers(hdrs),
            "body": mask(body2 if body2 is not None else text, secrets),
        }
        print(f"  HTTP {status}")
        print(f"  X-RATELIMIT-*: {rate_limit_headers(hdrs) or 'none received'}")
        if status != 200 or not isinstance(body2, dict):
            print(f"  response (masked): {json.dumps(saved['securitiesSummary']['body'], ensure_ascii=False)}")
            _save(saved, args.symbol)
            return 1
        print(f"  top-level fields: {sorted(body2)}")
        compare("page", set(body2), DOC_PAGE_FIELDS)
        items = body2.get("data")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            print(f"  item fields ({len(items)} item(s) on this page): {sorted(items[0])}")
            compare("item", set(items[0]), DOC_ITEM_FIELDS)
        else:
            print("  no data[] items found: structure differs from docs, or the range has no trading day. "
                  "Raw masked response saved; ask the project owner.")
    except SmokeError as e:
        print(f"ERROR: {mask(str(e), secrets)}", file=sys.stderr)
        return 1

    path = _save(saved, args.symbol)
    print(f"\nSaved masked raw responses to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
