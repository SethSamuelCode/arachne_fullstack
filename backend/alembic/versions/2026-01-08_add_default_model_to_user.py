"""add default_model to user

Revision ID: f624d4ee58b2
Revises: e513c3dd47a1
Create Date: 2026-01-08 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f624d4ee58b2'
down_revision: str | None = 'e513c3dd47a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('default_model', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'default_model')
