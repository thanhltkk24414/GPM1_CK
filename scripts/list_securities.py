"""List the securities of one board from SSI REST (read-only) and show the response STRUCTURE.

    python scripts/list_securities.py --board HOSE

Calls only GET /api/v3/data/securitiesByBoard (plus the token request). Saves the raw response unchanged to
data/smoke/securities_<BOARD>.json, prints the structure and 3 sample items, and does NOT decide which field is the
symbol code: that needs the project owner's confirmation. Never prints credentials or tokens.

One session per apiKey: do not run this while the collector is running (a new token would drop its WebSocket).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from liquidity_lens import config
from liquidity_lens.envfile import load_env
from liquidity_lens.ssi.auth import TokenManager, urllib_http
from liquidity_lens.ssi.redact import mask
from liquidity_lens.ssi.securities import SECURITIES_PATH, build_watchlist, describe_structure, fetch_securities_raw


def force_utf8_stdout() -> None:
    """Vietnamese names must print on a default Windows (cp1252) console instead of raising."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(board: str, out_dir: Path, manager: TokenManager, http=urllib_http, base_url: str | None = None) -> int:
    kwargs = {"base_url": base_url} if base_url else {}
    status, headers, text = fetch_securities_raw(board, manager.authorization, http, **kwargs)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"securities_{board.upper()}.json"
    path.write_text(text, encoding="utf-8", newline="")  # exactly as received

    def say(line: str) -> None:
        print(mask(line, manager.secrets()))

    say(f"GET {SECURITIES_PATH}?board={board.upper()}")
    say(f"HTTP {status}")
    limits = {k: v for k, v in headers.items() if k.upper().startswith("X-RATELIMIT-")}
    say(f"X-RATELIMIT-*: {limits or 'none received'}")
    say(f"saved the raw response unchanged to {path} ({len(text.encode('utf-8'))} bytes)")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        say("response is not JSON; first 200 characters:")
        say(text[:200])
        return 1
    info = describe_structure(parsed)
    say(f"top-level type: {info['type']}")
    if info["top_level_keys"] is not None:
        say(f"top-level keys: {info['top_level_keys']}")
    if not info["lists"]:
        say("no list found in the response")
    for list_path, lst in info["lists"].items():
        say(f"list at {list_path!r}: {lst['count']} item(s)")
        say(f"  fields of the first item: {lst['item_fields']}")
        for i, sample in enumerate(lst["samples"], 1):
            say(f"  sample {i}: {json.dumps(sample, ensure_ascii=False)}")
    say("Not inferred: which field holds the symbol code, or the security type. Waiting for confirmation.")
    return 0 if status == 200 else 1


def write_watchlist(board: str, out_dir: Path, target: Path, fetch_raw, now: datetime | None = None) -> int:
    """Write the watchlist file for `board` (stockType == "Stock" only).

    Uses data/smoke/securities_<BOARD>.json when it exists (its modification time is the fetch date); otherwise
    calls `fetch_raw()` -> (status, headers, text), saves the raw response and uses `now`.
    """
    raw_path = out_dir / f"securities_{board.upper()}.json"
    if raw_path.exists():
        text = raw_path.read_text(encoding="utf-8")
        fetched_at = datetime.fromtimestamp(raw_path.stat().st_mtime, tz=config.TZ)
        print(f"using the saved response {raw_path} (fetched {fetched_at.date().isoformat()})")
    else:
        result = fetch_raw()
        if result is None:
            return 2
        status, _, text = result
        if status != 200:
            print(f"HTTP {status}: not writing a watchlist")
            return 1
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(text, encoding="utf-8", newline="")
        fetched_at = now or datetime.now(config.TZ)
        print(f"fetched {board.upper()} from the API and saved the raw response to {raw_path}")
    try:
        content = build_watchlist(json.loads(text), board, fetched_at)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"STOP, no file written: {e}")
        return 3
    target.write_text(content, encoding="utf-8", newline="\n")
    n = len(content.splitlines()) - 1
    print(f"wrote {n} symbols ({n} lines after the comment) to {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", default="HOSE", help="board code (default: HOSE)")
    ap.add_argument("--out-dir", default="data/smoke")
    ap.add_argument("--write-watchlist", metavar="FILE",
                    help="write the board's stockType == Stock symbols to FILE (from the saved raw response if present)")
    args = ap.parse_args(argv)

    force_utf8_stdout()
    load_env()
    if args.write_watchlist:
        def fetch_raw():
            key, secret = os.environ.get("SSI_API_KEY", ""), os.environ.get("SSI_API_SECRET", "")
            if not (key and secret):
                print("ERROR: no saved response and SSI_API_KEY / SSI_API_SECRET are not set", file=sys.stderr)
                return None
            return fetch_securities_raw(args.board, TokenManager(key, secret).authorization)

        return write_watchlist(args.board, Path(args.out_dir), Path(args.write_watchlist), fetch_raw)
    key, secret = os.environ.get("SSI_API_KEY", ""), os.environ.get("SSI_API_SECRET", "")
    missing = [n for n, v in (("SSI_API_KEY", key), ("SSI_API_SECRET", secret)) if not v]
    if missing:
        print(f"ERROR: missing environment variable(s): {', '.join(missing)} (see .env.example)", file=sys.stderr)
        return 2
    return run(args.board, Path(args.out_dir), TokenManager(key, secret))


if __name__ == "__main__":
    sys.exit(main())
