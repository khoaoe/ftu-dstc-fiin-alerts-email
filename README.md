# ftu-dstc-fiin-alerts-email

Email alerts for FTU DSTC using Gmail API (OAuth2).

## Setup
1. Put `credentials.json` (downloaded from Google Cloud) into `secrets/`.
2. Create a virtual environment & install dependencies:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
   ```
3. Copy the sample environment file and adjust values:
   ```bash
   cp .env.example .env
   ```
4. Initialize Gmail OAuth (creates `secrets/token.json`):
   ```bash
   python scripts/init_oauth.py
   ```

## Configuration
Update `.env` to control runtime behaviour. Key settings:
- `RUN_MODE` (`INTRADAY|EOD|BOTH`) ? default job mode.
- `INTRADAY_BY` (`1m|5m|15m`) and `INTRADAY_LOOKBACK_MIN` ? sampling interval and lookback for FiinQuant pulls.
- `TICKERS` ? default comma-separated tickers.
- `ALERT_TO`, `ALERT_FROM`, `SUBJECT_PREFIX` ? email routing.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS` ? optional Telegram delivery.
- `GMAIL_MAX_RETRY`, `HTTP_MAX_RETRY` ? retry budgets for Gmail/HTTP clients.
- `DATA_PARQUET_PATH`, `FQ_USERNAME`, `FQ_PASSWORD` ? parquet fallback and FiinQuant credentials.

Set `TIMEZONE` if you need something other than `Asia/Ho_Chi_Minh`.

## Running Jobs
### Dry run / development
Use `--dry-run` to simulate the workflow without sending email or Telegram messages:
```bash
python -m app.schedule.jobs_notify
```
- Khung intraday: 09:15–10:45 (mỗi 15 phút), 11:00/11:15/11:30, 13:00–13:45 (mỗi 15 phút), 14:00/14:15/14:30.
- Khung EOD: 15:00.
- `timezone` đọc từ `.env` (mặc định `Asia/Ho_Chi_Minh`), `coalesce=True`, `max_instances=1`.
- Alert được dedup theo hash `ticker|event|slot` và log đầy đủ vào SQLite.

The `--force-test` flag injects a dummy alert so you can verify rendering.

### Regular execution
```bash
python -m src.fiin_alerts.jobs.generate_and_send_alerts [--mode INTRADAY|EOD|BOTH] [--tickers VNM,HPG]
```
- When `RUN_MODE=BOTH`, the job will try intraday ingest first, then fall back to parquet.
- Alerts are de-duplicated per 15-minute slot and logged before sending.
- Telegram notifications are sent when both bot token and chat IDs are configured.

### Scheduler
A blocking APScheduler runner triggers intraday jobs every 15 minutes during HOSE trading hours and an end-of-day pass at 15:02 (Mon?Fri):
```bash
python -m src.fiin_alerts.jobs.scheduler
```
Ensure the virtual environment is active so `python` resolves dependencies.

### Gmail smoke test
```bash
python -m src.fiin_alerts.jobs.send_test_email --to you@example.com
```

## Notes
- Gmail API sends via `users.messages.send` with base64url MIME payloads.
- In OAuth testing mode, refresh tokens may expire after ~7 days; run `scripts/renew_oauth.py` or switch the Google project to Production.
- According to Byterover memory layer, always keep credentials out of version control.
