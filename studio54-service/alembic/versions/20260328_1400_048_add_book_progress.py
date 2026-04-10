"""Add book_progress table for audiobook resume playback

Revision ID: 20260328_1400_048
Revises: 20260323_0200_047
Create Date: 2026-03-28 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260328_1400_048'
down_revision = '20260323_0200_047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'book_progress',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('book_id', UUID(as_uuid=True),
                  sa.ForeignKey('books.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('chapter_id', UUID(as_uuid=True),
                  sa.ForeignKey('chapters.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('position_ms', sa.Integer(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('completed', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('user_id', 'book_id', name='uq_book_progress_user_book'),
    )
    op.create_index('ix_book_progress_user_book', 'book_progress',
                    ['user_id', 'book_id'])


def downgrade() -> None:
    op.drop_index('ix_book_progress_user_book')
    op.drop_table('book_progress')
