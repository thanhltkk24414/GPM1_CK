"""Smoke test for SSI FastConnect (Task 10): REST, then WebSocket.

Step 1: POST /api/v3/auth/token with apiKey + apiSecret only (no otp, no transactionId).
Step 1b: GET /api/v3/data/securitiesSummary for one HOSE symbol (skip with --skip-rest).
Step 2: WebSocket wss://stream.ssi.com.vn/ws/v3, header "Authorization: Bearer <accessToken>", SUBSCRIBE to
        quote/trade/market for 3 HOSE symbols plus market.flag, listen for --ws-seconds, save EVERY raw frame
        to data/smoke/ (masked), print statistics. Source of these WebSocket details: ssi-sdk 3.3.2, NOT yet
        verified against the real server (docs/ssi/10-python-sdk-notes.md).

Credentials come from the environment or the project-root .env file (SSI_API_KEY, SSI_API_SECRET). They, the access token and the refresh
token are never printed or written to disk. Read-only: never touches the Trading API, order.*, fco.* or the
TRADING channel. If the server refuses for OTP/permission reasons the script STOPS and reports; it never tries OTP.
Only one session per apiKey is allowed: do not run this while the collector is running.

Usage:  python scripts/smoke_test.py [--symbol SSI] [--days 7] [--ws-seconds 60] [--ws-symbols VIC,HPG,FPT]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from liquidity_lens import config
from liquidity_lens.envfile import load_env
from liquidity_lens.ssi.frames import FrameStats
from liquidity_lens.ssi.redact import mask

DEFAULT_BASE_URL = "https://api.ssi.com.vn"
DEFAULT_WS_URL = "wss://stream.ssi.com.vn/ws/v3"
DEFAULT_WS_SYMBOLS = "VIC,HPG,FPT"
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


# ---------------------------------------------------------------- WebSocket helpers

def ws_topics(symbols: list[str]) -> list[str]:
    return [f"{kind}.{s}" for s in symbols for kind in ("quote", "trade", "market")] + ["market.flag"]


def subscribe_frame(topics: list[str]) -> dict:
    return {"method": "SUBSCRIBE", "channel": "DATA", "topics": topics}


def pong_for(ping: dict) -> dict:
    # docs/ssi/04: client answers a server PING with PONG carrying the time field. Echo is [Kiểm tra].
    return {"method": "PONG", "channel": "HEARTBEAT", "time": ping.get("time")}


async def ws_stage(url: str, token_type: str, access_token: str, symbols: list[str], seconds: int,
                   secrets: list[str]) -> int:
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

    started = datetime.now(config.TZ)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"ws_{started.strftime('%Y%m%dT%H%M%S')}.jsonl"
    stats = FrameStats(secrets)
    topics = ws_topics(symbols)
    headers = {"Authorization": f"{token_type} {access_token}", "User-Agent": "liquidity-lens-smoke-test"}
    result = 1
    closed: tuple | None = None

    with open(path, "w", encoding="utf-8") as out:
        def log(direction: str, raw: str) -> None:
            rec = {"received_at": datetime.now(config.TZ).isoformat(timespec="milliseconds"),
                   "direction": direction, "raw": stats.mask_frame(raw)}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()

        out.write(json.dumps({
            "label": f"REAL DATA from SSI FastConnect WebSocket, started {started.isoformat(timespec='seconds')} "
                     f"({config.TZ.key}). Every frame as received, credentials masked. Not a DOC SAMPLE.",
            "url": url, "topics": topics, "listen_seconds": seconds,
        }, ensure_ascii=False) + "\n")

        print(f"\n[2] WebSocket {url}  topics={topics}")
        try:
            # ping_interval=None: SSI uses its own application-level HEARTBEAT, not WebSocket protocol pings.
            async with connect(url, additional_headers=headers, open_timeout=20, ping_interval=None) as ws:
                print("  connected (handshake accepted)")
                for frame in (subscribe_frame(topics), {"method": "LIST_SUBSCRIPTION"}):
                    text = json.dumps(frame)
                    await ws.send(text)
                    log("out", text)
                print(f"  SUBSCRIBE + LIST_SUBSCRIPTION sent; listening {seconds}s")
                loop = asyncio.get_running_loop()
                end = loop.time() + seconds
                while (remaining := end - loop.time()) > 0:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), remaining)
                    except asyncio.TimeoutError:
                        break
                    except ConnectionClosed as e:
                        closed = (e.rcvd.code if e.rcvd else None, e.rcvd.reason if e.rcvd else None)
                        break
                    raw = msg if isinstance(msg, str) else msg.decode("utf-8", "replace")
                    log("in", raw)
                    before = len(stats.rejections)
                    kind = stats.add(raw)
                    if kind == "heartbeat":
                        obj = parse_json(raw)
                        if isinstance(obj, dict) and obj.get("method") == "PING":
                            pong = json.dumps(pong_for(obj))
                            await ws.send(pong)
                            log("out", pong)
                            stats.add(pong, "out")
                    if len(stats.rejections) > before:
                        print("  STOP: a frame looks like an OTP/permission refusal. Not retrying, not trying OTP.")
                        result = 3
                        break
                if result != 3:
                    result = 0
        except InvalidStatus as e:
            body = e.response.body.decode("utf-8", "replace") if e.response.body else ""
            print(f"  REJECTED at handshake: HTTP {e.response.status_code}; body (masked): {mask(body, secrets)[:300]}")
            if any(k in body.lower() for k in ("otp", "permission", "forbidden", "unauthori")):
                result = 3
        except (OSError, TimeoutError, WebSocketException) as e:
            print(f"  connection failed: {type(e).__name__}: {mask(str(e), secrets)}")

    if closed is not None:
        print(f"  server closed the connection: code={closed[0]} reason={mask(str(closed[1]), secrets)!r}")
    print(f"  frames saved to {path} (every frame, masked)")
    print("  " + stats.report().replace("\n", "\n  "))
    if result == 0 and stats.total == 0:
        print("  NOTE: connected but no frame arrived. If the market is closed this is expected; "
              "the subscribe cannot be confirmed without an acknowledgement frame.")
    return result


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="SSI", help="HOSE symbol for the REST summary (default: SSI)")
    ap.add_argument("--days", type=int, default=7, help="REST look-back window in calendar days")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="override only for local fake-server tests")
    ap.add_argument("--ws-url", default=DEFAULT_WS_URL, help="override only for local fake-server tests")
    ap.add_argument("--ws-seconds", type=int, default=60, help="how long to listen on the WebSocket")
    ap.add_argument("--ws-symbols", default=DEFAULT_WS_SYMBOLS, help="comma-separated HOSE symbols")
    ap.add_argument("--skip-rest", action="store_true", help="skip the securitiesSummary call")
    ap.add_argument("--skip-ws", action="store_true", help="skip the WebSocket step")
    args = ap.parse_args(argv)

    load_env()  # project-root .env; variables already set in the shell win
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
    rc = 0

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
        for name in ("accessToken", "refreshToken"):
            if body.get(name):
                secrets.append(body[name])
        if not body.get("accessToken") or not body.get("tokenType"):
            print("  STOP: accessToken or tokenType missing; docs do not say what to do. Ask the project owner.")
            _save(saved, args.symbol)
            return 1

        # 1b. securitiesSummary: parameters exactly as in docs/ssi/06 (symbol, from, to; YYYY/MM/DD).
        if not args.skip_rest:
            today = fetched_at.date()
            params = {
                "symbol": args.symbol,
                "from": (today - timedelta(days=args.days)).strftime("%Y/%m/%d"),
                "to": today.strftime("%Y/%m/%d"),
            }
            url = f"{base}{SUMMARY_PATH}?{urllib.parse.urlencode(params)}"
            print(f"\n[1b] GET {SUMMARY_PATH} {params}")
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
                rc = 1
            else:
                print(f"  top-level fields: {sorted(body2)}")
                compare("page", set(body2), DOC_PAGE_FIELDS)
                items = body2.get("data")
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    print(f"  item fields ({len(items)} item(s) on this page): {sorted(items[0])}")
                    compare("item", set(items[0]), DOC_ITEM_FIELDS)
        path = _save(saved, args.symbol)
        print(f"\nSaved masked REST responses to {path}")

        # 2. WebSocket.
        if not args.skip_ws:
            symbols = [s.strip().upper() for s in args.ws_symbols.split(",") if s.strip()]
            ws_rc = asyncio.run(ws_stage(args.ws_url, body["tokenType"], body["accessToken"], symbols,
                                         args.ws_seconds, secrets))
            rc = rc or ws_rc
    except SmokeError as e:
        print(f"ERROR: {mask(str(e), secrets)}", file=sys.stderr)
        return 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
