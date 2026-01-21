"""add default_system_prompt to user

Revision ID: e513c3dd47a1
Revises: d432b2cc3690
Create Date: 2026-01-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e513c3dd47a1'
down_revision: str | None = 'd432b2cc3690'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('default_system_prompt', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'default_system_prompt')
