"""Releasing an entry to Jira and Slack, now or later.

An entry can be written at 18:00 and released at 20:00. Both paths — the
immediate one behind a request and the scheduled one behind a cron job — go
through `publish` here, so a scheduled plan reaches Jira by exactly the same
route as an unscheduled one. They were briefly separate and immediately drifted:
only the request path honoured `jira_wanted`.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.dates import now as ist_now
from integrations import jira, slack
from core.orm import DailyEntry, EntryItem

log = logging.getLogger(__name__)


def is_held(entry: DailyEntry, now: datetime | None = None) -> bool:
    """Scheduled for later, so nothing goes out yet."""
    return entry.post_at is not None and entry.post_at > (now or ist_now())


def mark_pending(entry: DailyEntry) -> list[EntryItem]:
    """Flag the items that want a Jira ticket, and return everything to push.

    Items nobody asked to ticket keep `jira_state='none'` and are never queued —
    that flag is the whole opt-in.

    Deliberately does not commit. It used to, and the caller committed again a
    moment later; the second commit on an already-finished transaction killed
    the pooled connection and every plan POST failed at teardown. One writer,
    one commit.
    """
    pushable = []
    for item in entry.items:
        if item.jira_issue_key:
            pushable.append(item)
        elif item.jira_wanted:
            item.jira_state = "pending"
            pushable.append(item)
    return pushable


async def reload_stamps(db: AsyncSession, entry: DailyEntry) -> None:
    """Re-read the timestamps the database just computed for itself.

    `updated_at` carries a server-side `onupdate`, so once the entry row is
    UPDATEd SQLAlchemy cannot know its new value and expires the attribute.
    Serialising the entry afterwards then triggers a lazy refresh from inside
    the response, which in async SQLAlchemy is a `MissingGreenlet` — the whole
    POST fails at teardown with no obvious link to the write that caused it.

    Nothing dirtied the entry itself before scheduling existed, only its items,
    which is why this was never hit. Refreshing the two named columns keeps the
    already-loaded `items` collection intact.
    """
    await db.refresh(entry, attribute_names=["updated_at", "posted_at"])


async def publish(db: AsyncSession, entry: DailyEntry) -> int:
    """Push the entry's items to Jira and post it to Slack. Awaits everything,
    so the caller controls when it happens."""
    pushable = mark_pending(entry)
    await db.commit()
    for item in pushable:
        try:
            if item.jira_issue_key:
                await jira.push_status(item.id, item.status, item.notes)
            else:
                await jira.push_item(item.id)
        except Exception:
            # One bad item must not strand the rest of the entry, and the sweep
            # will retry whatever is left in `failed`.
            log.exception("jira push failed for item %s", item.id)

    try:
        await slack.post_entry(entry.id)
    except Exception:
        log.exception("slack post failed for entry %s", entry.id)

    entry.posted_at = ist_now()
    await db.commit()
    return len(pushable)


async def publish_due(db: AsyncSession, now: datetime | None = None) -> dict:
    """Release every entry whose scheduled time has arrived.

    `posted_at` is the guard: a process restart between the Jira push and the
    commit must not publish the same plan twice, and a missed window publishes
    late rather than never.
    """
    now = now or ist_now()
    entries = (await db.scalars(
        select(DailyEntry)
        .options(selectinload(DailyEntry.items))
        .where(
            DailyEntry.post_at.isnot(None),
            DailyEntry.post_at <= now,
            DailyEntry.posted_at.is_(None),
        )
        .order_by(DailyEntry.post_at)
    )).all()

    published = 0
    for entry in entries:
        try:
            await publish(db, entry)
            published += 1
        except Exception:
            log.exception("publishing entry %s failed", entry.id)
    return {"due": len(entries), "published": published}
