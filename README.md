# ftu-dstc-fiin-alerts-email

Email alerts for FTU DSTC using Gmail API (OAuth2).

## Setup
1) Put `credentials.json` (downloaded from Google Cloud) to `secrets/`.
2) Create venv & install:
   ```bash
   # create & activate environment
   python -m venv .venv 
   .venv/Scripts/activate
   ```
   
   ```bash
   # install dependencies
   pip install -r requirements.txt
   ```
   
   ```bash
   # install FiinQuantX
   pip install --extra-index-url https://fiinquant.github.io/fiinquantx/simple fiinquantx
   ```

   ```bash
   # Create .env
   cp .env.example .env
   ```

Initialize OAuth (Testing OK):

```bash
python scripts/init_oauth.py
```

This generates secrets/token.json (refresh token may expire ~7 days in Testing).

Send a test email:

```bash
python -m src.fiin_alerts.jobs.send_test_email --to you@example.com
```

Run alerts job (demo uses parquet fallback if FiinQuantX not available):

```bash
python -m src.fiin_alerts.jobs.generate_and_send_alerts 
```

---
Ghi chú:
- Gmail API gửi qua `users.messages.send` với `raw` chứa MIME RFC 2822 đã base64url (OAuth2).
- Testing mode: refresh token có thể hết hạn khoảng 7 ngày; dùng `scripts/renew_oauth.py` hoặc chuyển Production để ổn định hơn.
