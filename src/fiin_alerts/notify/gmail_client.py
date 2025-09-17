from __future__ import annotations

import base64
import logging
import pathlib
import random
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable

LOG = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
SECRETS_DIR = pathlib.Path("secrets")
TOKEN = SECRETS_DIR / "token.json"
_MAX_BACKOFF_SECONDS = 60.0


class NeedsReconsentError(RuntimeError):
    pass


def _load_google_modules():
    try:
        from google.auth.exceptions import RefreshError  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.errors import HttpError  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency missing handled at runtime
        raise RuntimeError("Google client libraries not installed") from exc
    return Credentials, build, Request, RefreshError, HttpError


def _load_creds():
    Credentials, _, Request, RefreshError, _ = _load_google_modules()
    if not TOKEN.exists():
        raise NeedsReconsentError("Missing secrets/token.json. Run: python scripts/init_oauth.py")
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                TOKEN.write_text(creds.to_json(), encoding="utf-8")
            except RefreshError as exc:
                raise NeedsReconsentError("Token expired/revoked. Run: python scripts/renew_oauth.py") from exc
        else:
            raise NeedsReconsentError("Invalid creds. Re-run OAuth init.")
    return creds


def _build_message(sender: str, to: Iterable[str], subject: str, html: str, text: str | None = None) -> dict:
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def _extract_status(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if status is not None:
        return status
    response = getattr(error, "resp", None)
    return getattr(response, "status", None) if response is not None else None


def send_email(
    sender: str,
    to: list[str],
    subject: str,
    html: str,
    text: str | None = None,
    max_retry: int = 5,
) -> str:
    creds = _load_creds()
    _, build, _, _, HttpError = _load_google_modules()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    body = _build_message(sender, to, subject, html, text)

    attempts = max(int(max_retry or 0), 1)
    delay = 1.0

    for attempt in range(1, attempts + 1):
        try:
            response = service.users().messages().send(userId="me", body=body).execute(num_retries=0)
            message_id = response.get("id", "")
            LOG.info("Email sent id=%s recipients=%s", message_id, len(to))
            return message_id
        except HttpError as error:  # type: ignore[except-type]
            status = _extract_status(error)
            retryable = status in {403, 429, 500, 502, 503, 504} or status is None
            if not retryable or attempt >= attempts:
                raise
            wait = min(delay, _MAX_BACKOFF_SECONDS) + random.uniform(0.0, 1.0)
            LOG.warning(
                "Gmail API error status=%s attempt=%s/%s retrying in %.1fs",
                status,
                attempt,
                attempts,
                wait,
            )
            time.sleep(wait)
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
    raise RuntimeError("Failed to send email after retries")

