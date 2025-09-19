# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


# =========================
#  Config & Time windows
# =========================
TZ = "Asia/Ho_Chi_Minh"
# Khung giờ HOSE (tham chiếu)
OPEN1, CLOSE1 = time(9, 0), time(11, 30)
OPEN2, CLOSE2 = time(13, 0), time(15, 0)


# =========================
#  Public dataclass
# =========================
@dataclass
class AlertItem:
    ticker: str
    event_type: str   # BUY_NEW / SELL / RISK / TP / SL / INFO
    price: Optional[float]
    when: str
    explain: str


# =========================
#  Time helpers
# =========================
def _to_ts(x) -> Optional[pd.Timestamp]:
    if isinstance(x, pd.Timestamp):
        return x
    if isinstance(x, (int, float, np.integer, np.floating)):
        # epoch seconds → timestamp
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


# =========================
#  Feature builders
# =========================
def _rsi14(close: pd.Series) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-d.clip(upper=0)).rolling(14, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _estimate_bars_per_day(df: pd.DataFrame) -> int:
    """Ước lượng số bars/ngày cho intraday (15' ~ 18-20 bar/ngày tuỳ dữ liệu)."""
    if "time" not in df.columns or "ticker" not in df.columns:
        return 20
    x = df[["time", "ticker"]].copy()
    x["date"] = pd.to_datetime(x["time"]).dt.normalize()
    # Lấy median số bar/ngày/ticker (ổn định hơn)
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
    """Nếu có market_close mà thiếu market_MA200: dùng daily rolling 200 → ffill intraday."""
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
    # Map về theo ngày
    map_df = daily_last[["d", "market_MA200_daily"]]
    z = pd.to_datetime(df["time"], errors="coerce").dt.normalize().to_frame(name="d")
    out = z.merge(map_df, on="d", how="left")["market_MA200_daily"]
    # ffill theo thứ tự thời gian
    out = pd.Series(out.values, index=df.index)
    # ffill theo index order
    out = out.ffill()
    return out


def _ensure_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """
    Bổ sung đầy đủ các cột cần cho screener/trigger y hệt V4-Robust vòng 2.
    Trả về (df_đã_bổ_sung, bars_per_day).
    """
    if df is None or df.empty:
        return df, 20

    x = df.copy()

    # Chuẩn hoá time & sort
    if "time" in x.columns:
        x["time"] = pd.to_datetime(x["time"], errors="coerce")
    if "ticker" not in x.columns:
        x["ticker"] = x.get("symbol", np.nan)
    x = x.sort_values(["ticker", "time"])
    g = x.groupby("ticker", group_keys=False)

    # Ước lượng bars/ngày (để tính highest_in_5d intraday)
    bars_per_day = _estimate_bars_per_day(x)

    # close/volume bắt buộc
    if "close" not in x.columns or "volume" not in x.columns:
        # Nếu thiếu, không thể tính; trả về nguyên bản
        return x, bars_per_day

    # MA & RSI
    if "sma_50" not in x.columns:
        x["sma_50"] = g["close"].transform(lambda s: s.rolling(50, min_periods=20).mean())
    if "sma_200" not in x.columns:
        x["sma_200"] = g["close"].transform(lambda s: s.rolling(200, min_periods=50).mean())
    if "rsi_14" not in x.columns:
        x["rsi_14"] = g["close"].transform(_rsi14)

    # Volume features
    if "volume_ma20" not in x.columns:
        x["volume_ma20"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    if "volume_spike" not in x.columns:
        x["volume_spike"] = (x["volume"] / x["volume_ma20"].replace(0, np.nan)).clip(upper=10)

    # Bollinger width (20,2σ)
    if "boll_width" not in x.columns:
        ma20 = g["close"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        sd20 = g["close"].transform(lambda s: s.rolling(20, min_periods=10).std())
        upper = ma20 + 2 * sd20
        lower = ma20 - 2 * sd20
        x["boll_width"] = (upper - lower).abs()

    # Highest in 5d
    need_high = "high" in x.columns
    if need_high and "highest_in_5d" not in x.columns:
        # Nếu daily: dùng 5 hàng; nếu intraday: ~5*bars/day và shift(1)
        # Nhận diện daily thô bằng median bars/day≈1
        window = 5 if bars_per_day <= 2 else max(5 * bars_per_day, 10)
        x["highest_in_5d"] = g["high"].transform(lambda s: s.rolling(window, min_periods=max(2, window // 5)).max().shift(1))

    # Market MA200 nếu thiếu mà có market_close
    if "market_MA200" not in x.columns and "market_close" in x.columns:
        x["market_MA200"] = _compute_market_ma200(x)

    return x, bars_per_day


# =========================
#  Screener (y hệt vòng 2)
# =========================
def apply_baseline_screener(df_day: pd.DataFrame, min_volume_ma20: int = 100_000) -> List[str]:
    """
    Lọc watchlist/weekly: đúng rule vòng 2.
    Expect df_day: snapshot (mỗi ticker 1 dòng) của ngày dùng để tạo watchlist.
    """
    if df_day is None or df_day.empty:
        return []
    z = df_day.copy()

    # volume_ma20 & volume filter
    z = z[z["volume_ma20"] > min_volume_ma20]
    z = z[z["volume"] > 200_000]

    # Market filter (nếu có đủ cột; nếu thiếu 'market_MA200' cố gắng đã được _ensure_features tính)
    if "market_close" in z.columns and "market_MA200" in z.columns:
        z = z[z["market_close"] > z["market_MA200"]]

    # Trend + momentum
    z = z[(z["close"] > z["sma_200"])]
    z = z[(z["close"] > z["sma_50"]) & (z["rsi_14"] > 55) & (z["rsi_14"] < 75)]

    # Volume confirmation baseline
    z = z.dropna(subset=["volume_spike"])
    z = z[z["volume_spike"] > 0.5]

    return z["ticker"].dropna().astype(str).unique().tolist()


# =========================
#  Weekly watchlist snapshot
# =========================
def _get_weekly_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """
    Lấy snapshot thứ Hai của tuần hiện tại (nếu không có → ngày gần nhất ≤ thứ Hai).
    Mỗi ticker 1 dòng (bar cuối của ngày chọn).
    """
    if df is None or df.empty:
        return df

    x = df.copy()
    x["time"] = pd.to_datetime(x["time"], errors="coerce")
    x["d"] = x["time"].dt.normalize()

    latest_ts = x["time"].max()
    if pd.isna(latest_ts):
        return pd.DataFrame(columns=x.columns)

    # Monday of current week
    weekday = int(latest_ts.weekday())  # Monday=0
    monday = (latest_ts.normalize() - pd.Timedelta(days=weekday)).normalize()

    # Nếu không có dữ liệu đúng Monday → lùi ngược đến ngày gần nhất trước Monday
    candidate_dates = x.loc[x["d"] <= monday, "d"].unique()
    if len(candidate_dates) == 0:
        # Fallback: dùng ngày gần nhất có dữ liệu
        fallback = x["d"].max()
        snap = x[x["d"] == fallback]
    else:
        # Chọn ngày gần Monday nhất (max <= Monday)
        chosen = pd.to_datetime(candidate_dates).max()
        snap = x[x["d"] == chosen]

    # Lấy bản ghi cuối ngày mỗi ticker
    snap = snap.sort_values(["ticker", "time"]).groupby("ticker", as_index=False).tail(1)
    return snap.drop(columns=["d"], errors="ignore")


# =========================
#  Alert generation (vòng 2)
# =========================
def generate_alerts(df: pd.DataFrame) -> List[AlertItem]:
    """
    Sinh tín hiệu BUY_NEW theo chiến lược V4-Robust vòng 2:
      - Weekly watchlist (apply_baseline_screener) trên snapshot thứ Hai.
      - Trigger hàng ngày/intraday: close > highest_in_5d & volume_spike > 0.5.
      - Explain: "Breakout 5d; Vol spike≈x.xx; RSI14≈yy".
    DataFrame kỳ vọng có cột: time, ticker, close, high, volume (+ các feature nếu có).
    Hàm sẽ tự tính feature còn thiếu.
    """
    if df is None or df.empty:
        return []

    x, _ = _ensure_features(df)
    if "ticker" not in x.columns or "time" not in x.columns:
        return []

    # Snapshot thứ Hai để tạo watchlist tuần
    weekly_snap = _get_weekly_snapshot(x)
    wl = apply_baseline_screener(weekly_snap, min_volume_ma20=100_000)
    if not wl:
        return []

    # Bar mới nhất cho mỗi ticker thuộc watchlist
    latest = (
        x[x["ticker"].isin(wl)]
        .sort_values(["ticker", "time"])
        .groupby("ticker", as_index=False)
        .tail(1)
    )

    # Điều kiện trigger (vòng 2)
    cond_breakout = latest["close"] > latest.get("highest_in_5d", np.nan)
    cond_vol = latest["volume_spike"] > 0.5
    picked = latest[cond_breakout & cond_vol].copy()

    out: List[AlertItem] = []
    if picked.empty:
        return out

    for _, r in picked.iterrows():
        ts = _to_ts(r.get("time"))
        # Chỉ gửi trong giờ thị trường
        if ts is not None and not _is_market_open(ts):
            continue

        explain_parts = ["Breakout 5d", f"Vol spike≈{float(r['volume_spike']):.2f}"]
        rsi_v = r.get("rsi_14", np.nan)
        if pd.notna(rsi_v):
            explain_parts.append(f"RSI14≈{float(rsi_v):.0f}")

        out.append(
            AlertItem(
                ticker=str(r["ticker"]),
                event_type="BUY_NEW",
                price=float(r.get("close")) if pd.notna(r.get("close")) else None,
                when=ts.strftime("%H:%M") if isinstance(ts, pd.Timestamp) else "now",
                explain="; ".join(explain_parts),
            )
        )

    return out


# =========================
#  Module exports
# =========================
__all__ = [
    "AlertItem",
    "apply_baseline_screener",
    "generate_alerts",
]