from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from liquidity_lens.data.schema import DDL, TABLES


def init_db(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(DDL)
    conn.commit()
    return conn


def insert_many(
    conn: sqlite3.Connection, table: str, rows: Sequence[Mapping[str, Any]], commit: bool = True
) -> int:
    """Insert rows in a single transaction. Column names come from the first row's keys.

    With commit=False the caller owns the transaction and must commit (used for batched writes).
    """
    if table not in TABLES:
        raise ValueError(f"unknown table: {table!r}")
    if not rows:
        return 0
    cols = list(rows[0].keys())
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    if commit:
        with conn:
            conn.executemany(sql, rows)
    else:
        conn.executemany(sql, rows)
    return len(rows)
