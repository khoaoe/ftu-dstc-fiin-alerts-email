from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

ALERT_TO = [e.strip() for e in os.getenv("ALERT_TO", "").split(",") if e.strip()]
ALERT_FROM = os.getenv("ALERT_FROM", "me")
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "[FTU-DSTC Alerts] ")

DATA_PARQUET_PATH = os.getenv("DATA_PARQUET_PATH")
FQ_USERNAME = os.getenv("FQ_USERNAME")
FQ_PASSWORD = os.getenv("FQ_PASSWORD")

TIMEZONE = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
