"""Add star rating columns for tracks and artists

Revision ID: 20260309_0100_037
Revises: 20260307_0200_036
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260309_0100_037'
down_revision = '20260307_0200_036'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tracks', sa.Column('rating', sa.Integer(), nullable=True))
    op.add_column('artists', sa.Column('rating_override', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('artists', 'rating_override')
    op.drop_column('tracks', 'rating')
