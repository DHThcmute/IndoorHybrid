# Kết quả kiểm thử phần mềm (không phải thí nghiệm đo RSSI ngoài thực tế)

Các trường hợp đã được kiểm tra: giữ nguyên giao thức Anchor Client v2, hiệu chuẩn tọa độ bốn anchor, xây mô hình Hybrid trực tiếp từ các mốc tham chiếu, import CSV chỉ khi người dùng xác nhận, chạy Hybrid LIVE không cần model khoảng cách Geometry, xử lý BSSID thay đổi, kiểm thử ở điểm độc lập không làm thay đổi tập huấn luyện, hoạt động với L3 bị loại trừ, lưu log hai chế độ, kiểm tra biên Kalman, chạy GUI trong Xvfb.

Các phép test tạo dữ liệu RSSI giả lập để kiểm tra logic phần mềm. Không được dùng chúng để tuyên bố độ chính xác thực tế, đặc biệt mục tiêu <1 m hoặc độ trễ <6 s. Các chỉ số Hybrid nghiên cứu ngoại tuyến từ 25 vị trí cũ thuộc nghiên cứu độc lập, không chuyển thành kết quả LIVE của bản GUI này.

## Kiểm tra thực hiện ngày 22-10-2026

- `python3 -m unittest discover -s tests -q`: **40/40 PASS**.
- GUI Tkinter khởi chạy trong màn hình ảo 1680×1050; ảnh `GUI_HYBRID_PREVIEW.png` chụp trực tiếp cửa sổ ứng dụng ở chế độ chưa kết nối.
- Nhập thủ công CSV nguồn 25 mốc / 5.000 mẫu của thí nghiệm cũ: nhận đủ 25 mốc, mô hình fit thành công; một lần suy luận trên lưới hoàn tất trong môi trường kiểm thử. Đây chỉ là smoke test ngoại tuyến, không phải phép đo độ trễ đầu-cuối ngoài phòng.
- Với test RSSI nhân tạo, bộ thu chạy LIVE ở chế độ Hybrid khi không có RangeCalibration và từ chối BSSID khác mốc huấn luyện.
