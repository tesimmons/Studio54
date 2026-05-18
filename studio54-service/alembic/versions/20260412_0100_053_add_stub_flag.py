"""add is_stub flag to artists, albums, tracks

Revision ID: 20260412_0100_053
Revises: 20260411_1200_052
Create Date: 2026-04-12 01:00:00.000000

Marks synthetic stub records created from file metadata when no MusicBrainz
match is available. Allows future re-resolution runs to retry stub records
and prevents stubs from polluting real artist/album lookups.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260412_0100_053'
down_revision = '20260411_1200_052'
branch_labels = None
depends_on = None


def upgrade():
    for table in ['artists', 'albums', 'tracks']:
        op.add_column(
            table,
            sa.Column('is_stub', sa.Boolean(), nullable=False, server_default='false')
        )


def downgrade():
    for table in ['artists', 'albums', 'tracks']:
        op.drop_column(table, 'is_stub')
