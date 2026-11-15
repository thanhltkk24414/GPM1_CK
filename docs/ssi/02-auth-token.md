> Bản chép từ tài liệu SSI FastConnect do người dùng cung cấp ngày 2026-11-15 (nguồn: https://developers.ssi.com.vn). Dùng để tham khảo nội bộ.

# Authentication – auth-token

Xác thực apiKey/apiSecret để lấy access token và refresh token (kèm thông tin hết hạn).

- Server URL: `https://api.ssi.com.vn`
- `POST /api/v3/auth/token`

## Request Body (required, object)

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `apiKey` | string | có | API key do SSI/FastConnect cấp cho ứng dụng. |
| `apiSecret` | string | có | API secret tương ứng với `apiKey`. |
| `otp` | string \| null | không | Mã OTP (SMS OTP hoặc SmartOTP) cần phải có nếu bạn muốn token cấp ra có quyền thực hiện giao dịch. Trường hợp chỉ sử dụng để truy vấn dữ liệu (data, query trading) thì không cần truyền OTP. |
| `transactionId` | string \| null | không | Mã transaction trả về từ API `auth/requestOtp` khi tài khoản dùng 2FA loại SmartOTP và đã kích hoạt luồng phê duyệt qua ứng dụng iBoard. |

## Response Headers

| Header | Mô tả |
|---|---|
| `X-RATELIMIT-LIMIT` | Giới hạn số request trong chu kỳ. |
| `X-RATELIMIT-REMAINING` | Số request còn lại trong chu kỳ hiện tại. |
| `X-RATELIMIT-RESET` | Thời điểm reset giới hạn request. |

## Response Body

**200 – Thành công** (`response` object):

| Trường | Kiểu | Mô tả |
|---|---|---|
| `tokenType` | string | Loại token dùng trong header Authorization. |
| `accessToken` | string | Access token dùng để gọi các API nghiệp vụ. |
| `expiresAt` | integer | Thời điểm hết hạn của access token theo timestamp (epoch milliseconds). |
| `refreshToken` | string | Refresh token dùng để xin access token mới khi hết hạn. |
| `refreshExpiresAt` | integer | Thời điểm hết hạn của refresh token theo timestamp (epoch milliseconds). |

**400 – Request không hợp lệ** (`response`): `code` (integer, mã lỗi), `msg` (string, chi tiết lỗi để hỗ trợ xử lý phía client).

## Ghi chú của dự án (không thuộc tài liệu SSI)

- **[Kiểm tra]** Tài liệu ghi `expiresAt` là mili-giây nhưng ví dụ ở trang "Cách lấy API Key" có 10 chữ số (giống giây). Collector nhận biết theo số chữ số.
- Đồ án chỉ dùng token đọc dữ liệu: **không** truyền `otp`/`transactionId`.
