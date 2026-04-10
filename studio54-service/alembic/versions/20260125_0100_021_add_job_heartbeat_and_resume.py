"""Add heartbeat and resumability columns to file_organization_jobs

Revision ID: 20260125_0100_021
Revises: 20260119_0100_020
Create Date: 2026-01-25

Adds columns for:
- Heartbeat tracking (stall detection)
- Current file tracking (debugging)
- Resumability support (pick up where left off)
- Better error tracking
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '20260125_0100_021'
down_revision = '20260119_0100_020'
branch_labels = None
depends_on = None


def upgrade():
    # Heartbeat for stall detection
    op.add_column('file_organization_jobs',
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Last heartbeat timestamp for stall detection'))

    # Current processing state (for debugging)
    op.add_column('file_organization_jobs',
        sa.Column('current_file_path', sa.Text(), nullable=True,
                  comment='Currently processing file path'))

    op.add_column('file_organization_jobs',
        sa.Column('current_file_index', sa.Integer(), nullable=True, server_default='0',
                  comment='Current index in file list'))

    op.add_column('file_organization_jobs',
        sa.Column('last_processed_file_id', UUID(as_uuid=True), nullable=True,
                  comment='Last successfully processed file ID for resumability'))

    # Better error tracking
    op.add_column('file_organization_jobs',
        sa.Column('last_error_file', sa.Text(), nullable=True,
                  comment='File path that caused the last error'))

    op.add_column('file_organization_jobs',
        sa.Column('last_error_details', sa.Text(), nullable=True,
                  comment='Full error details and traceback'))

    # Index for stall detection queries
    op.create_index('idx_file_org_jobs_heartbeat', 'file_organization_jobs',
                    ['last_heartbeat_at'],
                    postgresql_where=sa.text("status = 'running'"))


def downgrade():
    op.drop_index('idx_file_org_jobs_heartbeat', 'file_organization_jobs')
    op.drop_column('file_organization_jobs', 'last_error_details')
    op.drop_column('file_organization_jobs', 'last_error_file')
    op.drop_column('file_organization_jobs', 'last_processed_file_id')
    op.drop_column('file_organization_jobs', 'current_file_index')
    op.drop_column('file_organization_jobs', 'current_file_path')
    op.drop_column('file_organization_jobs', 'last_heartbeat_at')
