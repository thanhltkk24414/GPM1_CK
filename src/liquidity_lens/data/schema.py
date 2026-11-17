"""SQLite DDL, following docs/design.md section 4. Timestamps are ISO-8601 text with +07:00."""

TABLES = (
    "raw_message", "market_ref", "session_flag", "trade_tick",
    "book_snapshot", "metrics_1m", "alerts", "collector_events", "symbol_board",
)

DDL = """
CREATE TABLE IF NOT EXISTS raw_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_ref (
    trading_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    board TEXT,
    ceiling INTEGER,
    floor INTEGER,
    ref INTEGER,
    PRIMARY KEY (trading_date, symbol)
);
CREATE TABLE IF NOT EXISTS session_flag (
    board TEXT NOT NULL,
    ts TEXT NOT NULL,
    flag TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trade_tick (
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    price INTEGER NOT NULL,
    qty INTEGER NOT NULL,
    side TEXT,
    total_vol INTEGER,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trade_tick_symbol_ts ON trade_tick (symbol, ts);
CREATE TABLE IF NOT EXISTS book_snapshot (
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    received_at TEXT NOT NULL,
    bid_p1 INTEGER, bid_p2 INTEGER, bid_p3 INTEGER,
    bid_q1 INTEGER, bid_q2 INTEGER, bid_q3 INTEGER,
    ask_p1 INTEGER, ask_p2 INTEGER, ask_p3 INTEGER,
    ask_q1 INTEGER, ask_q2 INTEGER, ask_q3 INTEGER,
    n_bids INTEGER NOT NULL,
    n_asks INTEGER NOT NULL,
    session_flag TEXT,
    flags TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_book_snapshot_symbol_ts ON book_snapshot (symbol, ts);
CREATE TABLE IF NOT EXISTS metrics_1m (
    symbol TEXT NOT NULL,
    minute TEXT NOT NULL,
    spread_abs INTEGER,
    spread_bps REAL,
    spread_ticks REAL,
    obi1 REAL,
    obi3 REAL,
    depth_bid3 INTEGER,
    depth_ask3 INTEGER,
    depth_val_bid3 INTEGER,
    depth_val_ask3 INTEGER,
    volume INTEGER,
    z_obi3 REAL,
    z_spread_bps REAL,
    z_volume REAL,
    n_obs INTEGER,
    PRIMARY KEY (symbol, minute)
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    minute TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    z REAL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collector_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS symbol_board (
    symbol TEXT PRIMARY KEY,
    board TEXT NOT NULL
);
"""
