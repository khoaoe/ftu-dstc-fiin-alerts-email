
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


_ALLOWED_RUN_MODES = {"INTRADAY", "EOD", "BOTH"}
_ALLOWED_INTRADAY_BY = {"1m", "5m", "15m"}


def _read_csv(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


ALERT_TO = _read_csv("ALERT_TO")
ALERT_FROM = os.getenv("ALERT_FROM", "me")
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "[FTU-DSTC Alerts] ")

DATA_PARQUET_PATH = os.getenv("DATA_PARQUET_PATH")
FQ_USERNAME = os.getenv("FQ_USERNAME")
FQ_PASSWORD = os.getenv("FQ_PASSWORD")

RUN_MODE = os.getenv("RUN_MODE", "BOTH").upper()
if RUN_MODE not in _ALLOWED_RUN_MODES:
    RUN_MODE = "BOTH"

INTRADAY_BY = os.getenv("INTRADAY_BY", "15m").lower()
if INTRADAY_BY not in _ALLOWED_INTRADAY_BY:
    INTRADAY_BY = "15m"

INTRADAY_LOOKBACK_MIN = max(_read_int("INTRADAY_LOOKBACK_MIN", 45), 1)
DEFAULT_TICKERS = [ticker.upper() for ticker in _read_csv("TICKERS", "HPG,SSI,VCB,VNM")]

TIMEZONE = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
