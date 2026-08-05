"""E-mailmeldingen versturen (bijv. bij een dip-signaal).

De SMTP-gegevens komen uit omgevingsvariabelen (.env). Voor Gmail gebruik je
een 'app-wachtwoord' (niet je gewone wachtwoord): https://myaccount.google.com/apppasswords
"""
from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class EmailConfig:
    host: str
    port: int
    user: str | None
    password: str | None
    sender: str | None
    recipient: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.user and self.password and self.recipient)


def load_email_config() -> EmailConfig:
    user = os.environ.get("STOX_SMTP_USER")
    return EmailConfig(
        host=os.environ.get("STOX_SMTP_HOST", "smtp.gmail.com"),
        port=int(os.environ.get("STOX_SMTP_PORT", "587")),
        user=user,
        password=os.environ.get("STOX_SMTP_PASSWORD"),
        sender=os.environ.get("STOX_ALERT_FROM", user),
        recipient=os.environ.get("STOX_ALERT_TO", user),
    )


def send_email(cfg: EmailConfig, subject: str, body: str) -> None:
    """Verstuur een platte-tekst e-mail via SMTP met STARTTLS."""
    if not cfg.is_configured:
        raise RuntimeError(
            "E-mail niet geconfigureerd. Zet STOX_SMTP_USER, STOX_SMTP_PASSWORD "
            "en STOX_ALERT_TO in je .env."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as server:
        server.starttls(context=context)
        server.login(cfg.user, cfg.password)
        server.send_message(msg)
