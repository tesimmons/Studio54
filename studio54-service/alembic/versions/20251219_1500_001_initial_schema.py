"""Initial schema - Studio54 database tables

Revision ID: 001
Revises:
Create Date: 2025-12-19 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create quality_profiles table
    op.create_table('quality_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('allowed_formats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('preferred_formats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('min_bitrate', sa.Integer(), nullable=True),
        sa.Column('max_size_mb', sa.Integer(), nullable=True),
        sa.Column('upgrade_enabled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_quality_profiles_name'), 'quality_profiles', ['name'], unique=True)

    # Create artists table
    op.create_table('artists',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('musicbrainz_id', sa.String(length=36), nullable=True),
        sa.Column('is_monitored', sa.Boolean(), nullable=True),
        sa.Column('quality_profile_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('root_folder_path', sa.Text(), nullable=True),
        sa.Column('album_count', sa.Integer(), nullable=True),
        sa.Column('track_count', sa.Integer(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['quality_profile_id'], ['quality_profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('musicbrainz_id')
    )
    op.create_index(op.f('ix_artists_musicbrainz_id'), 'artists', ['musicbrainz_id'], unique=True)
    op.create_index(op.f('ix_artists_name'), 'artists', ['name'], unique=False)

    # Create albums table
    op.create_table('albums',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('artist_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('musicbrainz_id', sa.String(length=36), nullable=True),
        sa.Column('release_mbid', sa.String(length=36), nullable=True),
        sa.Column('release_date', sa.Date(), nullable=True),
        sa.Column('album_type', sa.String(length=50), nullable=True),
        sa.Column('status', sa.Enum('WANTED', 'SEARCHING', 'DOWNLOADING', 'DOWNLOADED', 'FAILED', name='albumstatus'), nullable=False),
        sa.Column('monitored', sa.Boolean(), nullable=True),
        sa.Column('cover_art_url', sa.Text(), nullable=True),
        sa.Column('track_count', sa.Integer(), nullable=True),
        sa.Column('muse_library_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('muse_verified', sa.Boolean(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['artist_id'], ['artists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('musicbrainz_id')
    )
    op.create_index(op.f('ix_albums_artist_id'), 'albums', ['artist_id'], unique=False)
    op.create_index(op.f('ix_albums_musicbrainz_id'), 'albums', ['musicbrainz_id'], unique=True)
    op.create_index(op.f('ix_albums_status'), 'albums', ['status'], unique=False)

    # Create tracks table
    op.create_table('tracks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('album_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('musicbrainz_id', sa.String(length=36), nullable=True),
        sa.Column('track_number', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('has_file', sa.Boolean(), nullable=True),
        sa.Column('muse_file_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tracks_album_id'), 'tracks', ['album_id'], unique=False)

    # Create indexers table
    op.create_table('indexers',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('base_url', sa.Text(), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('indexer_type', sa.String(length=50), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=True),
        sa.Column('categories', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('rate_limit_per_second', sa.Float(), nullable=True),
        sa.Column('success_count', sa.Integer(), nullable=True),
        sa.Column('failure_count', sa.Integer(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_indexers_name'), 'indexers', ['name'], unique=True)

    # Create download_clients table
    op.create_table('download_clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('client_type', sa.String(length=50), nullable=True),
        sa.Column('host', sa.Text(), nullable=False),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('use_ssl', sa.Boolean(), nullable=True),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_download_clients_name'), 'download_clients', ['name'], unique=True)

    # Create download_queue table
    op.create_table('download_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('album_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('indexer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('download_client_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('nzb_title', sa.Text(), nullable=False),
        sa.Column('nzb_guid', sa.Text(), nullable=True),
        sa.Column('nzb_url', sa.Text(), nullable=True),
        sa.Column('sabnzbd_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.Enum('QUEUED', 'DOWNLOADING', 'POST_PROCESSING', 'IMPORTING', 'COMPLETED', 'FAILED', name='downloadstatus'), nullable=False),
        sa.Column('progress_percent', sa.Integer(), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('download_path', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['download_client_id'], ['download_clients.id'], ),
        sa.ForeignKeyConstraint(['indexer_id'], ['indexers.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nzb_guid')
    )
    op.create_index(op.f('ix_download_queue_album_id'), 'download_queue', ['album_id'], unique=False)
    op.create_index(op.f('ix_download_queue_nzb_guid'), 'download_queue', ['nzb_guid'], unique=True)
    op.create_index(op.f('ix_download_queue_sabnzbd_id'), 'download_queue', ['sabnzbd_id'], unique=False)
    op.create_index(op.f('ix_download_queue_status'), 'download_queue', ['status'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign key constraints)
    op.drop_index(op.f('ix_download_queue_status'), table_name='download_queue')
    op.drop_index(op.f('ix_download_queue_sabnzbd_id'), table_name='download_queue')
    op.drop_index(op.f('ix_download_queue_nzb_guid'), table_name='download_queue')
    op.drop_index(op.f('ix_download_queue_album_id'), table_name='download_queue')
    op.drop_table('download_queue')

    op.drop_index(op.f('ix_download_clients_name'), table_name='download_clients')
    op.drop_table('download_clients')

    op.drop_index(op.f('ix_indexers_name'), table_name='indexers')
    op.drop_table('indexers')

    op.drop_index(op.f('ix_tracks_album_id'), table_name='tracks')
    op.drop_table('tracks')

    op.drop_index(op.f('ix_albums_status'), table_name='albums')
    op.drop_index(op.f('ix_albums_musicbrainz_id'), table_name='albums')
    op.drop_index(op.f('ix_albums_artist_id'), table_name='albums')
    op.drop_table('albums')

    op.drop_index(op.f('ix_artists_name'), table_name='artists')
    op.drop_index(op.f('ix_artists_musicbrainz_id'), table_name='artists')
    op.drop_table('artists')

    op.drop_index(op.f('ix_quality_profiles_name'), table_name='quality_profiles')
    op.drop_table('quality_profiles')

    # Drop enums
    op.execute('DROP TYPE downloadstatus')
    op.execute('DROP TYPE albumstatus')
