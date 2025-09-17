# ftu-dstc-fiin-alerts-email (Gmail API)

## 1. Tổng quan
- Ứng dụng sinh cảnh báo chứng khoán FTU DSTC và gửi qua Gmail API (OAuth2).
- Lịch chạy: intraday mỗi 15 phút trong giờ HOSE, thêm lượt cuối ngày 15:00 (múi giờ `Asia/Ho_Chi_Minh`).
- Tránh gửi trùng bằng cách lưu dấu `ticker:event:slot` trong SQLite (`alerts_state.sqlite`).

## 2. Thành phần chính
- `src/fiin_alerts/jobs/generate_and_send_alerts.py`: kết nối nguồn dữ liệu, tạo cảnh báo, render email, gọi Gmail API.
- `src/fiin_alerts/notify/gmail_client.py`: bọc Gmail API (`users.messages.send`) với tự động refresh token.
- `src/fiin_alerts/jobs/send_test_email.py`: script gửi email thử nhanh.
- `app/schedule/jobs_notify.py`: APScheduler lập lịch chạy `generate_and_send_alerts.run_once` theo khung intraday/EOD.

## 3. Chuẩn bị môi trường
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
cp .env.example .env
```
Tiếp theo:
1. Tạo project Google Cloud và tải `credentials.json` (Gmail API OAuth client) vào thư mục `secrets/`.
2. Khởi tạo token lần đầu:
   ```bash
   python scripts/init_oauth.py
   ```
   -> sinh `secrets/token.json` dùng cho các lần gửi tiếp theo.

## 4. Cấu hình `.env`
- `ALERT_TO`, `ALERT_FROM`, `SUBJECT_PREFIX`: cấu hình email nhận/gửi (đặt `ALERT_FROM=me` để dùng account vừa ủy quyền).
- `RUN_MODE` (`INTRADAY|EOD|BOTH`), `INTRADAY_BY`, `INTRADAY_LOOKBACK_MIN`: tham số lấy dữ liệu realtime từ FiinQuantX.
- `TICKERS`: danh sách mã mặc định.
- `DATA_PARQUET_PATH`: fallback parquet khi không truy cập được realtime.
- `FQ_USERNAME`, `FQ_PASSWORD`: thông tin FiinQuantX (bỏ trống nếu không dùng).
- `TIMEZONE`: múi giờ dùng cho scheduler.

## 5. Kiểm thử & vận hành
1. **Gửi thử Gmail API**
   ```bash
   python -m src.fiin_alerts.jobs.send_test_email --to you@example.com
   ```
   Thêm `--dry-run` nếu chỉ muốn hiển thị subject/recipients.
2. **Tạo cảnh báo và gửi một lượt**
   ```bash
   python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode INTRADAY --force-test
   ```
   - Thêm `--dry-run` để kiểm tra nội dung email nhưng không gửi.
   - Dùng `--to` để override danh sách nhận.
3. **Chạy scheduler**
   ```bash
   python -m app.schedule.jobs_notify
   ```
   - Intraday: 09:15–10:45 (mỗi 15 phút), 11:00/11:15/11:30, 13:00–13:45 (mỗi 15 phút), 14:00/14:15/14:30.
   - EOD: 15:00.
   - Dừng bằng `Ctrl+C` (scheduler sẽ shutdown an toàn).

## 6. Gỡ lỗi & giám sát
- Check file `alerts_state.sqlite` để theo dõi nhãn đã gửi:
  ```bash
  sqlite3 alerts_state.sqlite "select ts, k from sent order by ts desc limit 10"
  ```
- Nếu Gmail API trả `401` hoặc `invalid_grant`, chạy lại `python scripts/renew_oauth.py`.
- Đặt `LOG_LEVEL=DEBUG` trong `.env` (hoặc biến môi trường) để xem chi tiết pipeline.

## 7. Rollback
- Khôi phục các file sửa đổi (`app/schedule/jobs_notify.py`, `src/fiin_alerts/jobs/generate_and_send_alerts.py`, `src/fiin_alerts/jobs/send_test_email.py`, `.env.example`, `requirements.txt`, `README.md`, `src/fiin_alerts/config.py`).
- Xóa `alerts_state.sqlite` nếu muốn làm sạch bộ nhớ dedup.
- Nếu cần quay lại SMTP/Telegram, phục hồi file/requirements cũ từ VCS.
