from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any, Iterable

import pandas as pd
from zoneinfo import ZoneInfo

from src.fiin_alerts.config import HTTP_MAX_RETRY, TIMEZONE

LOG = logging.getLogger(__name__)
_FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "bu",
    "sd",
    "fb",
    "fs",
    "fn",
]
_MAX_BACKOFF_SECONDS = 60.0


def _ensure_dataframe(raw: Any) -> pd.DataFrame:
    if raw is None:
        return pd.DataFrame()
    if isinstance(raw, pd.DataFrame):
        return raw.copy()
    if isinstance(raw, (list, tuple)):
        return pd.DataFrame(list(raw))
    if isinstance(raw, dict):
        payload = raw.get("data") or raw.get("Data") or raw.get("items") or raw.get("Items")
        return pd.DataFrame(payload or [])
    LOG.warning("FiinQuant returned unsupported payload type=%s", type(raw))
    return pd.DataFrame()


def _normalize(df: pd.DataFrame, tz: ZoneInfo) -> pd.DataFrame:
    if df.empty:
        return df

    renamed = df.rename(columns={"Ticker": "ticker", "symbol": "ticker"})
    if "ticker" in renamed.columns:
        renamed["ticker"] = renamed["ticker"].astype(str).str.upper()
    else:
        renamed["ticker"] = ""

    if "time" in renamed.columns:
        times = pd.to_datetime(renamed["time"], errors="coerce")
    elif "timestamp" in renamed.columns:
        times = pd.to_datetime(renamed["timestamp"], unit="ms", errors="coerce")
    else:
        times = pd.Series([pd.NaT] * len(renamed))

    if hasattr(times.dt, "tz") and times.dt.tz is None:
        times = times.dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT")
    elif hasattr(times.dt, "tz") and times.dt.tz is not None:
        times = times.dt.tz_convert(tz)

    renamed["time"] = times
    return renamed


def fetch_intraday(
    username: str,
    password: str,
    tickers: Iterable[str],
    minutes: int = 45,
    by: str = "15m",
    max_retry: int = 5,
) -> pd.DataFrame:
    tickers_list = [ticker.upper() for ticker in tickers if str(ticker).strip()]
    if not username or not password or not tickers_list:
        return pd.DataFrame()

    try:
        import FiinQuantX as fq  # type: ignore
    except Exception:
        LOG.warning("FiinQuantX not installed; skipping realtime fetch.")
        return pd.DataFrame()

    tz = ZoneInfo(TIMEZONE)
    lookback_minutes = max(minutes, 1)
    since_dt = datetime.now(tz) - timedelta(minutes=lookback_minutes)
    since = since_dt.strftime("%Y-%m-%d %H:%M")

    attempts = max(int(max_retry or HTTP_MAX_RETRY or 0), 1)
    delay = 1.0

    for attempt in range(1, attempts + 1):
        try:
            session = fq.FiinSession(username=username, password=password)
            client = session.login()
            raw = (
                client.Fetch_Trading_Data(
                    realtime=False,
                    tickers=tickers_list,
                    fields=_FIELDS,
                    adjusted=True,
                    by=by,
                    from_date=since,
                )
            ).get_data()
            df = _normalize(_ensure_dataframe(raw), tz)
            if df.empty:
                LOG.info("FiinQuant returned empty dataframe for tickers=%s", tickers_list)
            return df
        except Exception as exc:
            if attempt >= attempts:
                LOG.error(
                    "FiinQuant intraday fetch failed after %s attempts: %s",
                    attempts,
                    exc,
                )
                break
            sleep_for = min(delay, _MAX_BACKOFF_SECONDS) + random.uniform(0.0, 1.0)
            LOG.warning(
                "FiinQuant intraday fetch error (%s). Retrying in %.1fs (%s/%s)",
                exc.__class__.__name__,
                sleep_for,
                attempt,
                attempts,
            )
            time.sleep(sleep_for)
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)

    return pd.DataFrame()



