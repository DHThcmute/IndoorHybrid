# IndoorSystem HYBRID LIVE — GUI riêng cho thuật toán RSSI xác suất

**Đây là ứng dụng độc lập**, KHÔNG phải bản cập nhật ghi đè RangeLive v2. Bạn có thể đặt hai thư mục cạnh nhau. Chỉ chạy **một Master tại một thời điểm**, vì cả hai dùng cổng `8765` (RSSI) và `8766` (điều khiển GUI).

**Trạng thái:** Đã kiểm thử phần mềm bằng dữ liệu tổng hợp; GUI đã mở thử trong môi trường kiểm thử. Chưa chạy thử trực tiếp với bốn laptop của bạn. Hiệu năng mô phỏng KHÔNG phải kết quả RSSI ngoài thực tế; chưa bảo đảm độ chính xác dưới 1 m hoặc độ trễ dưới 6 giây.

## 1. Hybrid làm gì khác?

- Với bốn RSSI (L1–L4), Hybrid tính độ phù hợp tín hiệu của **nhiều tọa độ** trên lưới phòng; không ép mỗi RSSI trở thành đúng một khoảng cách.
- Mô hình được học từ các vị trí hiệu chuẩn do bạn đo thật: log-distance vật lý + hiệu chỉnh không gian RBF trơn có chính quy hóa; dùng mất mát robust để hạn chế ngoại lai.
- Kết quả có vị trí RAW, vị trí Kalman 2D, điểm ứng viên thay thế và bán kính phân tán *tương đối* từ mô hình. Bán kính này **không phải cam kết 68% về sai số thực nghiệm**.
- Có chế độ **GEOMETRY** cũ để đối chứng, nhưng HYBRID chạy độc lập ngay cả khi chưa có model RSSI→khoảng cách của Geometry.
- Nếu một laptop đo kém (ví dụ L3), có thể chọn **Loại L3**; khi đó Hybrid dùng RSSI của ba máy còn lại. Tự động giảm độ tin cậy chỉ dùng khi có đủ thông tin CALIB chất lượng, không coi score là xác suất đúng.
- KHÔNG tự nạp dữ liệu cũ, không tự học từ vị trí test, không đọc tọa độ iPhone trong lúc START LIVE.

## 2. Cài đặt MASTER Ubuntu

1. Giữ nguyên thư mục RangeLive v2 cũ, **dừng Master cũ**.
2. Giải nén ZIP, vào thư mục `IndoorSystem_Hybrid_IMU_Plot`.
3. Trên Terminal:

```bash
cd ~/Downloads/IndoorSystem_Hybrid_IMU_Plot
chmod +x *.sh
./setup_ubuntu.sh
./run_master.sh
```

Nếu đã cài Python 3, numpy, scipy, tkinter, và `iw` thì có thể bỏ qua bước `setup_ubuntu.sh`.

4. Trong GUI, để Session `room_live` hoặc tên khác nhất quán. Nhấn **CHẠY MASTER + L1**.
5. L2/L3/L4 dùng Anchor Client cũ đang chạy tốt (không bắt buộc thay). Chọn ID đúng, nhập **IP của Master**, cổng 8765, cùng Session, kết nối cùng Personal Hotspot của iPhone. Trên GUI, kiểm tra cả bốn RSSI cập nhật liên tục. Tắt chế độ Sleep và cắm sạc laptop.

> Nếu GUI nói cổng đang bận, đóng **Master của bản RangeLive v2 trước**. Không chạy hai Master đồng thời.

## 3. Cấu hình phòng và vị trí bốn anchor

Chọn **PHÒNG / TỨ GIÁC / VỊ TRÍ L1–L4**. Bạn có thể nhập chữ nhật 5×5 m, 6×4 m hoặc tứ giác lồi với tọa độ Q1–Q4 ngược chiều kim đồng hồ. Nhập tọa độ thực X, Y, Z của từng laptop và chiều cao iPhone khi hiệu chuẩn. Đổi hình học sẽ xóa các mốc hiệu chuẩn cũ (vì không còn đúng hệ tọa độ).

