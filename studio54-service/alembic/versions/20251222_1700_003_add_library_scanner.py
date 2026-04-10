"""Add library scanner tables

Revision ID: 003
Revises: 002
Create Date: 2025-12-22 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create library_paths table
    op.create_table('library_paths',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('total_files', sa.Integer(), nullable=True),
        sa.Column('total_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('last_scan_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_scan_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path')
    )
    op.create_index(op.f('ix_library_paths_path'), 'library_paths', ['path'], unique=True)

    # Create library_files table
    op.create_table('library_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('library_path_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('file_name', sa.Text(), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('file_modified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('format', sa.String(length=20), nullable=True),
        sa.Column('bitrate_kbps', sa.Integer(), nullable=True),
        sa.Column('sample_rate_hz', sa.Integer(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('artist', sa.Text(), nullable=True),
        sa.Column('album', sa.Text(), nullable=True),
        sa.Column('album_artist', sa.Text(), nullable=True),
        sa.Column('track_number', sa.Integer(), nullable=True),
        sa.Column('disc_number', sa.Integer(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('genre', sa.Text(), nullable=True),
        sa.Column('musicbrainz_trackid', sa.String(length=36), nullable=True),
        sa.Column('musicbrainz_albumid', sa.String(length=36), nullable=True),
        sa.Column('musicbrainz_artistid', sa.String(length=36), nullable=True),
        sa.Column('musicbrainz_releasegroupid', sa.String(length=36), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('has_embedded_artwork', sa.Boolean(), nullable=True),
        sa.Column('album_art_fetched', sa.Boolean(), nullable=True),
        sa.Column('album_art_url', sa.Text(), nullable=True),
        sa.Column('artist_image_fetched', sa.Boolean(), nullable=True),
        sa.Column('artist_image_url', sa.Text(), nullable=True),
        sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['library_path_id'], ['library_paths.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_path')
    )
    op.create_index(op.f('ix_library_files_album'), 'library_files', ['album'], unique=False)
    op.create_index(op.f('ix_library_files_artist'), 'library_files', ['artist'], unique=False)
    op.create_index(op.f('ix_library_files_file_name'), 'library_files', ['file_name'], unique=False)
    op.create_index(op.f('ix_library_files_file_path'), 'library_files', ['file_path'], unique=True)
    op.create_index(op.f('ix_library_files_format'), 'library_files', ['format'], unique=False)
    op.create_index(op.f('ix_library_files_genre'), 'library_files', ['genre'], unique=False)
    op.create_index(op.f('ix_library_files_library_path_id'), 'library_files', ['library_path_id'], unique=False)
    op.create_index(op.f('ix_library_files_title'), 'library_files', ['title'], unique=False)
    op.create_index(op.f('ix_library_files_year'), 'library_files', ['year'], unique=False)
    op.create_index('idx_library_artist_album', 'library_files', ['artist', 'album'], unique=False)
    op.create_index('idx_library_musicbrainz_album', 'library_files', ['musicbrainz_albumid'], unique=False)
    op.create_index('idx_library_musicbrainz_artist', 'library_files', ['musicbrainz_artistid'], unique=False)

    # Create scan_jobs table
    op.create_table('scan_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('library_path_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('celery_task_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('files_scanned', sa.Integer(), nullable=True),
        sa.Column('files_added', sa.Integer(), nullable=True),
        sa.Column('files_updated', sa.Integer(), nullable=True),
        sa.Column('files_skipped', sa.Integer(), nullable=True),
        sa.Column('files_failed', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['library_path_id'], ['library_paths.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('celery_task_id')
    )
    op.create_index(op.f('ix_scan_jobs_celery_task_id'), 'scan_jobs', ['celery_task_id'], unique=True)
    op.create_index(op.f('ix_scan_jobs_library_path_id'), 'scan_jobs', ['library_path_id'], unique=False)
    op.create_index(op.f('ix_scan_jobs_status'), 'scan_jobs', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scan_jobs_status'), table_name='scan_jobs')
    op.drop_index(op.f('ix_scan_jobs_library_path_id'), table_name='scan_jobs')
    op.drop_index(op.f('ix_scan_jobs_celery_task_id'), table_name='scan_jobs')
    op.drop_table('scan_jobs')

    op.drop_index('idx_library_musicbrainz_artist', table_name='library_files')
    op.drop_index('idx_library_musicbrainz_album', table_name='library_files')
    op.drop_index('idx_library_artist_album', table_name='library_files')
    op.drop_index(op.f('ix_library_files_year'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_title'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_library_path_id'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_genre'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_format'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_file_path'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_file_name'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_artist'), table_name='library_files')
    op.drop_index(op.f('ix_library_files_album'), table_name='library_files')
    op.drop_table('library_files')

    op.drop_index(op.f('ix_library_paths_path'), table_name='library_paths')
    op.drop_table('library_paths')
