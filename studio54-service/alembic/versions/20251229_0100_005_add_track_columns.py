"""Add missing track columns

Revision ID: 20251229_0100_005
Revises: 20251227_1000_004
Create Date: 2025-12-29 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    """Add missing columns to tracks table"""
    # Add disc_number column (default 1)
    op.add_column('tracks', sa.Column('disc_number', sa.Integer(), nullable=True))

    # Set default value for existing rows
    op.execute("UPDATE tracks SET disc_number = 1 WHERE disc_number IS NULL")

    # Add created_at column
    op.add_column('tracks', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))

    # Set created_at for existing rows to current time
    op.execute(f"UPDATE tracks SET created_at = NOW() WHERE created_at IS NULL")

    # Add updated_at column
    op.add_column('tracks', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    # Set updated_at for existing rows to current time
    op.execute(f"UPDATE tracks SET updated_at = NOW() WHERE updated_at IS NULL")


def downgrade():
    """Remove added columns from tracks table"""
    op.drop_column('tracks', 'updated_at')
    op.drop_column('tracks', 'created_at')
    op.drop_column('tracks', 'disc_number')
