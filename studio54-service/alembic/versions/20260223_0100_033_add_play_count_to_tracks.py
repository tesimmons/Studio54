"""Add play_count and last_played_at to tracks table

Revision ID: 20260223_0100_033
Revises: 20260222_0100_032
Create Date: 2026-02-23

Adds play_count (integer, default 0) and last_played_at (timestamptz, nullable)
columns to the tracks table for tracking playback statistics.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260223_0100_033'
down_revision = '20260222_0100_032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tracks', sa.Column('play_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('tracks', sa.Column('last_played_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('tracks', 'last_played_at')
    op.drop_column('tracks', 'play_count')
