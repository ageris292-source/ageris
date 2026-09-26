"""Alerts (spec §34): always stored in-app; optionally pushed to Telegram or
email when configured. A channel failure never loses the in-app alert."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
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
    return {
        "in_app": {"available": True},
        "telegram": {
            "available": bool(cfg.telegram_enabled and s.telegram_bot_token and s.telegram_chat_id),
            "reason": None
            if cfg.telegram_enabled and s.telegram_bot_token
            else "disabled or AEGIS_TELEGRAM_BOT_TOKEN / AEGIS_TELEGRAM_CHAT_ID not set",
        },
        "email": {
            "available": bool(cfg.email_enabled and s.smtp_url and s.alert_email_to),
            "reason": None
            if cfg.email_enabled and s.smtp_url
            else "disabled or AEGIS_SMTP_URL / AEGIS_ALERT_EMAIL_TO not set",
        },
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
    """Store an alert once per dedupe key (flush, caller commits) and push it
    to configured channels if severe enough. Returns None for a duplicate."""
    if db.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key)) is not None:
        return None
    deliveries: dict[str, str] = {"in_app": "stored"}
    if SEVERITY[severity] >= SEVERITY[get_config().alerts.min_severity_to_push]:
        for ch in configured_channels():
            try:
                ch.send(title, body)
                deliveries[ch.name] = "sent"
            except Exception as exc:  # a push failure never loses the alert
                log.warning("alert channel %s failed: %s", ch.name, exc.__class__.__name__)
                deliveries[ch.name] = f"failed: {exc.__class__.__name__}"
    a = Alert(
        kind=kind,
        severity=severity,
        title=title[:200],
        body=body,
        link=link,
        dedupe_key=dedupe_key[:200],
        deliveries=deliveries,
    )
    db.add(a)
    db.flush()
    return a
