# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

TZ = "Asia/Ho_Chi_Minh"
OPEN1, CLOSE1 = time(9, 0), time(11, 30)
OPEN2, CLOSE2 = time(13, 0), time(15, 0)

@dataclass
class AlertItem:
    ticker: str
    event_type: str   # BUY_NEW / SELL / RISK / TP / SL / INFO
    price: Optional[float]
    when: str
    explain: str

def _to_ts(x) -> Optional[pd.Timestamp]:
    if isinstance(x, pd.Timestamp):
        return x
    if isinstance(x, (int, float, np.integer, np.floating)):
        return pd.to_datetime(x, unit="s")
    try:
        return pd.to_datetime(x)
    except Exception:
        return None

def _is_market_open(ts: Optional[pd.Timestamp]) -> bool:
    if ts is None:
        return False
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize(TZ)
        else:
            ts = ts.tz_convert(TZ)
        tt = ts.time()
    elif isinstance(ts, datetime):
        tt = ts.time()
    else:
        return False
    return (OPEN1 <= tt <= CLOSE1) or (OPEN2 <= tt <= CLOSE2)

def _rsi14(close: pd.Series) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-d.clip(upper=0)).rolling(14, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _estimate_bars_per_day(df: pd.DataFrame) -> int:
    if "time" not in df.columns or "ticker" not in df.columns:
        return 20
    x = df[["time", "ticker"]].copy()
    x["date"] = pd.to_datetime(x["time"]).dt.normalize()
    cnt = (
        x.groupby(["ticker", "date"])
        .size()
        .groupby("ticker")
        .median()
        .median()
    )
    try:
        v = int(max(1, min(64, int(cnt))))
        return v if v > 0 else 20
    except Exception:
        return 20

def _compute_market_ma200(df: pd.DataFrame) -> pd.Series:
    if "market_close" not in df.columns:
        return df.get("market_MA200", pd.Series(index=df.index, dtype="float64"))
    t = df[["time", "market_close"]].copy()
    t["time"] = pd.to_datetime(t["time"], errors="coerce")
    t["d"] = t["time"].dt.normalize()
    daily_last = t.sort_values("time").groupby("d", as_index=False).tail(1)
    daily_last = daily_last.dropna(subset=["market_close"]).drop_duplicates("d")
    daily_last = daily_last.sort_values("d")
    daily_last["market_MA200_daily"] = (
        daily_last["market_close"].rolling(200, min_periods=50).mean()
    )
    map_df = daily_last[["d", "market_MA200_daily"]]
    z = pd.to_datetime(df["time"], errors="coerce").dt.normalize().to_frame(name="d")
    out = z.merge(map_df, on="d", how="left")["market_MA200_daily"]
    out = pd.Series(out.values, index=df.index).ffill()
    return out

def _ensure_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    if df is None or df.empty:
        return df, 20
    x = df.copy()
    if "time" in x.columns:
        x["time"] = pd.to_datetime(x["time"], errors="coerce")
    if "ticker" not in x.columns:
        x["ticker"] = x.get("symbol", np.nan)
    x = x.sort_values(["ticker", "time"])
    g = x.groupby("ticker", group_keys=False)
    bars_per_day = _estimate_bars_per_day(x)
    if "close" not in x.columns or "volume" not in x.columns:
        return x, bars_per_day
    if "sma_50" not in x.columns:
        x["sma_50"] = g["close"].transform(lambda s: s.rolling(50, min_periods=20).mean())
    if "sma_200" not in x.columns:
        x["sma_200"] = g["close"].transform(lambda s: s.rolling(200, min_periods=50).mean())
    if "rsi_14" not in x.columns:
        x["rsi_14"] = g["close"].transform(_rsi14)
    if "volume_ma20" not in x.columns:
        x["volume_ma20"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    if "volume_spike" not in x.columns:
        x["volume_spike"] = (x["volume"] / x["volume_ma20"].replace(0, np.nan)).clip(upper=10)
    if "boll_width" not in x.columns:
        ma20 = g["close"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        sd20 = g["close"].transform(lambda s: s.rolling(20, min_periods=10).std())
        x["boll_width"] = (ma20 + 2 * sd20 - (ma20 - 2 * sd20)).abs()
    if "high" in x.columns and "highest_in_5d" not in x.columns:
        window = 5 if bars_per_day <= 2 else max(5 * bars_per_day, 10)
        x["highest_in_5d"] = g["high"].transform(
            lambda s: s.rolling(window, min_periods=max(2, window // 5)).max().shift(1)
        )
    if "market_MA200" not in x.columns and "market_close" in x.columns:
        x["market_MA200"] = _compute_market_ma200(x)
    return x, bars_per_day

def apply_baseline_screener(df_day: pd.DataFrame, min_volume_ma20: int = 100_000) -> List[str]:
    if df_day is None or df_day.empty:
        return []
    z = df_day.copy()
    required_cols = ["volume_ma20", "volume", "close", "sma_200", "sma_50", "rsi_14", "volume_spike"]
    if any(col not in z.columns for col in required_cols):
        return []
    z = z[z["volume_ma20"] > min_volume_ma20]
    z = z[z["volume"] > 200_000]
    if "market_close" in z.columns and "market_MA200" in z.columns:
        z = z[z["market_close"] > z["market_MA200"]]
    z = z[(z["close"] > z["sma_200"])]
    z = z[(z["close"] > z["sma_50"]) & (z["rsi_14"] > 55) & (z["rsi_14"] < 75)]
    z = z.dropna(subset=["volume_spike"])
    z = z[z["volume_spike"] > 0.5]
    return z["ticker"].dropna().astype(str).unique().tolist()

def _get_weekly_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    x = df.copy()
    x["time"] = pd.to_datetime(x["time"], errors="coerce")
    x["d"] = x["time"].dt.normalize()
    latest_ts = x["time"].max()
    if pd.isna(latest_ts):
        return pd.DataFrame(columns=x.columns)
    weekday = int(latest_ts.weekday())  # Monday=0
    monday = (latest_ts.normalize() - pd.Timedelta(days=weekday)).normalize()
    candidate_dates = x.loc[x["d"] <= monday, "d"].unique()
    if len(candidate_dates) == 0:
        snap = x[x["d"] == x["d"].max()]
    else:
        chosen = pd.to_datetime(candidate_dates).max()
        snap = x[x["d"] == chosen]
    snap = snap.sort_values(["ticker", "time"]).groupby("ticker", as_index=False).tail(1)
    return snap.drop(columns=["d"], errors="ignore")

def generate_alerts(df: pd.DataFrame) -> List[AlertItem]:
    if df is None or df.empty:
        return []
    x, _ = _ensure_features(df)
    if "ticker" not in x.columns or "time" not in x.columns:
        return []
    weekly_snap = _get_weekly_snapshot(x)
    wl = apply_baseline_screener(weekly_snap, min_volume_ma20=100_000)
    if not wl:
        return []
    latest = (
        x[x["ticker"].isin(wl)]
        .sort_values(["ticker", "time"])
        .groupby("ticker", as_index=False)
        .tail(1)
    )
    cond_breakout = latest["close"] > latest.get("highest_in_5d", np.nan)
    cond_vol = latest["volume_spike"] > 0.5
    picked = latest[cond_breakout & cond_vol].copy()
    out: List[AlertItem] = []
    for _, r in picked.iterrows():
        ts = _to_ts(r.get("time"))
        if ts is not None and not _is_market_open(ts):
            continue
        explain = ["Breakout 5d", f"Vol spike≈{float(r['volume_spike']):.2f}"]
        rv = r.get("rsi_14", np.nan)
        if pd.notna(rv):
            explain.append(f"RSI14≈{float(rv):.0f}")
        out.append(
            AlertItem(
                ticker=str(r["ticker"]),
                event_type="BUY_NEW",
                price=float(r.get("close")) if pd.notna(r.get("close")) else None,
                when=ts.strftime("%H:%M") if isinstance(ts, pd.Timestamp) else "now",
                explain="; ".join(explain),
            )
        )
    return out

__all__ = ["AlertItem", "apply_baseline_screener", "generate_alerts"]
