
from __future__ import annotations

import argparse
import logging
from typing import Iterable, List

import pandas as pd
from src.fiin_alerts.config import (
    ALERT_FROM,
    ALERT_TO,
    DATA_PARQUET_PATH,
    DEFAULT_TICKERS,
    FQ_PASSWORD,
    FQ_USERNAME,
    INTRADAY_BY,
    INTRADAY_LOOKBACK_MIN,
    RUN_MODE,
    SUBJECT_PREFIX,
)
from src.fiin_alerts.data.fiinquant_adapter import fetch_intraday
from src.fiin_alerts.data.parquet_adapter import load_recent_from_parquet
from src.fiin_alerts.logging import setup
from src.fiin_alerts.notify.composer import render_alert_email
from src.fiin_alerts.notify.gmail_client import send_email
from src.fiin_alerts.signals.v4_robust import AlertItem, generate_alerts
from src.fiin_alerts.state.store import already_sent, mark_sent

LOG = logging.getLogger(__name__)
_FALLBACK_TICKERS = DEFAULT_TICKERS or ["HPG", "SSI", "VCB", "VNM"]


def _parse_tickers(raw: Iterable[str] | None) -> List[str]:
    if not raw:
        return [t.upper() for t in _FALLBACK_TICKERS]
    parsed = [token.strip().upper() for token in raw if token and token.strip()]
    return parsed or [t.upper() for t in _FALLBACK_TICKERS]


def _fetch_source_data(tickers: List[str]) -> pd.DataFrame:
    df = pd.DataFrame()
    if FQ_USERNAME and FQ_PASSWORD:
        try:
            df = fetch_intraday(
                FQ_USERNAME,
                FQ_PASSWORD,
                tickers,
                minutes=INTRADAY_LOOKBACK_MIN,
                by=INTRADAY_BY,
            )
        except Exception as exc:  # pragma: no cover - defensive
            LOG.warning("FiinQuant fetch failed: %s", exc)
            df = pd.DataFrame()
    if df is None or df.empty:
        fallback = pd.DataFrame()
        if DATA_PARQUET_PATH:
            try:
                candidate = load_recent_from_parquet(DATA_PARQUET_PATH)
            except FileNotFoundError:
                LOG.info('Parquet fallback missing path=%s', DATA_PARQUET_PATH)
                candidate = None
            if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                fallback = candidate
        df = fallback
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _dedupe_alerts(alerts: List[AlertItem], mode: str) -> tuple[list[AlertItem], list[str]]:
    deduped: list[AlertItem] = []
    keys: list[str] = []
    for alert in alerts:
        slot = alert.when or mode
        key = f"{alert.ticker}:{alert.event_type}:{slot}"
        if already_sent(key):
            LOG.debug("Skip duplicate alert key=%s", key)
            continue
        deduped.append(alert)
        keys.append(key)
    return deduped, keys


def _build_subject(mode: str, count: int) -> str:
    mode_tag = f"[{mode}] " if mode and mode != "BOTH" else ""
    return f"{SUBJECT_PREFIX}{mode_tag}{count} alerts"


def _log_summary(alerts: list[AlertItem]) -> None:
    lines = []
    for alert in alerts[:10]:
        price_display = f"{alert.price:.2f}" if alert.price is not None else "-"
        lines.append(
            f"{alert.ticker} {alert.event_type} price={price_display} when={alert.when}"
        )
    extra = max(len(alerts) - len(lines), 0)
    if extra:
        lines.append(f"(+{extra} more)")
    LOG.info("Summary: %s", "".join(lines))

def run_once(
    mode: str | None = None,
    tickers: Iterable[str] | None = None,
    recipients: Iterable[str] | None = None,
    dry_run: bool = False,
    force_test: bool = False,
) -> int:
    effective_mode = (mode or RUN_MODE).upper()
    resolved_tickers = _parse_tickers(tickers)
    frame = _fetch_source_data(resolved_tickers)
    if frame.empty:
        LOG.info("No market data available for tickers=%s", resolved_tickers)
    alerts = generate_alerts(frame)

    if force_test:
        alerts = [AlertItem("TEST", "INFO", 1234.0, "now", "force-test alert")]

    if not alerts:
        LOG.info("No alerts generated for mode=%s", effective_mode)
        return 0

    deduped, keys = _dedupe_alerts(alerts, effective_mode)
    if not deduped:
        LOG.info("All alerts already delivered for mode=%s", effective_mode)
        return 0

    target_raw = list(recipients) if recipients else ALERT_TO
    target = [addr.strip() for addr in target_raw if addr and addr.strip()]
    if not target:
        LOG.error("No recipients configured. Set ALERT_TO in .env or pass --to")
        return 0

    html, text = render_alert_email(deduped)
    subject = _build_subject(effective_mode, len(deduped))
    _log_summary(deduped)

    if dry_run:
        LOG.info("Dry-run: would send to=%s subject=%s", target, subject)
        return len(deduped)

    message_id = send_email(ALERT_FROM, target, subject, html, text)
    mark_sent(keys)
    LOG.info(
        "Email sent via Gmail API msg_id=%s count=%s recipients=%s",
        message_id,
        len(deduped),
        len(target),
    )
    return len(deduped)


def main() -> None:
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["INTRADAY", "EOD", "BOTH"])
    parser.add_argument("--tickers", help="Comma separated tickers override")
    parser.add_argument("--to", help="Comma separated recipients override ALERT_TO")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-test", action="store_true")
    args = parser.parse_args()

    tickers = (
        [token.strip() for token in args.tickers.split(",") if token.strip()]
        if args.tickers
        else None
    )
    override_recipients = (
        [token.strip() for token in args.to.split(",") if token.strip()]
        if args.to
        else None
    )

    run_once(
        mode=args.mode,
        tickers=tickers,
        recipients=override_recipients,
        dry_run=args.dry_run,
        force_test=args.force_test,
    )


if __name__ == "__main__":
    main()