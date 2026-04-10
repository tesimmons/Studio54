"""Add scheduled_jobs table

Revision ID: 20260315_0100_042
Revises: 20260314_0300_041
Create Date: 2026-03-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = '20260315_0100_042'
down_revision = '20260314_0300_041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'scheduled_jobs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('task_key', sa.String(255), nullable=False),
        sa.Column('frequency', sa.String(50), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='true'),
        sa.Column('run_at_hour', sa.Integer(), server_default='2'),
        sa.Column('day_of_week', sa.Integer(), nullable=True),
        sa.Column('day_of_month', sa.Integer(), nullable=True),
        sa.Column('task_params', sa.JSON(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_job_id', UUID(as_uuid=True), nullable=True),
        sa.Column('last_status', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('idx_scheduled_jobs_enabled_next_run', 'scheduled_jobs', ['enabled', 'next_run_at'])


def downgrade() -> None:
    op.drop_index('idx_scheduled_jobs_enabled_next_run')
    op.drop_table('scheduled_jobs')
