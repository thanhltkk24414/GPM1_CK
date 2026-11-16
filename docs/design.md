# LIQUIDITY LENS – Design (spec)

Đồ án cá nhân cuối kỳ, học phần Gói phần mềm ứng dụng cho tài chính 1 (UEL). **Hạn nộp: 2026-12-01.**
Hệ thống giám sát thanh khoản và mất cân bằng sổ lệnh theo thời gian thực trên thị trường chứng khoán Việt Nam.
Công cụ phân tích học thuật, không phải khuyến nghị đầu tư.

Quy ước: **[Xác nhận]** = có trong tài liệu SSI đã đọc; **[Giả định]** = quyết định thiết kế; **[Kiểm tra]** = phải xác minh bằng dữ liệu/tài liệu thật.

## 1. Nguồn dữ liệu: SSI FastConnect API V3

Đề thi nêu NEO API (VPBankS) là API chính, SSI chỉ bổ sung; giảng viên đã dặn miệng "dùng API nào cũng được". **Cần xác nhận bằng chữ** (chụp tin nhắn, đưa vào phụ lục báo cáo).

| Mục | Trạng thái |
|---|---|
| `POST https://api.ssi.com.vn/api/v3/auth/token` body `apiKey`, `apiSecret`; trả `tokenType`, `accessToken`, `expiresAt`, `refreshToken`, `refreshExpiresAt` | [Xác nhận] |
| Token chỉ đọc dữ liệu: **không** truyền `otp`/`transactionId` | [Xác nhận] |
| `POST /api/v3/auth/refresh` body `refreshToken` | [Xác nhận] |
| `expiresAt`: tài liệu ghi mili-giây, nhưng thực tế 10 chữ số = **giây** (smoke test REST 2026-11-16); SDK cũng ghi epoch giây. `refreshExpiresAt` chưa quan sát | [Xác nhận bằng thực nghiệm 2026-11-16]; vẫn nhận biết theo số chữ số |
| WebSocket `wss://stream.ssi.com.vn/ws/v3` (tài liệu ghi gốc không có `/ws/v3`), kênh `DATA`, thông điệp `{"method":"SUBSCRIBE","channel":"DATA","topics":[...]}`; server trả frame xác nhận `{"method":"SUBSCRIBE","channel":"DATA","status":"ok","message":"Subscribed to N topic(s)"}` | [Xác nhận bằng thực nghiệm 2026-11-16] |
| Topic: `trade`, `quote`, `room`, `put`, `oddlot`, `market`, `trade.index`, `indexsummary`; nhiều mã nối bằng `-` | [Xác nhận] |
| `quote`: `s`, `t` (`YYYY/MM/DD HH:mm:ss`), `bids`, `asks` = danh sách `[giá, khối lượng]` (chuỗi). Mẫu có 5 mức | [Xác nhận] |
| `trade`: `s`,`t`,`p` (đồng),`q`,`a`,`si` (B/S),`o`,`h`,`l`,`v` (tổng KL cộng dồn) | [Xác nhận] |
| `market`: `ce`,`fl`,`ref` (giá trần/sàn/tham chiếu) và thông điệp cờ phiên `{b,t,f}` với `f` như ATO, LO, ATC | [Xác nhận] |
| Heartbeat: server gửi `{"method":"PING","channel":"HEARTBEAT","time":...}`, client trả `PONG` cùng định dạng, nếu không phiên bị đóng | [Xác nhận] |
| REST `GET /api/v3/data/securitiesSummary` (symbol hoặc index, from, to, phân trang) trả dữ liệu theo ngày, gồm `totalMatch`, `totalMatchValue` | [Xác nhận] |
| Header giới hạn tần suất: server gửi `X-RateLimit-Limit` và `X-RateLimit-Remaining`, **không** gửi `Reset`. `auth/token` limit 200, `securitiesSummary` limit 20 (chu kỳ chưa biết) | [Xác nhận bằng thực nghiệm 2026-11-16]; chu kỳ hồi: [Kiểm tra] |
| REST `securitiesSummary`: body 200 có thêm `code` (số nguyên 200) và `msg` (rỗng); 25 trường đúng tài liệu; các bản ghi **không sắp xếp theo ngày**; `close` tính bằng đồng | [Xác nhận bằng thực nghiệm 2026-11-16] |
| Gắn token khi kết nối WebSocket: header HTTP `Authorization: Bearer <accessToken>` ở bước handshake được chấp nhận; không cần `client_id`, không OTP | [Xác nhận bằng thực nghiệm 2026-11-16] |
| Cờ phiên: topic `market.flag` cho mọi sàn (board `HOSE/HNX/UPCOM/DER`, giá trị ví dụ `ATO`, `LO`, `ATC`); trần/sàn/tham chiếu: topic `market.<mã>` hoặc REST master data | [Xác nhận từ tài liệu SDK, chưa thử thật] |
| Mỗi `apiKey` chỉ có **1 phiên hoạt động**; dùng lại refresh token làm server thu hồi mọi phiên của key (401103). Tối đa 10 kết nối WebSocket mỗi client | [Xác nhận từ tài liệu SDK]; lấy token mới có làm rớt WebSocket đang mở hay không: [Kiểm tra] |

