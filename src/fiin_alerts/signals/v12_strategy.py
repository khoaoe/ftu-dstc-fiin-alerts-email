from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "market_close",
    "market_MA50",
    "market_MA200",
    "market_rsi",
    "market_adx",
    "market_boll_width",
    "close",
    "volume",
    "volume_ma20",
    "sma_50",
    "sma_200",
    "rsi_14",
    "volume_spike",
    "ticker",
    "macd",
    "macd_signal",
    "boll_width",
    "sma_5",
    "atr_14",
]


def _ensure_time_index(data: pd.DataFrame) -> pd.DataFrame:
    if "time" in data.columns:
        clone = data.copy()
        clone["time"] = pd.to_datetime(clone["time"], errors="coerce")
        clone = clone.dropna(subset=["time"])
        clone = clone.sort_values(["time", "ticker"])
        clone["date"] = clone["time"].dt.normalize()
        return clone
    if isinstance(data.index, pd.DatetimeIndex):
        clone = data.copy()
        clone["time"] = clone.index.to_series()
        clone["date"] = clone["time"].dt.normalize()
        return clone.reset_index(drop=True)
    raise ValueError("data must provide datetime index or 'time' column")


def _compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window, min_periods=window).mean()
    avg_loss = loss.rolling(window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_macd(series: pd.Series) -> Tuple[pd.Series, pd.Series]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    high_low = high - low
    high_prev_close = (high - close.shift()).abs()
    low_prev_close = (low - close.shift()).abs()
    true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    return true_range.rolling(window, min_periods=window).mean()


def _compute_bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ma = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    width = (upper - lower) / ma.replace(0.0, np.nan)
    return upper, lower, width


def _compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    adjusted_volume = volume.fillna(0.0) * direction
    return adjusted_volume.cumsum()


def _compute_mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 14) -> pd.Series:
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    delta = typical_price.diff()
    pos_flow = money_flow.where(delta > 0, 0.0)
    neg_flow = -money_flow.where(delta < 0, 0.0)
    pos_roll = pos_flow.rolling(window, min_periods=window).sum()
    neg_roll = neg_flow.rolling(window, min_periods=window).sum()
    flow_ratio = pos_roll / neg_roll.replace(0.0, np.nan)
    return 100 - (100 / (1 + flow_ratio))

