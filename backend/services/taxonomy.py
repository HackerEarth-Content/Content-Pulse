"""The HackerEarth skill taxonomy, editable from Utils > Skill Taxonomy.

Seeded once from utils/taxonomy.py (see scripts/seed_taxonomy.py); from then
on this table — not the seed file — is what the MCQ reviewer's Skill Tag
Coverage check reads, so an edit here applies to the very next review with no
deploy needed.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.orm import SkillTaxonomyTag


def _conflict(category: str, tag: str) -> HTTPException:
    return HTTPException(
        409,
        {
            "code": "tag_exists",
            "detail": f"{tag!r} already exists under {category!r}.",
        },
    )


async def list_taxonomy(db: AsyncSession) -> list[SkillTaxonomyTag]:
    rows = await db.scalars(
        select(SkillTaxonomyTag).order_by(
            SkillTaxonomyTag.category, SkillTaxonomyTag.tag
        )
    )
    return list(rows)


async def add_tag(db: AsyncSession, category: str, tag: str) -> SkillTaxonomyTag:
    row = SkillTaxonomyTag(category=category.strip(), tag=tag.strip())
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _conflict(category, tag)
    await db.refresh(row)
    return row


async def remove_tag(db: AsyncSession, tag_id: int) -> None:
    row = await db.get(SkillTaxonomyTag, tag_id)
    if row is None:
        raise HTTPException(404, {"code": "not_found", "detail": "Tag not found."})
    await db.delete(row)
    await db.commit()


async def taxonomy_prompt_block(db: AsyncSession) -> str:
    """The taxonomy formatted for injection into MCQ_REVIEWER_PROMPT — grouped
    by category, exactly what the "companion reference file" the prompt
    describes would have contained. Empty when nothing has been seeded yet;
    the prompt's own `taxonomy_not_provided` handling covers that case."""
    rows = await list_taxonomy(db)
    if not rows:
        return ""

    by_category: dict[str, list[str]] = {}
    for row in rows:
        by_category.setdefault(row.category, []).append(row.tag)

    lines = ["# HackerEarth Skill Taxonomy\n"]
    for category, tags in by_category.items():
        lines.append(f"## {category}")
        lines.extend(f"* {tag}" for tag in tags)
        lines.append("")
    return "\n".join(lines)
