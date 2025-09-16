# ftu-dstc-fiin-alerts-email

Email alerts for FTU DSTC using Gmail API (OAuth2).

## Setup
1) Put `credentials.json` (downloaded from Google Cloud) to `secrets/`.
2) Create venv & install:
   ```bash
   # create & activate environment
   python -m venv .venv 
   .venv/Scripts/activate
   # install dependencies
   pip install -r requirements.txt
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
python -m src.fiin_alerts.jobs.generate_and_send_alerts --dry-run
```

Notes

Gmail API requires MIME RFC 2822 encoded as base64url in raw for users.messages.send.

Use minimal scope https://www.googleapis.com/auth/gmail.send.

In Testing mode, tokens can expire ~7 days → re-run scripts/renew_oauth.py.

---
