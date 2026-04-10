"""Add trigram search indexes for fuzzy search

Revision ID: 20260321_0100_043
Revises: 20260315_0100_042
Create Date: 2026-03-21
"""
from alembic import op

# revision identifiers
revision = '20260321_0100_043'
down_revision = '20260315_0100_042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Install extensions for trigram similarity and accent-insensitive search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    # GIN trigram indexes for fuzzy search on key text columns
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artists_name_trgm "
        "ON artists USING gin (LOWER(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_albums_title_trgm "
        "ON albums USING gin (LOWER(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracks_title_trgm "
        "ON tracks USING gin (LOWER(title) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tracks_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_albums_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_artists_name_trgm")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
