# LIQUIDITY LENS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây hệ thống thu thập sổ lệnh SSI theo thời gian thực, tính Spread/OBI/Depth/Rolling Z-score, phát cảnh báo thống kê và hiển thị trên dashboard Streamlit.

**Architecture:** Hai tiến trình tách biệt: collector (WebSocket → raw → chuẩn hóa → SQLite) và dashboard (chỉ đọc SQLite). Lớp `finance/` và `analytics/` là hàm thuần, kiểm thử được không cần mạng. **Phase 1 (Task 1–9) không cần API key**, chạy được bằng dữ liệu phát lại; **Phase 2 (Task 10–15) bị chặn bởi key và xác minh API**.

**Tech Stack:** Python ≥ 3.10, sqlite3, pytest, tzdata; Phase 2 thêm websockets, requests, streamlit, plotly, pandas.

**Spec:** `docs/design.md`

## Global Constraints

- Python ≥ 3.10 (giả định, chưa xác nhận máy người dùng).
- Mọi timestamp lưu/hiển thị theo `Asia/Ho_Chi_Minh` (UTC+7).
- Giá nội bộ là VND số nguyên. Giá `quote`/`market`/`put` từ API nhân `QUOTE_PRICE_MULTIPLIER = 1000` (giả định, xác minh ngày có key); `trade.p` đã là đồng.
- Không gọi Trading API, `order.*`, `fco.*`, kênh `TRADING`. Token request không có `otp`/`transactionId`. Subscribe chỉ kênh `DATA`.
- Không khóa trong repo: `SSI_API_KEY`, `SSI_API_SECRET` qua biến môi trường. Tệp `data/*.db` và `.env` không commit.
- Dữ liệu trong `tests/fixtures/` là mẫu từ tài liệu SSI, gắn nhãn `DOC SAMPLE`, không phải dữ liệu thị trường.
- OBI/Z-score chỉ mô tả trạng thái; thông điệp cảnh báo dùng cụm "bất thường thống kê", không dùng "thao túng".
- REST: tôn trọng `X-RATELIMIT-*`; dữ liệu thời gian thực dùng WebSocket, không lặp REST.

## Review Focus

1. Sổ lệnh một phía (mã trần/sàn): spread và OBI phải là `None`, không phải 0 hay lỗi chia 0. Test ở Task 2.
2. Cửa sổ z-score có phương sai bằng 0 hoặc chưa đủ quan sát: kết quả `None`, không `inf`/`nan`. Test ở Task 3.
3. Snapshot ATO/ATC/nghỉ trưa lọt vào chuỗi chỉ số và cửa sổ z-score. Test ở Task 7 và Task 8.
4. Lẫn đơn vị giá (đồng và nghìn đồng) làm sai spread theo tick và depth theo giá trị. Test ở Task 5.
5. Sổ chéo, giá ngoài biên trần/sàn, thứ tự mức sai bị tính chỉ số như bình thường. Test ở Task 6.

---

## File Structure

```
liquidity-lens/
├── CLAUDE.md, README.md, pyproject.toml, .gitignore, .env.example
├── docs/design.md, docs/ssi/ (tài liệu SSI đã lưu), docs/superpowers/plans/
├── src/liquidity_lens/
│   ├── config.py
│   ├── finance/   orderbook.py  metrics.py  zscore.py
│   ├── data/      schema.py  store.py  normalize.py  quality.py
│   ├── analytics/ bars.py  alerts.py
│   ├── collector/ pipeline.py  replay.py  main.py(P2)
│   ├── ssi/       auth.py  stream.py (P2)
│   └── app/       queries.py  dashboard.py (P2)
├── scripts/       smoke_test.py (P2)  reconcile.py (P2)
├── tests/         fixtures/ssi_doc_samples.py  test_*.py
└── data/          (không commit)  data_sample/
```

---

