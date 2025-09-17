from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

from src.fiin_alerts.config import TIMEZONE

OPEN1_START = time(9, 15)
OPEN1_END = time(11, 30)
OPEN2_START = time(13, 0)
OPEN2_END = time(14, 30)

_TZ = ZoneInfo(TIMEZONE)


def _ensure_aware(ts: Any) -> datetime | None:
    if isinstance(ts, pd.Timestamp):
        if pd.isna(ts):
            return None
        ts = ts.to_pydatetime()
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=_TZ)
        return ts.astimezone(_TZ)
    return None


def is_market_open(ts: Any) -> bool:
    localized = _ensure_aware(ts)
    if localized is None:
        return False
    if localized.weekday() > 4:  # Saturday/Sunday
        return False
    current_time = localized.time()
    in_morning = OPEN1_START <= current_time <= OPEN1_END
    in_afternoon = OPEN2_START <= current_time <= OPEN2_END
    return in_morning or in_afternoon


@dataclass
class AlertItem:
    ticker: str
    event_type: str  # BUY / SELL / RISK / TP / SL ...
    price: float | None
    when: str
    explain: str
    ts: datetime | None = None


def generate_alerts(df: pd.DataFrame) -> list[AlertItem]:
    """Very light rule demo. Replace by your V4-Robust logic from Round 2."""
    if df is None or df.empty:
        return []
    if "ticker" not in df.columns:
        return []

    frame = df.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    if "time" in frame.columns:
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce")

    latest = frame.sort_values(["ticker", "time"]).groupby("ticker").tail(1)

    alerts: list[AlertItem] = []
    for _, row in latest.iterrows():
        ticker = str(row["ticker"]).upper()
        price_val = row.get("close")
        price = float(price_val) if price_val is not None and not pd.isna(price_val) else None

        ts_value = row.get("time")
        ts_local = _ensure_aware(ts_value)
        if ts_value is not None and not pd.isna(ts_value) and not is_market_open(ts_value):
            continue
        when_str = ts_local.strftime("%H:%M") if ts_local else ""

        bu = float(row.get("bu", 0) or 0)
        sd = float(row.get("sd", 0) or 0)
        fn = float(row.get("fn", 0) or 0)

        reasons: list[str] = []
        event: str | None = None
        if fn >= 5_000_000_000:  # foreign net buying > 5B
            event = "BUY"
            reasons.append("Foreign net buying strong")
        if bu > 0 and sd > 0:
            ratio = bu / sd
            if ratio >= 1.5:
                event = event or "BUY"
                reasons.append(f"BU/SD ratio {ratio:.2f}")

        if event:
            alerts.append(
                AlertItem(
                    ticker=ticker,
                    event_type=event,
                    price=price,
                    when=when_str,
                    explain="; ".join(reasons),
                    ts=ts_local,
                )
            )

    return alerts
