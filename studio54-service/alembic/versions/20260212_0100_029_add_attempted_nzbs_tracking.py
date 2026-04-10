"""Add attempted NZBs tracking for duplicate fallback

Revision ID: 20260212_0100_029
Revises: 20260209_0100_028
Create Date: 2026-02-12

Adds:
- download_queue: attempted_nzb_guids (JSON array of previously tried GUIDs)
- download_queue: sab_fail_message (raw SABnzbd fail message)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '20260212_0100_029'
down_revision = '20260209_0100_028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Track which NZB GUIDs have been attempted for each album
    op.add_column('download_queue', sa.Column('attempted_nzb_guids', JSONB, server_default='[]', nullable=False))
    # Store raw SABnzbd fail_message separately from our error_message
    op.add_column('download_queue', sa.Column('sab_fail_message', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('download_queue', 'sab_fail_message')
    op.drop_column('download_queue', 'attempted_nzb_guids')