### Task 1: Scaffold và cấu hình

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `src/liquidity_lens/__init__.py`, `src/liquidity_lens/config.py`, `tests/test_config.py`
- (CLAUDE.md và docs/design.md đã có)

**Interfaces:**
- Produces: `config.TZ: ZoneInfo`, `config.QUOTE_PRICE_MULTIPLIER: int`, `config.DB_PATH: Path`, `config.CONTINUOUS_FLAGS: frozenset[str]`.

- [ ] **Step 1: Write the failing test** `tests/test_config.py::test_defaults`
```python
def test_defaults():
    from zoneinfo import ZoneInfo
    from liquidity_lens import config
    assert config.TZ == ZoneInfo("Asia/Ho_Chi_Minh")
    assert config.QUOTE_PRICE_MULTIPLIER == 1000
    assert config.DB_PATH.as_posix().endswith("data/liquidity_lens.db")
    assert config.CONTINUOUS_FLAGS == frozenset({"LO"})
```
- [ ] **Step 2: Run** `pytest tests/test_config.py -v` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `pyproject.toml` (src layout, deps `tzdata`, dev extra `pytest`; `pythonpath=["src"]` trong cấu hình pytest), `.gitignore` (`.env`, `.venv/`, `data/*.db*`, `__pycache__/`), `.env.example` (chỉ tên `SSI_API_KEY=`, `SSI_API_SECRET=`), `config.py` với bốn hằng trên (`DB_PATH` đọc từ biến `LL_DB_PATH` nếu có), `README.md` khung (cài đặt, chạy test, link `docs/design.md`).
- [ ] **Step 4: Run** `pip install -e ".[dev]" && pytest -q` → 1 passed.
- [ ] **Step 5: Verify ignore** `git init && git check-ignore .env data/x.db` → in ra cả hai đường dẫn.
- [ ] **Step 6: Commit** `git add -A && git commit -m "chore: scaffold project"`

### Task 2: Mô hình sổ lệnh và chỉ số

**Files:**
- Create: `src/liquidity_lens/finance/orderbook.py`, `src/liquidity_lens/finance/metrics.py`, `tests/fixtures/ssi_doc_samples.py`, `tests/test_metrics.py`

**Interfaces:**
- Produces (`orderbook.py`): `@dataclass(frozen=True) Level(price: int, qty: int)`; `@dataclass(frozen=True) BookSnapshot(symbol: str, ts: datetime, bids: tuple[Level, ...], asks: tuple[Level, ...], received_at: datetime | None = None)`.
- Produces (`metrics.py`): `mid_price(b) -> float|None`, `spread_abs(b) -> int|None`, `spread_bps(b) -> float|None`, `spread_ticks(b, tick: int) -> float|None`, `obi(b, k: int) -> float|None`, `depth_qty(b, side: Literal["bid","ask"], k: int) -> int`, `depth_value(b, side, k) -> int`, `SlippageResult(filled: bool, avg_price: float|None, slippage_bps: float|None)`, `buy_slippage(b, qty: int, k: int = 3) -> SlippageResult`.
- Quy tắc: mức được dùng theo thứ tự đã cho (giả định tốt nhất trước; Task 6 gắn cờ nếu sai); `obi` và `spread_*` trả `None` khi một phía trống hoặc tổng khối lượng bằng 0.

