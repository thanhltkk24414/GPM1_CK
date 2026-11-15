# LIQUIDITY LENS

Đồ án FinTech: giám sát thanh khoản và mất cân bằng sổ lệnh chứng khoán VN theo thời gian thực. **Hạn nộp 2026-12-01.**
Đọc `docs/design.md` (spec) và `docs/superpowers/plans/` (kế hoạch) trước khi làm. Tài liệu API SSI đã lưu trong `docs/ssi/` (nếu có): chỉ dựa vào đó, không đoán.

## Lệnh
- Cài: `python -m venv .venv`, kích hoạt (Windows: `.venv\Scripts\activate`; macOS/Linux: `source .venv/bin/activate`), `pip install -e ".[dev]"`
- Test: `pytest -q`

## Quy tắc bắt buộc
- Giao tiếp tiếng Việt, giữ thuật ngữ tiếng Anh. Code, tên biến, commit bằng tiếng Anh.
- **Không bao giờ** gọi Trading API, `order.*`, `fco.*`, kênh `TRADING`; token chỉ lấy bằng `apiKey` + `apiSecret`, **không** `otp`/`transactionId`.
- Không có khóa trong repo: dùng biến môi trường `SSI_API_KEY`, `SSI_API_SECRET` (xem `.env.example`). Không in khóa/token ra log.
- Không đoán endpoint, tên trường, đơn vị. Điều chưa xác minh ghi `[Kiểm tra]` trong `docs/design.md` và hỏi lại.
- Dữ liệu trong `tests/fixtures/` là dữ liệu mẫu từ tài liệu, phải gắn nhãn; không trình bày như dữ liệu thị trường.
- Timestamp lưu và hiển thị theo `Asia/Ho_Chi_Minh`. Giá nội bộ là VND số nguyên.
- Không viết OBI/Z-score như tín hiệu dự báo giá hay bằng chứng thao túng.
- TDD: viết test trước, chạy thấy FAIL, rồi mới cài đặt. Không đổi tên file/hàm/công thức khi chưa giải thích lý do.
- Dừng và hỏi khi gặp việc không thể hoàn tác (xóa dữ liệu thu, sửa schema đã có dữ liệu).
