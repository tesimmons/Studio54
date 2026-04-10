"""Add secondary_types column to albums

Revision ID: 20260310_0100_038
Revises: 20260309_0100_037
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260310_0100_038'
down_revision = '20260309_0100_037'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('albums', sa.Column('secondary_types', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('albums', 'secondary_types')