## 4. Cách huấn luyện Hybrid KHÔNG cần CSV

Đây là cách an toàn nhất nếu hotspot hoặc cách bố trí phòng đã thay đổi:

1. Đặt iPhone ở vị trí có X/Y/Z **đã đo thật**, giữ cố định trong lúc lấy mẫu. Giữ hướng máy và cao độ nhất quán.
2. Ở mục **THU MỐC TỌA ĐỘ THẬT CHO HYBRID**, nhập X, Y, Z, số mẫu `8` (nên 10–15 nếu có đủ thời gian), nhấn **CALIB CẢ 4 MÁY TẠI MỐC NÀY**.
3. Chờ cho đến khi Master báo hiệu chuẩn xong và trở về `IDLE`.
4. Chuyển điện thoại đến vị trí khác, lặp lại. Phải có **ít nhất 8 mốc** phân bố ở cả X và Y, không thẳng hàng. Khuyến nghị **12–25 mốc phủ vùng đo**, gồm tâm, biên và các góc gần khu vực thường đi lại. Một mốc tương ứng với bốn RSSI; không nhấn CALIB từng anchor nếu muốn thêm một mốc tọa độ Hybrid.
5. Nhấn **XÂY / CẬP NHẬT MÔ HÌNH HYBRID**. GUI hiển thị `SẴN SÀNG`.
6. Chọn chế độ `hybrid` và bấm **START LIVE**. Chấm đen = vị trí sau lọc; vòng xám = đo thô; vòng đứt nét = độ phân tán mô hình tham khảo.
7. Di chuyển iPhone: không cần nhập tọa độ thật khi LIVE. Tọa độ thật chỉ dùng sau đó ở mục **KIỂM TRA** để ghi sai số.

**Không CALIB tại vị trí dùng để kiểm tra độc lập.** Cần tối thiểu 5–10 vị trí kiểm tra ngoài những điểm đã đo làm mô hình, và đi thử ở nhiều hướng. Nếu thêm điểm hiệu chuẩn, nhấn lại **XÂY MÔ HÌNH**.

## 5. Nhập CSV làm mốc Hybrid (chỉ khi chắc chắn phù hợp)

Nút **NHẬP MỐC TỪ CSV** là tùy chọn thủ công; không phải điều kiện bắt buộc. Nó hỗ trợ CSV gồm các dòng `point_id`, `anchor_id`, `x_true_m`, `y_true_m`, `rssi_dbm`, `bssid`, tùy chọn `z_true_m` và `orientation_deg` (=0).

Điều kiện:
- CSV và thí nghiệm hiện tại cùng **BSSID của iPhone**, cùng vị trí bốn anchor, hệ tọa độ, chiều cao/hướng iPhone.
- Mỗi điểm tọa độ có đủ RSSI của bốn anchor, không trộn nhiều BSSID hoặc sai nhãn điểm.
- Phải xác nhận thủ công trên cửa sổ GUI. Chương trình không tự động nạp dữ liệu quá khứ.
- Không đưa điểm kiểm thử độc lập vào CSV CALIB. Nếu hotspot đổi BSSID, đo lại, không cố vượt cảnh báo.

**Đặc biệt:** bộ 25 điểm cũ chỉ có ích nếu mọi điều kiện nói trên khớp; không nên import chỉ để thấy chấm định vị chạy.

## 6. So sánh thực nghiệm

Có hai chế độ hiển thị: `hybrid` (mặc định) và `geometry` (đối chứng). Chế độ Geometry chỉ dùng khi từng anchor đã CALIB RSSI–khoảng cách, nhưng Hybrid không cần điều kiện này.

