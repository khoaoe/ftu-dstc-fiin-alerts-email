from __future__ import annotations
import sqlite3, pathlib, datetime as dt
from typing import Iterable

DB = pathlib.Path("alerts_state.sqlite")

def _conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS sent(
        k TEXT PRIMARY KEY,
        ts TEXT NOT NULL
    )""")
    return c

def already_sent(key: str) -> bool:
    c = _conn()
    row = c.execute("SELECT 1 FROM sent WHERE k=?", (key,)).fetchone()
    c.close()
    return row is not None

def mark_sent(keys: Iterable[str]) -> None:
    now = dt.datetime.utcnow().isoformat()
    c = _conn()
    c.executemany("INSERT OR REPLACE INTO sent(k, ts) VALUES(?,?)", [(k, now) for k in keys])
    c.commit(); c.close()
