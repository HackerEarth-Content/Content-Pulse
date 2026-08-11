"""Outbound email over Gmail SMTP.

stdlib `smtplib` in a worker thread rather than a new async dependency — this
sends a handful of messages once a day, so the cost of blocking a thread for a
second is irrelevant next to another package to keep patched.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from core.config import settings

log = logging.getLogger(__name__)

HOST, PORT = "smtp.gmail.com", 465


class EmailDisabled(Exception):
    """No credentials, or sending is switched off. Callers treat this as skip."""


def _check() -> None:
    if not (settings.GMAIL_SMTP_USER and settings.GMAIL_SMTP_APP_PASSWORD):
        raise EmailDisabled("GMAIL_SMTP_USER / GMAIL_SMTP_APP_PASSWORD not set")
    # Same guard as Jira and Slack: a test run must never mail real people.
    if not settings.EMAIL_ENABLED:
        raise EmailDisabled("EMAIL_ENABLED is off — nothing was sent")


def _deliver(to: str, subject: str, body: str, html: str | None = None) -> None:
    message = EmailMessage()
    message["From"] = f"ContentOps <{settings.GMAIL_SMTP_USER}>"
    message["To"] = to
    message["Subject"] = subject
    if settings.SUPPORT_EMAIL:
        message["Reply-To"] = settings.SUPPORT_EMAIL
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL(HOST, PORT, timeout=20) as smtp:
        smtp.login(settings.GMAIL_SMTP_USER, settings.GMAIL_SMTP_APP_PASSWORD)
        smtp.send_message(message)


async def send(to: str, subject: str, body: str, html: str | None = None) -> bool:
    """True if it went out. Never raises — a failed reminder must not take the
    scheduler down with it."""
    try:
        _check()
    except EmailDisabled as e:
        log.info("email skipped for %s: %s", to, e)
        return False
    try:
        await asyncio.to_thread(_deliver, to, subject, body, html)
        return True
    except Exception:
        log.exception("email to %s failed", to)
        return False


def plan_reminder(name: str, url: str) -> tuple[str, str, str]:
    """Subject and body for the 11am nudge. Short, specific, one link — a
    reminder people learn to ignore is worse than no reminder."""
    subject = "Your plan for today isn't in yet"
    body = (
        f"Morning {name},\n\n"
        "Today's plan hasn't been filed on ContentOps yet. It takes a minute:\n\n"
        f"    {url}\n\n"
        "Log what you're picking up, then update it as the day goes.\n"
    )
    html = f"""\
<div style="font-family:system-ui,-apple-system,'Segoe UI',sans-serif;font-size:15px;
            line-height:1.5;color:#20242c">
  <p>Morning {name},</p>
  <p>Today's plan hasn't been filed on ContentOps yet. It takes a minute.</p>
  <p><a href="{url}" style="display:inline-block;background:#0939e6;color:#fff;
        text-decoration:none;padding:10px 18px;border-radius:999px;font-weight:600">
    Plan my day</a></p>
  <p style="color:#6b7280;font-size:13px">
    Log what you're picking up, then update it as the day goes.</p>
</div>"""
    return subject, body, html


async def send_plan_reminders(people: list, url: str) -> dict:
    """One message each. Returns what actually went out, for the log."""
    sent, skipped = [], []
    for member in people:
        subject, body, html = plan_reminder(member.display_name.split()[0], url)
        if await send(member.email, subject, body, html):
            sent.append(member.display_name)
        else:
            skipped.append(member.display_name)
    return {"sent": sent, "skipped": skipped}
