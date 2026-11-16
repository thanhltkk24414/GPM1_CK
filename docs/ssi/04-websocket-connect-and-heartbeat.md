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

- **[Kiểm tra]** Cách gắn token khi kết nối `wss://stream.ssi.com.vn` (header, query hay thông điệp đầu tiên) và vai trò `client_id`: tài liệu đã có không nói rõ.
- **[Kiểm tra]** Cú pháp `quote`: trang Sub/Unsub cho `quote.[...]@[tick/1m/5m]`, trang này chỉ ghi `quote.<symbol>@tick`.
- Đồ án chỉ subscribe kênh `DATA`, không dùng kênh `TRADING`.

## Ghi chú của dự án (không thuộc tài liệu SSI)

Nguồn: tài liệu và mã nguồn `ssi-sdk` 3.3.2 (đọc ngày 2026-11-16), **chưa thử với server thật**. Chi tiết: `10-python-sdk-notes.md`.

- **[Xác nhận từ SDK, chưa thử thật]** URL mặc định của SDK là `wss://stream.ssi.com.vn/ws/v3`. Token gắn bằng header HTTP `Authorization: Bearer <accessToken>` khi handshake. `client_id` không dùng cho token và dữ liệu thị trường.
- **[Kiểm tra]** Chiều heartbeat: tài liệu trên ghi server gửi `PING`, client trả `PONG`; SDK lại tự gửi `{"method":"PING_PONG","channel":"HEARTBEAT"}` từ client. Ghi mọi frame `HEARTBEAT` thật để xác định.
- Mỗi `apiKey` chỉ có 1 phiên hoạt động; tối đa 10 kết nối mỗi client. Sau khi reconnect phải subscribe lại.
- Mọi lỗi sau khi đã kết nối (mất mạng, token hết hạn) không ném ra luồng chính trong SDK; collector tự viết cần ghi `collector_events` cho từng lần ngắt và nối lại.
- **[Kiểm tra]** Server có chấp nhận header Bearer ở handshake không; mã lỗi hoặc mã đóng kết nối khi bị từ chối.
- **[Kiểm tra]** `PONG` có echo đúng `time` của `PING` không, và định dạng `time` thực tế.
- **[Kiểm tra]** Hành vi khi mở phiên thứ hai bằng cùng `apiKey` (đẩy phiên cũ hay từ chối).
- **[Kiểm tra]** Cấu trúc bao ngoài (envelope) của mỗi frame dữ liệu: tài liệu chỉ mô tả phần `data`.
- Quy tắc: **chỉ collector giữ token và mở WebSocket; dashboard không bao giờ gọi auth** (chỉ đọc SQLite).

### Kết quả smoke test WebSocket thật (2026-11-16 17:34, thị trường đã đóng cửa)
- **[Xác nhận bằng thực nghiệm 2026-11-16]** `wss://stream.ssi.com.vn/ws/v3` chấp nhận header `Authorization: Bearer <accessToken>` khi handshake, không cần `client_id`, không OTP.
- **[Xác nhận bằng thực nghiệm 2026-11-16]** Server có frame xác nhận subscribe: `{"method":"SUBSCRIBE","channel":"DATA","status":"ok","message":"Subscribed to 10 topic(s)"}` (không có trong tài liệu SSI).
- **[Xác nhận bằng thực nghiệm 2026-11-16]** Phản hồi `LIST_SUBSCRIPTION` là `{"trading":"","data":"<các topic đã subscribe, nối bằng ;>"}`: scope trading rỗng, scope data liệt kê đúng 10 topic vừa gửi (`quote|trade|market` cho VIC, HPG, FPT và `market.flag`).
- Trong 60 giây (ngoài giờ giao dịch) **không có frame HEARTBEAT nào** từ server và kết nối vẫn mở. Chu kỳ PING và chiều heartbeat vẫn **[Kiểm tra]**. Chưa có frame `quote`/`trade`/`market` nào (đã đóng cửa): cấu trúc bao ngoài, số mức giá, đơn vị giá, payload `market.flag` vẫn **[Kiểm tra]**, cần chạy lại trong giờ giao dịch.
