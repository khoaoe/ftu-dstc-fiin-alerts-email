# ftu-dstc-fiin-alerts-email

Email alerts for FTU DSTC using Gmail API (OAuth2).

## Setup
1) Put `secrets/credentials.json` (downloaded from Google Cloud) here.
2) Create venv & install:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
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