def ensure_technical_indicators(data: pd.DataFrame) -> pd.DataFrame:
    working = _ensure_time_index(data)
    working["ticker"] = working["ticker"].astype(str)
    working = working.sort_values(["ticker", "time"])
    grouped = working.groupby("ticker", group_keys=False)

    if "volume_ma20" not in working.columns:
        working["volume_ma20"] = grouped["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())

    if "sma_5" not in working.columns:
        working["sma_5"] = grouped["close"].transform(lambda s: s.rolling(5, min_periods=5).mean())

    if "sma_50" not in working.columns:
        working["sma_50"] = grouped["close"].transform(lambda s: s.rolling(50, min_periods=20).mean())

    if "sma_200" not in working.columns:
        working["sma_200"] = grouped["close"].transform(lambda s: s.rolling(200, min_periods=50).mean())

    if "rsi_14" not in working.columns:
        working["rsi_14"] = grouped["close"].transform(_compute_rsi)

    if "volume_spike" not in working.columns:
        denom = working["volume_ma20"].replace(0.0, np.nan)
        working["volume_spike"] = (working["volume"] / denom).clip(upper=10)

    needs_macd = {"macd", "macd_signal"}.difference(working.columns)
    if needs_macd:
        macd_parts: List[pd.Series] = []
        signal_parts: List[pd.Series] = []
        for _, idx in grouped.groups.items():
            close = working.loc[idx, "close"]
            macd, signal = _compute_macd(close)
            macd_parts.append(macd)
            signal_parts.append(signal)
        working["macd"] = pd.concat(macd_parts).sort_index()
        working["macd_signal"] = pd.concat(signal_parts).sort_index()

    if "atr_14" not in working.columns and {"high", "low", "close"}.issubset(working.columns):
        atr_parts: List[pd.Series] = []
        for _, idx in grouped.groups.items():
            atr_parts.append(_compute_atr(
                working.loc[idx, "high"],
                working.loc[idx, "low"],
                working.loc[idx, "close"],
            ))
        working["atr_14"] = pd.concat(atr_parts).sort_index()

    if "boll_width" not in working.columns:
        uppers: List[pd.Series] = []
        lowers: List[pd.Series] = []
        widths: List[pd.Series] = []
        for _, idx in grouped.groups.items():
            upper, lower, width = _compute_bollinger(working.loc[idx, "close"])
            uppers.append(upper)
            lowers.append(lower)
            widths.append(width)
        working["boll_upper"] = pd.concat(uppers).sort_index()
        working["boll_lower"] = pd.concat(lowers).sort_index()
        working["boll_width"] = pd.concat(widths).sort_index()

    if "mfi_14" not in working.columns:
        if {"high", "low", "close", "volume"}.issubset(working.columns):
            mfi_parts: List[pd.Series] = []
            for _, idx in grouped.groups.items():
                mfi_parts.append(_compute_mfi(
                    working.loc[idx, "high"],
                    working.loc[idx, "low"],
                    working.loc[idx, "close"],
                    working.loc[idx, "volume"],
                ))
            working["mfi_14"] = pd.concat(mfi_parts).sort_index()
        else:
            working["mfi_14"] = np.nan

    if "obv" not in working.columns:
        if {"close", "volume"}.issubset(working.columns):
            obv_parts: List[pd.Series] = []
            for _, idx in grouped.groups.items():
                obv_parts.append(_compute_obv(
                    working.loc[idx, "close"],
                    working.loc[idx, "volume"],
                ))
            working["obv"] = pd.concat(obv_parts).sort_index()
        else:
            working["obv"] = np.nan

    if "market_close" in working.columns:
        market_cols = ["market_close"]
        if "market_high" in working.columns and "market_low" in working.columns:
            market_cols.extend(["market_high", "market_low"])
        market_daily = working[["date", *market_cols]].drop_duplicates("date").set_index("date").sort_index()

        if "market_MA50" not in working.columns:
            ma50 = market_daily["market_close"].rolling(50, min_periods=20).mean()
            working["market_MA50"] = working["date"].map(ma50)

        if "market_MA200" not in working.columns:
            ma200 = market_daily["market_close"].rolling(200, min_periods=50).mean()
            working["market_MA200"] = working["date"].map(ma200)

        if "market_rsi" not in working.columns:
            market_rsi = _compute_rsi(market_daily["market_close"]).ffill()
            working["market_rsi"] = working["date"].map(market_rsi)

        if "market_boll_width" not in working.columns:
            _, _, market_width = _compute_bollinger(market_daily["market_close"])
            working["market_boll_width"] = working["date"].map(market_width)
            # Align with original v12.py behavior: provide a reasonable default
            working["market_boll_width"] = working["market_boll_width"].fillna(0.5)

        if "market_adx" not in working.columns and {"market_high", "market_low"}.issubset(working.columns):
            plus_dm = (market_daily["market_high"].diff().clip(lower=0)).fillna(0.0)
            minus_dm = (-market_daily["market_low"].diff().clip(upper=0)).fillna(0.0)
            tr_components = pd.concat([
                (market_daily["market_high"] - market_daily["market_low"]),
                (market_daily["market_high"] - market_daily["market_close"].shift()).abs(),
                (market_daily["market_low"] - market_daily["market_close"].shift()).abs(),
            ], axis=1)
            tr = tr_components.max(axis=1)
            atr = tr.rolling(14, min_periods=14).mean()
            plus_di = 100 * (plus_dm.rolling(14, min_periods=14).sum() / atr.replace(0.0, np.nan))
            minus_di = 100 * (minus_dm.rolling(14, min_periods=14).sum() / atr.replace(0.0, np.nan))
            dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9) * 100).rolling(14, min_periods=14).mean()
            working["market_adx"] = working["date"].map(dx.ffill())

        # Fallback: if we still don't have market_adx (e.g., parquet lacks market_high/market_low),
        # set a neutral baseline (25) to mirror v12.py defaulting behavior.
        if "market_adx" not in working.columns:
            working["market_adx"] = 25.0
        else:
            working["market_adx"] = working["market_adx"].fillna(25.0)

    missing = [col for col in REQUIRED_COLUMNS if col not in working.columns]
    if missing:
        raise ValueError(f"Missing required columns after indicator preparation: {missing}")

    return working

