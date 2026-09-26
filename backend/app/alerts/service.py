"""Alerts (spec §34): always stored in-app; optionally pushed to Telegram or
email when configured. A channel failure never loses the in-app alert."""

from __future__ import annotations

import logging
import smtplib
from datetime import date
from email.message import EmailMessage
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config_file import get_config
from app.core.settings import get_settings
from app.models import Alert

log = logging.getLogger(__name__)
SEVERITY = {"info": 0, "warning": 1, "critical": 2}


class Channel(Protocol):
    name: str

    def send(self, title: str, body: str) -> None: ...


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, transport: httpx.BaseTransport | None = None):
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat = chat_id
        self._client = httpx.Client(timeout=10, transport=transport)

    def send(self, title: str, body: str) -> None:
        r = self._client.post(self._url, json={"chat_id": self._chat, "text": f"{title}\n\n{body}"})
        r.raise_for_status()


class EmailChannel:
    name = "email"

    def __init__(self, url: str, to: str, sender: str):
        self._u, self._to, self._from = urlparse(url), to, sender

    def send(self, title: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = f"[Aegis] {title}", self._from, self._to
        msg.set_content(body)
        u = self._u
        cls = smtplib.SMTP_SSL if u.scheme == "smtps" else smtplib.SMTP
        with cls(u.hostname or "localhost", u.port or (465 if u.scheme == "smtps" else 587)) as s:
            if u.scheme == "smtp":
                s.starttls()
            if u.username:
                s.login(u.username, u.password or "")
            s.send_message(msg)


_override: list[Channel] | None = None


def set_channels(channels: list[Channel] | None) -> None:
    """Tests: replace the configured push channels (None = from settings)."""
    global _override
    _override = channels


def configured_channels() -> list[Channel]:
    if _override is not None:
        return _override
    cfg, s = get_config().alerts, get_settings()
    out: list[Channel] = []
    if cfg.telegram_enabled and s.telegram_bot_token and s.telegram_chat_id:
        out.append(TelegramChannel(s.telegram_bot_token.get_secret_value(), s.telegram_chat_id))
    if cfg.email_enabled and s.smtp_url and s.alert_email_to:
        out.append(
            EmailChannel(s.smtp_url.get_secret_value(), s.alert_email_to, s.alert_email_from)
        )
    return out


def channel_status() -> dict[str, Any]:
    cfg, s = get_config().alerts, get_settings()

    def status(enabled: bool, configured: bool, env: str) -> dict[str, Any]:
        if not enabled:
            return {"available": False, "reason": "disabled in config/aegis.yaml (alerts)"}
        if not configured:
            return {"available": False, "reason": f"{env} not set"}
        return {"available": True, "reason": None}

    return {
        "in_app": {"available": True, "reason": None},
        "telegram": status(
            cfg.telegram_enabled,
            bool(s.telegram_bot_token and s.telegram_chat_id),
            "AEGIS_TELEGRAM_BOT_TOKEN / AEGIS_TELEGRAM_CHAT_ID",
        ),
        "email": status(
            cfg.email_enabled,
            bool(s.smtp_url and s.alert_email_to),
            "AEGIS_SMTP_URL / AEGIS_ALERT_EMAIL_TO",
        ),
        "min_severity_to_push": cfg.min_severity_to_push,
    }


def raise_alert(
    db: Session,
    *,
    kind: str,
    severity: str,
    title: str,
    body: str,
    dedupe_key: str,
    link: str | None = None,
) -> Alert | None:
    """Store an alert once per dedupe key (flush, caller commits), then push
    it to configured channels if severe enough. Returns None for a duplicate,
    which is never pushed again."""
    if severity not in SEVERITY:
        raise ValueError(f"unknown alert severity {severity!r}")
    key = dedupe_key[:200]
    if db.scalar(select(Alert).where(Alert.dedupe_key == key)) is not None:
        return None
    a = Alert(
        kind=kind,
        severity=severity,
        title=title[:200],
        body=body,
        link=link,
        dedupe_key=key,
        deliveries={"in_app": "stored"},
    )
    try:
        with db.begin_nested():  # a concurrent duplicate loses the race quietly
            db.add(a)
    except IntegrityError:
        return None
    if SEVERITY[severity] >= SEVERITY[get_config().alerts.min_severity_to_push]:
        deliveries = dict(a.deliveries)
        for ch in configured_channels():
            try:
                ch.send(a.title, body)
                deliveries[ch.name] = "sent"
            except Exception as exc:  # a push failure never loses the alert
                log.warning("alert channel %s failed: %s", ch.name, exc.__class__.__name__)
                deliveries[ch.name] = f"failed: {exc.__class__.__name__}"
        a.deliveries = deliveries
        db.flush()
    return a


def alert_ingestion_failures(
    db: Session, job: str, results: dict[str, str], day: date
) -> Alert | None:
    """One warning per job per day listing every item whose ingestion failed
    (status failed/rejected or an exception). Caller commits."""
    bad = {
        k: v
        for k, v in results.items()
        if v in ("failed", "rejected") or v.startswith(("error", "failed"))
    }
    if not bad:
        return None
    listed = "; ".join(f"{k}: {v}" for k, v in sorted(bad.items()))
    return raise_alert(
        db,
        kind="ingestion_failed",
        severity="warning",
        title=f"{job} ingestion failed for {len(bad)} of {len(results)}",
        body=f"{listed[:1800]}. Affected data may be stale; gates will reject on freshness.",
        dedupe_key=f"ingest:{job}:{day.isoformat()}",
    )
