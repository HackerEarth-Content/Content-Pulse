"""Self-rated skill levels (L1 Awareness .. L5 Expert) per member.

Window and exclusion list both live in one `integration_settings` row —
there's nothing here that needs its own table, and it's the same mechanism
Jira/Slack config already uses.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dates import today
from core.orm import IntegrationSetting, Member, MemberSkillRating, Skill

SETTING_KEY = "skill_graph"
DEFAULT_SETTING = {"open_weekdays": [0, 1, 2, 3, 4, 5, 6], "excluded_member_ids": []}


def err(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "detail": detail})


async def _setting(db: AsyncSession) -> IntegrationSetting:
    row = await db.get(IntegrationSetting, SETTING_KEY)
    if row is None:
        row = IntegrationSetting(key=SETTING_KEY, value=dict(DEFAULT_SETTING))
        db.add(row)
        await db.commit()
    return row


async def window_state(db: AsyncSession) -> dict:
    row = await _setting(db)
    weekdays = row.value.get("open_weekdays", DEFAULT_SETTING["open_weekdays"])
    return {
        "open": today().weekday() in weekdays,
        "open_weekdays": weekdays,
        "excluded_member_ids": row.value.get("excluded_member_ids", []),
    }


async def set_window(
    db: AsyncSession,
    *,
    open_weekdays: list[int] | None,
    excluded_member_ids: list[int] | None,
) -> dict:
    row = await _setting(db)
    value = dict(row.value)
    if open_weekdays is not None:
        if any(d < 0 or d > 6 for d in open_weekdays):
            raise err(
                422, "bad_weekday", "Weekdays must be 0 (Monday) through 6 (Sunday)."
            )
        value["open_weekdays"] = sorted(set(open_weekdays))
    if excluded_member_ids is not None:
        value["excluded_member_ids"] = sorted(set(excluded_member_ids))
    row.value = value
    await db.commit()
    return await window_state(db)


async def _guard_window(db: AsyncSession) -> None:
    state = await window_state(db)
    if not state["open"]:
        raise err(
            422, "window_closed", "Skill entry isn't open today — check with an admin."
        )


async def list_skills(db: AsyncSession) -> list[Skill]:
    return list(
        await db.scalars(
            select(Skill)
            .where(Skill.is_active.is_(True))
            .order_by(Skill.category, Skill.sort_order)
        )
    )


async def member_ratings(db: AsyncSession, member_id: int) -> dict[int, int]:
    rows = await db.scalars(
        select(MemberSkillRating).where(MemberSkillRating.member_id == member_id)
    )
    return {r.skill_id: r.level for r in rows}


async def upsert_ratings(
    db: AsyncSession,
    member_id: int,
    ratings: list[tuple[int, int]],
) -> dict[int, int]:
    await _guard_window(db)

    skill_ids = {sid for sid, _ in ratings}
    valid_ids = set(await db.scalars(select(Skill.id).where(Skill.id.in_(skill_ids))))
    if skill_ids - valid_ids:
        raise err(422, "bad_skill", "One or more skills don't exist.")

    existing = {
        r.skill_id: r
        for r in await db.scalars(
            select(MemberSkillRating).where(MemberSkillRating.member_id == member_id)
        )
    }
    for skill_id, level in ratings:
        if row := existing.get(skill_id):
            row.level = level
        else:
            db.add(
                MemberSkillRating(member_id=member_id, skill_id=skill_id, level=level)
            )
    await db.commit()
    return await member_ratings(db, member_id)


async def team_matrix(db: AsyncSession) -> tuple[list[Skill], list[dict]]:
    """Every active, non-excluded member's full rating map — small enough
    (skills × people) that the Overview/People/Skill views slice it
    client-side rather than each needing its own aggregation endpoint."""
    state = await window_state(db)
    excluded = set(state["excluded_member_ids"])

    skills = await list_skills(db)
    members = list(
        await db.scalars(
            select(Member)
            .where(Member.is_active.is_(True), Member.id.notin_(excluded or [-1]))
            .order_by(Member.display_name)
        )
    )
    ratings = list(await db.scalars(select(MemberSkillRating)))
    by_member: dict[int, dict[int, int]] = {}
    for r in ratings:
        by_member.setdefault(r.member_id, {})[r.skill_id] = r.level

    return skills, [
        {
            "member_id": m.id,
            "display_name": m.display_name,
            "role": m.role,
            "ratings": by_member.get(m.id, {}),
        }
        for m in members
    ]
