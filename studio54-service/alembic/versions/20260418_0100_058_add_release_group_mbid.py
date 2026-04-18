"""Add release_group_mbid to albums

Revision ID: 20260418_0100_058
Revises: 20260414_0100_057
Create Date: 2026-04-18

Adds release_group_mbid so albums can be re-keyed to a specific release MBID
while retaining a reference back to the parent release group.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260418_0100_058'
down_revision = '20260414_0100_057'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('albums', sa.Column(
        'release_group_mbid', sa.String(36), nullable=True
    ))
    op.create_index('ix_albums_release_group_mbid', 'albums', ['release_group_mbid'])


def downgrade():
    op.drop_index('ix_albums_release_group_mbid', table_name='albums')
    op.drop_column('albums', 'release_group_mbid')
