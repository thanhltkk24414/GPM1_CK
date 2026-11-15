> Bản chép từ tài liệu SSI FastConnect do người dùng cung cấp ngày 2026-11-15 (nguồn: https://developers.ssi.com.vn). Dùng để tham khảo nội bộ.

# Authentication – auth-refresh

Làm mới access token bằng refresh token còn hiệu lực.

- Server URL: `https://api.ssi.com.vn`
- `POST /api/v3/auth/refresh`

## Request Body (required, object)

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `refreshToken` | string | có | Refresh token còn hiệu lực để cấp mới access token. |

## Response Headers

`X-RATELIMIT-LIMIT`, `X-RATELIMIT-REMAINING`, `X-RATELIMIT-RESET` (giống auth-token).

## Response Body

**200 – Thành công**: `tokenType`, `accessToken`, `expiresAt` (epoch milliseconds), `refreshToken`, `refreshExpiresAt` (giống auth-token).

**400 – Request không hợp lệ**: `code` (integer), `msg` (string, chi tiết lỗi để hỗ trợ xử lý phía client).
