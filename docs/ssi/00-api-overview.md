> Bản chép từ tài liệu SSI FastConnect do người dùng cung cấp ngày 2026-11-15 (nguồn: https://developers.ssi.com.vn). Dùng để tham khảo nội bộ; khi khác thực tế thì thực tế thắng và ghi vào docs/design.md.

SSI API Overview
Tổng quan hệ sinh thái API FastConnect gồm Authentication, Trading, Market Data và WebSocket.

Giới thiệu
FastConnect API được thiết kế để hỗ trợ đầy đủ vòng đời tích hợp giao dịch điện tử, từ xác thực truy cập, xử lý nghiệp vụ giao dịch, truy vấn dữ liệu thị trường đến nhận dữ liệu thời gian thực.

Bộ tài liệu trong mục API Reference được tổ chức theo 7 nhóm chức năng chính:

Authentication — Xác thực và quản lý phiên truy cập.
Trading — Đặt/sửa/hủy lệnh, truy vấn tài khoản.
Market Data — Dữ liệu thị trường qua REST API.
WebSocket — Dữ liệu realtime qua WebSocket.
Lệnh điều kiện (FCO) — Đặt/hủy lệnh điều kiện, truy vấn sổ lệnh FCO.
WebSocket API — Đặt/sửa/hủy lệnh, lệnh điều kiện và truy vấn tài khoản thuần qua kết nối WebSocket bền vững, độ trễ thấp.
Phụ lục tham khảo — Luồng trạng thái lệnh, tham khảo FCO, tra cứu mã lỗi.
Mục tiêu tích hợp
Nền tảng API hướng đến các mục tiêu sau:

Xác thực và quản lý phiên truy cập an toàn.
Đặt/sửa/hủy lệnh (kể cả hàng loạt) và truy vấn trạng thái giao dịch.
Đặt lệnh điều kiện (FCO) với nhiều chiến lược khác nhau.
Truy vấn dữ liệu thị trường theo REST API.
Nhận dữ liệu realtime qua WebSocket.
Trang này cung cấp góc nhìn tổng thể trước khi đi vào tài liệu endpoint chi tiết.

Luồng tích hợp đề xuất
Luồng triển khai phổ biến:

Gọi nhóm Authentication để lấy token truy cập.
Dùng token để gọi các API Trading, Lệnh điều kiện (FCO) và Market Data qua REST.
Dùng token để kết nối WebSocket và subscribe các topic realtime.
Tham khảo Phụ lục để tra cứu mã lỗi, luồng trạng thái lệnh và tham số FCO.
1) Authentication
Nhóm API này phụ trách cấp mới và làm mới token, là tiền đề cho mọi phiên làm việc với hệ thống.

auth-token: cấp accessToken và refreshToken.
auth-refresh: làm mới cặp token trước khi hết hạn.
auth-requestOtp: yêu cầu OTP phục vụ các nghiệp vụ cần xác minh.
Xem chi tiết tại:

auth-token
auth-refresh
auth-requestOtp
2) Trading
Nhóm Trading phục vụ các nghiệp vụ giao dịch cốt lõi và truy vấn dữ liệu tài khoản:

Đặt/sửa/hủy lệnh.
Đặt/hủy hàng loạt lệnh (Batch Order, tối đa 50 lệnh mỗi lần gọi).
Truy vấn thông tin tài khoản, vị thế, số dư, sức mua.
Truy vấn sổ lệnh và dữ liệu liên quan tới quản trị rủi ro.
Một số API quan trọng:

trade-order-place
trade-order-modify
trade-order-cancel
trade-order-batch-place — Đặt hàng loạt lệnh.
trade-order-batch-cancel — Hủy hàng loạt lệnh.
trade-orderBook
trade-position
trade-accountBalance
trade-maxbuysell
trade-ppmmrAccount
account-info
Mỗi lệnh trải qua nhiều trạng thái trong vòng đời đặt/sửa/hủy/khớp lệnh (PD → RS → SD → QU → PF/FF, hoặc WC → CL, RJ, EX...). Khi tích hợp, consumer cần hiểu ý nghĩa từng trạng thái và luồng chuyển đổi giữa chúng để xử lý đúng phản hồi của các API trên cũng như các sự kiện streaming (orderEvent, orderMatchEvent).

📄 Đọc thêm: Luồng trạng thái của lệnh — sơ đồ và mô tả chi tiết 16 trạng thái lệnh cùng các luồng đặt/sửa/hủy/khớp.

3) Market Data
Nhóm Market Data cung cấp dữ liệu thị trường qua REST API để phục vụ phân tích, hiển thị và xử lý nghiệp vụ:

