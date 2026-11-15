# Tài liệu SSI FastConnect (bản chép tham khảo)

Chép từ văn bản người dùng sao chép trên https://developers.ssi.com.vn ngày 2026-11-15. Không phải bản chính thức; khi khác thực tế thì thực tế thắng và ghi vào `../design.md`.

| Tệp | Nội dung |
|---|---|
| `00-api-overview.md` | Tổng quan 7 nhóm API |
| `01-get-api-key.md` | Tạo API key, luồng token, OTP (không dùng OTP trong đồ án) |
| `02-auth-token.md`, `03-auth-refresh.md` | Lấy và làm mới token |
| `04-websocket-connect-and-heartbeat.md` | Kết nối, heartbeat, subscription |
| `05-websocket-sub-unsub-market-data.md` | Topic `trade`, `quote`, `market`, `room`, `put`... và cấu trúc thông điệp |
| `06-data-securities-summary.md` | REST dữ liệu tổng hợp theo ngày |
| `09-error-codes.md` | Bảng mã lỗi |

Cố ý **không** lưu trang đặt lệnh điều kiện (FCO) và Trading vì đồ án không dùng các API đó.
