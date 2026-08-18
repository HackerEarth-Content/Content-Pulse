"""add jira_missing flag to entry items

Revision ID: 416250145d5e
Revises: 9ed27130dbfa
Create Date: 2026-08-17 16:14:58.850704

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '416250145d5e'
down_revision: Union[str, Sequence[str], None] = '9ed27130dbfa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'entry_items',
        sa.Column('jira_missing', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('entry_items', 'jira_missing')
