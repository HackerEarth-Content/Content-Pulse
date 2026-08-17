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
from core.orm import DailyEntry, Member, SlackDayThread

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
    # Same rule as members_without_a_plan/today_status: a Jira-sync mirror of
    # ticket activity is not someone filing a plan or update in this app.
    return list(await db.scalars(
        select(DailyEntry)
        .options(selectinload(DailyEntry.items))
        .where(DailyEntry.entry_date == on, DailyEntry.kind == kind,
               DailyEntry.source != "jira")
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


# ── roll call: who's planned/updated today, who hasn't ───────────────────────

# email -> Slack user id, or None if it doesn't resolve. In-process only: the
# mapping doesn't change within a run, and there's no reason to hit Slack
# twice a day for the same handful of people.
# ponytail: resets on restart; a persistent mapping is the upgrade if lookups
# ever get expensive enough to matter.
_slack_id_cache: dict[str, str | None] = {}


async def _mention(slack_user_id: str | None, email: str | None, display_name: str) -> str:
    """`<@U123>`, so the channel actually pings them.

    A `slack_user_id` set on the member (Settings) wins outright — no API
    call needed. Otherwise falls back to resolving their email via
    `users.lookupByEmail`, which needs the bot's `users:read.email` scope;
    if that's missing or the lookup fails, falls back to a plain name rather
    than erroring the whole roll call.
    """
    if slack_user_id:
        return f"<@{slack_user_id}>"
    if not email:
        return display_name
    if email not in _slack_id_cache:
        try:
            body = await _call("users.lookupByEmail", {"email": email})
            _slack_id_cache[email] = body["user"]["id"]
        except Exception:
            _slack_id_cache[email] = None
    user_id = _slack_id_cache[email]
    return f"<@{user_id}>" if user_id else display_name


# Tests run against this same live database (see tests/conftest.py) and flip
# these exact rows to is_active=True for the duration of a run. A roll call
# triggered while a test run is mid-flight would otherwise call them out by
# name. ponytail: name-matching a known fixture list, not a real "is_test"
# column — the real fix is tests/conftest.py's own noted TODO, a separate
# test database.
_TEST_FIXTURE_NAMES = {"PyTest Member", "PyTest AE", "PyTest Admin", "RBAC Ada", "RBAC Grace"}


async def post_roll_call(on: date, phase: str) -> dict:
    """Post the whole roster's plan/update status as one message — not a
    thread reply, a standalone post, since it's a summary rather than
    someone's individual entry.

    `phase="morning"` reports who's filed today's plan; `phase="evening"`
    reports who's followed it with an update. Same Jira-sync exclusion as
    `services.entries.today_status` — a backfilled ticket isn't someone
    filing a plan, and "active" means every active member, admins included.
    """
    async with Session() as db:
        planned = {
            mid: name for mid, name in await db.execute(
                select(DailyEntry.member_id, Member.display_name)
                .join(Member, Member.id == DailyEntry.member_id)
                .where(DailyEntry.entry_date == on, DailyEntry.kind == "plan",
                       DailyEntry.source != "jira")
            )
        }
        updated_ids = {mid for (mid,) in await db.execute(
            select(DailyEntry.member_id)
            .where(DailyEntry.entry_date == on, DailyEntry.kind == "update")
        )}
        active = list(await db.execute(
            select(Member.id, Member.display_name, Member.email, Member.slack_user_id)
            .where(Member.is_active.is_(True), Member.display_name.notin_(_TEST_FIXTURE_NAMES))
            .order_by(Member.display_name)
        ))

    no_plan = [row for row in active if row[0] not in planned]
    planned_rows = [row for row in active if row[0] in planned]
    done = [row for row in planned_rows if row[0] in updated_ids]
    pending = [row for row in planned_rows if row[0] not in updated_ids]

    async def names(rows: list) -> str:
        return ", ".join(
            [await _mention(slack_id, email, name) for _, name, email, slack_id in rows]
        ) or "—"

    day = on.strftime("%A, %d %b %Y")
    if phase == "morning":
        lines = [f"📋 *Plan check-in — {day}*", "",
                  f"{len(planned_rows)} of {len(active)} people have filed today's plan.", "",
                  f"✅ *Planned* ({len(planned_rows)})", await names(planned_rows)]
        if no_plan:
            lines += ["", f"❌ *No plan yet* ({len(no_plan)})", await names(no_plan)]
    else:
        lines = [f"✅ *Update check-in — {day}*", "",
                  f"{len(done)} of {len(planned_rows)} planned today have logged an update.", "",
                  f"✅ *Updated* ({len(done)})", await names(done)]
        if pending:
            lines += ["", f"⏳ *Still pending* ({len(pending)})", await names(pending)]
        if no_plan:
            lines += ["", f"⚠️ *Never planned today* ({len(no_plan)})", await names(no_plan)]

    try:
        await _call("chat.postMessage", {"channel": settings.SLACK_CHANNEL, "text": "\n".join(lines)})
        return {"posted": True}
    except SlackDisabled as e:
        return {"posted": False, "reason": str(e)}
    except Exception as e:
        log.warning("roll call failed: %s", e)
        return {"posted": False, "reason": str(e)}
