"""add_conversation_pinned_content

Revision ID: bbba8c5e7d65
Revises: b2c3d4e5f6a7
Create Date: 2026-01-26 06:24:09.121135

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bbba8c5e7d65'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create conversation_pinned_content table for context caching."""
    op.create_table('conversation_pinned_content',
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('file_paths', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('file_hashes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('total_tokens', sa.Integer(), nullable=False),
        sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('conversation_pinned_content_conversation_id_fkey'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('conversation_pinned_content_pkey')),
        sa.UniqueConstraint('conversation_id', name='uq_pinned_content_conversation')
    )
    op.create_index(
        op.f('conversation_pinned_content_conversation_id_idx'),
        'conversation_pinned_content',
        ['conversation_id'],
        unique=False,
    )


def downgrade() -> None:
    """Drop conversation_pinned_content table."""
    op.drop_index(
        op.f('conversation_pinned_content_conversation_id_idx'),
        table_name='conversation_pinned_content',
    )
    op.drop_table('conversation_pinned_content')
