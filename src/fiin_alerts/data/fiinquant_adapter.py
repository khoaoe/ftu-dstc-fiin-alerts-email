from __future__ import annotations
import pandas as pd
import logging

LOG = logging.getLogger(__name__)

def fetch_intraday(username: str, password: str, tickers: list[str], minutes: int = 10, by: str = "1m") -> pd.DataFrame:
    try:
        import FiinQuantX as fq
    except Exception:
        LOG.warning("FiinQuantX not installed; skipping realtime fetch.")
        return pd.DataFrame()

    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")

    client = fq.FiinSession(username=username, password=password).login()
    data = client.Fetch_Trading_Data(
        realtime=False,
        tickers=tickers,
        fields=["open","high","low","close","volume","bu","sd","fb","fs","fn"],
        adjusted=True,
        by=by,
        from_date=since,
    ).get_data()  # may return list of dicts
    return pd.DataFrame(data or [])