def screen_candidates_v12(
    df_day: pd.DataFrame,
    *,
    min_volume_ma20: int = 100000,
    max_candidates: int = 20,
) -> pd.DataFrame:
    if df_day.empty:
        return pd.DataFrame(columns=df_day.columns)
    missing = [col for col in REQUIRED_COLUMNS if col not in df_day.columns]
    if missing:
        return pd.DataFrame(columns=df_day.columns)

    market_close = df_day["market_close"].iloc[0]
    market_ma50 = df_day["market_MA50"].iloc[0]
    market_ma200 = df_day["market_MA200"].iloc[0]
    market_rsi = df_day["market_rsi"].iloc[0]
    market_adx = df_day["market_adx"].iloc[0]
    market_boll_width = df_day["market_boll_width"].iloc[0]

    is_bull = (market_close > market_ma50) and (market_close > market_ma200) and (market_rsi > 55)
    is_sideway = (market_adx < 25) and (market_boll_width < 0.35) and (35 <= market_rsi <= 60)
    if not is_bull and not is_sideway:
        return pd.DataFrame(columns=df_day.columns)

    scoped = df_day.copy()
    scoped["close_adj"] = scoped["close"] * scoped.get("adj_factor", 1)
    scoped = scoped[(scoped["volume_ma20"] > min_volume_ma20) & (scoped["volume"] > 300000)]
    if scoped.empty:
        return scoped

    scoped["relative_strength"] = (
        ((scoped["close_adj"] - scoped["sma_50"]) / scoped["sma_50"]) /
        ((market_close - market_ma50) / market_ma50 + 1e-6)
    )
    scoped["short_momentum"] = (scoped["close_adj"] - scoped["sma_5"]) / scoped["sma_5"]
    scoped["macd_histogram"] = scoped["macd"] - scoped["macd_signal"]

    if is_bull:
        scoped = scoped[
            (scoped["close_adj"] > scoped["sma_200"]) &
            (scoped["close_adj"] > scoped["sma_50"]) &
            (scoped["sma_50"] > scoped["sma_200"]) &
            (scoped["rsi_14"] > 50) & (scoped["rsi_14"] < 80) &
            (scoped["volume_spike"] > 0.3) &
            (scoped["relative_strength"] > 1.05) &
            (scoped["short_momentum"] > 0.01) &
            (scoped["close_adj"] > scoped["sma_5"])
        ]
        if scoped.empty:
            return scoped
        scoped["score"] = (
            scoped["relative_strength"] * 0.35 +
            scoped["short_momentum"] * 0.25 +
            scoped["volume_spike"] * 0.25 +
            scoped["macd_histogram"] * 0.15
        )
    else:
        scoped = scoped[
            (scoped["rsi_14"] > 48) & (scoped["rsi_14"] < 55) &
            (scoped["boll_width"] < 0.3) &
            (scoped["macd_histogram"] > 0) &
            (scoped["volume_spike"] >= 1.0) &
            (scoped["short_momentum"] > 0.02) &
            (scoped["atr_14"] / scoped["close_adj"] > 0.02) &
            (scoped["close_adj"] > scoped["sma_50"] * 0.95) &
            (scoped["close_adj"] > scoped["sma_200"] * 0.95) &
            (scoped["close_adj"] > scoped["sma_50"] + scoped["boll_width"] * scoped["sma_50"] * 0.75)
        ]
        if scoped.empty:
            return scoped
        max_candidates = max(5, int(max_candidates * 0.5))
        scoped["boll_proximity"] = (
            (scoped["close_adj"] - scoped["sma_50"]) /
            (scoped["sma_50"] * scoped["boll_width"])
        )
        scoped["score"] = (
            scoped["volume_spike"] * 0.4 +
            scoped["macd_histogram"] * 0.3 +
            (55 - (scoped["rsi_14"] - 55).abs()) * 0.2 +
            scoped["boll_proximity"] * 0.1
        )

    return scoped.nlargest(max_candidates, "score")


