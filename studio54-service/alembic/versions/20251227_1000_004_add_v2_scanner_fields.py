"""Add V2 scanner fields to scan_jobs

Revision ID: 004_add_v2_scanner_fields
Revises: 20251222_1700_003_add_library_scanner
Create Date: 2025-12-27 10:00:00.000000

This migration adds fields for the V2 scanner enhancements:
- pause_requested: Pause/cancel control
- checkpoint_data: Resume from failure/restart
- skip_statistics: Track skipped files by reason
- elapsed_seconds: Progress time tracking
- estimated_remaining_seconds: Time estimates
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add V2 scanner fields to scan_jobs table"""

    # Add pause_requested boolean (default False)
    op.add_column('scan_jobs', sa.Column('pause_requested', sa.Boolean(), nullable=False, server_default='false'))

    # Add checkpoint_data JSONB (stores: phase, last_batch, files_processed, start_time)
    op.add_column('scan_jobs', sa.Column('checkpoint_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Add skip_statistics JSONB (stores: {resource_fork: N, hidden: N, system: N, etc.})
    op.add_column('scan_jobs', sa.Column('skip_statistics', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Add time tracking fields
    op.add_column('scan_jobs', sa.Column('elapsed_seconds', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('scan_jobs', sa.Column('estimated_remaining_seconds', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    """Remove V2 scanner fields from scan_jobs table"""

    op.drop_column('scan_jobs', 'estimated_remaining_seconds')
    op.drop_column('scan_jobs', 'elapsed_seconds')
    op.drop_column('scan_jobs', 'skip_statistics')
    op.drop_column('scan_jobs', 'checkpoint_data')
    op.drop_column('scan_jobs', 'pause_requested')
