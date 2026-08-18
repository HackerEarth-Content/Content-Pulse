"""consolidate duplicate other task type

Revision ID: 9ed27130dbfa
Revises: 2bbdc0a17f9b
Create Date: 2026-08-17 15:50:16.210486

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ed27130dbfa'
down_revision: Union[str, Sequence[str], None] = '2bbdc0a17f9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed had both 'Other' and 'Others' as separate task_types rows, which
    never both matched Jira's single 'Others' picklist option — one of them
    always fell through and got Jira's own default instead. Repoint anything
    on 'Other' to 'Others' and drop the duplicate."""
    bind = op.get_bind()
    other = bind.execute(sa.text("SELECT id FROM task_types WHERE name = 'Other'")).scalar()
    if other is None:
        return
    others = bind.execute(sa.text("SELECT id FROM task_types WHERE name = 'Others'")).scalar()
    if others is None:
        bind.execute(sa.text("UPDATE task_types SET name = 'Others' WHERE id = :id"), {"id": other})
        return
    bind.execute(
        sa.text("UPDATE entry_items SET task_type_id = :others WHERE task_type_id = :other"),
        {"others": others, "other": other},
    )
    bind.execute(sa.text("DELETE FROM task_types WHERE id = :id"), {"id": other})


def downgrade() -> None:
    """Data merge — not reversible."""
    pass
