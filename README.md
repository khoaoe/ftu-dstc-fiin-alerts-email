# ftu-dstc-fiin-alerts-email (SMTP Email-only)

## 1. Tổng quan
- Ứng dụng tạo và gửi cảnh báo chứng khoán FTU DSTC qua email SMTP (không dùng Gmail API/OAuth).
- Dedup & nhật ký lưu trong SQLite (`alerts_sent`, `alerts_outbox`) để đảm bảo idempotent theo hash `ticker|event|slot`.
- Scheduler chạy intraday mỗi 15 phút theo khung HOSE và một lượt cuối ngày lúc 15:00 (mặc định múi giờ `Asia/Ho_Chi_Minh`).

## 2. Thành phần chính
- `src/fiin_alerts/jobs/generate_and_send_alerts.py`: sinh danh sách `Alert` đã chuẩn hóa sự kiện (BUY_NEW/Mua mới, SELL_TP/Bán chốt lời, RISK/Cảnh báo rủi ro).
- `app/notify/alert_router_email.py`: gửi SMTP với backoff, lưu outbox & dedup bằng SQLite.
- `app/schedule/jobs_notify.py`: BlockingScheduler lập lịch intraday/EOD, dùng chung `AlertRouterEmail`.
- `src/fiin_alerts/jobs/send_test_email.py`: gửi email thử bằng cùng router (tùy chọn override người nhận).
- Dữ liệu đầu vào: FiinQuant intraday (`fetch_intraday`) và parquet dự phòng (`load_recent_from_parquet`).

## 3. Chuẩn bị môi trường
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
cp .env.example .env
```
- Tạo App Password nếu dùng Gmail/Workspace và bật 2-Step Verification.

## 4. Cấu hình `.env`
Các biến quan trọng:
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASS`, `SMTP_TIMEOUT`: tham số SMTP (Gmail: host `smtp.gmail.com`, SSL 465 hoặc TLS 587, bắt buộc App Password).
- `MAIL_TO`, `ALERT_TO`, `ALERT_FROM`, `SUBJECT_PREFIX`: cấu hình người nhận/gửi và prefix tiêu đề.
- `ALERT_DB_PATH`: đường dẫn file SQLite outbox/dedup.
- `RUN_MODE` (`INTRADAY|EOD|BOTH`), `INTRADAY_BY` (`1m|5m|15m`), `INTRADAY_LOOKBACK_MIN`: điều khiển producer.
- `TICKERS`: danh sách mã mặc định, phân tách dấu phẩy.
- `DATA_PARQUET_PATH`: file parquet fallback khi không lấy được realtime.
- `FQ_USERNAME`, `FQ_PASSWORD`: thông tin FiinQuant (để trống nếu không dùng).
- `HTTP_MAX_RETRY`: retry các request HTTP (FiinQuant).
- `TIMEZONE`: múi giờ cho scheduler & producer (mặc định `Asia/Ho_Chi_Minh`).
- `ENV_NAME`: nhãn môi trường thêm vào subject/log.
- Phần Telegram vẫn giữ trống với ghi chú "KHÔNG dùng trong mục C" để tránh lỗi import.

## 5. Kiểm thử nhanh
1. **Smoke router SMTP + SQLite**
   ```bash
   python -m app.notify.alert_router_email
   ```
   → Tạo 1 alert demo, ghi log `alerts_outbox`, kiểm tra bảng bằng `sqlite3 alerts.db "select id,ticker,event,status from alerts_outbox order by id desc limit 5"`.
2. **Dry-run producer**
   ```bash
   python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode INTRADAY --dry-run --force-test
   ```
   → Chỉ log kết quả, không gửi email.
3. **Gửi thử thực tế**
   ```bash
   python -m src.fiin_alerts.jobs.send_test_email --to you@example.com
   ```
   → Nếu thấy lỗi `535 5.7.8` hãy kiểm tra lại App Password hoặc bật 2FA.

## 6. Scheduler intraday & EOD
```bash
python -m app.schedule.jobs_notify
```
- Intraday: 09:15–10:45 (mỗi 15 phút), 11:00/11:15/11:30, 13:00–13:45 (mỗi 15 phút), 14:00/14:15/14:30.
- EOD: 15:00.
- `coalesce=True`, `max_instances=1`, `misfire_grace_time` 120s (intraday) và 600s (EOD).
- Dùng chung một `AlertRouterEmail` instance để tận dụng dedup/outbox.
- Dừng bằng `Ctrl+C` (scheduler shutdown an toàn).

## 7. Vận hành sản xuất
- Producer sẽ thử ingest realtime từ FiinQuant (nếu có tài khoản), fallback sang parquet.
- Mỗi `Alert` chứa `extras` với `event_label`, `mode`, `price_hint`, v.v… giúp hiển thị mail rõ ràng.
- Router tính hash theo `(ticker, event, slot_start UTC floored)` để tránh gửi trùng.
- Các bản ghi outbox lưu mã phản hồi SMTP, số lần retry; xem log qua `sqlite3` hoặc đọc file DB bằng GUI.

## 8. Giám sát & gỡ lỗi
- Kiểm tra log: đặt `LOG_LEVEL=DEBUG` trong `.env` để theo dõi retry/backoff.
- SMTP lỗi tạm thời (421/450/451/452, timeout, disconnect) sẽ được retry exponential tối đa `max_retry`.
- Lỗi xác thực (535, 534) thường do Sai App Password, tài khoản chưa bật 2FA hoặc bị chặn "Less secure app".
- Để kiểm tra nhanh trạng thái mới nhất:
  ```bash
  sqlite3 alerts.db "select ts, ticker, event, status, resp_code from alerts_outbox order by id desc limit 10"
  ```

## 9. Rollback
- Khôi phục các file đã chỉnh sửa: `app/notify/alert_router_email.py`, `app/schedule/jobs_notify.py`, `src/fiin_alerts/jobs/generate_and_send_alerts.py`, `src/fiin_alerts/jobs/send_test_email.py`, `.env.example`, `requirements.txt`, `README.md`, `src/fiin_alerts/config.py`.
- Cài lại bộ thư viện Google nếu quay về mô hình Gmail API OAuth (`google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`).
- Khôi phục tài liệu/flow OAuth cũ (`scripts/init_oauth.py`, `scripts/renew_oauth.py`) nếu cần sử dụng lại.
