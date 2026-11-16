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

Nguồn: mã nguồn ssi-sdk 3.3.2 (chỉ đọc, không cài/import). Mọi mục gắn nhãn [Xác nhận từ mã nguồn SDK, chưa thử thật] chưa được thử với server thật; smoke test (Task 10) sẽ xác minh.

- [Xác nhận từ mã nguồn SDK, chưa thử thật] Endpoint kết nối là `wss://stream.ssi.com.vn/ws/v3` (trang trên ghi gốc `wss://stream.ssi.com.vn`).
- [Xác nhận từ mã nguồn SDK, chưa thử thật] Token gắn bằng header handshake `Authorization: Bearer <accessToken>`. Không cần `client_id`, không dùng OTP.
- [Xác nhận từ mã nguồn SDK, chưa thử thật] Mỗi `apiKey` chỉ có **một** phiên WebSocket. Hệ quả: **chỉ collector giữ token và mở kết nối; dashboard không gọi auth** (dashboard chỉ đọc SQLite).
- Heartbeat: server gửi `PING`, client trả `PONG` có trường `time`. Mọi frame `HEARTBEAT` (cả hai chiều) được ghi vào `collector_events` để đối chiếu.
- [Xác nhận từ mã nguồn SDK, chưa thử thật] `LIST_SUBSCRIPTION`: `{"method":"LIST_SUBSCRIPTION"}`.
- Đồ án chỉ subscribe kênh `DATA`, không dùng kênh `TRADING`.

### Còn [Kiểm tra]
- **[Kiểm tra]** Header Bearer có được server chấp nhận khi handshake không; mã lỗi/đóng kết nối khi bị từ chối.
- **[Kiểm tra]** `PONG` có phải echo đúng `time` của `PING` không, và định dạng `time` thực tế.
- **[Kiểm tra]** Hành vi khi mở phiên thứ hai bằng cùng `apiKey` (đẩy phiên cũ hay từ chối).
- **[Kiểm tra]** Cú pháp `quote`: có/không `@tick`.
- **[Kiểm tra]** Cấu trúc bao ngoài (envelope) của mỗi frame dữ liệu: tài liệu chỉ mô tả phần `data`.
