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
from pathlib import Path

from liquidity_lens.envfile import load_env
from liquidity_lens.ssi.auth import TokenManager, urllib_http
from liquidity_lens.ssi.redact import mask
from liquidity_lens.ssi.securities import SECURITIES_PATH, describe_structure, fetch_securities_raw


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", default="HOSE", help="board code (default: HOSE)")
    ap.add_argument("--out-dir", default="data/smoke")
    args = ap.parse_args(argv)

    load_env()
    key, secret = os.environ.get("SSI_API_KEY", ""), os.environ.get("SSI_API_SECRET", "")
    missing = [n for n, v in (("SSI_API_KEY", key), ("SSI_API_SECRET", secret)) if not v]
    if missing:
        print(f"ERROR: missing environment variable(s): {', '.join(missing)} (see .env.example)", file=sys.stderr)
        return 2
    return run(args.board, Path(args.out_dir), TokenManager(key, secret))


if __name__ == "__main__":
    sys.exit(main())
