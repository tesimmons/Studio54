"""Add current_action column to scan_jobs

Revision ID: 20260125_0300_023
Revises: 20260125_0200_022
Create Date: 2026-01-25 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260125_0300_023'
down_revision = '20260125_0200_022'
branch_labels = None
depends_on = None


def upgrade():
    """Add current_action column for progress display during scans"""
    op.add_column('scan_jobs', sa.Column('current_action', sa.Text(), nullable=True))


def downgrade():
    """Remove current_action column"""
    op.drop_column('scan_jobs', 'current_action')
