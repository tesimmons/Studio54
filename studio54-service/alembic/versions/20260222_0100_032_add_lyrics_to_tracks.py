"""Add lyrics columns to tracks table

Revision ID: 20260222_0100_032
Revises: 20260219_0100_031
Create Date: 2026-02-22

Adds synced_lyrics, plain_lyrics, and lyrics_source columns to tracks table
for caching lyrics fetched from LRCLIB.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260222_0100_032'
down_revision = '20260219_0100_031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tracks', sa.Column('synced_lyrics', sa.Text(), nullable=True))
    op.add_column('tracks', sa.Column('plain_lyrics', sa.Text(), nullable=True))
    op.add_column('tracks', sa.Column('lyrics_source', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('tracks', 'lyrics_source')
    op.drop_column('tracks', 'plain_lyrics')
    op.drop_column('tracks', 'synced_lyrics')
