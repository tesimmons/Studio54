"""Add files_removed column to scan_jobs

Revision ID: 20260125_0200_022
Revises: 20260125_0100_021
Create Date: 2026-01-25 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260125_0200_022'
down_revision = '20260125_0100_021'
branch_labels = None
depends_on = None


def upgrade():
    """Add files_removed column to track deleted files during scan"""
    op.add_column('scan_jobs', sa.Column('files_removed', sa.Integer(), nullable=True, server_default='0'))


def downgrade():
    """Remove files_removed column"""
    op.drop_column('scan_jobs', 'files_removed')
