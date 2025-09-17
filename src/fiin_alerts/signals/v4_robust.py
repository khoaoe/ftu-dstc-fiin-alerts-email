from __future__ import annotations
import pandas as pd
from dataclasses import dataclass
from datetime import datetime, time

OPEN1, CLOSE1 = time(9, 0), time(11, 30)
OPEN2, CLOSE2 = time(13, 0), time(15, 0)

def is_market_open(ts):
    import pandas as pd
    if not isinstance(ts, (pd.Timestamp, datetime)):
        return False
    if isinstance(ts, pd.Timestamp):
        ts = ts.tz_localize("Asia/Ho_Chi_Minh") if ts.tzinfo is None else ts
        ts = ts.tz_convert("Asia/Ho_Chi_Minh")
        t = ts.time()
    else:
        t = ts.time()
    return (OPEN1 <= t <= CLOSE1) or (OPEN2 <= t <= CLOSE2)

@dataclass
class AlertItem:
    ticker: str
    event_type: str  # BUY / SELL / RISK / TP / SL ...
    price: float | None
    when: str
    explain: str

def generate_alerts(df: pd.DataFrame) -> list[AlertItem]:
    """Very light rule demo. Replace by your V4-Robust logic from Round 2."""
    if df is None or df.empty:
        return []
    # Expect columns: ticker,time,close,rsi_14,sma_50,sma_200,bu,sd,fn...
    out: list[AlertItem] = []
    if "ticker" not in df.columns:
        return out
    df = df.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    latest = df.sort_values(["ticker", "time"]).groupby("ticker").tail(1)

    for _, r in latest.iterrows():
        t = str(r["ticker"])
        px = float(r.get("close", 0) or 0)
        when = r.get("time")
        if when is not None and not pd.isna(when) and not is_market_open(when):
            continue
        when_str = when.strftime("%H:%M") if isinstance(when, (pd.Timestamp, datetime)) else ""
        bu, sd = float(r.get("bu", 0) or 0), float(r.get("sd", 0) or 0)
        fn = float(r.get("fn", 0) or 0)

        reason = []
        evt = None
        if fn >= 5e9:  # ngoại mua ròng > 5 tỷ
            evt = "BUY"; reason.append("NĐTNN mua ròng mạnh")
        if bu > 0 and sd > 0 and (bu/sd) >= 1.5:
            evt = evt or "BUY"; reason.append(f"BU/SD≈{bu/sd:.2f}")
        if evt:
            out.append(AlertItem(t, evt, px, when_str, "; ".join(reason)))
    return out