Chọn `Loại khỏi phép tính: Không` hoặc `L3` rồi **ÁP DỤNG** (chỉ khi STOP LIVE). Bạn có thể so sánh 4 anchor và 3 anchor trên cùng các vị trí kiểm tra. Tránh chọn mô hình chỉ dựa trên một lần đi qua phòng.

Tại vị trí test chưa huấn luyện, nhập `X thật, Y thật`, nhấn **GHI / TÍNH SAI SỐ**. Đây là một thao tác chỉ phục vụ đánh giá, tọa độ không đi vào mô hình định vị đang chạy. Kết quả ghi tại `data/evaluation_...csv`. Mỗi chu kỳ LIVE có RSSI / kết quả ở `data/positions_live_...csv`, dữ liệu gói nhận ở `data/rssi_raw_...csv`.

## 7. Giới hạn kỹ thuật

- RSSI không đo trực tiếp khoảng cách và có thể bị thay đổi đáng kể bởi hướng cầm iPhone hoặc vật cản.
- Mô hình không nhìn thấy tương lai. Ngoại suy khỏi các vùng có mốc hiệu chuẩn là rủi ro lớn; kết quả kiểm thử bỏ nguyên một cột vị trí cho thấy mô hình cục bộ có thể kém hơn giải pháp vật lý.
- Độ trễ đầu-cuối còn phụ thuộc driver Wi-Fi, thời gian lấy RSSI và Kalman; chưa đo xác nhận dưới 6 giây trên bộ thiết bị thực tế.
- Phiên bản hiện đã có **bộ tiếp nhận và hợp nhất IMU từ iPhone qua Sensor Logger**; truyền dữ liệu thực tế trong khi điện thoại phát hotspot vẫn cần kiểm chứng trên thiết bị thật (xem mục 9).
- Không dùng `measurement_mode=simulation` cho LIVE; collector chỉ chấp nhận gói khai báo đo thực, còn test phần mềm có dữ liệu nhân tạo riêng và không chứng minh đo ngoài đời.

## 8. Tự chạy kiểm thử phần mềm

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Dữ liệu trong các bài test là RSSI **tổng hợp** nhằm kiểm tra thuật toán và giao thức, không phải sai số thực nghiệm.

## 9. Tích hợp IMU từ iPhone bằng Sensor Logger (bản thử nghiệm)

Bản này đã tích hợp **nhận dữ liệu IMU trực tiếp qua mạng**, nhưng **chưa xác minh truyền thành công khi iPhone 13 đang phát Personal Hotspot**. Chế độ IMU là lựa chọn **bật/tắt độc lập**, mặc định TẮT để tránh làm thay đổi kết quả Hybrid khi chưa kiểm tra.

### Thao tác trên iPhone

1. Cài **Sensor Logger** của Kelvin Choi trên iPhone (một số tính năng stream có thể cần gói trả phí). Mở ứng dụng, vào phần cấu hình HTTP Push, bật gửi dữ liệu qua HTTP. Thông tin kỹ thuật: <https://github.com/tszheichoi/awesome-sensor-logger/blob/main/PUSHING.md>.
2. Chỉ bật tối thiểu cảm biến **Accelerometer** và **Orientation**. Theo tài liệu Sensor Logger, gia tốc đơn vị m/s², yaw đo bằng radian; dữ liệu gửi theo dạng JSON cùng timestamp epoch nanoseconds.
3. Nhập URL đang hiển thị trong GUI: `http://IP_MASTER:8767/imu`. Ví dụ nếu Master là `172.20.10.2`, URL tương ứng là `http://172.20.10.2:8767/imu`. **Không dùng `localhost` trên iPhone.** Cổng 8767 chỉ nhận dữ liệu IMU, hai cổng RSSI 8765 và điều khiển 8766 giữ nguyên.
4. Chạm **Test Pushing** nếu ứng dụng có chức năng này; sau đó bắt đầu **Recording** để dữ liệu thực sự truyền liên tục. Một gói thử không có bản ghi accelerometer/orientation chưa đủ để căn hướng.
5. Trên GUI phải thấy số **gói IMU** tăng và trạng thái `IMU đã nhận, cần CĂN HƯỚNG`.