- [ ] **Step 1: Write failing tests** (fixture `BOOK`: bids `[(45450,3200),(45400,1500),(45350,4200)]`, asks `[(45500,2800),(45550,1900),(45600,3600)]`, nhãn `DOC SAMPLE` suy từ mẫu `quote` của SSI sau khi nhân 1000)
```python
def test_spread_and_mid():
    assert mid_price(BOOK) == 45475.0
    assert spread_abs(BOOK) == 50
    assert spread_bps(BOOK) == pytest.approx(10.99505, abs=1e-4)
    assert spread_ticks(BOOK, tick=50) == 1.0
def test_obi():
    assert obi(BOOK, 1) == pytest.approx(400/6000)
    assert obi(BOOK, 3) == pytest.approx(600/17200)
def test_depth():
    assert depth_qty(BOOK, "bid", 3) == 8900 and depth_qty(BOOK, "ask", 3) == 8300
    assert depth_value(BOOK, "bid", 3) == 404_010_000
    assert depth_value(BOOK, "ask", 3) == 378_105_000
def test_buy_slippage_within_depth():
    r = buy_slippage(BOOK, 4000)
    assert r.filled and r.avg_price == 45515.0
    assert r.slippage_bps == pytest.approx(8.79604, abs=1e-4)
def test_buy_slippage_exceeds_visible_depth():
    r = buy_slippage(BOOK, 20000)
    assert (r.filled, r.avg_price, r.slippage_bps) == (False, None, None)
def test_one_sided_book_returns_none():   # Review Focus 1
    b = replace(BOOK, asks=())
    assert spread_abs(b) is None and spread_bps(b) is None and obi(b, 3) is None
    assert mid_price(b) is None
```
- [ ] **Step 2: Run** `pytest tests/test_metrics.py -v` → FAIL (import error).
- [ ] **Step 3: Implement** các hàm trên trong `orderbook.py`, `metrics.py` (hàm thuần, không phụ thuộc ngoài thư viện chuẩn).
- [ ] **Step 4: Run** → 6 passed.
- [ ] **Step 5: Commit** `git commit -am "feat: orderbook metrics"` (sau `git add`).

### Task 3: Rolling Z-score

**Files:** Create `src/liquidity_lens/finance/zscore.py`, `tests/test_zscore.py`

**Interfaces:**
- Produces: `rolling_zscore(values: Sequence[float|None], window: int, min_periods: int, groups: Sequence[Hashable] | None = None) -> list[float|None]`
- Quy tắc: tại i, lấy tối đa `window` giá trị không-`None` **đứng trước** i trong cùng nhóm; ít hơn `min_periods` → `None`; độ lệch chuẩn mẫu (ddof=1) bằng 0 → `None`; `values[i]` là `None` → `None`.

