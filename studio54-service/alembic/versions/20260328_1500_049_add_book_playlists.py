"""Add book_playlists and book_playlist_chapters tables

Revision ID: 20260328_1500_049
Revises: 20260328_1400_048
Create Date: 2026-03-28 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260328_1500_049'
down_revision = '20260328_1400_048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'book_playlists',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('series_id', UUID(as_uuid=True),
                  sa.ForeignKey('series.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )

    op.create_table(
        'book_playlist_chapters',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('playlist_id', UUID(as_uuid=True),
                  sa.ForeignKey('book_playlists.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('chapter_id', UUID(as_uuid=True),
                  sa.ForeignKey('chapters.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('book_position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('playlist_id', 'chapter_id',
                            name='uq_book_playlist_chapter'),
    )
    op.create_index('ix_book_playlist_chapters_playlist_position',
                    'book_playlist_chapters', ['playlist_id', 'position'])


def downgrade() -> None:
    op.drop_index('ix_book_playlist_chapters_playlist_position')
    op.drop_table('book_playlist_chapters')
    op.drop_table('book_playlists')
