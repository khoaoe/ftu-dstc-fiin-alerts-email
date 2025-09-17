from __future__ import annotations

import logging
import random
import time
from typing import Iterable

import requests

from src.fiin_alerts.config import HTTP_MAX_RETRY

LOG = logging.getLogger(__name__)
_API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_BACKOFF_SECONDS = 60.0
_DEFAULT_TIMEOUT = 15


def _sleep_with_jitter(base_delay: float) -> None:
    wait = min(base_delay, _MAX_BACKOFF_SECONDS) + random.uniform(0.0, 1.0)
    time.sleep(wait)


def send_telegram(
    token: str,
    chat_ids: Iterable[str],
    text: str,
    parse_mode: str = "HTML",
    max_retry: int = HTTP_MAX_RETRY,
) -> list[str]:
    if not token:
        return []

    ids = [str(chat_id).strip() for chat_id in chat_ids if str(chat_id).strip()]
    if not ids:
        return []

    attempts = max(int(max_retry or HTTP_MAX_RETRY or 0), 1)
    url = _API_TEMPLATE.format(token=token)
    message_ids: list[str] = []

    for chat_id in ids:
        delay = 1.0
        for attempt in range(1, attempts + 1):
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            try:
                response = requests.post(url, json=payload, timeout=_DEFAULT_TIMEOUT)
            except requests.RequestException as exc:
                if attempt >= attempts:
                    LOG.error("Telegram send failed after %s attempts for chat=%s", attempts, chat_id)
                    break
                LOG.warning(
                    "Telegram send error %s attempt=%s/%s", exc.__class__.__name__, attempt, attempts
                )
                _sleep_with_jitter(delay)
                delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
                continue

            if response.status_code == 200:
                data = response.json()
                message_id = str(data.get("result", {}).get("message_id", ""))
                message_ids.append(message_id)
                LOG.info("Telegram message sent chat=%s message_id=%s", chat_id, message_id)
                break

            if response.status_code == 429:
                retry_after = response.json().get("parameters", {}).get("retry_after")
                sleep_for = float(retry_after) if isinstance(retry_after, (int, float)) else delay
                LOG.warning("Telegram rate limited. Sleeping %.1fs before retry", sleep_for)
                _sleep_with_jitter(sleep_for)
                delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
                continue

            if 500 <= response.status_code < 600:
                LOG.warning(
                    "Telegram server error status=%s attempt=%s/%s", response.status_code, attempt, attempts
                )
                _sleep_with_jitter(delay)
                delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
                continue

            LOG.error("Telegram send failed status=%s", response.status_code)
            break

    return message_ids
