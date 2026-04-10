"""add custom folder path to albums

Revision ID: 009
Revises: 008
Create Date: 2026-01-02 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    """Add custom_folder_path column to albums table"""
    op.add_column('albums', sa.Column('custom_folder_path', sa.Text(), nullable=True))


def downgrade():
    """Remove custom_folder_path column from albums table"""
    op.drop_column('albums', 'custom_folder_path')
