"""add_single_count_to_artists

Revision ID: 014
Revises: 013
Create Date: 2026-01-04 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None

def upgrade():
    """Add single_count column to artists table."""
    op.add_column(
        'artists',
        sa.Column('single_count', sa.Integer, nullable=False, server_default='0')
    )

def downgrade():
    """Remove single_count column from artists table."""
    op.drop_column('artists', 'single_count')
