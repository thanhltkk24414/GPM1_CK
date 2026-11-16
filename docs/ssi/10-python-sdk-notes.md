# Ghi chú tham khảo: Python SDK `ssi-sdk` 3.3.2

> Không phải tài liệu API chính thức của SSI. Tổng hợp của dự án từ các trang tài liệu SDK do người dùng sao chép (ngày 2026-11-16) và mã nguồn gói `ssi-sdk` 3.3.2 (chỉ đọc, không chạy với SSI). Điều gì khác thực tế thì thực tế thắng. Đồ án **không cài và không import `ssi-sdk`**; SDK chỉ là nguồn tham chiếu.

## Vì sao không dùng SDK trong collector

- Message có kiểu của SDK (`QuoteMessage`, `TradeMessage`...) **không giữ frame gốc** (trường `raw` bị comment ở mã nguồn) và đổi giá sang `float`. Đồ án cần lưu `raw_message` nguyên văn và parse giá bằng `Decimal`.
- Gói SDK chứa Trading, FCO và Trading WebSocket; `CLAUDE.md` cấm dùng các API đó.

## Điều rút ra (dùng để tự viết `ssi/auth.py`, `ssi/stream.py`)

| Điều | Nội dung | Mức độ |
|---|---|---|
| URL stream | `wss://stream.ssi.com.vn/ws/v3` (`Config.streaming_url`) | [Xác nhận từ SDK, chưa thử thật] |
| Token khi handshake | Header `Authorization: Bearer <accessToken>` | [Xác nhận từ SDK, chưa thử thật] |
| `client_id` | Không dùng khi lấy token và nhận dữ liệu thị trường; chỉ dùng cho danh mục và Trading WS | [Xác nhận từ SDK + smoke test REST] |
| Khung subscribe | `{"method":"SUBSCRIBE","channel":"DATA","topics":["quote.SSI","trade.SSI"]}`; topic mã viết hoa; mỗi topic một bộ lọc (`*`, một mã hoặc `A-B`), không dùng dấu phẩy | [Xác nhận từ SDK, khớp `05`] |
| `LIST_SUBSCRIPTION` | `{"method":"LIST_SUBSCRIPTION"}` (không có `channel`, không có `topics`) | [Xác nhận từ SDK, khớp `04`] |
| Cờ phiên | Topic `market.flag`; model gồm `board` (HOSE/HNX/UPCOM/DER), `trading_time`, `flag` (ví dụ `ATO`, `LO`, `ATC`) | [Xác nhận từ tài liệu SDK] |
| Trần/sàn/tham chiếu | Topic `market.<mã>` (`s`,`b`,`t`,`ce`,`fl`,`ref`); REST master data trả `board`, `symbol`, `trading_date`, `ceiling`, `floor`, `ref_price` (có thể `None`) | [Xác nhận từ SDK; đường dẫn REST master data chưa có trong docs đã đọc: không đoán] |
| Mức giá `quote` | `bids`/`asks` là danh sách `[giá, khối lượng]`, "best first"; số mức và đơn vị giá chưa nêu | [Kiểm tra] bằng frame thật |
| `trade.price` | "Price in VND" (đồng) | [Xác nhận từ tài liệu SDK] |
| Phiên | Mỗi `apiKey` chỉ có **1 phiên hoạt động**; dùng lại refresh token (đã dùng) làm server thu hồi mọi phiên của key (401103). Token coi như hết hạn sớm 30 giây | [Xác nhận từ tài liệu SDK]; có đá WebSocket đang mở khi xin token mới hay không: [Kiểm tra] |
| Giới hạn | Tối đa 10 kết nối WebSocket mỗi client; frame gửi đi tối đa 4096 byte (SDK giữ 4000); gặp 429 SDK chờ tối thiểu 30 giây; reconnect backoff tăng dần có jitter, trần 60 giây, subscribe lại sau khi nối lại | [Xác nhận từ tài liệu SDK] |
| Kênh không cần OTP | Dữ liệu thị trường "không cần OTP riêng"; OTP chỉ cho kênh trading (`on_order`, `on_order_match`, `on_portfolio`). Một ví dụ stream trong trang "Cài đặt" có `authenticate(otp=...)` kèm `private_key` nhưng đó là cấu hình cho kênh trading | [Xác nhận từ tài liệu SDK]; thử thật bằng token không OTP, nếu bị từ chối thì dừng và báo |
| Heartbeat | SDK client tự gửi `{"method":"PING_PONG","channel":"HEARTBEAT"}`; `docs/ssi/04` ghi server gửi `PING` và client trả `PONG` có `time` | [Kiểm tra] chiều và tên method |

## Rate limit (từ SDK, chưa thử thật)

SDK mặc định `rate_limit_per_second=10`; lỗi 429 có `Retry-After` (giây); header `X-RateLimit-Limit/Remaining` có, `Reset` thường không có. Số quan sát thật của đồ án: xem `02-auth-token.md` và `06-data-securities-summary.md`.

## REST dữ liệu khác trong SDK (chưa dùng, chưa kiểm tra đường dẫn)

OHLC theo phút/giờ/ngày, danh sách chỉ số, `get_securities_info`, master data, corporate actions. Chỉ dùng nếu cần thiết cho đồ án; endpoint cụ thể phải lấy từ tài liệu REST chính thức, không đoán từ tên hàm SDK.
