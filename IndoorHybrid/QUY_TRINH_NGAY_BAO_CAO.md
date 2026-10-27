# Quy trình gọn để demo

1. Tắt tất cả Master cũ. Chạy `./run_master.sh`. Bấm **CHẠY MASTER + L1**.
2. Ba laptop khác nối hotspot, bật Anchor Client L2/L3/L4 với session `room_live`, IP Master, interval `1.0` s.
3. Mở **PHÒNG / TỨ GIÁC / VỊ TRÍ L1–L4**, đo và nhập tọa độ + chiều cao thật. Không nhầm thứ tự đỉnh.
4. Khi 4 RSSI đều fresh và BSSID giống nhau, CALIB chung tại vị trí tham chiếu P1 trong 8 mẫu (iPhone đứng yên). Lặp P2 xa P1. Mỗi máy cần >=2 mốc để ước lượng n.
5. Nhấn **START LIVE**, di chuyển iPhone. Chấm đen bám vị trí theo ước lượng Kalman (3 m/s tối đa hiển thị). Không có auto-stop.
6. Thử ba điểm **chưa CALIB**, ghi X/Y thật, bấm **GHI / TÍNH SAI SỐ**; nhận log evaluation để làm bằng chứng báo cáo.
7. Giải thích: RSSI chỉ là cường độ tín hiệu, khoảng cách là ước lượng từ mô hình suy hao đã hiệu chuẩn; không có RSSI → khoảng cách chính xác tuyệt đối, nhất là trong phòng đa đường. Phải công bố sai số đo thật.