Danh sách và tổng hợp chỉ số.
Danh sách và tổng hợp chứng khoán.
Dữ liệu OHLC và tệp dữ liệu thị trường.
Sự kiện quyền của doanh nghiệp (cổ tức, thưởng cổ phiếu, phát hành thêm...).
Tải file dữ liệu thị trường.
Một số API quan trọng:

data-securitiesByBoard
data-securitiesSummary
data-indexList
data-indexSummary
data-ohlc
data-corporateActions — Sự kiện quyền của doanh nghiệp.
4) WebSocket
Nhóm WebSocket cung cấp luồng dữ liệu realtime với 2 kênh chính:

Trading stream: sự kiện liên quan lệnh, khớp lệnh, biến động tài khoản.
Market stream: sự kiện trade/quote/room/put/oddlot/market theo topic, kèm giá trị chỉ số theo thời gian thực (trade.index, nến tick/1m/5m) và thông tin tổng hợp chỉ số (indexsummary).
Tài liệu WebSocket bao gồm:

Kết nối WebSocket
Heartbeat và Subscription
Sub/Unsub Trading Data
Sub/Unsub Market Data
5) Lệnh điều kiện (FCO)
Nhóm API Lệnh điều kiện (FastConnect Conditional Order) cho phép đặt các lệnh tự động kích hoạt khi thỏa điều kiện thị trường. Hệ thống hỗ trợ 7 loại lệnh điều kiện:

Trailing Stop (TS) — lệnh dừng trượt theo giá thị trường.
Take Profit (PRO) — chốt lời khi đạt mức giá mục tiêu.
Stop Loss (ST) — cắt lỗ khi giá chạm ngưỡng.
Trailing Take Profit (TPRO) — chốt lời với mức trượt.
Bull/Bear (BB) — kết hợp chốt lời và cắt lỗ.
One Cancels Other (OCO) — hai lệnh loại trừ nhau.
Market Alert (MA) — cảnh báo khi điều kiện thị trường thỏa.
Các API chính:

fco-order-place — Đặt lệnh điều kiện mới.
fco-order-cancel — Hủy lệnh điều kiện.
fco-list — Danh sách lệnh điều kiện.
fco-orderbook — Sổ lệnh điều kiện.
fco-statusHistory — Lịch sử trạng thái lệnh.
6) WebSocket API
WebSocket API cho phép đặt/sửa/hủy lệnh thường, đặt/hủy hàng loạt lệnh (Batch Order), đặt/hủy lệnh điều kiện (FCO), và tra cứu vị thế/số dư/sổ lệnh — tất cả trên một kết nối WebSocket duy nhất, độ trễ thấp hơn nhiều so với gọi REST cho từng lệnh. Trên cùng kết nối, bạn cũng có thể đăng ký nhận thông báo ngay khi lệnh khớp hoặc tài khoản có thay đổi.

Các API chính:

Kết nối WebSocket API
order.place — Đặt lệnh mới.
order.amend — Sửa lệnh.
order.cancel — Hủy lệnh.
order.batchNew — Đặt hàng loạt lệnh.
order.batchCancel — Hủy hàng loạt lệnh.
fco.place — Đặt lệnh điều kiện qua WebSocket.
query.position — Truy vấn vị thế.
subscribe/unsubscribe — Đăng ký nhận thông báo order/portfolio.
7) Phụ lục tham khảo
Các tài liệu bổ sung giúp hiểu rõ hơn về quy trình nghiệp vụ và xử lý lỗi:

Luồng trạng thái lệnh — Sơ đồ và mô tả chi tiết 16 trạng thái lệnh trong vòng đời đặt/sửa/hủy/khớp lệnh.
Tham khảo đặt lệnh điều kiện — Tham số chi tiết và ví dụ JSON cho từng loại lệnh FCO.
Tra cứu mã lỗi (ErrCode) — Bảng mã lỗi đầy đủ phân theo HTTP status code (400, 401, 403, 404, 405, 408, 409, 429, 500, 502, 503, 504).
Khuyến nghị triển khai
Quản lý chặt vòng đời token (cấp mới, refresh, hết hạn).
Chuẩn hóa xử lý lỗi dựa trên ErrCode — xem Tra cứu mã lỗi để map code sang hành động cụ thể.
Tách biệt luồng REST và luồng realtime trong kiến trúc tích hợp.
Với WebSocket, luôn triển khai cơ chế reconnect và subscribe lại topic.
Với lệnh điều kiện (FCO), tham khảo bảng tham số chi tiết để đảm bảo đúng tham số cho từng loại lệnh.