### Cần kiểm tra bằng dữ liệu thật (smoke test ngày có key)
1. ~~Cách gắn token và vai trò `client_id`~~: đã xác nhận bằng thực nghiệm 2026-11-16 (header `Authorization: Bearer`, không `client_id`, không OTP). Nếu sau này server đòi OTP thì dừng và báo, không dùng OTP.
2. Số mức giá thực nhận trong `quote`, thứ tự (tốt nhất trước?), toàn bộ snapshot hay chỉ phần thay đổi (tài liệu báo bản sau sẽ chỉ gửi thay đổi).
3. Đơn vị giá: `trade.p` ghi "đồng", còn `quote`/`put`/`market` trong mẫu là 45.45, 48.50 (nghìn đồng?). Cấu hình `QUOTE_PRICE_MULTIPLIER = 1000` [Giả định].
4. Múi giờ của `t` (giả định giờ Việt Nam), tần suất cập nhật (độ phân giải giây).
5. Cú pháp subscribe `quote.SYM` có/không `@tick`: `quote.VIC` (không `@tick`) được chấp nhận (2026-11-16), chưa biết có nhận dữ liệu không. `LIST_SUBSCRIPTION` trả `{"trading":"","data":"<topic nối bằng ;>"}` [Xác nhận bằng thực nghiệm 2026-11-16].
6. Cờ phiên thực tế (`LO` có phải phiên khớp liên tục?), hành vi sổ lệnh quanh ATO, nghỉ trưa, ATC.
   - **[Kiểm tra]** Khung giờ dự phòng `config.CONTINUOUS_WINDOWS` = 09:15-11:30 và 13:00-14:30, chỉ dùng khi snapshot chưa có `session_flag`. Chưa có trong tài liệu SSI đã đọc; chỉ đúng cho mã HOSE, nên giữ watchlist chỉ gồm mã HOSE cho đến khi xác minh các sàn khác.
7. Chiều heartbeat: `docs/ssi/04` ghi server gửi `PING`, client trả `PONG` có `time`; SDK lại tự gửi `{"method":"PING_PONG","channel":"HEARTBEAT"}` từ client. Chưa biết cái nào đúng; ghi mọi frame `HEARTBEAT` thật vào `collector_events`. Smoke test 2026-11-16 17:34 (đã đóng cửa): 60 giây không có PING nào từ server.
8. Bước giá (tick size) theo mức giá và sàn: lấy từ quy định sàn, không hardcode khi chưa xác minh.
9. **Quy tắc phiên**: chỉ collector giữ token và kết nối WebSocket; dashboard Streamlit không bao giờ gọi `auth`; không chạy smoke test hay xin token thủ công khi collector đang chạy.
10. Đơn vị giá thông điệp `quote`/`market`, số mức giá, snapshot hay delta, múi giờ của `t`: chỉ xác minh được bằng frame thật (không thay đổi so với trước).

## 2. Công thức (đơn vị nội bộ: VND, số nguyên)

