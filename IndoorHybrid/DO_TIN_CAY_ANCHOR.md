# RangeLive v2 — ĐỘ TIN CẬY ANCHOR (4 anchor hoặc 3 anchor)

## Thay đổi chính

- Giữ nguyên kiến trúc **RSSI thực → Median(3) → CALIB từng laptop → multilateration → Innovation Gate → Kalman 2D**. Không sử dụng 25 điểm/GPR/Radio Map.
- Thêm **điểm chẩn đoán chất lượng CALIB cho từng anchor** (0–100), kèm lý do. Điểm này **không phải xác suất định vị đúng** và không thay thế phép đo sai số độc lập.
- Kiểm tra đường cong RSSI theo khoảng cách: khi hai mốc cách nhau >=1,5 lần mà RSSI giảm dưới 3 dB hoặc tăng ngược, đánh dấu **RSSI phẳng/đảo chiều**. Dùng độ lệch giữa các mốc so với mô hình suy hao để giảm mức tin cậy. Khi RSSI LIVE nằm ngoài dải CALIB cũng giảm độ tin cậy.
- Chế độ **Trọng số tự động**: tính độ không chắc chắn của khoảng cách từ độ dao động RSSI, sai khác mô hình CALIB, hệ số suy hao và điểm chẩn đoán; sau đó dùng weighted robust multilateration. Điểm thấp làm anchor ảnh hưởng ít hơn, không làm nó biến mất.
- Chế độ **Trọng số bằng nhau**: tắt ô “Trọng số tự động” để so sánh A/B trên cùng sơ đồ.
- Chế độ **Loại khỏi phép tính: L3**: chỉ dùng L1/L2/L4. L3 **không cần kết nối** để START LIVE khi đã loại. Ba anchor còn lại phải được CALIB, có RSSI mới, cùng BSSID và **không thẳng hàng**.
- Thay đổi trọng số/anchor loại trừ chỉ được phép khi **STOP LIVE**, nhằm tránh đổi thuật toán giữa chừng. Cấu hình lưu ở `config/state.json`.
- Log `data/positions_live_*.csv` có thêm `weight_L1`–`weight_L4`, `quality_L1`–`quality_L4`, `excluded_anchor`, `adaptive_weights` để phân tích.

## Thao tác nhanh trong GUI

1. Dừng LIVE nếu đang chạy.
2. Ở **ĐỘ TIN CẬY ANCHOR / SO SÁNH 3–4 MÁY**: bật “Trọng số tự động”, chọn “Loại khỏi phép tính: Không”, bấm **ÁP DỤNG**.
3. CALIB các laptop bằng 3–4 mốc tham chiếu. **Riêng L3 nên đo ở 1 m, 2 m, 4 m, 6 m** để phát hiện hiện tượng RSSI phẳng. Mỗi mốc 8–20 mẫu RSSI *mới*, giữ hướng và chiều cao iPhone nhất quán.
4. START LIVE. Quan sát mỗi ô anchor có `Tin cậy: .../100`, tọa độ và các trọng số `w=`.
5. Đánh giá tại tọa độ **chưa dùng CALIB**. Ghi sai số. Kéo thanh cuộn bên phải xuống để thấy phần “GHI / TÍNH SAI SỐ”.
6. STOP LIVE → chọn “Loại khỏi phép tính: L3” → **ÁP DỤNG** → START LIVE → đánh giá tại **chính các vị trí kiểm tra đó**. So sánh sai số thô và Kalman.
7. Có thể STOP LIVE → tắt “Trọng số tự động”, chọn “Không”, ÁP DỤNG để so sánh 4 anchor trọng số bằng nhau.

## Giới hạn quan trọng

- Chỉ 1–2 mốc CALIB **không đủ phát hiện** việc L3 giảm nhanh trong 2 m đầu nhưng gần như đứng yên ở 2–6 m. Đừng suy luận L3 tốt chỉ vì hai mốc khớp mô hình.
- Điểm tin cậy chỉ phản ánh **độ phù hợp của các mốc CALIB**, không phát hiện chắc chắn lỗi driver, RSSI bị cache, thay đổi môi trường hoặc che anten khi đi lại.
- Giảm trọng số L3 có thể cải thiện hoặc làm xấu tọa độ tùy vị trí; **phải đo sai số thật** mới kết luận.
- Không có bảo đảm sai số <1 m hay độ trễ <6 giây trước khi thử trên bốn laptop thật.
- Khi bỏ L3, ba laptop còn lại phải không thẳng hàng và đủ dữ liệu. Hệ thống không tự loại nhiều anchor đồng thời.
- Nếu muốn chuyển dữ liệu CALIB cũ sang bản mới, chỉ chép `config/state.json` khi sơ đồ anchor, chiều cao và BSSID **thực sự không đổi**. Hãy sao lưu trước; đừng ghi đè dữ liệu đang sử dụng.

## Cài đặt

Giải nén vào thư mục riêng, **không chép đè lên bản đang dùng**:

```bash
cd ~/Downloads/IndoorSystem_RangeLive_Fresh_v2_Reliability
chmod +x *.sh
./run_master.sh
```

Nếu thiếu môi trường Python, chạy `./setup_ubuntu.sh` một lần rồi `./run_master.sh`. L2–L4 vẫn có thể dùng Anchor Client cũ (giao thức RSSI v2 không đổi). Đóng Master cũ trước khi mở bản này để tránh trùng TCP 8765/8766.

## Kiểm thử phần mềm

```bash
python3 -m unittest discover -s tests -v
```

Các bài test dùng dữ liệu tổng hợp để kiểm tra luồng xử lý, **không phải bằng chứng độ chính xác thực địa**.
