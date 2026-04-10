"""add_create_folders_on_monitor

Revision ID: 013
Revises: 012
Create Date: 2026-01-03 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    """Add create_folders_on_monitor column to media_management_config table."""
    op.add_column(
        'media_management_config',
        sa.Column('create_folders_on_monitor', sa.Boolean, nullable=False, server_default='true')
    )


def downgrade():
    """Remove create_folders_on_monitor column from media_management_config table."""
    op.drop_column('media_management_config', 'create_folders_on_monitor')