Nếu không thấy gói IMU, cần kiểm tra liệu iPhone có thể kết nối TCP đến laptop Master trên chính mạng hotspot nó đang phát hay không. **Chưa có kiểm chứng trên iPhone thực tế trong môi trường xây dựng này.** Nếu không có đường kết nối, không có phép thuật xử lý tín hiệu nào thay thế được luồng dữ liệu bị thiếu.

### Căn hướng và cho phép PDR

1. STOP LIVE. Để điện thoại **nằm gần ngang, màn hình hướng lên**, đầu điện thoại chỉ theo đúng **hướng định di chuyển**. Khi đi, giữ cố định đầu máy với hướng đi; không xoay điện thoại ngẫu nhiên trong tay.
2. Trên bản đồ, 0° là hướng +X (phải), 90° là hướng +Y (lên), 180° là -X, 270° là -Y. Nhập hướng bạn đang chỉ đầu điện thoại, ví dụ `0`, vào ô **Đặt ĐẦU iPhone theo hướng bản đồ**, nhấn **CĂN HƯỚNG**.
3. Chọn **Dùng IMU làm prior mềm**; nhập chiều dài bước dự kiến (mặc định 0.62 m) rồi nhấn **ÁP DỤNG IMU**. Có thể thay đổi độ dài bước từ 0.25 đến 1.10 m tùy người dùng.
4. **LƯU Ý THỨ TỰ:** Khi nhấn ÁP DỤNG IMU, bộ lọc vị trí được khởi tạo lại; bạn có thể bật IMU trước hoặc sau khi căn hướng. Nếu app Sensor Logger bắt đầu phiên ghi mới thì phải căn hướng lại vì góc yaw có thể đổi mốc tham chiếu.
5. Nhấn START LIVE. Đi thử một đường thẳng 3–4 m, giữ tư thế máy ổn định và quan sát số bước, hướng và sai số. Dữ liệu IMU là dự đoán chuyển động *mềm* cho trường xác suất RSSI. Khi IMU không còn mới (quá 2.5 s), không có dữ liệu Orientation, hoặc chưa căn hướng thì chỉ dùng RSSI.

### Cơ chế và giới hạn cần hiểu

- Không tích phân gia tốc hai lần vì sai số trôi rất nhanh. Thay vào đó, hệ thống tìm **đỉnh động gia tốc tương đối**, ước lượng bước chân với khoảng nghỉ tối thiểu 0.36 s, tích lũy độ dài và hướng bước.
- Mỗi lần có tọa độ RSSI mới, nếu có bước chân IMU hợp lệ kể từ lần cập nhật trước, thuật toán tạo một **prior vị trí**. Dữ liệu Wi-Fi tiếp tục quyết định nghiệm xác suất; phần IMU không làm giả RSSI, không lấy tọa độ thật trong khi LIVE.
- Hướng yaw chỉ đáng tin khi điện thoại gần ngang và hướng đầu máy gần với hướng đi; xoay máy trong tay sẽ khiến prior sai.
- Bộ đếm bước còn là thuật toán thử nghiệm với ngưỡng cố định; chưa được hiệu chuẩn với dáng đi thực tế. Có thể bỏ bước, đếm nhầm, hoặc lệch chiều dài bước. Vì vậy, phải **so sánh IMU TẮT/BẬT ở cùng đường đi trước khi kết luận nó cải thiện độ chính xác**.
- Dữ liệu gửi HTTP nội bộ chưa mã hóa và không có xác thực trong bản thử nghiệm; chỉ dùng trong mạng thử nghiệm riêng và không công khai cổng 8767 ra Internet.
- Kết quả trong `data/positions_live_*.csv` có các trường `imu_enabled`, `imu_fresh`, `imu_fused`, `imu_step_count`, `imu_steps_since_wifi`, `imu_heading_deg`, `imu_prior_x`, `imu_prior_y`. Chỉ `imu_fused=True` mới là chu kỳ định vị có dùng prior chuyển động mới.



