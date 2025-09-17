from __future__ import annotations

import numpy as np
import pandas as pd

RSI_PERIOD = 14
SMA_SHORT = 50
SMA_LONG = 200
BOLLINGER_WINDOW = 20
VOLUME_WINDOW = 20


def _compute_rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def enrich_intraday_features(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    if df.empty:
        return df.copy()
    if "ticker" not in df.columns:
        return df.copy()

    enriched = df.copy()
    enriched["ticker"] = enriched["ticker"].astype(str).str.upper()
    if "time" in enriched.columns:
        enriched = enriched.sort_values(["ticker", "time"])  # ensure chronological order per ticker

    grouped = enriched.groupby("ticker", group_keys=False)

    if "close" in enriched.columns:
        enriched["sma_50"] = grouped["close"].transform(lambda s: s.rolling(window=SMA_SHORT, min_periods=1).mean())
        enriched["sma_200"] = grouped["close"].transform(lambda s: s.rolling(window=SMA_LONG, min_periods=1).mean())
        enriched["rsi_14"] = grouped["close"].transform(_compute_rsi)
        std_20 = grouped["close"].transform(lambda s: s.rolling(window=BOLLINGER_WINDOW, min_periods=1).std(ddof=0))
        enriched["bollinger_width_20"] = 2 * std_20.fillna(0.0)
    else:
        enriched["sma_50"] = np.nan
        enriched["sma_200"] = np.nan
        enriched["rsi_14"] = 50.0
        enriched["bollinger_width_20"] = np.nan

    if "volume" in enriched.columns:
        volume_ma = grouped["volume"].transform(lambda s: s.rolling(window=VOLUME_WINDOW, min_periods=1).mean())
        volume_ma = volume_ma.fillna(0.0)
        enriched["volume_ma20"] = volume_ma
        enriched["volume_spike"] = np.where(
            volume_ma > 0,
            (enriched["volume"] - volume_ma) / volume_ma,
            0.0,
        )
    else:
        enriched["volume_ma20"] = np.nan
        enriched["volume_spike"] = 0.0

    return enriched
