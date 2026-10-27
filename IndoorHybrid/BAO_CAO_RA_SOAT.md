# Báo cáo rà soát RangeLive v2 Reliability

**Ngày:** 19/10/2026  
**Phạm vi:** Kiểm tra mã nguồn và thuật toán, không phải thử nghiệm Wi-Fi trên bốn laptop thực.

## Kết luận

Bản `RangeLive_Fresh_v2_Reliability` cũ có cơ chế độ tin cậy thật, không chỉ là nút trang trí: trọng số đi vào hàm tối ưu multilateration và có thể loại L3 hoàn toàn. Tuy nhiên, 29 kiểm thử cũ chưa bao phủ một số trường hợp quan trọng. **Không thể coi các test đó là bằng chứng đã đạt yêu cầu sai số hoặc độ trễ.**

## Các lỗi được sửa trong bản Reviewed

1. **Kalman có thể hiển thị tọa độ ngoài phòng.** Ví dụ, trong phòng 10×6 m với các phép đo RAW tới biên `x=10`, Kalman trước sửa có thể hiển thị `x=10.17` hoặc `x=10.28`. Đã bổ sung phép chiếu nghiệm lên tứ giác lồi sau bước Kalman và ngăn vận tốc nội suy tiếp tục hướng ra ngoài; xử lý được phòng xiên. Thêm test hồi quy cho phòng chữ nhật và tứ giác xiên.
2. **CSV đánh giá sai số thiếu thông tin về cấu hình thuật toán.** Bản cũ chỉ ghi tọa độ và sai số. Nếu cùng buổi thử cả bốn máy và ba máy, rất dễ trộn kết quả. Bản Reviewed bổ sung `excluded_anchor`, `adaptive_weights`, `active_anchors`, chất lượng/trọng số từng anchor, gate, NIS, BSSID hiệu chuẩn, thời gian RSSI gần nhất và mốc ghi LIVE trong CSV đánh giá.

## Các hạn chế đã xác minh, chưa thể giải quyết bằng kiểm thử phần mềm

- **Điểm tin cậy CALIB ≠ xác suất định vị đúng.** `RangeCalibration.quality()` dựa trên số mốc, MAD tại mốc, sai khác RSSI với mô hình log-distance, tình trạng RSSI phẳng/đảo chiều. Không có nhãn sai số khoảng cách ở các mốc kiểm tra độc lập trong cơ chế trọng số hiện tại.
- **Hai mốc 1 m và 6 m không đủ nhận ra L3 phẳng ở 2–6 m.** Trong bộ dữ liệu minh họa `1m:-45, 2m:-59, 4m:-61, 6m:-59 dBm`, hiệu chuẩn chỉ hai mốc 1 m và 6 m có điểm CALIB 0.68, còn đủ bốn mốc có điểm khoảng 0.09. Vì vậy cần thêm mốc 2 m và 4 m.
- **Không bảo đảm mô hình RSSI–khoảng cách đơn trị.** Trong vùng 2–6 m RSSI gần như giống nhau, không thể tái tạo khoảng cách đúng chỉ bằng RSSI L3; thuật toán chỉ có thể hạ ảnh hưởng của anchor này hoặc loại khỏi phép tính.
- **RSSI age hiện đo từ lúc Collector nhận gói, không phải tuổi phép đo vật lý bên trong driver.** Nếu Windows `netsh` trả RSSI đã cache, kiểm tra gói mới không phát hiện chắc chắn. Client có cảnh báo sau 12 RSSI giống hệt, nhưng chưa có cách chứng minh độ mới của driver.
- **Kalman có thể giảm nhiễu nhưng tạo trễ và bias**, nhất là khi chuyển động hoặc reacquire sau khi nhiều phép đo bị gate. Dưới 6 giây là mục tiêu, không phải kết quả đo được.
- **So sánh 3 anchor với 4 anchor cần cùng vị trí thử, tốt hơn là xử lý lại cùng một log RSSI** để tránh thay đổi hướng iPhone, cơ thể chắn sóng và nhiễu môi trường. Bản này chưa tích hợp công cụ replay cùng log; thao tác A/B bằng START LIVE hai lần là kiểm tra sơ bộ, chưa phải so sánh đồng điều kiện.
- **Trọng số là heuristic, chưa được hiệu chỉnh bằng sai số thật từng anchor.** Không bảo đảm adaptive luôn hơn chế độ ba anchor. Cần đánh giá trên điểm chưa dùng CALIB.

## Thực nghiệm phần mềm bổ sung

- 29 test cũ: **PASS**.
- 4 test mới: Kalman bên trong phòng chữ nhật, phép chiếu tứ giác xiên, thông tin cấu hình trong evaluation CSV, và việc 2 mốc không đủ phát hiện plateau: **PASS**.
- Tổng: **33/33**; thử mở Tkinter GUI trong Xvfb: **PASS**.
- Mô phỏng có kiểm soát: L3 gần như cố định -60 dBm ngoài ~2 m, ba laptop còn lại dùng suy hao log-distance với nhiễu giả lập. Adaptive và loại L3 thường cải thiện so với bốn anchor trọng số bằng nhau trong mô phỏng này, nhưng không có khẳng định áp dụng trực tiếp cho phòng thật.
- Chưa chạy đo vật lý với bốn laptop và iPhone 13, chưa chứng minh sai số/độ trễ đầu-cuối.

## Khuyến nghị trình diễn

1. Cố định bốn laptop và iPhone, không restart hotspot trong quá trình CALIB và LIVE. Xác nhận BSSID không đổi.
2. CALIB L3 ở **1, 2, 4, 6 m**. Các laptop khác dùng từ 3 mốc khác nhau trở lên nếu đủ thời gian, mỗi mốc lấy nhiều mẫu RSSI cập nhật thực.
3. Đánh giá với các vị trí **chưa sử dụng CALIB**; trước mỗi phép ghi, để yên iPhone và kiểm tra tuổi RSSI/gate.
4. Thử `Không loại anchor + AUTO`, sau đó `Loại L3 + AUTO`. Phải bấm STOP LIVE trước khi đổi; mỗi phép đánh giá ghi cấu hình vào CSV mới.
5. Đánh giá cả sai số RAW và KALMAN. Không chỉ nhìn điểm tin cậy hoặc chấm đen trông mượt.

## Chạy kiểm thử

```bash
python3 -m unittest discover -s tests -v
```

**Vì lý do thận trọng, hãy sử dụng bản Reviewed riêng và giữ nguyên ZIP cũ dự phòng; chưa nên khẳng định 'đã khắc phục L3' trước khi đo trên thiết bị thật.**