- [ ] **Step 1: Write failing tests**
```python
def test_basic():
    assert rolling_zscore([1,2,3,4,5], window=3, min_periods=3) == [None, None, None, 2.0, 2.0]
def test_zero_variance_returns_none():   # Review Focus 2
    assert rolling_zscore([5,5,5,5], 3, 3) == [None, None, None, None]
def test_groups_do_not_cross():
    out = rolling_zscore([1,2,3,4,1,2,3,4], 3, 3, groups=list("AAAABBBB"))
    assert out[3] == 2.0 and out[4:7] == [None, None, None] and out[7] == 2.0
def test_none_values_skipped():
    assert rolling_zscore([1,2,None,3,4], 3, 3)[4] is not None
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `rolling_zscore` bằng `statistics.stdev`/`mean` (hoặc tương đương), O(n·window) là đủ.
- [ ] **Step 4: Run** → 4 passed.
- [ ] **Step 5: Commit.**

### Task 4: Schema SQLite và ghi theo lô

**Files:** Create `src/liquidity_lens/data/schema.py`, `src/liquidity_lens/data/store.py`, `tests/test_store.py`

**Interfaces:**
- Produces: `init_db(path: str | Path) -> sqlite3.Connection` (tạo đủ 8 bảng theo `docs/design.md` mục 4, `PRAGMA journal_mode=WAL`, `row_factory=sqlite3.Row`); `insert_many(conn, table: str, rows: Sequence[Mapping[str, Any]]) -> int` (một giao dịch; `table` phải thuộc danh sách bảng hợp lệ, ngược lại `ValueError`).

- [ ] **Step 1: Write failing tests**: `test_tables_exist` (đủ 8 tên bảng), `test_wal_enabled` (`PRAGMA journal_mode` trả `"wal"`), `test_insert_many_and_second_connection_reads` (chèn 1000 dòng `trade_tick`; kết nối thứ hai đọc `COUNT(*) == 1000`), `test_unknown_table_rejected` (`pytest.raises(ValueError)`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** DDL trong `schema.py` đúng cột ở design; `insert_many` dựng câu lệnh từ khóa của dòng đầu, dùng `executemany`.
- [ ] **Step 4: Run** → 4 passed.
- [ ] **Step 5: Commit.**

### Task 5: Phân tích thông điệp SSI

**Files:** Create `src/liquidity_lens/data/normalize.py`; Modify `tests/fixtures/ssi_doc_samples.py` (thêm `QUOTE`, `TRADE`, `MARKET_REF`, `MARKET_FLAG` đúng như mẫu trong tài liệu SSI, nhãn `DOC SAMPLE`); Test `tests/test_normalize.py`

**Interfaces:**
- Consumes: `Level`, `BookSnapshot` (Task 2), `config.TZ`, `config.QUOTE_PRICE_MULTIPLIER`.
- Produces: `parse_vn_time(s: str) -> datetime` (định dạng `YYYY/MM/DD HH:mm:ss`, gắn `config.TZ`); `parse_quote(payload: dict, received_at: datetime, price_multiplier: int = QUOTE_PRICE_MULTIPLIER) -> BookSnapshot`; `@dataclass TradeTick(symbol, ts, price: int, qty: int, side: str, total_vol: int, received_at)` và `parse_trade(payload, received_at) -> TradeTick`; `@dataclass MarketRef(symbol, board, trading_date: date, ceiling: int, floor: int, ref: int)` và `parse_market_ref(payload, price_multiplier=...) -> MarketRef`; `@dataclass SessionFlag(board, ts, flag)` và `parse_session_flag(payload) -> SessionFlag`.
- Quy tắc: đổi giá bằng `int(Decimal(s) * multiplier)` (tránh sai số float); `parse_trade` **không** nhân hệ số (đã là đồng).

- [ ] **Step 1: Write failing tests**
```python
def test_quote_prices_scaled_to_vnd():     # Review Focus 4
    b = parse_quote(QUOTE, RECEIVED)
    assert b.bids[0] == Level(45450, 3200) and b.asks[0] == Level(45500, 2800)
    assert len(b.bids) == 5 and b.symbol == "SSI"
    assert b.ts == datetime(2026, 7, 29, 9, 15, 32, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
def test_trade_price_not_scaled():
    t = parse_trade(TRADE, RECEIVED)
    assert (t.price, t.qty, t.side, t.total_vol) == (45500, 1000, "B", 1_250_000)
def test_market_ref():
    r = parse_market_ref(MARKET_REF)
    assert (r.ceiling, r.floor, r.ref, r.board) == (48500, 42100, 45300, "HOSE")
def test_session_flag():
    assert parse_session_flag(MARKET_FLAG).flag == "ATO"
def test_multiplier_is_applied():
    assert parse_quote(QUOTE, RECEIVED, price_multiplier=1).bids[0].price == 45
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** các hàm và dataclass trên.
- [ ] **Step 4: Run** → 5 passed.
- [ ] **Step 5: Commit.**

### Task 6: Kiểm tra chất lượng sổ lệnh

**Files:** Create `src/liquidity_lens/data/quality.py`, `tests/test_quality.py`

**Interfaces:**
- Consumes: `BookSnapshot`, `MarketRef`.
- Produces: `quality_flags(book: BookSnapshot, ref: MarketRef | None = None, tick: int | None = None) -> frozenset[str]` với các cờ `EMPTY_BID`, `EMPTY_ASK`, `CROSSED` (bid1 ≥ ask1), `BID_ORDER` (giá mua không giảm dần chặt), `ASK_ORDER`, `OUT_OF_BAND` (giá ngoài [floor, ceiling] khi có `ref`), `OFF_TICK` (giá không chia hết `tick` khi có `tick`), `BAD_QTY` (qty ≤ 0); `is_usable(flags: frozenset[str]) -> bool` (False nếu có `CROSSED`, `BID_ORDER`, `ASK_ORDER`, `OUT_OF_BAND`, `BAD_QTY`; `EMPTY_*` vẫn usable, chỉ số trả `None`).

- [ ] **Step 1: Write failing tests**: `test_clean_book_has_no_flags` (BOOK → `frozenset()`); `test_crossed_book` (bid1=45500, ask1=45450 → `"CROSSED"` trong cờ và `is_usable` False); `test_bid_order`, `test_ask_order`; `test_out_of_band` (ref ceiling 45400, floor 42100 với BOOK → có `OUT_OF_BAND`); `test_off_tick` (tick=100 với giá 45450 → `OFF_TICK`); `test_bad_qty`; `test_empty_side_is_usable_but_flagged` (asks=() → `{"EMPTY_ASK"}` và `is_usable` True).  (Review Focus 5)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → 7 passed.
- [ ] **Step 5: Commit.**

### Task 7: Gom snapshot thành thanh 1 phút

**Files:** Create `src/liquidity_lens/analytics/bars.py`, `tests/test_bars.py`

**Interfaces:**
- Consumes: Task 2 (metrics), Task 5 (`TradeTick`), Task 6 (`quality_flags`, `is_usable`), `config.CONTINUOUS_FLAGS`.
- Produces: `@dataclass MinuteBar(symbol: str, minute: datetime, spread_abs: int|None, spread_bps: float|None, spread_ticks: float|None, obi1: float|None, obi3: float|None, depth_bid3: int, depth_ask3: int, depth_val_bid3: int, depth_val_ask3: int, volume: int)`; `to_minute_bars(books: Sequence[tuple[BookSnapshot, str | None]], trades: Sequence[TradeTick], tick: int | None = None, continuous_flags: frozenset[str] = CONTINUOUS_FLAGS) -> list[MinuteBar]` (phần tử thứ hai của cặp là cờ phiên lúc đó).
- Quy tắc: chỉ lấy snapshot có cờ phiên thuộc `continuous_flags` và `is_usable`; mỗi (mã, phút) lấy snapshot **cuối cùng**; phút không có snapshot hợp lệ thì **không có thanh** (không điền tiếp); `volume` = tổng `qty` các `TradeTick` của mã trong phút.

- [ ] **Step 1: Write failing tests**: `test_auction_and_lunch_excluded` (snapshot 09:00:10 cờ `"ATO"`, 09:15:05 và 09:15:40 cờ `"LO"`, 12:00:00 cờ `None` → đúng một thanh lúc 09:15 lấy dữ liệu của 09:15:40);  `test_unusable_snapshot_skipped` (sổ chéo trong phiên `LO` không tạo thanh); `test_volume_sums_trades_in_minute`; `test_no_forward_fill` (09:15 và 09:18 có dữ liệu → đúng 2 thanh).  (Review Focus 3)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → 4 passed.
- [ ] **Step 5: Commit.**

### Task 8: Z-score theo thanh và cảnh báo

**Files:** Create `src/liquidity_lens/analytics/alerts.py`, `tests/test_alerts.py`

**Interfaces:**
- Consumes: `MinuteBar` (Task 7), `rolling_zscore` (Task 3).
- Produces: `score_bars(bars: Sequence[MinuteBar], window: int = 30, min_periods: int = 15) -> list[dict[str, float | None]]` (mỗi phần tử có khóa `obi3`, `spread_bps`, `volume`; nhóm theo `(symbol, ngày, "AM" nếu giờ < 12 ngược lại "PM")`); `@dataclass Alert(symbol, minute, metric: str, value: float, z: float, severity: Literal["WATCH","ALERT"], message: str)`; `detect_alerts(symbol: str, minute: datetime, values: Mapping[str, float|None], zscores: Mapping[str, float|None], watch: float, alert: float) -> list[Alert]`; `calibrate_threshold(abs_z: Sequence[float], percentile: float) -> float` (nội suy tuyến tính, `percentile` trong [0,1]).
- Quy tắc: `|z| ≥ alert` → `ALERT`, `≥ watch` → `WATCH`; `z` là `None` thì không cảnh báo; `message` chứa "bất thường thống kê" và không chứa "thao túng".

- [ ] **Step 1: Write failing tests**: `test_calibrate_threshold` (`calibrate_threshold(list(range(101)), 0.99) == 99.0`); `test_alert_severity` (z=2.5, watch=2, alert=3 → một `WATCH`; z=-3.2 → `ALERT`); `test_none_z_no_alert`; `test_message_wording`; `test_score_bars_resets_between_am_pm` (các thanh sáng đủ cửa sổ, thanh đầu tiên buổi chiều có `obi3` z là `None`).  (Review Focus 3)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → 5 passed.
- [ ] **Step 5: Commit.**

### Task 9: Pipeline và phát lại dữ liệu

**Files:** Create `src/liquidity_lens/collector/pipeline.py`, `src/liquidity_lens/collector/replay.py`, `tests/test_pipeline.py`, `tests/fixtures/replay_sample.jsonl` (nhãn `DOC SAMPLE`)

**Interfaces:**
- Consumes: Task 4–6.
- Produces: `class Pipeline(conn: sqlite3.Connection, tick_for: Callable[[str, int], int] | None = None)` với `handle(kind: Literal["quote","trade","market_ref","market_flag"], payload: dict, received_at: datetime) -> None`; `replay_jsonl(pipeline: Pipeline, path: str | Path) -> int` (mỗi dòng `{"received_at": ISO-8601, "kind": ..., "payload": {...}}`, trả số dòng xử lý).
- Quy tắc: luôn ghi `raw_message`; `quote` → `book_snapshot` kèm `session_flag` hiện hành của sàn (từ `market_ref` của mã, `None` nếu chưa biết) và `flags`; bỏ snapshot trùng hệt snapshot liền trước của cùng mã (so sánh bids/asks); `trade`, `market_ref`, `market_flag` ghi vào bảng tương ứng.

- [ ] **Step 1: Write failing tests**: `test_raw_always_stored_dedupe_snapshots` (phát lại 3 `quote` của cùng mã, hai cái đầu giống hệt nhau, cái thứ ba khác → `raw_message` 3 dòng, `book_snapshot` 2 dòng); `test_session_flag_attached` (`market_ref` SSI/HOSE, `market_flag` HOSE `"ATO"`, rồi `quote` SSI → `book_snapshot.session_flag == "ATO"`); `test_flags_recorded` (quote sổ chéo → cột `flags` chứa `CROSSED`); `test_replay_counts_lines`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -q` → toàn bộ pass.
- [ ] **Step 5: Commit** `git commit -m "feat: pipeline and replay"`.

---

## Phase 2 — chỉ bắt đầu khi có key và đã xác minh (Gate)

**Gate G1:** `apiKey`/`apiSecret` đã tạo, lưu trong `.env`. **Gate G2:** đã biết cách gắn token vào kết nối WebSocket và vai trò `client_id` (lấy từ mục Thực hành/SDK của SSI, lưu vào `docs/ssi/`). Mỗi task dưới đây chỉ chốt chi tiết cài đặt sau khi các điểm [Kiểm tra] liên quan trong `docs/design.md` đã được ghi kết quả.

### Task 10: Smoke test thu thông điệp thô (G1, G2)
**Files:** Create `scripts/smoke_test.py`
**Interfaces:** CLI `python scripts/smoke_test.py --symbols SSI,ACB --minutes 10 --out data_sample/` ghi JSONL `{"received_at","kind","payload"}` (cùng định dạng replay).
- [ ] **Step 1:** Viết script: lấy token, kết nối, subscribe `quote`, `trade`, `market`, trả PONG, ghi tệp; cuối chạy in bảng kiểm: số mức giá mỗi phía, thứ tự giá, nghi vấn đơn vị giá, chênh lệch `t` so với đồng hồ máy (múi giờ), số thông điệp/phút, có/không cờ phiên.
- [ ] **Step 2:** Chạy trong giờ giao dịch. Kỳ vọng: tệp JSONL có ít nhất một `quote` mỗi mã và bảng kiểm in ra không lỗi.
- [ ] **Step 3:** Ghi kết quả từng mục [Kiểm tra] vào `docs/design.md` (đổi nhãn thành [Xác nhận] hoặc sửa giả định). Nếu đơn vị giá hoặc số mức khác giả định, sửa `config.py` và test Task 5 trước khi đi tiếp.
- [ ] **Step 4: Commit** (không commit dữ liệu chứa thông tin nhạy cảm; thông điệp thị trường công khai thì được).

### Task 11: Xác thực (G1)
**Files:** Create `src/liquidity_lens/ssi/auth.py`, `tests/test_auth.py`
**Interfaces:** `normalize_epoch(value: int) -> datetime` (10 chữ số = giây, 13 chữ số = mili-giây, trả `datetime` gắn `config.TZ`); `@dataclass TokenSet(access_token, refresh_token, expires_at: datetime, refresh_expires_at: datetime)`; `request_token(api_key: str, api_secret: str, http: Callable) -> TokenSet`; `refresh_token(refresh: str, http: Callable) -> TokenSet`; `needs_refresh(t: TokenSet, now: datetime, margin_s: int = 300) -> bool`.
- [ ] **Step 1: Failing tests:** `normalize_epoch(1779806203) == normalize_epoch(1779806203000)`; `test_token_body_has_no_otp` (http giả ghi lại body, khẳng định chỉ có khóa `apiKey`, `apiSecret`); `test_needs_refresh_margin`.
- [ ] **Step 2–5:** Chạy FAIL, cài đặt, chạy PASS, commit.

### Task 12: Luồng WebSocket (G2)
**Files:** Create `src/liquidity_lens/ssi/stream.py`, `tests/test_stream.py`
**Interfaces:** `build_subscribe(topics: Sequence[str]) -> dict` (kênh `"DATA"`; `ValueError` nếu topic bắt đầu bằng `order.` hoặc `portfolio.`); `build_unsubscribe(topics) -> dict`; `pong_for(ping: dict) -> dict` (giả định phản hồi lại `time` của PING, xác minh ở Task 10); `class StreamClient` với vòng lặp kết nối lại backoff lũy tiến, subscribe lại sau mỗi lần nối, làm mới token trước khi hết hạn, ghi `collector_events`.
- [ ] **Step 1: Failing tests:** `build_subscribe(["quote.SSI"]) == {"method":"SUBSCRIBE","channel":"DATA","topics":["quote.SSI"]}`; `build_subscribe(["order.0001"])` raise `ValueError`; `pong_for({"method":"PING","channel":"HEARTBEAT","time":"16-11-2026 09-00-05"}) == {"method":"PONG","channel":"HEARTBEAT","time":"16-11-2026 09-00-05"}`; kiểm thử với websocket giả: ngắt kết nối giữa chừng thì client nối lại và gửi lại đúng thông điệp subscribe.
- [ ] **Step 2–5:** FAIL, cài đặt, PASS, commit.

### Task 13: Collector chạy thật
**Files:** Create `src/liquidity_lens/collector/main.py`
**Interfaces:** `python -m liquidity_lens.collector.main --symbols FILE --db PATH` nối `StreamClient` → `Pipeline`, ghi theo lô, tự dừng sau giờ giao dịch (giờ đóng cửa lấy từ kết quả Task 10), ghi tổng kết phiên vào `collector_events`.
- [ ] **Step 1:** Cài đặt nối các thành phần (không có logic mới).
- [ ] **Step 2: Verify** chạy 5 phút trong giờ giao dịch với 2 mã. Kỳ vọng: `book_snapshot` > 0 dòng, `collector_events` có `connect`, không có lỗi chưa xử lý, ngắt wifi 30 giây thì tự nối lại và dữ liệu tiếp tục.
- [ ] **Step 3: Commit.** Từ đây chạy mỗi phiên và kiểm tra `SELECT COUNT(*)` cuối ngày.

### Task 14: Dashboard
**Files:** Create `src/liquidity_lens/app/queries.py`, `src/liquidity_lens/app/dashboard.py`, `tests/test_queries.py`
**Interfaces:** `latest_update(conn) -> datetime | None`; `load_minute_metrics(conn, symbol: str, since: datetime) -> list[dict]`; `liquidity_ranking(conn, minute: datetime) -> list[dict]` (xếp hạng theo spread_bps tăng dần và depth_val giảm dần). Dashboard Streamlit theo Mục 6 của đề: tên và mục tiêu, thời điểm cập nhật và trạng thái kết nối, ≥3 chỉ số, ≥2 biểu đồ (sổ lệnh Plotly, chuỗi thời gian OBI/spread), bộ lọc mã và thời gian, bảng cảnh báo và xếp hạng, ghi chú phương pháp và giới hạn, trạng thái "không có dữ liệu".
- [ ] **Step 1: Failing tests** cho `queries.py` trên DB tạm từ `replay_jsonl`: `latest_update` là `None` với DB rỗng; `load_minute_metrics` trả đúng số dòng và thứ tự thời gian; `liquidity_ranking` xếp mã spread hẹp hơn trước.
- [ ] **Step 2–4:** FAIL, cài đặt, PASS.
- [ ] **Step 5: Verify thủ công** `streamlit run src/liquidity_lens/app/dashboard.py` với DB có dữ liệu và với DB rỗng. Kỳ vọng: không treo, không lỗi, hiện thông báo trạng thái dữ liệu rõ ràng.
- [ ] **Step 6: Commit.**

### Task 15: Đối chiếu và hiệu chỉnh ngưỡng
**Files:** Create `scripts/reconcile.py`, `tests/test_reconcile.py`
**Interfaces:** `reconcile_volume(ws_total: int, rest_total: int, tolerance: float = 0.0) -> ReconcileResult(match: bool, diff: int, rel_diff: float)`; script so sánh `trade_tick.total_vol` cuối phiên với `totalMatch` của `securitiesSummary` theo mã/ngày (tôn trọng `X-RATELIMIT-*`, phân trang), và chạy `calibrate_threshold` trên |z| đã tích lũy để đề xuất `watch`/`alert`.
- [ ] **Step 1: Failing tests:** bằng nhau → `match=True`; lệch 1% với `tolerance=0` → `match=False, diff` đúng.
- [ ] **Step 2–5:** FAIL, cài đặt, PASS, commit. Kết quả đối chiếu và bảng ngưỡng dùng cho Chương 7 báo cáo.

---

## Self-Review (đã chạy)

- **Spec coverage:** Spread/OBI/Depth/trượt giá → Task 2; Z-score → 3, 8; schema → 4; quy tắc ATO/ATC, chất lượng, trùng → 6, 7, 9; collector, token, heartbeat → 11–13; dashboard → 14; đối chiếu và ngưỡng có cơ sở → 15; bảo mật và an toàn → Global Constraints và test Task 11, 12. Báo cáo, README đầy đủ, video là việc không phải code, ngoài kế hoạch này.
- **Type consistency:** `Level.price: int`, `BookSnapshot.bids/asks: tuple[Level, ...]`, `MinuteBar` dùng đúng tên hàm `metrics.py`; `Pipeline.handle` kind khớp với `replay_jsonl`.
- **Proportion:** các task mô tả giao diện, test, giá trị kỳ vọng; thân hàm do người cài đặt viết.
