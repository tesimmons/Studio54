"""Add file management tables and organization tracking

Revision ID: 016
Revises: 015
Create Date: 2026-01-11 01:00:00.000000

This migration adds comprehensive file management capabilities:
- album_metadata_files: Tracks .mbid.json files in album directories
- file_organization_jobs: Background jobs for organizing files
- file_operation_audit: Audit trail for all file operations
- Adds organization tracking columns to library_files and tracks tables
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ========================================
    # Create album_metadata_files table
    # ========================================
    op.create_table('album_metadata_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('album_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('album_mbid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('release_mbid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('release_group_mbid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('track_count', sa.Integer(), nullable=False),
        sa.Column('tracks_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('last_validated', sa.DateTime(timezone=True), nullable=True),
        sa.Column('validation_status', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('album_id')
    )

    # Create indexes for album_metadata_files
    op.create_index('idx_album_metadata_files_path', 'album_metadata_files', ['file_path'])
    op.create_index('idx_album_metadata_files_mbid', 'album_metadata_files', ['album_mbid'])
    op.create_index('idx_album_metadata_files_validation', 'album_metadata_files', ['validation_status'])

    # ========================================
    # Create file_organization_jobs table
    # ========================================
    op.create_table('file_organization_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('job_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('library_path_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('artist_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('album_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('progress_percent', sa.Numeric(precision=5, scale=2), nullable=True, server_default='0.0'),
        sa.Column('current_action', sa.Text(), nullable=True),
        sa.Column('files_total', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('files_processed', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('files_renamed', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('files_moved', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('files_failed', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('directories_created', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('celery_task_id', sa.String(length=255), nullable=True),
        sa.Column('pause_requested', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('cancel_requested', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['library_path_id'], ['library_paths.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['artist_id'], ['artists.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for file_organization_jobs
    op.create_index('idx_file_org_jobs_status', 'file_organization_jobs', ['status'])
    op.create_index('idx_file_org_jobs_type', 'file_organization_jobs', ['job_type'])
    op.create_index('idx_file_org_jobs_artist', 'file_organization_jobs', ['artist_id'])
    op.create_index('idx_file_org_jobs_album', 'file_organization_jobs', ['album_id'])
    op.create_index('idx_file_org_jobs_created', 'file_organization_jobs', ['created_at'])

    # ========================================
    # Create file_operation_audit table
    # ========================================
    op.create_table('file_operation_audit',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('operation_type', sa.String(length=20), nullable=False),
        sa.Column('file_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source_path', sa.Text(), nullable=False),
        sa.Column('destination_path', sa.Text(), nullable=True),
        sa.Column('artist_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('album_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('track_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('recording_mbid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('release_mbid', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('rollback_possible', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('rolled_back', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('backup_path', sa.Text(), nullable=True),
        sa.Column('performed_by', sa.String(length=50), nullable=True, server_default='system'),
        sa.Column('performed_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['artist_id'], ['artists.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['job_id'], ['file_organization_jobs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for file_operation_audit
    op.create_index('idx_file_audit_type', 'file_operation_audit', ['operation_type'])
    op.create_index('idx_file_audit_timestamp', 'file_operation_audit', ['performed_at'])
    op.create_index('idx_file_audit_artist', 'file_operation_audit', ['artist_id'])
    op.create_index('idx_file_audit_album', 'file_operation_audit', ['album_id'])
    op.create_index('idx_file_audit_track', 'file_operation_audit', ['track_id'])
    op.create_index('idx_file_audit_job', 'file_operation_audit', ['job_id'])
    op.create_index('idx_file_audit_rollback', 'file_operation_audit', ['rollback_possible', 'rolled_back'])
    op.create_index('idx_file_audit_success', 'file_operation_audit', ['success'])

    # ========================================
    # Add organization tracking to library_files
    # ========================================
    op.add_column('library_files', sa.Column('is_organized', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('library_files', sa.Column('organization_status', sa.String(length=50), nullable=True, server_default='unprocessed'))
    op.add_column('library_files', sa.Column('target_path', sa.Text(), nullable=True))
    op.add_column('library_files', sa.Column('last_organization_check', sa.DateTime(timezone=True), nullable=True))

    # Create indexes for library_files organization columns
    op.create_index('idx_library_files_org_status', 'library_files', ['organization_status'])
    op.create_index('idx_library_files_organized', 'library_files', ['is_organized'])

    # ========================================
    # Add organization tracking to tracks
    # ========================================
    op.add_column('tracks', sa.Column('file_organized', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('tracks', sa.Column('file_organization_error', sa.Text(), nullable=True))

    # Create index for tracks organization column
    op.create_index('idx_tracks_organized', 'tracks', ['file_organized'])


def downgrade() -> None:
    # Drop indexes for tracks
    op.drop_index('idx_tracks_organized', table_name='tracks')

    # Drop columns from tracks
    op.drop_column('tracks', 'file_organization_error')
    op.drop_column('tracks', 'file_organized')

    # Drop indexes for library_files
    op.drop_index('idx_library_files_organized', table_name='library_files')
    op.drop_index('idx_library_files_org_status', table_name='library_files')

    # Drop columns from library_files
    op.drop_column('library_files', 'last_organization_check')
    op.drop_column('library_files', 'target_path')
    op.drop_column('library_files', 'organization_status')
    op.drop_column('library_files', 'is_organized')

    # Drop indexes for file_operation_audit
    op.drop_index('idx_file_audit_success', table_name='file_operation_audit')
    op.drop_index('idx_file_audit_rollback', table_name='file_operation_audit')
    op.drop_index('idx_file_audit_job', table_name='file_operation_audit')
    op.drop_index('idx_file_audit_track', table_name='file_operation_audit')
    op.drop_index('idx_file_audit_album', table_name='file_operation_audit')
    op.drop_index('idx_file_audit_artist', table_name='file_operation_audit')
    op.drop_index('idx_file_audit_timestamp', table_name='file_operation_audit')
    op.drop_index('idx_file_audit_type', table_name='file_operation_audit')

    # Drop file_operation_audit table
    op.drop_table('file_operation_audit')

    # Drop indexes for file_organization_jobs
    op.drop_index('idx_file_org_jobs_created', table_name='file_organization_jobs')
    op.drop_index('idx_file_org_jobs_album', table_name='file_organization_jobs')
    op.drop_index('idx_file_org_jobs_artist', table_name='file_organization_jobs')
    op.drop_index('idx_file_org_jobs_type', table_name='file_organization_jobs')
    op.drop_index('idx_file_org_jobs_status', table_name='file_organization_jobs')

    # Drop file_organization_jobs table
    op.drop_table('file_organization_jobs')

    # Drop indexes for album_metadata_files
    op.drop_index('idx_album_metadata_files_validation', table_name='album_metadata_files')
    op.drop_index('idx_album_metadata_files_mbid', table_name='album_metadata_files')
    op.drop_index('idx_album_metadata_files_path', table_name='album_metadata_files')

    # Drop album_metadata_files table
    op.drop_table('album_metadata_files')
