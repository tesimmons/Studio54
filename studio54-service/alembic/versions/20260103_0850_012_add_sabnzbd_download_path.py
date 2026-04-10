"""add_sabnzbd_download_path

Revision ID: 012
Revises: 011
Create Date: 2026-01-03 08:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    """Add sabnzbd_download_path column to media_management_config table."""
    op.add_column(
        'media_management_config',
        sa.Column('sabnzbd_download_path', sa.Text, nullable=True)
    )


def downgrade():
    """Remove sabnzbd_download_path column from media_management_config table."""
    op.drop_column('media_management_config', 'sabnzbd_download_path')
