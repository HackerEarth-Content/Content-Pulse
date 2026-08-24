"""revise tech skill list

Revision ID: 18d9191557ed
Revises: 017629e138f6
Create Date: 2026-08-24 11:58:21.074553

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18d9191557ed'
down_revision: Union[str, Sequence[str], None] = '017629e138f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Combined entries that either split apart or already duplicate a standalone
# skill (HTML/CSS/JavaScript all exist on their own already).
REMOVED = [
    ".NET 6.0, ASP.NET Core 8.0, C#",
    "React with TypeScript",
    "HTML, CSS, JavaScript",
    "HTML, CSS",
]
ADDED = [".NET 6.0", "ASP.NET Core 8.0", "C#", "FastAPI", "Advanced Java"]


def _skills_table():
    return sa.table(
        "skills",
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("sub_domain", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )


def upgrade() -> None:
    """No ratings exist yet on any of these — a plain delete-and-reinsert,
    not a rename, since one entry splits into three and two others are
    dropped outright as duplicates of skills that already stand alone."""
    bind = op.get_bind()
    for name in REMOVED:
        bind.execute(sa.text("DELETE FROM skills WHERE name = :name"), {"name": name})

    max_order = bind.execute(
        sa.text("SELECT COALESCE(MAX(sort_order), 0) FROM skills WHERE category = 'tech'")
    ).scalar()
    bind.execute(
        _skills_table().insert(),
        [
            {"name": name, "category": "tech", "sub_domain": None,
             "sort_order": max_order + i + 1, "is_active": True}
            for i, name in enumerate(ADDED)
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    for name in ADDED:
        bind.execute(sa.text("DELETE FROM skills WHERE name = :name"), {"name": name})

    max_order = bind.execute(
        sa.text("SELECT COALESCE(MAX(sort_order), 0) FROM skills WHERE category = 'tech'")
    ).scalar()
    bind.execute(
        _skills_table().insert(),
        [
            {"name": name, "category": "tech", "sub_domain": None,
             "sort_order": max_order + i + 1, "is_active": True}
            for i, name in enumerate(REMOVED)
        ],
    )
