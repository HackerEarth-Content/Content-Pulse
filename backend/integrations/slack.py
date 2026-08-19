"""Slack: one parent message per (date, kind), one thread reply per entry.

Async port of the Django tracker's slack_notify.py, with the parent-post race
closed — two entries saved at once both saw parent_ts NULL and each posted a
parent, giving the channel two threads for the same day.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date

import httpx
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from core.config import settings
from core.database import Session
from core.dates import today as ist_today
from core.orm import DailyEntry, EntryItem, Member, SlackDayThread

log = logging.getLogger(__name__)

STATUS_EMOJI = {"open": "◻️", "in_progress": "⏳", "blocked": "🚫", "closed": "✅"}
WEEKLY_STATUS_EMOJI = {"yet_to_start": "◻️", "in_progress": "⏳", "blocked": "🚫", "completed": "✅"}
WEEKLY_STATUS_LABEL = {
    "yet_to_start": "not started", "in_progress": "in progress",
    "blocked": "blocked", "completed": "done",
}


def _mins(m: int | None) -> str:
    if not m:
        return "0m"
    h, rest = divmod(m, 60)
    if h and rest:
        return f"{h}h {rest}m"
    return f"{h}h" if h else f"{rest}m"


def _due_phrase(due_at: date | None, today: date) -> str | None:
    if due_at is None:
        return None
    delta = (due_at - today).days
    if delta < 0:
        return "⚠️ overdue"
    if delta == 0:
        return "due today"
    if delta == 1:
        return "due tomorrow"
    return f"due {due_at.strftime('%d %b')}"


_TAG_RE = re.compile(r"<[^>]+>")


def _plain(html: str | None) -> str:
    """Weekly plan actions/achievements are sanitized HTML from a rich-text
    field (bold/italic/bullets only — see richtext.ts) — Slack mrkdwn doesn't
    read HTML, so this strips tags rather than showing them literally."""
    return " ".join(_TAG_RE.sub(" ", html or "").split())
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


def _line(n: int, item, kind: str) -> str:
    parts = []
    if item.jira_issue_key:
        parts.append(f"<{item.jira_issue_url}|{item.jira_issue_key}>"
                     if item.jira_issue_url else item.jira_issue_key)
    parts.append(item.task_type.name)
    if item.customer and item.customer.strip():
        parts.append(f"*{item.customer.strip()}*")
    if kind == "update":
        parts.append(f"{STATUS_EMOJI.get(item.status, '')} {item.status.replace('_', ' ').title()}")
        if item.effort_minutes:
            parts.append(_mins(item.effort_minutes))
    else:
        phrase = _due_phrase(item.due_at, ist_today())
        if phrase:
            parts.append(phrase)
    line = f"{n}. " + " · ".join(parts)
    return line + (f"\n    _{item.notes.strip()}_" if item.notes and item.notes.strip() else "")


def reply_text(entry: DailyEntry) -> str:
    icon = "📋 Plan" if entry.kind == "plan" else "✅ Update"
    day_label = entry.entry_date.strftime("%A, %d %b")
    if entry.kind == "plan":
        due_today = sum(1 for it in entry.items if it.due_at == ist_today())
        extra = f" — {len(entry.items)} ticket{'s' if len(entry.items) != 1 else ''}"
        if due_today:
            extra += f", due today: {due_today}"
    else:
        effort = sum(it.effort_minutes or 0 for it in entry.items)
        closed = sum(1 for it in entry.items if it.status == "closed")
        still_open = len(entry.items) - closed
        extra = f" — {_mins(effort)} logged, {closed} closed"
        if still_open:
            extra += f", {still_open} still open"
    lines = [f"*{entry.member.display_name}* — {icon} for {day_label}{extra if entry.items else ''}"]
    if entry.items:
        lines += [_line(i, it, entry.kind) for i, it in enumerate(entry.items, 1)]
    else:
        lines.append(entry.raw_text or "_Nothing logged._")
    return "\n".join(lines)


def _type_summary(items) -> str:
    """'Content review, Documentation ×2' — task types in first-seen order,
    counted rather than listed once per ticket."""
    counts = Counter(it.task_type.name for it in items)
    seen: set[str] = set()
    parts = []
    for it in items:
        name = it.task_type.name
        if name in seen:
            continue
        seen.add(name)
        parts.append(f"{name} ×{counts[name]}" if counts[name] > 1 else name)
    return ", ".join(parts)


def parent_text(on: date, kind: str, entries: list[DailyEntry]) -> str:
    icon = "📋 *Daily Plans*" if kind == "plan" else "✅ *Daily Updates*"
    noun = "plan" if kind == "plan" else "update"
    total_tickets = sum(len(e.items) for e in entries)
    plural_e = "s" if len(entries) != 1 else ""
    plural_t = "s" if total_tickets != 1 else ""

    lines = [f"{icon} — {on.strftime('%A, %d %b %Y')}"]
    if kind == "plan":
        jira_wanted = sum(1 for e in entries for it in e.items if it.jira_wanted)
        summary = f"{len(entries)} {noun}{plural_e} filed"
        if total_tickets:
            summary += f" · {total_tickets} ticket{plural_t} planned"
        if jira_wanted:
            summary += f" · {jira_wanted} marked for Jira"
    else:
        effort = sum(it.effort_minutes or 0 for e in entries for it in e.items)
        summary = f"{len(entries)} {noun}{plural_e} filed"
        if total_tickets:
            summary += f" · {total_tickets} ticket{plural_t} reported"
        if effort:
            summary += f" · {_mins(effort)} logged"
    lines += [summary, ""]

    for e in entries:
        if e.items:
            n = len(e.items)
            lines.append(f"• {e.member.display_name} — {n} ticket{'s' if n != 1 else ''} "
                        f"({_type_summary(e.items)})")
        else:
            lines.append(f"• {e.member.display_name} — nothing logged")

    lines += ["", "_Replies below ↓_"]
    return "\n".join(lines)


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

        # One real ticket, one row — a plan row or an unmirrored update, same
        # dedup rule as services.analytics — so today's counts here match the
        # dashboard's rather than double-counting a mirror.
        stats: dict[int, dict[str, int]] = {}
        for mid, effort, status in await db.execute(
            select(DailyEntry.member_id, EntryItem.effort_minutes, EntryItem.status)
            .select_from(EntryItem).join(DailyEntry, DailyEntry.id == EntryItem.entry_id)
            .where(DailyEntry.entry_date == on, DailyEntry.source != "jira",
                   or_(DailyEntry.kind == "plan", EntryItem.plan_item_id.is_(None)))
        ):
            s = stats.setdefault(mid, {"tickets": 0, "effort": 0, "closed": 0})
            s["tickets"] += 1
            s["effort"] += effort or 0
            if status == "closed":
                s["closed"] += 1

    no_plan = [row for row in active if row[0] not in planned]
    planned_rows = [row for row in active if row[0] in planned]
    done = [row for row in planned_rows if row[0] in updated_ids]
    pending = [row for row in planned_rows if row[0] not in updated_ids]

    def stat_for(mid: int) -> dict[str, int]:
        return stats.get(mid, {"tickets": 0, "effort": 0, "closed": 0})

    async def names(rows: list) -> str:
        return ", ".join(
            [await _mention(slack_id, email, name) for _, name, email, slack_id in rows]
        ) or "—"

    async def bullet_list(rows: list, describe) -> str:
        out = []
        for mid, name, email, slack_id in rows:
            who = await _mention(slack_id, email, name)
            out.append(f"• {who} — {describe(stat_for(mid))}")
        return "\n".join(out) if out else "—"

    day = on.strftime("%A, %d %b %Y")
    board_link = f"<{settings.FRONTEND_URL}/plan-board|Open Plan Board →>"

    if phase == "morning":
        total_tickets = sum(stat_for(r[0])["tickets"] for r in planned_rows)
        summary = f"{len(planned_rows)} of {len(active)} people have filed today's plan"
        if total_tickets:
            summary += f" · {total_tickets} ticket{'s' if total_tickets != 1 else ''} planned across the team"
        lines = [f"📋 *Plan check-in — {day}*", summary, "",
                  f"✅ *Planned* ({len(planned_rows)})",
                  await bullet_list(planned_rows,
                                    lambda s: f"{s['tickets']} ticket{'s' if s['tickets'] != 1 else ''}")]
        if no_plan:
            lines += ["", f"❌ *No plan yet* ({len(no_plan)})", await names(no_plan)]
        lines += ["", board_link]
    else:
        total_effort = sum(stat_for(r[0])["effort"] for r in done)
        total_closed = sum(stat_for(r[0])["closed"] for r in done)
        summary = f"{len(done)} of {len(planned_rows)} planned today have logged an update"
        if total_effort or total_closed:
            summary += f" · {_mins(total_effort)} logged, {total_closed} tickets closed"
        lines = [f"✅ *Update check-in — {day}*", summary, "",
                  f"✅ *Updated* ({len(done)})",
                  await bullet_list(done, lambda s: f"{_mins(s['effort'])} logged, {s['closed']} closed")]
        if pending:
            lines += ["", f"⏳ *Still pending* ({len(pending)})",
                      await bullet_list(pending, lambda s: (
                          f"planned {s['tickets']} ticket{'s' if s['tickets'] != 1 else ''}, "
                          "nothing reported yet"
                      ))]
        if no_plan:
            lines += ["", f"⚠️ *Never planned today* ({len(no_plan)})", await names(no_plan)]
        lines += ["", board_link]

    try:
        await _call("chat.postMessage", {"channel": settings.SLACK_CHANNEL, "text": "\n".join(lines)})
        return {"posted": True}
    except SlackDisabled as e:
        return {"posted": False, "reason": str(e)}
    except Exception as e:
        log.warning("roll call failed: %s", e)
        return {"posted": False, "reason": str(e)}


def _weekly_describe_monday(rows: list[tuple[str, str, str]]) -> str:
    """'Ship the Acme refresh; Fix login copy' for a couple of actions, a bare
    count once there are more — a full list stops being scannable fast."""
    if not rows:
        return "—"
    if len(rows) <= 2:
        return "; ".join(_plain(action) for action, _, _ in rows)
    return f"{len(rows)} actions"


def _weekly_describe_friday(rows: list[tuple[str, str, str]]) -> str:
    """Per-item achievement text for a couple of items, a status roll-up
    ('✅ 2 done, 🚫 1 blocked') once there are more."""
    if not rows:
        return "—"
    if len(rows) <= 2:
        parts = []
        for action, achievement, status in rows:
            emoji = WEEKLY_STATUS_EMOJI.get(status, "◻️")
            parts.append(f"{emoji} {_plain(achievement) if achievement else _plain(action)}")
        return ", ".join(parts)
    counts = Counter(status for _, _, status in rows)
    order = ("completed", "blocked", "in_progress", "yet_to_start")
    return ", ".join(
        f"{WEEKLY_STATUS_EMOJI[s]} {counts[s]} {WEEKLY_STATUS_LABEL[s]}"
        for s in order if counts.get(s)
    )


async def post_weekly_plan_status(week_start: date, phase: str) -> dict:
    """Monday 11:59pm reports who's filed this week's plan; Friday 11:59pm
    reports who's updated it — same shape as `post_roll_call`, one week wide
    instead of one day.
    """
    from core.orm import WeeklyPlanItem

    async with Session() as db:
        active = list(await db.execute(
            select(Member.id, Member.display_name, Member.email, Member.slack_user_id)
            .where(Member.is_active.is_(True), Member.display_name.notin_(_TEST_FIXTURE_NAMES))
            .order_by(Member.display_name)
        ))
        items_by_member: dict[int, list[tuple[str, str, str]]] = {}
        for mid, action, achievement, status in await db.execute(
            select(WeeklyPlanItem.member_id, WeeklyPlanItem.action,
                   WeeklyPlanItem.achievement, WeeklyPlanItem.status)
            .where(WeeklyPlanItem.week_start == week_start)
            .order_by(WeeklyPlanItem.id)
        ):
            items_by_member.setdefault(mid, []).append((action, achievement, status))

    filed_ids = set(items_by_member)
    updated_ids = {
        mid for mid, rows in items_by_member.items()
        if any(status != "yet_to_start" for _, _, status in rows)
    }
    done_ids = filed_ids if phase == "monday" else updated_ids
    done = [row for row in active if row[0] in done_ids]
    missing = [row for row in active if row[0] not in done_ids]
    describe = _weekly_describe_monday if phase == "monday" else _weekly_describe_friday

    async def names(rows: list) -> str:
        return ", ".join(
            [await _mention(slack_id, email, name) for _, name, email, slack_id in rows]
        ) or "—"

    async def bullet_list(rows: list) -> str:
        out = []
        for mid, name, email, slack_id in rows:
            who = await _mention(slack_id, email, name)
            out.append(f"• {who} — {describe(items_by_member.get(mid, []))}")
        return "\n".join(out) if out else "—"

    week_label = week_start.strftime("Week of %d %b %Y")
    verb = "filed" if phase == "monday" else "updated"
    total_actions = sum(len(rows) for rows in items_by_member.values())

    summary = f"{len(done)} of {len(active)} people have {verb} this week's plan"
    if phase == "monday":
        if total_actions:
            summary += f" · {total_actions} action{'s' if total_actions != 1 else ''} planned"
    else:
        by_status = Counter(s for rows in items_by_member.values() for _, _, s in rows)
        if by_status:
            summary += (f" · {by_status['completed']} completed, "
                        f"{by_status['in_progress']} in progress, {by_status['blocked']} blocked")

    lines = [
        f"🗓️ *Weekly plan {verb} — {week_label}*", summary, "",
        f"✅ *{verb.title()}* ({len(done)})", await bullet_list(done),
    ]
    if missing:
        lines += ["", f"❌ *Not yet {verb}* ({len(missing)})", await names(missing)]

    try:
        await _call("chat.postMessage", {"channel": settings.SLACK_CHANNEL, "text": "\n".join(lines)})
        return {"posted": True}
    except SlackDisabled as e:
        return {"posted": False, "reason": str(e)}
    except Exception as e:
        log.warning("weekly plan status post failed: %s", e)
        return {"posted": False, "reason": str(e)}
