# 📧 (FTU-DSTC - FinLab) Trade Signal Alerts via Email (Gmail API)

> Hệ thống gửi cảnh báo chứng khoán tự động của đội FinLab. Gửi email qua Gmail API (OAuth2), dữ liệu FiinQuantX hoặc parquet lịch sử.

---

## 🧭 Tổng quan
- Sinh tín hiệu mua/bán, render email HTML/TXT, gửi Gmail.
- Lịch chạy: intraday mỗi 15 phút (giờ HOSE) + 1 lượt cuối ngày 15:00 (`Asia/Ho_Chi_Minh`).
- Tránh trùng lặp: lưu khóa `ticker:event:slot` trong SQLite (`alerts_state.sqlite`).

## 🧱 Thành phần chính
- `src/fiin_alerts/jobs/generate_and_send_alerts.py`: lấy dữ liệu, tạo alert, gửi mail.
- `app/schedule/jobs_notify.py`: APScheduler lên lịch intraday/EOD.
- `src/fiin_alerts/notify/gmail_client.py`: gọi Gmail API `users.messages.send`, quản lý OAuth.
- `src/fiin_alerts/notify/composer.py`: render Jinja2 HTML/TXT.
- `src/fiin_alerts/signals/v12_strategy.py`: logic chiến lược (tính chỉ báo, lọc, backtest).
- `src/fiin_alerts/jobs/export_v12_signals.py`: xuất CSV tín hiệu theo khoảng thời gian.
- (Legacy) `src/fiin_alerts/signals/v4_robust.py`: chiến lược cũ giữ làm fallback intraday.

## ⚙️ Chuẩn bị
1. Để `credentials.json` (tải từ Google Cloud cấp để sử dụng GmailAPI) vào folder `secrets/`.
2. Tạo môi trường ảo và cài đặt dependencies:
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
# cài FiinQuantX để lấy realtime
pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
```
3. Tạo file .env:
```bash
cp .env.example .env
```
4. Tải data:
- tải file data "data-v2.parquet" từ link https://drive.google.com/file/d/1oswrO_XOYhNorxSLNLOPnZMvUVfAaSUC/view?usp=sharing
- đưa file vào folder `data/`
4. Khởi tạo Gmail OAuth lần đầu:
```bash
python scripts/init_oauth.py   # sinh secrets/token.json
```

## 🧾 Cấu hình `.env`
- `ALERT_TO`, `ALERT_FROM`, `SUBJECT_PREFIX`: người nhận/gửi, tiền tố tiêu đề.
- `RUN_MODE` (`INTRADAY|EOD|BOTH`), `INTRADAY_BY`, `INTRADAY_LOOKBACK_MIN`: tham số realtime.
- `TICKERS`: danh sách mã mặc định.
- `DATA_PARQUET_PATH`: parquet lịch sử.
- `FQ_USERNAME`, `FQ_PASSWORD`: tài khoản FiinQuantX (nếu dùng realtime).
- `TIMEZONE`: múi giờ scheduler; 
- `ALERT_DB_PATH`: file SQLite chống trùng.

## 🔔 Luồng gửi email
- Đọc `DATA_PARQUET_PATH`, lấy NGÀY MỚI NHẤT trong dữ liệu, chạy backtest để sinh BUY_NEW/SELL cho ngày đó.
- Nếu không có tín hiệu (thiếu dữ liệu hoặc không có giao dịch), fallback sang chiến lược cũ (v4_robust).
- Nội dung email có cột “Action” (Buy/Sell).

## 🚀 Chạy & kiểm thử
- Gửi email thử (không gửi thật):
```bash
python -m src.fiin_alerts.jobs.send_test_email --to you@example.com --dry-run
```
- Sinh và xem email:
```bash
python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode EOD --dry-run
```
- Chạy scheduler (chờ tín hiệu):
```bash
python -m app.schedule.jobs_notify
```
  - Intraday: 09:15→10:45 (mỗi 15′), 11:00/11:15/11:30, 13:00→13:45 (mỗi 15′), 14:00/14:15/14:30
  - EOD: 15:00

## 📊 Xuất CSV tín hiệu
Dùng khi cần danh sách tín hiệu lịch sử (ví dụ 07/2025–08/2025):
```bash
python -m src.fiin_alerts.jobs.export_v12_signals \
  --data-path path/to/data-v2.parquet \
  --start 2025-07-01 --end 2025-08-31 \
  --output signals_v12_2025.csv
```
Yêu cầu dữ liệu: cần `time`, `ticker`, OHLCV (open/high/low/close/volume) và `market_close`. Các chỉ báo (RSI, MACD, ATR, Bollinger, OBV, MFI; market MA/ADX/Boll-width) được tự tính nếu thiếu.

## 🛠️ Giám sát & sự cố
- Xem bản ghi chống trùng gần nhất:
```bash
sqlite3 alerts_state.sqlite "select ts, k from sent order by ts desc limit 10"
```
- Gmail 401/invalid_grant: chạy `python scripts/renew_oauth.py`.
- Debug thêm: đặt `LOG_LEVEL=DEBUG` trong `.env`.

## 🔄 Ghi chú
- Sau khi cập nhật code, hãy restart scheduler để áp dụng thay đổi.
- Khi `DATA_PARQUET_PATH` trống hoặc dữ liệu ngày mới nhất không có giao dịch, hệ thống sẽ tự động fallback sang chiến lược cũ.
