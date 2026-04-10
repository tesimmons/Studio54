"""Add partial indexes on MBID columns for link_files performance

Revision ID: 20260307_0100_035
Revises: 20260303_0100_034
Create Date: 2026-03-07

Adds partial indexes on tracks.musicbrainz_id and library_files.musicbrainz_trackid
to speed up link_files_task bulk JOIN/UPDATE operations.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20260307_0100_035'
down_revision = '20260303_0100_034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'ix_tracks_musicbrainz_id',
        'tracks',
        ['musicbrainz_id'],
        postgresql_where='musicbrainz_id IS NOT NULL',
    )
    op.create_index(
        'ix_library_files_musicbrainz_trackid',
        'library_files',
        ['musicbrainz_trackid'],
        postgresql_where='musicbrainz_trackid IS NOT NULL',
    )


def downgrade() -> None:
    op.drop_index('ix_library_files_musicbrainz_trackid', table_name='library_files')
    op.drop_index('ix_tracks_musicbrainz_id', table_name='tracks')
