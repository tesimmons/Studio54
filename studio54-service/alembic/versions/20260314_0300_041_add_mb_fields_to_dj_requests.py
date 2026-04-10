"""Add musicbrainz fields to dj_requests

Revision ID: 20260314_0300_041
Revises: 20260314_0200_040
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '20260314_0300_041'
down_revision = '20260314_0200_040'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dj_requests', sa.Column('musicbrainz_id', sa.String(36), nullable=True))
    op.add_column('dj_requests', sa.Column('musicbrainz_name', sa.String(500), nullable=True))
    op.add_column('dj_requests', sa.Column('track_name', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('dj_requests', 'track_name')
    op.drop_column('dj_requests', 'musicbrainz_name')
    op.drop_column('dj_requests', 'musicbrainz_id')
