"""One-off: load utils/taxonomy.py's HACKEREARTH_SKILL_TAXONOMY dict into the
skill_taxonomy_tags table.

    uv run python -m scripts.seed_taxonomy

Idempotent — keyed on the (category, tag) unique constraint, safe to re-run.
After this, the taxonomy lives in the table and is managed from the Utils >
Skill Taxonomy screen; utils/taxonomy.py is not imported at request time.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.dialects.postgresql import insert

from core.database import Session
from core.orm import SkillTaxonomyTag
from utils.taxonomy import HACKEREARTH_SKILL_TAXONOMY


async def main() -> None:
    rows = [
        {"category": category, "tag": tag}
        for category, tags in HACKEREARTH_SKILL_TAXONOMY.items()
        for tag in tags
    ]
    async with Session() as db:
        stmt = insert(SkillTaxonomyTag).values(rows)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_taxonomy_category_tag")
        result = await db.execute(stmt)
        await db.commit()
        print(f"taxonomy: {result.rowcount} new tags inserted ({len(rows)} in source)")


if __name__ == "__main__":
    asyncio.run(main())
