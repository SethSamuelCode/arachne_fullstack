"""add_session_state_compression

Revision ID: c3d4e5f6a7b8
Revises: bbba8c5e7d65
Create Date: 2026-02-11 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'bbba8c5e7d65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add compressed_state and compressed_at_message_id to conversations."""
    op.add_column(
        'conversations',
        sa.Column('compressed_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'conversations',
        sa.Column('compressed_at_message_id', sa.UUID(), nullable=True),
    )


def downgrade() -> None:
    """Remove session state compression columns from conversations."""
    op.drop_column('conversations', 'compressed_at_message_id')
    op.drop_column('conversations', 'compressed_state')
