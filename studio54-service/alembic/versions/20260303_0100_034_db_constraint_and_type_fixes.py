"""DB constraint and type fixes

Revision ID: 20260303_0100_034
Revises: 20260223_0100_033
Create Date: 2026-03-03

Fixes:
1. download_queue.indexer_id: Add ON DELETE SET NULL, make nullable
2. download_queue.download_client_id: Add ON DELETE SET NULL, make nullable
3. download_queue: Add artist_id FK with backfill from albums
4. media_management_config: Fix timestamp columns from String to DateTime
5. download_history: Drop unused tracked_download_id column
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260303_0100_034'
down_revision = '20260223_0100_033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Fix download_queue.indexer_id: add ON DELETE SET NULL, make nullable
    op.drop_constraint('download_queue_indexer_id_fkey', 'download_queue', type_='foreignkey')
    op.alter_column('download_queue', 'indexer_id', nullable=True)
    op.create_foreign_key(
        'download_queue_indexer_id_fkey', 'download_queue',
        'indexers', ['indexer_id'], ['id'], ondelete='SET NULL'
    )

    # 2. Fix download_queue.download_client_id: add ON DELETE SET NULL, make nullable
    op.drop_constraint('download_queue_download_client_id_fkey', 'download_queue', type_='foreignkey')
    op.alter_column('download_queue', 'download_client_id', nullable=True)
    op.create_foreign_key(
        'download_queue_download_client_id_fkey', 'download_queue',
        'download_clients', ['download_client_id'], ['id'], ondelete='SET NULL'
    )

    # 3. Add artist_id to download_queue with FK and index
    op.add_column('download_queue', sa.Column('artist_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'download_queue_artist_id_fkey', 'download_queue',
        'artists', ['artist_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_download_queue_artist_id', 'download_queue', ['artist_id'])

    # Backfill artist_id from album->artist relationship
    op.execute("""
        UPDATE download_queue dq
        SET artist_id = a.artist_id
        FROM albums a
        WHERE dq.album_id = a.id
          AND dq.artist_id IS NULL
    """)

    # 4. Fix media_management_config timestamp types: String -> DateTime
    op.alter_column(
        'media_management_config', 'created_at',
        type_=sa.DateTime(timezone=True),
        postgresql_using='created_at::timestamptz',
        nullable=False
    )
    op.alter_column(
        'media_management_config', 'updated_at',
        type_=sa.DateTime(timezone=True),
        postgresql_using='updated_at::timestamptz',
        nullable=False
    )

    # 5. Drop unused tracked_download_id from download_history
    op.drop_constraint('download_history_tracked_download_id_fkey', 'download_history', type_='foreignkey')
    op.drop_column('download_history', 'tracked_download_id')


def downgrade() -> None:
    # 5. Re-add tracked_download_id to download_history
    op.add_column('download_history', sa.Column(
        'tracked_download_id', UUID(as_uuid=True), nullable=True
    ))
    op.create_foreign_key(
        'download_history_tracked_download_id_fkey', 'download_history',
        'tracked_downloads', ['tracked_download_id'], ['id'], ondelete='SET NULL'
    )

    # 4. Revert media_management_config timestamps back to String
    op.alter_column(
        'media_management_config', 'updated_at',
        type_=sa.String(),
        postgresql_using="to_char(updated_at, 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')",
        nullable=False
    )
    op.alter_column(
        'media_management_config', 'created_at',
        type_=sa.String(),
        postgresql_using="to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')",
        nullable=False
    )

    # 3. Drop artist_id from download_queue
    op.drop_index('ix_download_queue_artist_id', 'download_queue')
    op.drop_constraint('download_queue_artist_id_fkey', 'download_queue', type_='foreignkey')
    op.drop_column('download_queue', 'artist_id')

    # 2. Revert download_queue.download_client_id: remove ON DELETE SET NULL, make NOT NULL
    op.drop_constraint('download_queue_download_client_id_fkey', 'download_queue', type_='foreignkey')
    op.alter_column('download_queue', 'download_client_id', nullable=False)
    op.create_foreign_key(
        'download_queue_download_client_id_fkey', 'download_queue',
        'download_clients', ['download_client_id'], ['id']
    )

    # 1. Revert download_queue.indexer_id: remove ON DELETE SET NULL, make NOT NULL
    op.drop_constraint('download_queue_indexer_id_fkey', 'download_queue', type_='foreignkey')
    op.alter_column('download_queue', 'indexer_id', nullable=False)
    op.create_foreign_key(
        'download_queue_indexer_id_fkey', 'download_queue',
        'indexers', ['indexer_id'], ['id']
    )
