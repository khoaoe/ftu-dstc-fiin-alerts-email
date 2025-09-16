from __future__ import annotations
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from typing import Sequence

TEMPLATES_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"])
)

def render_alert_email(alerts: Sequence[dict]) -> tuple[str, str]:
    """Return (html, text) email bodies."""
    html = env.get_template("alert_email.html.j2").render(alerts=alerts)
    text = env.get_template("alert_email.txt.j2").render(alerts=alerts)
    return html, text