## 10. TAB PLOT KHOẢNG CÁCH: 4 BIỂU ĐỒ SONG SONG (MỚI)

Mở tab **PLOT KHOẢNG CÁCH L1–L4** cạnh tab **BẢN ĐỒ / LIVE**. Chức năng này dùng để đo thực nghiệm, **không tác động đến mô hình Hybrid, IMU, Kalman hoặc tọa độ LIVE**.

1. Nhấn **CHẠY MASTER + L1**, kết nối L2–L4 như bình thường. **Không bắt buộc nhấn START LIVE** để ghi biểu đồ.
2. Cần có mô hình **RSSI → khoảng cách** cho từng laptop. Nếu tab báo `CHƯA CALIB`, dùng mục **CALIB CẢ 4 MÁY TẠI MỐC NÀY** ở **ít nhất 2 mốc xa nhau** để lấy hệ số suy hao riêng cho từng laptop (3 mốc trở lên tốt hơn). Mô hình Hybrid xác suất có thể chạy độc lập, nhưng không tự cung cấp một khoảng cách RSSI đo trực tiếp; vì vậy biểu đồ tuyệt đối không tự đoán khoảng cách khi chưa có hiệu chuẩn.
3. Cố định iPhone tại **điểm kiểm tra thực**. Đo và nhập khoảng cách đến L1, L2, L3, L4. Dùng số đo trực tiếp theo không gian **3D** (từ anten laptop đến điện thoại) nếu chọn `3d`. Nếu khoảng cách đo trên mặt sàn, chọn `2d`. Không trộn hai cách đo trong cùng một lượt.
4. Nhấn **BẮT ĐẦU GHI**. Cả bốn biểu đồ được cập nhật từ RSSI mới của từng laptop. **Đường đỏ đứt nét** là khoảng cách thực được nhập; **đường xanh** là khoảng cách do RSSI + mô hình hiệu chuẩn riêng của anchor suy ra. Các đường không bị tự động dịch để khớp nhau. Trên biểu đồ hiện số mẫu, RSSI cuối, **MAE** (lỗi tuyệt đối trung bình, mét) và **Bias** (sai lệch có dấu, mét).
5. Giữ điện thoại đứng yên 30–60 giây để đánh giá dao động. Chọn cửa sổ 30/60/120/300/600 giây khi xem. Nhấn **DỪNG GHI → LƯU CSV** để lưu đầy đủ chuỗi đo phục vụ báo cáo. Khi kiểm tra điểm mới, nhập lại 4 khoảng cách rồi **BẮT ĐẦU GHI** để làm sạch dữ liệu điểm cũ.

**Cảnh báo khoa học:** Nếu đường xanh không dao động quanh đường đỏ mà nằm lệch cố định, đó là **sai số hệ thống của mô hình** hoặc đặc tính sóng/phần cứng. Nếu L3 không thay đổi RSSI khi đưa iPhone từ 2 đến 6 m, đồ thị sẽ phơi bày giới hạn này; Kalman không thể khôi phục khoảng cách bị mất. Một mốc CALIB có `n = 2` chỉ là **hiệu chuẩn tạm**, nên hãy đo thêm mốc gần và xa. Hệ thống chỉ chấp nhận gói mới, còn hạn sử dụng và **cùng BSSID với CALIB**; dữ liệu cũ hoặc khác BSSID không được vẽ thành dữ liệu mới.

CSV xuất gồm `timestamp, elapsed_s, anchor, seq, rssi_dbm, reference_m, estimated_m, error_m, absolute_error_m, cal_A, cal_n, cal_points, provisional, mode, bssid, session`.
