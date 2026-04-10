"""Add job_state table for resilient job tracking

Revision ID: 007
Revises: 006
Create Date: 2025-12-30 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create job_states table and add relationship columns to existing tables"""

    # Create job_states table
    op.create_table(
        'job_states',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('celery_task_id', sa.String(255), nullable=True),
        sa.Column('worker_id', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('current_step', sa.String(500), nullable=True),
        sa.Column('progress_percent', sa.Float(), nullable=True),
        sa.Column('items_processed', sa.Integer(), nullable=True),
        sa.Column('items_total', sa.Integer(), nullable=True),
        sa.Column('speed_metric', sa.Float(), nullable=True),
        sa.Column('eta_seconds', sa.Integer(), nullable=True),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('checkpoint_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('max_retries', sa.Integer(), nullable=True),
        sa.Column('result_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_traceback', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('album_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('scan_job_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('download_queue_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['album_id'], ['albums.id'], name='fk_job_states_album_id', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['download_queue_id'], ['download_queue.id'], name='fk_job_states_download_queue_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scan_job_id'], ['scan_jobs.id'], name='fk_job_states_scan_job_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_job_states_job_type', 'job_states', ['job_type'], unique=False)
    op.create_index('ix_job_states_entity_id', 'job_states', ['entity_id'], unique=False)
    op.create_index('ix_job_states_celery_task_id', 'job_states', ['celery_task_id'], unique=True)
    op.create_index('ix_job_states_worker_id', 'job_states', ['worker_id'], unique=False)
    op.create_index('ix_job_states_status', 'job_states', ['status'], unique=False)
    op.create_index('ix_job_states_last_heartbeat_at', 'job_states', ['last_heartbeat_at'], unique=False)

    # Add reverse relationship columns to existing tables
    # Albums: current_job_id to track active job
    op.add_column('albums', sa.Column('current_job_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_albums_current_job_id',
        'albums',
        'job_states',
        ['current_job_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # ScanJobs: job_state_id for linking
    op.add_column('scan_jobs', sa.Column('job_state_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_scan_jobs_job_state_id',
        'scan_jobs',
        'job_states',
        ['job_state_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # DownloadQueue: job_state_id for linking
    op.add_column('download_queue', sa.Column('job_state_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_download_queue_job_state_id',
        'download_queue',
        'job_states',
        ['job_state_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove job_states table and relationship columns"""

    # Drop foreign keys and columns from existing tables
    op.drop_constraint('fk_download_queue_job_state_id', 'download_queue', type_='foreignkey')
    op.drop_column('download_queue', 'job_state_id')

    op.drop_constraint('fk_scan_jobs_job_state_id', 'scan_jobs', type_='foreignkey')
    op.drop_column('scan_jobs', 'job_state_id')

    op.drop_constraint('fk_albums_current_job_id', 'albums', type_='foreignkey')
    op.drop_column('albums', 'current_job_id')

    # Drop indexes
    op.drop_index('ix_job_states_last_heartbeat_at', table_name='job_states')
    op.drop_index('ix_job_states_status', table_name='job_states')
    op.drop_index('ix_job_states_worker_id', table_name='job_states')
    op.drop_index('ix_job_states_celery_task_id', table_name='job_states')
    op.drop_index('ix_job_states_entity_id', table_name='job_states')
    op.drop_index('ix_job_states_job_type', table_name='job_states')

    # Drop job_states table
    op.drop_table('job_states')
