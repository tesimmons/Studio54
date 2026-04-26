"""Add retry state columns to albums and download_queue

Revision ID: 20260426_0100_061
Revises: 20260419_0300_060
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20260426_0100_061'
down_revision = '20260419_0300_060'
branch_labels = None
depends_on = None


def upgrade():
    # Add new enum value — IF NOT EXISTS prevents failure on re-run
    op.execute("ALTER TYPE download_event_type ADD VALUE IF NOT EXISTS 'retry_scheduled'")

    # albums: persistent retry tracking
    op.add_column('albums', sa.Column('retry_enabled', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('albums', sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('albums', sa.Column('download_retry_count', sa.Integer(), nullable=False, server_default='0'))

    # download_queue: un-tried alternate NZBs from the original search
    op.add_column('download_queue', sa.Column('pending_alternates', JSONB(), nullable=True))


def downgrade():
    op.drop_column('download_queue', 'pending_alternates')
    op.drop_column('albums', 'download_retry_count')
    op.drop_column('albums', 'next_retry_at')
    op.drop_column('albums', 'retry_enabled')
