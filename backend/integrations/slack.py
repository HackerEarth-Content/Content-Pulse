"""Slack: one parent message per (date, kind), one thread reply per entry.

Async port of the Django tracker's slack_notify.py, with the parent-post race
closed — two entries saved at once both saw parent_ts NULL and each posted a
parent, giving the channel two threads for the same day.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from core.config import settings
from core.database import Session
from core.orm import DailyEntry, SlackDayThread

log = logging.getLogger(__name__)
API = "https://slack.com/api"


class SlackDisabled(Exception):
    pass


async def _call(method: str, payload: dict) -> dict:
    if not settings.SLACK_BOT_TOKEN:
        raise SlackDisabled("SLACK_BOT_TOKEN not set")
    if not settings.SLACK_WRITES_ENABLED:
        raise SlackDisabled("SLACK_WRITES_ENABLED is off — nothing was posted")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{API}/{method}", json=payload,
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
        )
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("error", "slack_error"))
    return body


def _line(n: int, item, show_status: bool) -> str:
    parts = []
    if item.jira_issue_key:
        parts.append(f"<{item.jira_issue_url}|{item.jira_issue_key}>"
                     if item.jira_issue_url else item.jira_issue_key)
    parts.append(item.task_type.name)
    for value in (item.customer, item.question_type.name if item.question_type else None):
        if value and str(value).strip():
            parts.append(str(value).strip())
    if item.count is not None:
        parts.append(f"Count: {item.count}")
    if show_status:
        parts.append(item.status.replace("_", " ").title())
    line = f"{n}. " + " · ".join(parts)
    return line + (f"\n    _{item.notes.strip()}_" if item.notes and item.notes.strip() else "")


def reply_text(entry: DailyEntry) -> str:
    icon = "📋 Plan" if entry.kind == "plan" else "✅ Update"
    lines = [f"*{entry.member.display_name}* — {icon} for {entry.entry_date}"]
    if entry.items:
        lines += [_line(i, it, entry.kind == "update") for i, it in enumerate(entry.items, 1)]
    else:
        lines.append(entry.raw_text or "_Nothing logged._")
    return "\n".join(lines)


def parent_text(on: date, kind: str, entries: list[DailyEntry]) -> str:
    icon = "📋 *Daily Plans*" if kind == "plan" else "✅ *Daily Updates*"
    names = ", ".join(e.member.display_name for e in entries)
    noun = "plan" if kind == "plan" else "update"
    return (f"{icon} — {on.strftime('%A, %d %b %Y')}\n"
            f"{len(entries)} {noun}{'s' if len(entries) != 1 else ''} submitted "
            f"by: {names}\n_Replies below ↓_")


async def _entries_for(db, on: date, kind: str) -> list[DailyEntry]:
    return list(await db.scalars(
        select(DailyEntry)
        .options(selectinload(DailyEntry.items))
        .where(DailyEntry.entry_date == on, DailyEntry.kind == kind)
        .order_by(DailyEntry.created_at)
    ))


async def _thread_row(db, on: date, kind: str, channel: str) -> SlackDayThread:
    """Insert-or-get, then lock. Whoever wins the lock posts the parent; the
    loser waits and reuses the ts instead of posting a second one."""
    await db.execute(
        insert(SlackDayThread)
        .values(digest_date=on, kind=kind, channel=channel)
        .on_conflict_do_nothing(index_elements=["digest_date", "kind", "channel"])
    )
    await db.commit()
    return await db.scalar(
        select(SlackDayThread)
        .where(SlackDayThread.digest_date == on, SlackDayThread.kind == kind,
               SlackDayThread.channel == channel)
        .with_for_update()
    )


async def post_entry(entry_id: int) -> None:
    """Ensure the day's parent exists, refresh its summary, reply with this
    entry. Idempotent — slack_reply_ts means it's already posted."""
    channel = settings.SLACK_CHANNEL
    async with Session() as db:
        entry = await db.scalar(
            select(DailyEntry).options(selectinload(DailyEntry.items))
            .where(DailyEntry.id == entry_id)
        )
        if entry is None or entry.slack_reply_ts:
            return
        try:
            thread = await _thread_row(db, entry.entry_date, entry.kind, channel)
            siblings = await _entries_for(db, entry.entry_date, entry.kind)
            summary = parent_text(entry.entry_date, entry.kind, siblings)

            if thread.parent_ts:
                await _call("chat.update",
                            {"channel": channel, "ts": thread.parent_ts, "text": summary})
            else:
                sent = await _call("chat.postMessage", {"channel": channel, "text": summary})
                thread.parent_ts = sent["ts"]
            await db.commit()

            sent = await _call("chat.postMessage", {
                "channel": channel, "thread_ts": thread.parent_ts,
                "text": reply_text(entry),
            })
            entry.slack_reply_ts = sent["ts"]
            await db.commit()
        except SlackDisabled:
            await db.rollback()
        except Exception as e:
            await db.rollback()
            log.warning("slack post failed for entry %s: %s", entry_id, e)


async def post_digest(on: date, kind: str, dry_run: bool = False) -> dict:
    """Replaces `manage.py post_slack_daily`. Posts anything not yet threaded."""
    async with Session() as db:
        entries = await _entries_for(db, on, kind)
    if not entries:
        return {"posted": 0, "skipped": 0, "detail": "nothing to post"}
    if dry_run:
        return {"parent": parent_text(on, kind, entries),
                "replies": [reply_text(e) for e in entries]}

    posted = sum(e.slack_reply_ts is None for e in entries)
    for entry in entries:
        await post_entry(entry.id)
    return {"posted": posted, "skipped": len(entries) - posted}
