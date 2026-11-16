"""Minimal .env reader (standard library only; no python-dotenv).

Used by the collector and scripts/smoke_test.py so they work from a plain PowerShell window. Values are
never printed or returned: load_env() reports variable NAMES only.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# <project root>/.env  (this file lives in <root>/src/liquidity_lens/)
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Blank lines and lines starting with '#' are skipped, whitespace around the key and
    value is stripped, and one pair of matching quotes around the value is removed. An optional 'export ' prefix
    is accepted. Malformed lines are ignored (their content is never echoed)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not _NAME_RE.match(name):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[name] = value
    return out


def load_env(path: str | Path | None = None) -> list[str]:
    """Load a .env file into os.environ and return the NAMES that were set.

    Never overwrites a variable that already has a non-empty value (the shell wins). A missing file is not an
    error. Reads with utf-8-sig so the BOM that Windows PowerShell adds is harmless.
    """
    env_path = Path(path) if path is not None else DEFAULT_ENV_PATH
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    loaded: list[str] = []
    for name, value in parse_env(text).items():
        if os.environ.get(name):
            continue
        os.environ[name] = value
        loaded.append(name)
    return loaded
