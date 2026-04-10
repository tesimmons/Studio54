"""Add playlist_chapters table for audiobook chapters in playlists

Revision ID: 20260330_0100_051
Revises: 20260329_0100_050
Create Date: 2026-03-30 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260330_0100_051'
down_revision = '20260329_0100_050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'playlist_chapters',
        sa.Column('playlist_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('playlists.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('chapter_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chapters.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('playlist_chapters')
