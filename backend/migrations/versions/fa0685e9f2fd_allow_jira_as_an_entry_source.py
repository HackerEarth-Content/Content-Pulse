"""allow jira as an entry source

Revision ID: fa0685e9f2fd
Revises: 52f3183feaec
Create Date: 2026-08-06 13:43:30.031484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa0685e9f2fd'
down_revision: Union[str, Sequence[str], None] = '52f3183feaec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Written by hand: Alembic emits CHECK constraints when a table is first
    created but never notices when one changes, so every edit to an `_enum()`
    in core/orm.py needs a migration like this one.
    """
    op.drop_constraint("ck_source", "daily_entries", type_="check")
    op.create_check_constraint(
        "ck_source", "daily_entries",
        "source IN ('web', 'slack', 'api', 'import', 'jira')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE daily_entries SET source = 'import' WHERE source = 'jira'")
    op.drop_constraint("ck_source", "daily_entries", type_="check")
    op.create_check_constraint(
        "ck_source", "daily_entries",
        "source IN ('web', 'slack', 'api', 'import')",
    )
