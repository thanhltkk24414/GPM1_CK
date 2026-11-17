> Bản chép từ tài liệu SSI FastConnect do người dùng cung cấp ngày 2026-11-15 (nguồn: https://developers.ssi.com.vn). Dùng để tham khảo nội bộ.

# WebSocket – Kết nối WebSocket

Thiết lập kết nối FastConnect WebSocket và quy tắc request tổng quát.

## Tổng quan

FastConnect WebSocket dùng để stream dữ liệu giao dịch và dữ liệu thị trường theo thời gian thực. Trước khi kết nối, client cần lấy token từ API `getAccessToken`.

## Endpoint kết nối

```
wss://stream.ssi.com.vn
```

## Điều kiện sử dụng

- Access token còn hiệu lực.
- Client duy trì heartbeat trong suốt phiên kết nối.
- Sau khi reconnect, cần subscribe lại các topic cần theo dõi.

## Xác thực và kết nối

Tài liệu mô tả việc lấy token từ `client_id`, `api_key`, `api_secret` qua API auth. Sau đó dùng token để kết nối stream.

```
{ "client_id": "666666", "api_key": "<api-key>", "api_secret": "<api-secret>", "access_token": "<access-token>" }
```

## Cấu trúc request WebSocket tổng quát

```
{ "method": "SUBSCRIBE|UNSUBSCRIBE|LIST_SUBSCRIPTION|PING|PONG", "channel": "TRADING|DATA|HEARTBEAT", "topics": ["trade.SSI@tick", "trade.SSI@1m", "room.*"] }
```

## List subscription

Client có thể kiểm tra scope hiện tại bằng request `{ "method": "LIST_SUBSCRIPTION" }`. Response trả về các quyền truy cập theo nhóm trading/data.

## Event type chính

`connect`, `heartbeat`, `orderEvent`, `orderMatchEvent`, `clientPortfolioEvent`, `fcoEvent` (sự kiện lệnh điều kiện), `trade`, `quote`, `room`, `put`, `oddlot`, `market`, `trade.index` (giá trị chỉ số thời gian thực), `indexsummary` (thông tin tổng hợp của chỉ số).

---

# WebSocket – Heartbeat và Subscription

Mô tả cơ chế ping pong, heartbeat và danh sách subscription của WebSocket FastConnect.

## Heartbeat

Server gửi heartbeat định kỳ để xác nhận client còn online. Client phải phản hồi đúng định dạng để session không bị đóng. Channel sử dụng: `HEARTBEAT`.

Ping từ server:

```
{ "method": "PING", "channel": "HEARTBEAT", "time": "dd-mm-yyyy hh-mm-ss" }
```

Pong từ client:

```
{ "method": "PONG", "channel": "HEARTBEAT", "time": "dd-mm-yyyy hh-mm-ss" }
```

## LIST_SUBSCRIPTION

Request: `{ "method": "LIST_SUBSCRIPTION" }`

Response mẫu (tóm tắt scope):

```
{ "trading": "order.*;portfolio.123456", "data": "trade.*;quote.*;room.*" }
```

## Subscribe topic

```
{ "method": "SUBSCRIBE", "channel": "DATA|TRADING", "topics": ["trade.SSI@tick", "quote.SSI@tick", "order.0901351"] }
```

## Unsubscribe topic

```
{ "method": "UNSUBSCRIBE", "channel": "DATA|TRADING", "topics": ["trade.SSI@tick", "order.0901351"] }
```

## Topic convention

- `order.<accountNo>`
- `portfolio.<accountNo>`
- `trade.<symbol>@tick|1m|5m`
- `trade.index.<index_code>@tick|1m|5m`
- `indexsummary.<index_code|*>`
- `quote.<symbol>@tick`
- `room.<symbol|*>`
- `put.<symbol|*>`
- `oddlot.<symbol>`
- `market.<group|exchange>`

## Ghi chú của dự án (không thuộc tài liệu SSI)

Nguồn: tài liệu và mã nguồn `ssi-sdk` 3.3.2 (đọc 2026-11-16; chi tiết ở `10-python-sdk-notes.md`) và smoke test thật 2026-11-16 17:34 (thị trường đã đóng cửa).

### Đã xác nhận bằng thực nghiệm (2026-11-16)
- **[Xác nhận bằng thực nghiệm 2026-11-16]** `wss://stream.ssi.com.vn/ws/v3` chấp nhận header `Authorization: Bearer <accessToken>` khi handshake; không cần `client_id`, không OTP. (Thay cho mục [Kiểm tra] cũ về cách gắn token.)
- **[Xác nhận bằng thực nghiệm 2026-11-16]** Server gửi frame xác nhận subscribe: `{"method":"SUBSCRIBE","channel":"DATA","status":"ok","message":"Subscribed to 10 topic(s)"}` (không có trong tài liệu SSI).
- **[Xác nhận bằng thực nghiệm 2026-11-16]** Phản hồi `LIST_SUBSCRIPTION` là `{"trading":"","data":"<các topic đã subscribe, nối bằng ;>"}`: scope trading rỗng, scope data liệt kê đúng 10 topic vừa gửi (`quote|trade|market` cho VIC, HPG, FPT và `market.flag`).
- Trong 60 giây (ngoài giờ giao dịch) **không có frame HEARTBEAT nào** từ server và kết nối vẫn mở khi client không gửi gì.

### Từ SDK, chưa thử thật
- Mỗi `apiKey` chỉ có 1 phiên hoạt động; tối đa 10 kết nối mỗi client. Sau khi reconnect phải subscribe lại.
- Mọi lỗi sau khi đã kết nối (mất mạng, token hết hạn) không ném ra luồng chính trong SDK; collector tự viết phải ghi `collector_events` cho từng lần ngắt và nối lại.
- SDK client tự gửi `{"method":"PING_PONG","channel":"HEARTBEAT"}`, khác với mô tả PING/PONG ở trên.

### Quy tắc dự án
- **Chỉ collector giữ token và mở WebSocket; dashboard không bao giờ gọi auth** (chỉ đọc SQLite).
- Chỉ subscribe kênh `DATA`, không dùng kênh `TRADING`.
- Ghi mọi frame `HEARTBEAT` thật (cả hai chiều) vào `collector_events`.

### Còn [Kiểm tra]
- **[Kiểm tra]** Chiều và chu kỳ heartbeat: ai gửi `PING`/`PONG`/`PING_PONG`, `PONG` có echo đúng `time` không, định dạng `time` thực tế. Chạy lại trong giờ giao dịch.
- **[Kiểm tra]** Hành vi khi mở phiên thứ hai bằng cùng `apiKey` (đẩy phiên cũ hay từ chối).
- ~~Cấu trúc bao ngoài của frame dữ liệu~~: đã xác nhận, xem mục 2026-11-17 bên dưới.
- **[Kiểm tra]** Cú pháp `quote`: trang Sub/Unsub cho `quote.[...]@[tick/1m/5m]`, trang này chỉ ghi `quote.<symbol>@tick`. (Smoke test subscribe `quote.VIC` không có `@tick` và được chấp nhận; chưa biết có nhận được dữ liệu không.)

### Kết quả smoke test WebSocket thật trong giờ giao dịch (2026-11-17 09:05 đến 09:20, 3495 frame, 15 phút)
- **[Xác nhận bằng thực nghiệm 2026-11-17]** Frame dữ liệu có dạng `{"channel":"DATA","topic":"quote.HPG","data":{...}}`; `data` đúng cấu trúc mẫu trong `05`. Topic cờ phiên là `market.FLAG` (chữ hoa), `data` = `{"b":"HOSE","t":"...","f":"LO"}`: so khớp topic không phân biệt hoa thường.
- **[Xác nhận bằng thực nghiệm 2026-11-17]** Giá trong `quote` và `trade` tính bằng **đồng** (HPG 20850, FPT 49400). `trade.t` có mili-giây (`09:15:00.005`), `quote.t` chỉ đến giây.
- **[Xác nhận bằng thực nghiệm 2026-11-17]** Mỗi `quote` luôn có 10 mức mỗi phía, mức đệm là `["0","0"]`; chỉ 3 mức đầu là thật (2649/2649 frame có đúng 3 mức thật mỗi phía, đệm nằm cuối).
- **[Xác nhận bằng thực nghiệm 2026-11-17]** `market.VIC/HPG/FPT` không gửi frame nào (không có trần/sàn/tham chiếu qua WebSocket). Cờ phiên chỉ gửi khi đổi trạng thái, không gửi lại khi subscribe: không nhận được cờ ATO.
- **[Xác nhận bằng thực nghiệm 2026-11-17]** 0 frame HEARTBEAT trong 15 phút, kết nối vẫn mở khi client không gửi gì. Chiều heartbeat vẫn **[Kiểm tra]** nhưng collector không phụ thuộc vào nó (chỉ ghi cảnh báo khi im lặng).
