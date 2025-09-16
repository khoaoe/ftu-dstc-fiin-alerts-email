from __future__ import annotations
import base64, pathlib, logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

LOG = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
SECRETS_DIR = pathlib.Path("secrets")
TOKEN = SECRETS_DIR / "token.json"

class NeedsReconsentError(RuntimeError):
    pass

def _load_creds() -> Credentials:
    if not TOKEN.exists():
        raise NeedsReconsentError("Missing secrets/token.json. Run: python scripts/init_oauth.py")
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                TOKEN.write_text(creds.to_json(), encoding="utf-8")
            except RefreshError as e:
                raise NeedsReconsentError("Token expired/revoked. Run: python scripts/renew_oauth.py") from e
        else:
            raise NeedsReconsentError("Invalid creds. Re-run OAuth init.")
    return creds

def _build_message(sender: str, to: list[str], subject: str, html: str, text: str | None = None) -> dict:
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")  # base64url
    return {"raw": raw}

def send_email(sender: str, to: list[str], subject: str, html: str, text: str | None = None) -> str:
    creds = _load_creds()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    body = _build_message(sender, to, subject, html, text)
    try:
        resp = service.users().messages().send(userId="me", body=body).execute()
        msg_id = resp.get("id", "")
        LOG.info("Email sent id=%s to=%s", msg_id, to)
        return msg_id
    except HttpError as e:
        if getattr(e, "status_code", None) == 429:
            LOG.warning("Rate limited: %s", e)
        raise
