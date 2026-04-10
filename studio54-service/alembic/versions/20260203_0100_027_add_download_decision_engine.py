"""Add download decision engine support

Revision ID: 20260203_0100_027
Revises: 20260202_0100_026
Create Date: 2026-02-03

Adds Lidarr-style download decision engine support:
- tracked_downloads: Enhanced download tracking with full state machine
- pending_releases: Temporarily rejected releases for retry
- download_history: History of download events (grabbed, imported, failed)
- blacklist: Permanently rejected releases
- Adds last_search_time and quality_meets_cutoff to albums table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM


# revision identifiers, used by Alembic.
revision = '20260203_0100_027'
down_revision = '20260202_0100_026'
branch_labels = None
depends_on = None


def upgrade():
    # Create tracked_download_state enum using raw SQL for reliable IF NOT EXISTS
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tracked_download_state AS ENUM (
                'queued', 'downloading', 'paused', 'import_pending',
                'import_blocked', 'importing', 'imported', 'failed', 'ignored'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create download_event_type enum using raw SQL for reliable IF NOT EXISTS
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE download_event_type AS ENUM (
                'grabbed', 'import_started', 'imported', 'import_failed',
                'download_failed', 'deleted', 'blacklisted'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create tracked_downloads table
    op.create_table(
        'tracked_downloads',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('download_client_id', UUID(as_uuid=True), sa.ForeignKey('download_clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('download_id', sa.String(255), nullable=False, comment='ID in the download client (e.g., SABnzbd NZO ID)'),

        sa.Column('album_id', UUID(as_uuid=True), sa.ForeignKey('albums.id', ondelete='CASCADE'), nullable=True),
        sa.Column('artist_id', UUID(as_uuid=True), sa.ForeignKey('artists.id', ondelete='CASCADE'), nullable=True),
        sa.Column('indexer_id', UUID(as_uuid=True), sa.ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True),

        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('output_path', sa.String(1000), nullable=True, comment='Path where download will be placed'),
        sa.Column('state', ENUM(
            'queued', 'downloading', 'paused', 'import_pending',
            'import_blocked', 'importing', 'imported', 'failed', 'ignored',
            name='tracked_download_state', create_type=False
        ), nullable=False, server_default='queued'),

        # Release info (cached from indexer search)
        sa.Column('release_guid', sa.String(255), nullable=True, comment='GUID from indexer'),
        sa.Column('release_quality', sa.String(50), nullable=True, comment='Detected quality (FLAC, MP3-320, etc.)'),
        sa.Column('release_indexer', sa.String(100), nullable=True, comment='Indexer name'),

        # Progress tracking
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('downloaded_bytes', sa.BigInteger(), server_default='0'),
        sa.Column('progress_percent', sa.Float(), server_default='0'),
        sa.Column('eta_seconds', sa.Integer(), nullable=True),

        # Timestamps
        sa.Column('grabbed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),

        # Error handling
        sa.Column('error_message', sa.String(1000), nullable=True),
        sa.Column('status_messages', JSONB, nullable=True, comment='List of status/warning messages'),

        sa.Index('idx_tracked_downloads_state', 'state'),
        sa.Index('idx_tracked_downloads_album', 'album_id'),
        sa.Index('idx_tracked_downloads_artist', 'artist_id'),
        sa.Index('idx_tracked_downloads_download_id', 'download_id'),
    )

    # Create pending_releases table
    op.create_table(
        'pending_releases',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('album_id', UUID(as_uuid=True), sa.ForeignKey('albums.id', ondelete='CASCADE'), nullable=False),
        sa.Column('artist_id', UUID(as_uuid=True), sa.ForeignKey('artists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('indexer_id', UUID(as_uuid=True), sa.ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True),

        sa.Column('release_guid', sa.String(255), nullable=False),
        sa.Column('release_title', sa.String(500), nullable=False),
        sa.Column('release_data', JSONB, nullable=False, comment='Full ReleaseInfo as JSON'),

        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('retry_after', sa.DateTime(timezone=True), nullable=True, comment='Earliest time to retry this release'),
        sa.Column('rejection_reasons', JSONB, nullable=True, comment='List of rejection reasons'),
        sa.Column('retry_count', sa.Integer(), server_default='0'),

        sa.Index('idx_pending_releases_album', 'album_id'),
        sa.Index('idx_pending_releases_retry', 'retry_after'),
        sa.UniqueConstraint('album_id', 'release_guid', name='uq_pending_releases_album_guid'),
    )

    # Create download_history table
    op.create_table(
        'download_history',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('album_id', UUID(as_uuid=True), sa.ForeignKey('albums.id', ondelete='SET NULL'), nullable=True),
        sa.Column('artist_id', UUID(as_uuid=True), sa.ForeignKey('artists.id', ondelete='SET NULL'), nullable=True),
        sa.Column('indexer_id', UUID(as_uuid=True), sa.ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('download_client_id', UUID(as_uuid=True), sa.ForeignKey('download_clients.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tracked_download_id', UUID(as_uuid=True), sa.ForeignKey('tracked_downloads.id', ondelete='SET NULL'), nullable=True),

        sa.Column('release_guid', sa.String(255), nullable=True),
        sa.Column('release_title', sa.String(500), nullable=True),

        sa.Column('event_type', ENUM(
            'grabbed', 'import_started', 'imported', 'import_failed',
            'download_failed', 'deleted', 'blacklisted',
            name='download_event_type', create_type=False
        ), nullable=False),
        sa.Column('quality', sa.String(50), nullable=True),
        sa.Column('source', sa.String(100), nullable=True, comment='Source indexer or manual'),

        sa.Column('message', sa.String(1000), nullable=True),
        sa.Column('data', JSONB, nullable=True, comment='Additional event data'),

        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.Index('idx_download_history_album', 'album_id'),
        sa.Index('idx_download_history_artist', 'artist_id'),
        sa.Index('idx_download_history_event', 'event_type'),
        sa.Index('idx_download_history_occurred', 'occurred_at'),
    )

    # Create blacklist table
    op.create_table(
        'blacklist',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('album_id', UUID(as_uuid=True), sa.ForeignKey('albums.id', ondelete='CASCADE'), nullable=True),
        sa.Column('artist_id', UUID(as_uuid=True), sa.ForeignKey('artists.id', ondelete='CASCADE'), nullable=True),
        sa.Column('indexer_id', UUID(as_uuid=True), sa.ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True),

        sa.Column('release_guid', sa.String(255), nullable=False),
        sa.Column('release_title', sa.String(500), nullable=True),

        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('source_title', sa.String(500), nullable=True, comment='Original title from indexer'),

        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.Index('idx_blacklist_album', 'album_id'),
        sa.Index('idx_blacklist_artist', 'artist_id'),
        sa.Index('idx_blacklist_guid', 'release_guid'),
    )

    # Add columns to albums table
    op.add_column('albums',
        sa.Column('last_search_time', sa.DateTime(timezone=True), nullable=True,
                  comment='Last time this album was searched on indexers'))

    op.add_column('albums',
        sa.Column('quality_meets_cutoff', sa.Boolean(), server_default='false', nullable=False,
                  comment='Whether current quality meets the cutoff from quality profile'))

    # Add index for wanted album searches
    op.create_index(
        'idx_albums_wanted_search',
        'albums',
        ['status', 'monitored', 'last_search_time'],
        postgresql_where=sa.text("status = 'WANTED' AND monitored = true")
    )


def downgrade():
    # Drop index
    op.drop_index('idx_albums_wanted_search', 'albums')

    # Drop columns from albums
    op.drop_column('albums', 'quality_meets_cutoff')
    op.drop_column('albums', 'last_search_time')

    # Drop tables
    op.drop_table('blacklist')
    op.drop_table('download_history')
    op.drop_table('pending_releases')
    op.drop_table('tracked_downloads')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS download_event_type')
    op.execute('DROP TYPE IF EXISTS tracked_download_state')
