# HƯỚNG DẪN TAB PLOT KHOẢNG CÁCH (L1–L4)

Tab mới **PLOT KHOẢNG CÁCH L1–L4** nằm cạnh tab **BẢN ĐỒ / LIVE**. Bốn đồ thị hiển thị đồng thời trong cùng cửa sổ:

- Đỏ nét đứt: **khoảng cách thực do bạn nhập**, được giữ cố định trong một phép đo.
- Xanh: **khoảng cách ước lượng từ mẫu RSSI mới**, theo mô hình Log-Distance được hiệu chuẩn riêng cho từng máy.
- Dòng thông số mỗi biểu đồ: số mẫu, RSSI gần nhất, MAE (trung bình lỗi tuyệt đối) và Bias (lỗi trung bình có dấu).
- Trục ngang: **thời gian kể từ lúc bắt đầu ghi (giây)**; trục dọc: **khoảng cách (mét)**.

## Trình tự sử dụng

1. Dừng Master cũ, mở Master mới, kết nối cả 4 laptop L1–L4. Không bắt buộc chạy thuật toán định vị LIVE.
2. Hiệu chuẩn **RSSI → khoảng cách**: dùng công cụ **CALIB CẢ 4 MÁY TẠI MỐC NÀY** ở tối thiểu 2 mốc khác khoảng cách đủ rõ (khuyến nghị từ 3 mốc), hoặc CALIB riêng từng laptop. Lưu ý: chỉ nạp mốc Hybrid xác suất từ CSV mà không tạo mô hình khoảng cách thì tab sẽ chưa thể vẽ đường xanh.
3. Đặt iPhone cố định tại một điểm. Đo bốn khoảng cách thực từ iPhone đến vị trí anten L1, L2, L3, L4. Nhập bốn ô L1→L4 **theo đúng thứ tự**.
4. Chọn cách đo: `3d` = thước đo thẳng trong không gian (mặc định), `2d` = khoảng cách chiếu trên mặt sàn. Nếu bạn đo theo mặt sàn thì không chọn `3d`.
5. Nhấn **BẮT ĐẦU GHI**. Quan sát bốn đường xanh dao động theo mẫu RSSI mới trong 30–60 giây. Bạn có thể chọn cửa sổ biểu đồ 30/60/120/300/600 giây; dữ liệu thô vẫn được lưu trong bộ nhớ cả phiên.
6. Nhấn **DỪNG GHI → LƯU CSV** để xuất dữ liệu. Khi chuyển đến một vị trí thử mới, nhập lại bốn khoảng cách thực và bắt đầu ghi, hệ thống tự làm sạch bốn chuỗi cũ.

## Diễn giải

- Đường xanh dao động quanh đường đỏ: mô hình RSSI–khoảng cách phù hợp tương đối tại điểm đang đo.
- Đường xanh luôn ở phía trên: ước lượng khoảng cách quá xa (Bias > 0); phía dưới: ước lượng quá gần (Bias < 0).
- L3 không đổi ở nhiều khoảng cách khác nhau: có thể do kênh truyền/anten/driver, không thể sửa chỉ bằng median hoặc Kalman.
- Đường xanh không xuất hiện: kiểm tra RSSI mới, tình trạng CALIB, BSSID và tuổi gói dữ liệu. Không có đường xanh không có nghĩa RSSI bằng 0.

**QUAN TRỌNG:** khoảng cách thực chỉ được dùng làm đường tham chiếu và tính sai số, không tham gia quá trình đổi RSSI thành khoảng cách hoặc định vị. Vùng thời gian có vẻ phẳng có thể là tín hiệu thật ít biến thiên, không tự động kết luận thiết bị lỗi; cần lặp phép thử ở nhiều khoảng cách/hướng.

Nếu hotspot đổi BSSID hoặc thông số CALIB thay đổi trong khi ghi, tab tự dừng để tránh trộn các mô hình. Dữ liệu cũ chưa bị xóa; bạn có thể xuất CSV trước khi bắt đầu lượt mới.

CSV lưu trường `timestamp, elapsed_s, anchor, seq, rssi_dbm, reference_m, estimated_m, error_m, absolute_error_m, cal_A, cal_n, cal_points, provisional, mode, bssid, session`.

> Hình `GUI_PLOT_PREVIEW_SYNTHETIC.png` là **ảnh minh họa giao diện tạo bằng dữ liệu giả lập**. Không dùng các đường trong ảnh để báo cáo độ chính xác thực tế.
