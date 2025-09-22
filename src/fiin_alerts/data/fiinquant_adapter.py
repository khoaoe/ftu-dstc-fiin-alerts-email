from __future__ import annotations
import time
import pandas as pd
import logging

LOG = logging.getLogger(__name__)

def fetch_intraday(username: str, password: str, tickers: list[str], minutes: int = 10, by: str = "1m") -> pd.DataFrame:
    try:
        import FiinQuantX as fq
    except Exception:
        LOG.warning("FiinQuantX not installed; skipping realtime fetch.")
        return pd.DataFrame()

    # 1) Login
    client = fq.FiinSession(username=username, password=password).login()
    
    # 2) Time range
    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")

    last_exc: Exception | None = None
    raw = None
    for attempt in range(3):
        try:
            raw = client.Fetch_Trading_Data(
                realtime=False,
                tickers=tickers,
                fields=["open","high","low","close","volume","bu","sd","fb","fs","fn"],
                adjusted=True,
                by=by,
                from_date=since,
            ).get_data()
            break
        except Exception as exc:
            last_exc = exc
            LOG.warning("FiinQuant Fetch_Trading_Data failed (attempt %s): %s", attempt + 1, exc)
            time.sleep(1.0 * (attempt + 1))
    else:
        if last_exc is not None:
            LOG.warning("FiinQuant fetch failed after retries: %s", last_exc)

    # ---- Normalize to DataFrame (no boolean context on DataFrame!) ----
    df: pd.DataFrame
    if raw is None:
        df = pd.DataFrame()
    elif isinstance(raw, pd.DataFrame):
        df = raw.copy()
    elif isinstance(raw, (list, tuple)):
        df = pd.DataFrame(raw)
    elif isinstance(raw, dict):
        payload = raw.get("data") or raw.get("Data") or raw.get("items") or raw.get("Items")
        df = pd.DataFrame(payload or [])
    else:
        LOG.warning("Unknown data type from FiinQuantX: %s", type(raw))
        df = pd.DataFrame()

    # ---- Ensure time column exists & is datetime ----
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
    elif "timestamp" in df.columns:
        # nhiều API trả millis
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")

    return df
