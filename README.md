# ftu-dstc-fiin-alerts-email (Email-only SMTP)

Hệ thống gửi cảnh báo chứng khoán FTU DSTC qua email SMTP với nhật ký/dedup SQLite.

## 1. Chuẩn bị môi trường
1. Tạo môi trường ảo và cài đặt phụ thuộc:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
   ```
2. Sao chép mẫu cấu hình:
   ```bash
   cp .env.example .env
   ```
3. Cập nhật `.env` với thông tin SMTP (App Password nếu dùng Gmail/Workspace) và đường dẫn SQLite.

## 2. Cấu hình `.env`
- `RUN_MODE` (`INTRADAY|EOD|BOTH`): chế độ chạy mặc định cho producer.
- `INTRADAY_BY`, `INTRADAY_LOOKBACK_MIN`: khung dữ liệu và độ sâu ingest từ FiinQuant.
- `TICKERS`: danh sách mã theo dõi (phân tách bằng dấu phẩy).
- `ALERT_TO`, `ALERT_FROM`, `SUBJECT_PREFIX`: cấu hình email nhận/gửi.
- `SMTP_*`, `MAIL_TO`, `ALERT_DB_PATH`, `SMTP_TIMEOUT`: tham số SMTP + SQLite outbox (Email-only, không cần OAuth).
- `HTTP_MAX_RETRY`: số lần retry cho request HTTP (FiinQuant, Telegram không dùng trong mục C).
- `DATA_PARQUET_PATH`, `FQ_USERNAME`, `FQ_PASSWORD`: nguồn dữ liệu dự phòng.
- `TIMEZONE`: múi giờ, mặc định `Asia/Ho_Chi_Minh`.

## 3. Quickstart / Smoke test
1. Kiểm tra lớp router email + SQLite:
   ```bash
   python -m app.notify.alert_router_email
   ```
   → Nhận email demo, log ghi vào bảng `alerts_sent`/`alerts_outbox`.
2. Dry-run producer (không gửi mail, chỉ log):
   ```bash
   python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode INTRADAY --dry-run --force-test
   ```
3. Gửi thử SMTP thực tế (tùy chọn override người nhận):
   ```bash
   python -m src.fiin_alerts.jobs.send_test_email --to you@example.com
   ```

## 4. Scheduler Email-only
Chạy APScheduler để tự động sinh và gửi cảnh báo qua `AlertRouterEmail`:
```bash
python -m app.schedule.jobs_notify
```
- Khung intraday: 09:15–10:45 (mỗi 15 phút), 11:00/11:15/11:30, 13:00–13:45 (mỗi 15 phút), 14:00/14:15/14:30.
- Khung EOD: 15:00.
- `timezone` đọc từ `.env` (mặc định `Asia/Ho_Chi_Minh`), `coalesce=True`, `max_instances=1`.
- Alert được dedup theo hash `ticker|event|slot` và log đầy đủ vào SQLite.

## 5. Kiến trúc & triển khai
- `src/fiin_alerts/jobs/generate_and_send_alerts.produce_email_alerts()` chỉ tạo danh sách `Alert` cho router, mapping sự kiện `BUY_NEW → Mua mới`, `SELL_TP → Bán chốt lời`, `RISK → Cảnh báo rủi ro`.
- `app/notify/alert_router_email.AlertRouterEmail` gửi qua `smtplib`, retry/backoff, lưu nhật ký vào `alerts_outbox`, dedup qua `alerts_sent`.
- `src/fiin_alerts/jobs/send_test_email` sử dụng cùng router, không cần Gmail client.
- Module OAuth/Telegram vẫn còn trong repo để tham chiếu lịch sử nhưng không còn được gọi trong luồng mục C.

## 6. Giám sát & gỡ lỗi
- Kiểm tra outbox: `sqlite3 alerts.db "select id, ticker, event, status, resp_code, resp_body from alerts_outbox order by id desc limit 10"`.
- Đổi `LOG_LEVEL=DEBUG` trong `.env` để xem chi tiết retry/backoff.
- Nếu SMTP lỗi tạm thời, router tự retry exponential; duplicate bị bỏ qua nhờ hash `ticker|event|slot`.

## 7. Rollback
- Khôi phục các file đã chỉnh sửa (`app/notify/alert_router_email.py`, `app/schedule/jobs_notify.py`, `src/fiin_alerts/jobs/generate_and_send_alerts.py`, `src/fiin_alerts/jobs/send_test_email.py`, `.env.example`, `requirements.txt`, `README.md`, `src/fiin_alerts/config.py`).
- Cài lại các gói Google nếu cần dùng lại Gmail API OAuth (trước đây: `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`).
- Phục hồi tài liệu OAuth cũ (`scripts/init_oauth.py`, `scripts/renew_oauth.py`) nếu muốn quay lại mô hình trước.
