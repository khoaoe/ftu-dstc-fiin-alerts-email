# ftu-dstc-fiin-alerts-email

Hệ thống gửi cảnh báo chứng khoán FTU DSTC qua Gmail (OAuth2) và các kênh bổ sung.

## 1. Chuẩn bị môi trường
1. Tải file `credentials.json` từ Google Cloud Console và đặt vào thư mục `secrets/`.
2. Tạo môi trường ảo và cài đặt phụ thuộc:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
   ```
3. Tạo file cấu hình môi trường:
   ```bash
   cp .env.example .env
   ```
4. Khởi tạo OAuth cho Gmail (tạo `secrets/token.json`):
   ```bash
   python scripts/init_oauth.py
   ```

## 2. Cấu hình `.env`
Điền các biến môi trường theo nhu cầu:
- `RUN_MODE` (`INTRADAY|EOD|BOTH`): chế độ chạy mặc định.
- `INTRADAY_BY` (`1m|5m|15m`) và `INTRADAY_LOOKBACK_MIN`: khung thời gian và số phút truy hồi dữ liệu FiinQuant.
- `TICKERS`: danh sách mã cổ phiếu mặc định (phân tách bằng dấu phẩy).
- `ALERT_TO`, `ALERT_FROM`, `SUBJECT_PREFIX`: cấu hình email gửi/nhận.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`: thông tin bot và danh sách chat ID nếu muốn gửi Telegram.
- `GMAIL_MAX_RETRY`, `HTTP_MAX_RETRY`: số lần thử lại tối đa cho Gmail/API bên ngoài.
- `DATA_PARQUET_PATH`, `FQ_USERNAME`, `FQ_PASSWORD`: nguồn dữ liệu dự phòng (parquet) và tài khoản FiinQuant.
- `TIMEZONE`: múi giờ (mặc định `Asia/Ho_Chi_Minh`).

## 3. Chạy thử (dry-run)
Sử dụng `--dry-run` để kiểm tra luồng mà không gửi email/Telegram. Tham số `--force-test` sẽ tạo một cảnh báo giả để kiểm tra định dạng:
```bash
python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode INTRADAY --dry-run --force-test
```

## 4. Chạy tác vụ chính
Chọn lệnh phù hợp với nhu cầu:
```bash
# Chạy intraday với danh sách mã tùy chỉnh
python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode INTRADAY --tickers VNM,HPG

# Chạy cuối ngày (EOD) sử dụng thiết lập trong .env
python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode EOD

# Dựa hoàn toàn vào RUN_MODE trong .env
python -m src.fiin_alerts.jobs.generate_and_send_alerts
```
Ghi chú:
- Khi `RUN_MODE=BOTH`, hệ thống sẽ thử lấy dữ liệu realtime trước, sau đó fallback sang parquet nếu cần.
- Cảnh báo được khử trùng lặp theo slot 15 phút (`ticker:event:YYYY-MM-DD HH:MM`).
- Nếu cấu hình Telegram đầy đủ, tối đa 10 cảnh báo đầu tiên sẽ được gửi dạng HTML gọn nhẹ.

## 5. Lich notify tu dong
Su dung scheduler moi dua tren APScheduler de chay pipeline va lop notify email-only:
```bash
python -m app.schedule.jobs_notify
```
- Cron intraday: chay moi 15 phut (00,15,30,45) trong mui gio Asia/Ho_Chi_Minh.
- Cron cuoi ngay: 15:00 (coalesce truoc khi tat).
- max_instances=1 va coalesce=True tranh chong job. Bam Ctrl+C de dung an toan.

## 6. Kiểm tra Gmail nhanh
```bash
python -m src.fiin_alerts.jobs.send_test_email --to you@example.com
```

## 7. Ghi chú bổ sung
- Gmail API sử dụng `users.messages.send` với payload MIME base64url.
- Nếu dự án Google ở chế độ “Testing”, refresh token có thể hết hạn sau ~7 ngày; dùng `scripts/renew_oauth.py` hoặc chuyển sang chế độ Production.
- Theo lớp ghi nhớ của Byterover, không commit bất kỳ thông tin nhạy cảm nào (token, mật khẩu, chat ID) lên repo.

## 8. Notify email quickstart
Setup -> cap nhat `.env` voi SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO, ALERT_DB_PATH; cai dat `pip install -r requirements.txt`.
Run -> `python -m app.notify.alert_router_email` cho phep kiem tra mot lenh, hoac `python -m app.schedule.jobs_notify` de bat APScheduler (Ctrl+C de dung).
Test -> dung mock smtplib hoac chay demo 2 lan de dam bao idempotent; kiem tra `sqlite3 alerts.db "select hash,status from alerts_outbox order by id desc limit 5"`.
Rollback -> xoa file `alerts.db`, xoa thu muc `app/notify` va `app/schedule`, go bo import `Alert as NotifyAlert` va ham `produce_email_alerts` neu khong can notify.
