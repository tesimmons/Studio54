"""Add credit_name column to books table

Revision ID: 20260329_0100_050
Revises: 20260328_1500_049
Create Date: 2026-03-29 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260329_0100_050'
down_revision = '20260328_1500_049'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('books', sa.Column('credit_name', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('books', 'credit_name')
