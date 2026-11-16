> Bản chép từ tài liệu SSI FastConnect do người dùng cung cấp ngày 2026-11-15 (nguồn: https://developers.ssi.com.vn). Dùng để tham khảo nội bộ; khi khác thực tế thì thực tế thắng và ghi vào docs/design.md.

WebSocket
Sub/Unsub Market Data
Theo dõi và hủy theo dõi dữ liệu thị trường qua WebSocket FastConnect.

Tổng quan
Kênh DATA trả về 8 nhóm thông tin thị trường:

Topic	Mô tả
trade	Thông tin khớp lệnh
trade.index	Giá trị chỉ số thời gian thực
indexsummary	Thông tin tổng hợp của chỉ số
quote	Thông tin bid/ask
room	Thông tin room ngoại
put	Khớp lệnh thỏa thuận
oddlot	Giao dịch lô lẻ
market	Thông tin đầu ngày và cờ phiên
Topic pattern

trade.[index/exchange/symbol-symbol/*]@[tick/1m/5m]
trade.index.[index_code]@[tick/1m/5m]
indexsummary.[index_code/*]
quote.[index/exchange/symbol-symbol/*]@[tick/1m/5m]
room.[index/exchange/symbol-symbol/*]@[tick/1m/5m]
put.[index/exchange/symbol-symbol/*]@[tick/1m/5m]
oddlot.[index/exchange/symbol-symbol/*]@[tick/1m/5m]
market.[index/exchange/symbol-symbol/*]
Nhiều mã nối bằng dấu - (ví dụ ACB-SSI-GVR-KDH); * cho toàn bộ mã trong phạm vi quyền.
Không truyền @interval thì mặc định là tick. Riêng topic market và indexsummary không có interval.
trade.index và indexsummary chỉ nhận theo mã chỉ số (ví dụ VN30, VNINDEX, HNXINDEX, UPCOMINDEX).
Lưu ý: interval hợp lệ hiện tại là tick, 1m, 5m (không có 3m).

Subscribe market data

{
  "method": "SUBSCRIBE",
  "channel": "DATA",
  "topics": [
    "trade.SSI",
    "trade.ACB-SSI-GVR-KDH",
    "trade.vn30",
    "trade.hose"
  ]
}
trade.SSI — đăng ký nhận message khớp của một mã SSI
trade.ACB-SSI-GVR-KDH — đăng ký nhận message khớp của nhiều mã ACB, SSI, GVR, KDH
trade.vn30 — đăng ký nhận message khớp của toàn bộ các mã thuộc rổ VN30
trade.hose — đăng ký nhận message khớp của toàn bộ các mã thuộc sàn HOSE
Cú pháp tương tự áp dụng cho quote, room, put, oddlot, market — chỉ thay tiền tố topic (ví dụ quote.SSI, room.vn30, market.hose).

Unsubscribe market data

{
  "method": "UNSUBSCRIBE",
  "channel": "DATA",
  "topics": ["trade.SSI", "quote.SSI"]
}
I. Trade — thông tin khớp lệnh
Field	Name	Type	Description
s	symbol	String	Mã chứng khoán
t	tradingTime	String	YYYY/MM/DD HH:mi:ss
p	price	String	Giá khớp (đơn vị: đồng)
q	quantity	String	Khối lượng khớp
a	avgPrice	String	Giá khớp trung bình trong ngày (đơn vị: đồng) = tổng giá trị khớp / tổng khối lượng khớp. "0" nếu chưa có khớp
si	side	String	B: Buy Up (mua chủ động) / S: Sell Down (bán chủ động)
o	openPrice	String	Giá mở cửa (đơn vị: đồng)
h	highPrice	String	Giá cao nhất (đơn vị: đồng)
l	lowPrice	String	Giá thấp nhất (đơn vị: đồng)
v	totalVol	String	Tổng khối lượng khớp trong ngày
Sample output:


{
  "s": "SSI",
  "t": "2026/07/29 09:15:32",
  "p": "45500",
  "q": "1000",
  "a": "45350",
  "si": "B",
  "o": "45000",
  "h": "45800",
  "l": "44900",
  "v": "1250000"
}
I.1. Trade.index — giá trị chỉ số thời gian thực
Một số symbol trên topic trade (ví dụ s: "VN30") không phải cổ phiếu mà là chính giá trị realtime của chỉ số. Subscribe trade.vn30 như trên chỉ trả về các mã thuộc rổ VN30, không trả về giá trị của chính chỉ số. Để nhận tick realtime của bản thân chỉ số, dùng topic riêng trade.index.

Cú pháp subscribe: trade.index.[index_code]@[tick/1m/5m]


{
  "method": "SUBSCRIBE",
  "channel": "DATA",
  "topics": [
    "trade.index.VN30",
    "trade.index.VNINDEX",
    "trade.index.HNXINDEX",
    "trade.index.UPCOMINDEX"
  ]
}
trade.index.VN30 — đăng ký nhận realtime giá trị chỉ số VN30
trade.index.UPCOMINDEX — đăng ký nhận realtime giá trị chỉ số UPCOM. Nguồn HNX phát message gốc với s: "HNXUPCOMINDEX"; server tự động đổi tên thành UPCOMINDEX trước khi trả về client, subscribe bằng tên mới này.
trade.index.VN30@1m, trade.index.VN30@5m — đăng ký nhận nến 1 phút/5 phút của chỉ số. Message nến có data gồm s (mã chỉ số), st (thời điểm bắt đầu nến), t (thời điểm tick gần nhất), o, h, l, c (mở/cao/thấp/đóng), v (khối lượng).
Cấu trúc data của tick (không truyền interval) giống topic trade ở trên (s, t, p, q, v, ...), trong đó p là giá trị điểm số hiện tại của chỉ số.

Sample output:


{
  "s": "VN30",
  "t": "2026/09/14 13:39:10",
  "p": "1928.81",
  "q": "75412",
  "a": "0",
  "si": "",
  "o": "0",
  "h": "0",
  "l": "0",
  "v": "129161843"
}
I.2. Indexsummary — thông tin tổng hợp của chỉ số
Trả ra thông tin tổng hợp của chỉ số theo thời gian thực: giá trị và mức thay đổi của chỉ số, số mã tăng/giảm/đứng giá/trần/sàn, cùng tổng khối lượng và giá trị giao dịch khớp lệnh, thỏa thuận. Khác với trade.index (chỉ trả tick giá trị chỉ số), indexsummary trả thêm thông tin độ rộng thị trường và thanh khoản của chỉ số.

Cú pháp subscribe: indexsummary.[index_code/*]

Topic này cần scope stream:DATA:indexsummary.


{
  "method": "SUBSCRIBE",
  "channel": "DATA",
  "topics": [
    "indexsummary.VN30",
    "indexsummary.VNINDEX",
    "indexsummary.HNXINDEX",
    "indexsummary.UPCOMINDEX"
  ]
}
indexsummary.VN30 — đăng ký nhận thông tin tổng hợp của chỉ số VN30
indexsummary.UPCOMINDEX — đăng ký nhận thông tin tổng hợp của chỉ số UPCOM. Nguồn HNX phát message gốc với s: "HNXUPCOMINDEX"; client subscribe bằng tên UPCOMINDEX, server tự động ánh xạ sang mã gốc.
indexsummary.* — đăng ký nhận thông tin tổng hợp của toàn bộ các chỉ số
Lưu ý: indexsummary chỉ nhận theo mã chỉ số. Không subscribe theo mã sàn (hose, hnx, upcom) hay theo mã chứng khoán như topic trade.

Field	Name	Type	Description
s	indexName	String	Mã chỉ số
b	exchange	String	Sàn chứng khoán của chỉ số
ss	tradingSession	String	Phiên giao dịch hiện tại (ví dụ ATC)
t	tradingTime	String	Thời điểm giao dịch của message, định dạng YYYY/MM/DD HH:mi:ss
v	indexValue	String	Giá trị hiện tại của chỉ số (điểm)
c	indexChange	String	Mức thay đổi của chỉ số so với phiên trước (điểm). Âm: giảm, dương: tăng
cr	indexRatioChange	String	Phần trăm thay đổi của chỉ số so với phiên trước (%). Âm: giảm, dương: tăng
adv	advances	String	Tổng số mã tăng giá
dec	declines	String	Tổng số mã giảm giá
nc	noChange	String	Tổng số mã không thay đổi giá
ce	ceilings	String	Tổng số mã tăng trần
fl	floors	String	Tổng số mã giảm sàn
tmv	totalMatchedValue	String	Tổng giá trị giao dịch khớp lệnh (đơn vị: đồng)
tmq	totalMatchedQty	String	Tổng khối lượng giao dịch khớp lệnh (đơn vị: cổ phiếu)
tvp	totalValuePt	String	Tổng giá trị giao dịch thỏa thuận (đơn vị: đồng)
tqp	totalQtyPt	String	Tổng khối lượng giao dịch thỏa thuận (đơn vị: cổ phiếu)
tq	totalQty	String	Tổng khối lượng giao dịch khớp lệnh và thỏa thuận (đơn vị: cổ phiếu) = tmq + tqp
tv	totalValue	String	Tổng giá trị giao dịch khớp lệnh và thỏa thuận (đơn vị: đồng) = tmv + tvp
Sample output:


{
  "s": "VNIND",
  "b": "HOSE",
  "ss": "ATC",
  "t": "2026/10/13 14:30:55",
  "v": "793.02",
  "c": "-20.44",
  "cr": "-2.51",
  "adv": "15",
  "dec": "47",
  "nc": "11",
  "ce": "1",
  "fl": "0",
  "tmv": "792414028510",
  "tmq": "37448788",
  "tvp": "22700831600",
  "tqp": "1344858",
  "tq": "38793646",
  "tv": "815114860110"
}
II. Room — thông tin room ngoại
Field	Name	Type	Description
s	symbol	String	Mã chứng khoán
t	tradingtime	String	YYYY/MM/DD HH:mi:ss
tr	totalRoom	String	Tổng room ngoại
cr	currentRoom	String	Room ngoại còn lại
bq	buyQuantity	String	Khối lượng mua của khối ngoại
bv	buyValue	String	Giá trị mua của khối ngoại
sq	sellQuantity	String	Khối lượng bán của khối ngoại
sv	sellValue	String	Giá trị bán của khối ngoại
Sample output:


{
  "s": "SSI",
  "t": "2026/07/29 09:15:32",
  "tr": "1500000",
  "cr": "980000",
  "bq": "5000",
  "bv": "227500000",
  "sq": "3000",
  "sv": "136500000"
}
III. Quote — thông tin bid/ask
Field	Type	Description
s	String	Mã chứng khoán
t	String	tradingtime, YYYY/MM/DD HH:mi:ss
bids	List<String[2]>	Danh sách mức giá mua [price, quantity]. Bản nâng cấp sau sẽ chỉ trả ra các giá trị thay đổi.
asks	List<String[2]>	Danh sách mức giá bán [price, quantity]. Bản nâng cấp sau sẽ chỉ trả ra các giá trị thay đổi.
Sample output:


{
  "s": "SSI",
  "t": "2026/07/29 09:15:32",
  "bids": [
    ["45.45", "3200"],
    ["45.40", "1500"],
    ["45.35", "4200"],
    ["45.30", "2100"],
    ["45.25", "3300"]
  ],
  "asks": [
    ["45.50", "2800"],
    ["45.55", "1900"],
    ["45.60", "3600"],
    ["45.65", "2200"],
    ["45.70", "4100"]
  ]
}
IV. Put — khớp lệnh thỏa thuận
Field	Name	Type	Description
s	symbol	String	Mã chứng khoán
t	tradingtime	String	YYYY/MM/DD HH:mi:ss
p	price	String	Giá khớp thỏa thuận
q	quantity	String	Khối lượng khớp thỏa thuận
tq	TotalQuantity	String	Tổng khối lượng thỏa thuận trong ngày
tv	TotalValue	String	Tổng giá trị thỏa thuận trong ngày
Sample output:


{
  "s": "SSI",
  "t": "2026/07/29 10:05:12",
  "p": "45.00",
  "q": "50000",
  "tq": "350000",
  "tv": "15750000000"
}
V. Oddlot — giao dịch lô lẻ
Field	Name	Type	Description
s	symbol	String	Mã chứng khoán
t	tradingtime	String	YYYY/MM/DD HH:mi:ss
p	price	String	Giá khớp lô lẻ
q	quantity	String	Khối lượng khớp lô lẻ
bids	List<String[2]>	Danh sách mức giá mua lô lẻ [price, quantity]	
asks	List<String[2]>	Danh sách mức giá bán lô lẻ [price, quantity]	
Sample output:


{
  "s": "SSI",
  "t": "2026/07/29 09:16:05",
  "p": "45.50",
  "q": "80",
  "bids": [
    ["45.45", "50"],
    ["45.40", "30"]
  ],
  "asks": [
    ["45.55", "40"],
    ["45.60", "20"]
  ]
}
VI. Market — thông tin đầu ngày và phiên
Cú pháp subscribe không có interval: market.[index/exchange/symbol-symbol/*].

Market streaming data:

Field	Name	Type	Description
s	symbol	String	Mã chứng khoán
b	board	String	HOSE, HNX, UPCOM
t	tradingDate	String	YYYY/MM/DD
ce	ceilingPrice	String	Giá trần
fl	floorPrice	String	Giá sàn
ref	refPrice	String	Giá tham chiếu
Sample output:


{
  "s": "SSI",
  "b": "HOSE",
  "t": "2026/07/29",
  "ce": "48.50",
  "fl": "42.10",
  "ref": "45.30"
}
Market flag (message cờ phiên):

Field	Name	Type	Description
b	board	String	HOSE, HNX, UPCOM, DERIVATIVES
t	tradingTime	String	YYYY/MM/DD HH:mm:ss
f	flag	String	Cờ phiên: ATO, LO, ATC, v.v.
Sample output:


{
  "b": "HOSE",
  "t": "2026/07/29 09:00:00",
  "f": "ATO"
}

## Ghi chú của dự án (không thuộc tài liệu SSI)

- [Xác nhận từ mã nguồn SDK, chưa thử thật] Topic `market.flag` trả cờ phiên của mọi sàn. Ví dụ subscribe: `{"method":"SUBSCRIBE","channel":"DATA","topics":["quote.SSI","trade.SSI","market.SSI","market.flag"]}`.
- **[Kiểm tra]** Payload của `market.flag` có đúng dạng `{b,t,f}` như mẫu "Market flag" ở trên không.
- **[Kiểm tra]** Số mức giá thực nhận trong `quote`, thứ tự mức, snapshot đầy đủ hay chỉ phần thay đổi.
- **[Kiểm tra]** Đơn vị giá của `quote`/`market` (đồng hay nghìn đồng) so với mẫu 45.45.
