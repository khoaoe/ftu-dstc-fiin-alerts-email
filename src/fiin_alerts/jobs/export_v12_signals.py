from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd

from src.fiin_alerts.config import DATA_PARQUET_PATH
from src.fiin_alerts.signals.v12_strategy import (
    run_v12_backtest,
    trades_to_signal_frame,
)

DEFAULT_START = "2025-07-01"
DEFAULT_END = "2025-08-31"


def _load_source_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"data file not found: {path}")
    df = pd.read_parquet(path)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"])
    elif isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
    else:
        raise ValueError("dataframe must include 'time' column or datetime index")
    return df


def export_signals(
    *,
    data_path: Path,
    start_date: str,
    end_date: str,
    output_path: Path,
    min_volume_ma20: int,
    max_candidates: int,
) -> pd.DataFrame:
    data = _load_source_data(data_path)
    trades = run_v12_backtest(
        data,
        start_date,
        end_date,
        min_volume_ma20=min_volume_ma20,
        max_candidates=max_candidates,
    )
    frame = trades_to_signal_frame(trades)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export V12 buy/sell signals to CSV")
    parser.add_argument("--start", default=DEFAULT_START, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=DEFAULT_END, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", default="signals_v12.csv", help="Output CSV path")
    parser.add_argument(
        "--data-path",
        default=DATA_PARQUET_PATH or "",
        help="Parquet data source; defaults to DATA_PARQUET_PATH from config",
    )
    parser.add_argument("--min-volume", type=int, default=200000, help="Minimum MA20 volume filter")
    parser.add_argument("--max-candidates", type=int, default=20, help="Maximum tickers per day")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    data_path = Path(args.data_path or "") if args.data_path else None
    if data_path is None or not data_path:
        raise SystemExit("--data-path is required or set DATA_PARQUET_PATH in .env")

    output_path = Path(args.output)
    frame = export_signals(
        data_path=data_path,
        start_date=args.start,
        end_date=args.end,
        output_path=output_path,
        min_volume_ma20=args.min_volume,
        max_candidates=args.max_candidates,
    )

    print(f"Exported {len(frame)} signal rows to {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
