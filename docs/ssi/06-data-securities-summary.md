> Bản chép từ tài liệu SSI FastConnect do người dùng cung cấp ngày 2026-11-15 (nguồn: https://developers.ssi.com.vn). Dùng để tham khảo nội bộ.

# Market Data – data-securitiesSummary

Lấy thông tin tổng hợp giao dịch của một mã chứng khoán hoặc chỉ số theo từng ngày giao dịch. Chỉ truyền một trong hai tham số là `symbol` hoặc `index`.

- Server URL: `https://api.ssi.com.vn`
- `GET /api/v3/data/securitiesSummary`
- Authorization: `Bearer <token>` (JWT, header)

## Header Parameters

| Header | Bắt buộc | Mô tả |
|---|---|---|
| `Content-Type` | có | Sử dụng `application/json`. |
| `User-Agent` | không | Thông tin client gửi request. |
| `Accept-Language` | không | Ngôn ngữ phản hồi mong muốn. Nếu không có header này, hệ thống mặc định là `en`. |

## Query Parameters

| Tham số | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `symbol` | string | không | Mã chứng khoán. Chỉ truyền một trong hai tham số `symbol` hoặc `index`. |
| `index` | string | không | Mã chỉ số (ví dụ VNINDEX, VN30, VN100...). |
| `from` | string | có | Ngày bắt đầu, định dạng `YYYY/MM/DD`. |
| `to` | string | có | Ngày kết thúc, định dạng `YYYY/MM/DD`; phải lớn hơn hoặc bằng `from`. |
| `pageIndex` | integer | không | Chỉ số trang, bắt đầu từ 1; mặc định 1. |
| `pageSize` | integer | không | Số bản ghi mỗi trang; mặc định 10. |

## Response Headers

`X-RATELIMIT-LIMIT`, `X-RATELIMIT-REMAINING`, `X-RATELIMIT-RESET`.

## Response Body – 200 Success (`response` object)

Phân trang: `pageSize`, `pageIndex`, `pagesCount` (tổng số trang), `itemsCount` (tổng số bản ghi); `data[]` gồm (mọi trường kiểu string):

| Trường | Mô tả |
|---|---|
| `symbol` | Mã chứng khoán |
| `tradingDate` | Ngày giao dịch |
| `priceChange`, `priceChangePercentage` | Mức và phần trăm thay đổi giá so với phiên trước |
| `open`, `high`, `low`, `close` | Giá mở cửa, cao nhất, thấp nhất, đóng cửa |
| `average` (string \| null) | Giá trung bình |
| `totalMatch`, `totalMatchValue` | Tổng khối lượng và giá trị khớp lệnh |
| `totalBuy`, `totalTradeBuy` | Số lệnh đặt mua, khối lượng đặt mua |
| `totalSell`, `totalTradeSell` | Số lệnh đặt bán, khối lượng đặt bán |
| `totalForeignBuy`, `totalForeignBuyValue` | Khối lượng và giá trị khối ngoại mua |
| `totalForeignSell`, `totalForeignSellValue` | Khối lượng và giá trị khối ngoại bán |
| `remainForeignRoom`, `totalForeignRoom` | Room nước ngoài còn lại, tổng room |
| `totalDeal`, `totalDealValue` | Khối lượng và giá trị giao dịch thỏa thuận |
| `openInterest`, `settlementPrice` | Chỉ có giá trị với mã phái sinh |

## Response Body – 400 Yêu cầu không hợp lệ

`code` (string, mã lỗi hệ thống, xem trang mã lỗi), `msg` (string, thông điệp theo `Accept-Language` en/vi; mặc định tiếng Anh).

## Ghi chú của dự án (không thuộc tài liệu SSI)

- Dữ liệu theo **ngày**, không có sổ lệnh. Dùng để đối chiếu `totalMatch` với tổng khối lượng thu từ WebSocket (Task 15).
