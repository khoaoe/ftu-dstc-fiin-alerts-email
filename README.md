# 📧 FTU-DSTC Fiin Alerts via Gmail API

> Giải pháp gửi cảnh báo chứng khoán tự động của đội FTU DSTC, sử dụng Gmail API (OAuth2) và dữ liệu từ FiinQuantX.

---

## 🧭 1. Tổng quan
- Tạo tín hiệu mua/bán, dựng email HTML/TXT và gửi qua Gmail.
- Lịch chạy: intraday mỗi 15 phút trong giờ HOSE, thêm lượt chốt ngày lúc 15:00 (múi giờ `Asia/Ho_Chi_Minh`).
- Cơ chế tránh gửi lặp: lưu `ticker:event:slot` trong SQLite (`alerts_state.sqlite`).

## 🧱 2. Kiến trúc chính
| Module | Vai trò |
| --- | --- |
| `src/fiin_alerts/jobs/generate_and_send_alerts.py` | Thu thập dữ liệu, tạo alert, render email, gửi Gmail API |
| `src/fiin_alerts/notify/gmail_client.py` | Bao bọc Gmail API `users.messages.send`, quản lý OAuth token |
| `src/fiin_alerts/jobs/send_test_email.py` | Gửi email thử nhanh, tiện kiểm tra OAuth |
| `app/schedule/jobs_notify.py` | APScheduler, lập lịch intraday/EOD cho `run_once` |
| `src/fiin_alerts/signals/v12_strategy.py` | Logic screener (chuẩn hóa dữ liệu, backtest, trade log) |
| `src/fiin_alerts/jobs/export_v12_signals.py` | CLI xuất CSV tín hiệu theo khoảng thời gian |

_Chiến lược cũ hơn "v4 robust"  (`src/fiin_alerts/signals/v4_robust.py`) vẫn giữ để tham chiếu hoặc fallback._

## ⚙️ 3. Chuẩn bị môi trường
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
cp .env.example .env
```
Tiếp tục cấu hình Gmail OAuth:
1. Tạo Google Cloud project, bật Gmail API, tải `credentials.json` vào thư mục `secrets/`.
2. Khởi tạo token lần đầu:
   ```bash
   python scripts/init_oauth.py
   ```
   Sinh `secrets/token.json` dùng cho các lần gọi kế tiếp.

## 🧾 4. Biến môi trường `.env`
| Biến | Ý nghĩa |
| --- | --- |
| `ALERT_TO`, `ALERT_FROM`, `SUBJECT_PREFIX` | Danh sách người nhận, người gửi, tiền tố subject |
| `RUN_MODE` (`INTRADAY|EOD|BOTH`) | Kiểu chạy mặc định cho scheduler / CLI |
| `INTRADAY_BY`, `INTRADAY_LOOKBACK_MIN` | Tần suất & độ dài lookback khi lấy realtime FiinQuantX |
| `TICKERS` | Danh sách mã mặc định |
| `DATA_PARQUET_PATH` | Parquet fallback khi không có realtime |
| `FQ_USERNAME`, `FQ_PASSWORD` | Thông tin truy cập FiinQuantX |
| `TIMEZONE` | Múi giờ cho scheduler |
| `ALERT_DB_PATH` | Đường dẫn SQLite lưu trạng thái gửi |

## 🚀 5. kiểm thử nhanh
1. **Test Gmail API**
   ```bash
   python -m src.fiin_alerts.jobs.send_test_email --to you@example.com
   ```
   Thêm `--dry-run` để xem subject/recipients mà không gửi.

## 📦 6. Sử dụng thực tế
1. **Sinh alert và gửi một lượt**
   ```bash
   python -m src.fiin_alerts.jobs.generate_and_send_alerts --mode INTRADAY --force-test
   ```
   - `--dry-run` để chỉ log email.
   - `--to` để override danh sách nhận.

2. **Scheduler (đợi tín hiệu để gửi)**
   ```bash
   python -m app.schedule.jobs_notify
   ```
   - Intraday: 09:15→10:45 (mỗi 15 phút), 11:00/11:15/11:30, 13:00→13:45 (mỗi 15 phút), 14:00/14:15/14:30.
   - EOD: 15:00.
   - Dừng với `Ctrl+C` (scheduler shutdown an toàn).

## 📊 6. Xuất tín hiệu ra CSV
Dùng khi cần danh sách tín hiệu mua/bán lịch sử (ví dụ 07/2025–08/2025).
```bash
python -m src.fiin_alerts.jobs.export_v12_signals \
  --data-path path/to/data-v2.parquet \
  --start 2025-07-01 --end 2025-08-31 \
  --output signals_v12_2025.csv
```
Yêu cầu dữ liệu phải có các cột thị trường (`market_close`, `market_MA50`, …) và giá/khối lượng (open/high/low/close, volume). Hàm `ensure_technical_indicators` sẽ tự bổ sung RSI, MACD, ATR, Bollinger, OBV, MFI nếu thiếu.

## 🛠️ 7. Giám sát & xử lý sự cố
- Kiểm tra log gửi bằng SQLite:
  ```bash
  sqlite3 alerts_state.sqlite "select ts, k from sent order by ts desc limit 10"
  ```
- Lỗi Gmail `401` / `invalid_grant`: chạy lại `python scripts/renew_oauth.py` để refresh token.
- Debug thêm: đặt `LOG_LEVEL=DEBUG` trong `.env`.

## 🔄 8. Rollback / dọn dẹp
- Khôi phục file đã sửa (`app/schedule/jobs_notify.py`, `src/fiin_alerts/jobs/*.py`, `.env.example`, `requirements.txt`, `README.md`, `src/fiin_alerts/config.py`) từ VCS nếu cần.
- Xóa `alerts_state.sqlite` để reset cơ chế chống trùng.
- Muốn quay lại kênh gửi khác (SMTP/Telegram) thì trả lại cấu hình và requirements tương ứng.

---
