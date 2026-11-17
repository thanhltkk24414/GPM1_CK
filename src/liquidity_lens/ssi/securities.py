"""Read-only call to GET /api/v3/data/securitiesByBoard and a structure reader that makes no assumptions.

The response shape of this endpoint is not documented in docs/ssi/ (only the request example in 01-get-api-key.md),
so `describe_structure` reports what is there (every list it finds, the field names of the items, a few samples)
and never decides which field is the symbol code.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from typing import Any, Callable

from liquidity_lens import config
from liquidity_lens.ssi.auth import BASE_URL, HttpFn, urllib_http

SECURITIES_PATH = "/api/v3/data/securitiesByBoard"
_BOARD_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")


def fetch_securities_raw(
    board: str, authorization: Callable[[], str], http: HttpFn = urllib_http, base_url: str = BASE_URL
) -> tuple[int, dict, str]:
    """GET securitiesByBoard?board=<BOARD>. Returns (status, response headers, raw response text)."""
    if not _BOARD_RE.match(board):
        raise ValueError(f"board must be a plain code such as HOSE, got {board!r}")
    url = f"{base_url}{SECURITIES_PATH}?{urllib.parse.urlencode({'board': board.upper()})}"
    headers = {"Content-Type": "application/json", "User-Agent": "liquidity-lens-tools", "Authorization": authorization()}
    return http("GET", url, headers, None)


def _walk_lists(obj: Any, path: str, out: dict[str, list]) -> None:
    if isinstance(obj, list):
        out[path] = obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _walk_lists(value, key if path == "$" else f"{path}.{key}", out)


def describe_structure(parsed: Any, samples: int = 3) -> dict:
    """Top-level type and keys, plus every list found (path, item count, item field names, first samples)."""
    found: dict[str, list] = {}
    _walk_lists(parsed, "$", found)
    lists = {}
    for path, items in found.items():
        first = items[0] if items else None
        lists[path] = {
            "count": len(items),
            "item_fields": list(first) if isinstance(first, dict) else None,
            "samples": items[:samples],
        }
    return {
        "type": type(parsed).__name__,
        "top_level_keys": list(parsed) if isinstance(parsed, dict) else None,
        "lists": lists,
    }


STOCK_TYPE = "Stock"
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3}$")


def build_watchlist(items: Any, board: str, fetched_at: datetime) -> str:
    """Watchlist text for one board: only items with board == BOARD and stockType == "Stock" (confirmed by the
    project owner on 2026-11-17: code field = symbol, type field = stockType), sorted, no duplicates, one symbol
    per line, preceded by one comment line. Raises ValueError, writing nothing, if any kept symbol is not
    three upper-case letters/digits: unexpected codes are reported, never silently dropped."""
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("expected the response to be a list of objects")
    board = board.upper()
    kept = [i for i in items if i.get("board") == board and i.get("stockType") == STOCK_TYPE]
    odd = sorted({repr(i.get("symbol")) for i in kept if not _SYMBOL_RE.match(str(i.get("symbol")))})
    if odd:
        raise ValueError(f"unexpected symbol(s), expected ^[A-Z0-9]{{3}}$: {', '.join(odd)}")
    symbols = sorted({i["symbol"] for i in kept})
    when = fetched_at.astimezone(config.TZ).date().isoformat()
    header = (f"# source: securitiesByBoard; board: {board}; fetched: {when} ({config.TZ.key}); "
              f"filter: stockType == {STOCK_TYPE}; {len(symbols)} symbols")
    return "\n".join([header, *symbols]) + "\n"