def _pivot_by_column(data: pd.DataFrame, column: str) -> pd.DataFrame | None:
    if column not in data.columns:
        return None
    pivot = data.pivot_table(index="date", columns="ticker", values=column, aggfunc="last")
    return pivot.sort_index()


def create_pivot_tables(data: pd.DataFrame) -> Dict[str, pd.DataFrame | None]:
    mapping = {
        "close": "pivoted_close",
        "open": "pivoted_open",
        "high": "pivoted_high",
        "low": "pivoted_low",
        "boll_width": "pivoted_boll_width",
        "boll_upper": "pivoted_boll_upper",
        "boll_lower": "pivoted_boll_lower",
        "volume_ma20": "pivoted_volume_ma20",
        "volume_spike": "pivoted_volume_spike",
        "sma_5": "pivoted_sma_5",
        "volume": "pivoted_volume",
        "rsi_14": "pivoted_rsi",
        "mfi_14": "pivoted_mfi",
        "obv": "pivoted_obv",
        "sma_50": "pivoted_sma_50",
        "macd": "pivoted_macd",
    }
    tables: Dict[str, pd.DataFrame | None] = {}
    for source, target in mapping.items():
        tables[target] = _pivot_by_column(data, source)
    return tables

def run_v12_backtest(
    data: pd.DataFrame,
    start_date: str,
    end_date: str,
    *,
    min_volume_ma20: int = 200000,
    max_candidates: int = 20,
    initial_capital: float = 1_000_000_000,
    base_capital: float = 1_000_000_000,
    commission_buy: float = 0.001,
    commission_sell_base: float = 0.001,
    tax_sell: float = 0.001,
    trade_limit_pct: float = 0.01,
    max_investment_per_trade_pct: float = 0.10,
    max_open_positions: int = 8,
    lot_size: int = 100,
    liquidity_threshold: float = 0.1,
    entry_mode: str = "close",
    atr_multiplier: float = 2.0,
    trailing_stop_pct: float = 0.05,
    partial_profit_pct: float = 0.4,
    min_holding_days: int = 2,
    pyramid_limit: int = 1,
) -> List[Dict[str, object]]:
    prepared = ensure_technical_indicators(data)
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    mask = (prepared["date"] >= start_ts) & (prepared["date"] <= end_ts)
    backtest_data = prepared.loc[mask].copy()
    if backtest_data.empty:
        return []

    tables = create_pivot_tables(backtest_data)
    pivoted_close = tables["pivoted_close"]
    pivoted_open = tables["pivoted_open"]
    pivoted_high = tables["pivoted_high"]
    pivoted_low = tables["pivoted_low"]
    pivoted_boll_width = tables["pivoted_boll_width"]
    pivoted_boll_upper = tables["pivoted_boll_upper"]
    pivoted_boll_lower = tables["pivoted_boll_lower"]
    pivoted_volume_ma20 = tables["pivoted_volume_ma20"]
    pivoted_volume_spike = tables["pivoted_volume_spike"]
    pivoted_sma_5 = tables["pivoted_sma_5"]
    pivoted_volume = tables["pivoted_volume"]
    pivoted_rsi = tables["pivoted_rsi"]
    pivoted_mfi = tables["pivoted_mfi"]
    pivoted_obv = tables["pivoted_obv"]
    pivoted_sma_50 = tables["pivoted_sma_50"]
    pivoted_macd = tables["pivoted_macd"]

    daily_groups = dict(tuple(backtest_data.groupby("date")))
    market_cols = [
        "market_close",
        "market_MA50",
        "market_MA200",
        "market_rsi",
        "market_adx",
        "market_boll_width",
    ]
    market_context = backtest_data.drop_duplicates("date")[["date", *market_cols]].set_index("date").sort_index()

    working_capital = float(initial_capital)
    reserve_capital = float(base_capital) - working_capital
    current_portfolio: Dict[str, Dict[str, object]] = {}
    pending_settlements: deque[Tuple[pd.Timestamp, float]] = deque()
    trades: List[Dict[str, object]] = []

    all_dates = sorted(daily_groups.keys())
    date_to_idx = {date: idx for idx, date in enumerate(all_dates)}

    for idx, current_date in enumerate(all_dates):
        while pending_settlements and pending_settlements[0][0] <= current_date:
            _, amount = pending_settlements.popleft()
            working_capital += amount

        market_row = market_context.loc[current_date]
        market_close = market_row["market_close"]
        market_ma50 = market_row["market_MA50"]
        market_ma200 = market_row["market_MA200"]
        market_rsi = market_row["market_rsi"]
        market_adx = market_row["market_adx"]
        market_boll_width = market_row["market_boll_width"]

        is_bull = (market_close > market_ma50) and (market_close > market_ma200) and (market_rsi > 50)
        is_sideway = (market_adx < 20) and (market_boll_width < 0.4) and (40 <= market_rsi <= 60)
        is_bear = (market_close < market_ma200) or (market_rsi < 30)

        market_phase = "bull" if is_bull else "sideway" if is_sideway else "bear"
        position_multiplier = 1.2 if is_bull else 0.5 if is_sideway else 0.0
        max_hold_days = 45 if is_bull else 20 if is_sideway else 15
        loss_exit_threshold = -0.10 if is_bull else -0.03 if is_sideway else -0.12
        atr_mult = 2.0 if is_bull else 1.2 if is_sideway else 2.2
        pyramid_limit_phase = 2 if is_bull else 1

        positions_to_remove: List[str] = []
        for ticker, pos in list(current_portfolio.items()):
            if pivoted_close is None or ticker not in pivoted_close.columns:
                continue

            open_val = pivoted_open.at[current_date, ticker] if pivoted_open is not None else np.nan
            high_val = pivoted_high.at[current_date, ticker] if pivoted_high is not None else np.nan
            low_val = pivoted_low.at[current_date, ticker] if pivoted_low is not None else np.nan
            close_val = pivoted_close.at[current_date, ticker]
            rsi_val = pivoted_rsi.at[current_date, ticker] if pivoted_rsi is not None else np.nan
            mfi_val = pivoted_mfi.at[current_date, ticker] if pivoted_mfi is not None else np.nan
            obv_val = pivoted_obv.at[current_date, ticker] if pivoted_obv is not None else np.nan
            sma5_val = pivoted_sma_5.at[current_date, ticker] if pivoted_sma_5 is not None else close_val
            sma50_val = pivoted_sma_50.at[current_date, ticker] if pivoted_sma_50 is not None else close_val

            if pd.isna(close_val):
                continue

            holding_days = int((current_date - pos["entry_date"]).days)
            tp = pos["tp"]
            sl = pos["sl"]
            trailing_sl = pos.get("trailing_sl", pos["entry_price"] * (1 - trailing_stop_pct))
            highest_price = pos.get("highest_price", pos["entry_price"])

            if high_val > highest_price:
                highest_price = high_val
                trailing_sl = highest_price * (1 - trailing_stop_pct)
                pos["highest_price"] = highest_price
                pos["trailing_sl"] = trailing_sl

            if market_phase == "sideway" and pivoted_boll_upper is not None and pivoted_boll_lower is not None:
                upper = pivoted_boll_upper.at[current_date, ticker]
                lower = pivoted_boll_lower.at[current_date, ticker]
                if not pd.isna(upper):
                    tp = min(tp, upper)
                if not pd.isna(lower):
                    sl = max(sl, lower)

            trigger_tp = False
            trigger_sl = False
            exit_price = None
            partial_exit = False
            exit_type = "Normal"

            if not pd.isna(open_val) and holding_days >= min_holding_days:
                if open_val >= tp:
                    trigger_tp = True
                    exit_price = open_val
                    partial_exit = True
                    exit_type = "Pyramid" if pos.get("pyramid_count", 0) > 0 else "Normal"
                elif open_val <= min(sl, trailing_sl):
                    trigger_sl = True
                    exit_price = open_val
                    exit_type = "Normal"

            if exit_price is None and holding_days >= min_holding_days:
                if not pd.isna(high_val) and high_val >= tp:
                    trigger_tp = True
                    exit_price = close_val
                    partial_exit = True
                    exit_type = "Pyramid" if pos.get("pyramid_count", 0) > 0 else "Normal"
                elif not pd.isna(low_val) and low_val <= min(sl, trailing_sl):
                    trigger_sl = True
                    exit_price = close_val
                    exit_type = "Normal"

            prev_obv = np.nan
            if idx > 0 and pivoted_obv is not None and ticker in pivoted_obv.columns:
                prev_date = all_dates[idx - 1]
                prev_obv = pivoted_obv.at[prev_date, ticker]
            is_weak = (
                (not pd.isna(rsi_val) and rsi_val < 30) and
                (not pd.isna(mfi_val) and mfi_val < 20) and
                (not pd.isna(obv_val) and obv_val < prev_obv)
            )
            current_profit_pct = close_val / pos["entry_price"] - 1
            trigger_end = (
                holding_days >= max_hold_days or
                is_weak or
                (market_phase == "bear" and current_profit_pct < loss_exit_threshold) or
                (market_phase == "sideway" and current_profit_pct < -0.03)
            )
            extended_hold = holding_days >= 50 and current_profit_pct > 0.08 and market_phase == "bull"
            if extended_hold:
                trigger_end = False

            if market_phase == "sideway" and sma5_val < sma50_val and current_profit_pct < 0.01:
                trigger_end = True
                exit_type = "Momentum Loss"

            pyramid_triggered = False
            if (
                not trigger_tp and not trigger_sl and not trigger_end and
                market_phase == "bull" and
                2 <= holding_days <= 10 and
                0.05 < current_profit_pct < 0.10 and
                pos.get("pyramid_count", 0) < pyramid_limit_phase
            ):
                add_shares = int(pos["shares"] * 0.2 / lot_size) * lot_size
                add_cost = add_shares * close_val * (1 + commission_buy)
                if add_shares >= lot_size and working_capital >= add_cost:
                    new_avg_cost = (
                        pos["shares"] * pos["avg_cost"] + add_shares * close_val
                    ) / (pos["shares"] + add_shares)
                    pos["avg_cost"] = new_avg_cost
                    pos["shares"] += add_shares
                    pos["pyramid_count"] = pos.get("pyramid_count", 0) + 1
                    pos["tp"] = close_val * 1.12
                    pos["trailing_sl"] = close_val * (1 - trailing_stop_pct * 0.7)
                    pyramid_triggered = True
                    working_capital -= add_cost
            if (trigger_tp or trigger_sl or trigger_end) and holding_days >= min_holding_days and not pyramid_triggered:
                if trigger_end and exit_price is None:
                    exit_price = close_val
                    exit_type = "Pyramid" if pos.get("pyramid_count", 0) > 0 else "Normal"

                volume_today = pivoted_volume.at[current_date, ticker] if pivoted_volume is not None and ticker in pivoted_volume.columns else np.nan
                shares = pos["shares"]
                shares_to_sell = shares
                if trigger_tp and partial_exit:
                    shares_to_sell = int(shares * partial_profit_pct / lot_size) * lot_size
                shares_to_sell = max(lot_size if shares >= lot_size else shares, shares_to_sell)

                can_sell_today = (
                    not pd.isna(volume_today) and volume_today > 0 and
                    shares_to_sell <= volume_today * liquidity_threshold
                )

                use_exit_price = exit_price
                exit_date = current_date
                if not can_sell_today:
                    next_idx = idx
                    while next_idx < len(all_dates) - 1:
                        next_idx += 1
                        next_date = all_dates[next_idx]
                        if (next_date - pos["entry_date"]).days >= min_holding_days:
                            next_open = pivoted_open.at[next_date, ticker] if pivoted_open is not None else np.nan
                            if not pd.isna(next_open):
                                use_exit_price = next_open
                                exit_date = next_date
                                break
                    else:
                        use_exit_price = close_val
                        exit_date = current_date

                gross_proceeds = use_exit_price * shares_to_sell
                net_proceeds = gross_proceeds - (gross_proceeds * (commission_sell_base + tax_sell))
                if net_proceeds <= 0:
                    continue

                settlement_idx = date_to_idx.get(exit_date, idx) + 2
                settlement_date = all_dates[min(settlement_idx, len(all_dates) - 1)]
                pending_settlements.append((settlement_date, net_proceeds))

                holding_days_exit = int((exit_date - pos["entry_date"]).days)
                if holding_days_exit < min_holding_days:
                    continue

                profit = net_proceeds - (shares_to_sell * pos["avg_cost"] * (1 + commission_buy))
                trades.append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": exit_date,
                    "entry_price": pos["entry_price"],
                    "exit_price": use_exit_price,
                    "shares": shares_to_sell,
                    "profit": profit,
                    "holding_days": holding_days_exit,
                    "exit_type": exit_type,
                })

                if partial_exit and trigger_tp and shares_to_sell < shares:
                    pos["shares"] -= shares_to_sell
                    pos["tp"] = use_exit_price * 1.15
                    pos["sl"] = max(pos["sl"], use_exit_price * (1 - trailing_stop_pct * 1.2))
                else:
                    positions_to_remove.append(ticker)

        for ticker in positions_to_remove:
            current_portfolio.pop(ticker, None)

        day_frame = daily_groups[current_date]
        candidates = screen_candidates_v12(
            day_frame,
            min_volume_ma20=min_volume_ma20,
            max_candidates=max_candidates,
        )
        if entry_mode != "close" or candidates.empty or is_bear:
            continue

        slots_available = int((max_open_positions - len(current_portfolio)) * position_multiplier)
        if market_phase == "bear":
            slots_available = max(1, slots_available // 2)
        slots_available = max(slots_available, 0)
        if slots_available == 0:
            continue

        candidates = candidates.sort_values("score", ascending=False)
        allocation_multiplier = 1.1 if slots_available > 2 else 1.0
        max_investment = working_capital * max_investment_per_trade_pct
        executed = 0

        for _, row in candidates.iterrows():
            ticker = row["ticker"]
            if ticker in current_portfolio:
                continue
            entry_price = row["close"]
            if entry_price <= 0:
                continue

            investment_per_stock = min(
                (working_capital / max(slots_available, 1)) * position_multiplier * allocation_multiplier,
                max_investment,
            )
            intended_shares = (investment_per_stock / (1 + commission_buy)) / entry_price
            max_shares_by_volume = row["volume_ma20"] * trade_limit_pct
            actual_shares = int(min(intended_shares, max_shares_by_volume) / lot_size) * lot_size
            if actual_shares < lot_size:
                continue

            actual_cost = actual_shares * entry_price * (1 + commission_buy)
            liquidity_cap = row["volume"] * row["close"] * liquidity_threshold
            if actual_shares * entry_price > liquidity_cap:
                continue

            projected = working_capital - actual_cost
            if projected < 0:
                continue

            working_capital -= actual_cost
            current_portfolio[ticker] = {
                "shares": actual_shares,
                "entry_price": entry_price,
                "avg_cost": entry_price,
                "tp": entry_price + (atr_mult * row["atr_14"]),
                "sl": entry_price - (atr_mult * row["atr_14"]),
                "trailing_sl": entry_price * (1 - trailing_stop_pct),
                "highest_price": entry_price,
                "end_date": current_date + pd.Timedelta(days=max_hold_days),
                "entry_date": current_date,
                "pyramid_count": 0,
            }
            executed += 1
            if executed >= slots_available:
                break

    return trades

def trades_to_signal_frame(trades: Iterable[Dict[str, object]]) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
    for trade in trades:
        entry_date = pd.to_datetime(trade["entry_date"]).normalize()
        exit_date = pd.to_datetime(trade["exit_date"]).normalize()
        shares = int(trade["shares"])
        entry_price = float(trade["entry_price"])
        exit_price = float(trade["exit_price"])
        profit = float(trade["profit"])
        profit_pct = (exit_price / entry_price - 1) if entry_price else np.nan

        records.append({
            "date": entry_date,
            "signal_type": "BUY_NEW",
            "ticker": trade["ticker"],
            "price": entry_price,
            "shares": shares,
            "holding_days": trade["holding_days"],
            "exit_type": "",
            "profit": np.nan,
            "profit_pct": np.nan,
        })
        records.append({
            "date": exit_date,
            "signal_type": "SELL",
            "ticker": trade["ticker"],
            "price": exit_price,
            "shares": shares,
            "holding_days": trade["holding_days"],
            "exit_type": trade["exit_type"],
            "profit": profit,
            "profit_pct": profit_pct,
        })

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame
    frame = frame.sort_values(["date", "signal_type", "ticker"]).reset_index(drop=True)
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    return frame