- `mid = (ask1 + bid1)/2`; `spread = ask1 − bid1`; `spread_bps = spread/mid × 10000`; `spread_ticks = spread/tick`.
- `OBI_k = (ΣV_bid − ΣV_ask)/(ΣV_bid + ΣV_ask)` trên k mức tốt nhất, k = 1 và 3. Thuộc [−1, 1].
- `depth_qty(side,k) = ΣV`; `depth_value(side,k) = ΣP×V` (VND).
- Trượt giá mua khối lượng Q: duyệt các mức bán, `avg = Σ(P×Q_i)/Q`, `slippage_bps = (avg−mid)/mid × 10000`; nếu Q lớn hơn độ sâu k mức: không khớp hết, **không ngoại suy**.
- Rolling Z-score: `z_t = (x_t − μ)/σ` với μ, σ (sample, ddof=1) tính trên tối đa `w` quan sát **trước** t, cùng nhóm (mã, ngày, AM/PM). Không đủ `min_periods` hoặc σ = 0 → không tính. Mặc định `w=30`, `min_periods=15` trên lưới 1 phút [Giả định, hiệu chỉnh theo dữ liệu].
- Ngưỡng cảnh báo hiệu chỉnh bằng phân vị phân phối |z| thực tế (ví dụ 99%), không đặt tùy ý.
- Mọi chỉ số chỉ trên phần sổ lệnh nhìn thấy (k mức), không phải toàn bộ sổ lệnh.

## 3. Quy tắc nghiệp vụ

- Một phía sổ trống (trần/sàn) → spread, OBI = `None`, không phải 0.
- Sổ chéo (bid1 ≥ ask1), giá ngoài [sàn, trần], thứ tự mức sai, khối lượng ≤ 0 → gắn cờ, loại khỏi chỉ số.
- Chỉ dùng snapshot trong phiên khớp liên tục; loại ATO/ATC/nghỉ trưa khỏi cửa sổ z-score.
- Bỏ snapshot trùng hệt snapshot liền trước của cùng mã (`t` chỉ chính xác đến giây, không dùng làm khóa duy nhất; luôn lưu `received_at` mili-giây).
- Giao dịch thỏa thuận (`put`) không trộn vào chỉ số sổ lệnh.
- Cảnh báo gọi là "bất thường thống kê". Không kết luận thao túng, không dự báo giá, không khuyến nghị mua/bán.

## 4. Schema SQLite (`data/liquidity_lens.db`, WAL, timestamp ISO-8601 +07:00)

| Bảng | Cột |
|---|---|
| `raw_message` | id, received_at, kind, payload |
| `market_ref` | trading_date, symbol, board, ceiling, floor, ref (PK trading_date+symbol) |
| `session_flag` | board, ts, flag |
| `trade_tick` | symbol, ts, price, qty, side, total_vol, received_at |
| `book_snapshot` | symbol, ts, received_at, bid_p1..3, bid_q1..3, ask_p1..3, ask_q1..3, n_bids, n_asks, session_flag, flags |
| `metrics_1m` | symbol, minute, spread_abs, spread_bps, spread_ticks, obi1, obi3, depth_bid3, depth_ask3, depth_val_bid3, depth_val_ask3, volume, z_obi3, z_spread_bps, z_volume, n_obs (PK symbol+minute) |
| `alerts` | id, symbol, minute, metric, value, z, severity, message |
| `collector_events` | id, ts, event, detail |

## 5. Kiến trúc

Hai tiến trình: **collector** (WebSocket → raw → chuẩn hóa → SQLite, tự kết nối lại, chạy suốt phiên) và **dashboard Streamlit** (chỉ đọc SQLite). Không nhúng WebSocket vào Streamlit.

## 6. Phạm vi

- **Must:** collector có lưu trữ + reconnect + log; Spread/OBI/Depth; Rolling Z; cảnh báo có ngưỡng giải thích được; dashboard (trạng thái dữ liệu, ≥3 chỉ số, ≥2 biểu đồ, bộ lọc, phần phương pháp/giới hạn); pytest; README, `.env.example`, báo cáo, video.
- **Should:** đối chiếu tổng khối lượng với `securitiesSummary`; xếp hạng nhiều mã; trượt giá theo Q; báo cáo chất lượng dữ liệu; robust z (median/MAD).
- **Could:** cảnh báo ngoài dashboard; phân cụm; phái sinh.

## 7. Yêu cầu của đề cần chứng minh

NEO/SSI là lõi dữ liệu; có lớp logic tài chính; sản phẩm chạy được; có kiểm chứng; ≥1 luồng WebSocket có lưu trữ; ≥3 trường dữ liệu; **≥5 phiên (ưu tiên 10)**; múi giờ Asia/Ho_Chi_Minh; không lộ khóa; không gửi lệnh thật; báo cáo 8–12 trang; tên tệp nộp `MSSV_HoTen_NEOAPI_FinTech.zip`.
