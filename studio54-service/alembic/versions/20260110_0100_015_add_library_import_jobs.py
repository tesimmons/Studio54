"""Add library import jobs and artist matching tables

Revision ID: 015
Revises: 014
Create Date: 2026-01-10 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create library_import_jobs table
    op.create_table('library_import_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('library_path_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('current_phase', sa.String(length=50), nullable=True),
        sa.Column('progress_percent', sa.Numeric(precision=5, scale=2), nullable=True, server_default='0.0'),
        sa.Column('current_action', sa.String(length=500), nullable=True),
        sa.Column('phase_scanning', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('phase_artist_matching', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('phase_metadata_sync', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('phase_folder_matching', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('phase_track_matching', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('phase_enrichment', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('phase_finalization', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('artists_found', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('artists_matched', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('artists_created', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('artists_pending', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('albums_synced', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('albums_pending', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('tracks_matched', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('tracks_unmatched', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('files_scanned', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('auto_match_artists', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('auto_assign_folders', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('auto_match_tracks', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('confidence_threshold', sa.Integer(), nullable=True, server_default='70'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('warnings', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('estimated_completion', sa.DateTime(timezone=True), nullable=True),
        sa.Column('celery_task_id', sa.String(length=255), nullable=True),
        sa.Column('pause_requested', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('cancel_requested', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['library_path_id'], ['library_paths.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create library_artist_matches table
    op.create_table('library_artist_matches',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('import_job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('library_artist_name', sa.String(length=500), nullable=False),
        sa.Column('file_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('sample_albums', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('sample_file_paths', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('musicbrainz_id', sa.String(length=36), nullable=True),
        sa.Column('confidence_score', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('musicbrainz_suggestions', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('matched_artist_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['import_job_id'], ['library_import_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['matched_artist_id'], ['artists.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('library_artist_matches')
    op.drop_table('library_import_jobs')
