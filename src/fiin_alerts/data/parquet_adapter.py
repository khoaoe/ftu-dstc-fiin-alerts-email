from __future__ import annotations
import pandas as pd
from pathlib import Path

def load_recent_from_parquet(path: str, rows: int = 5000) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    return df.tail(rows)
