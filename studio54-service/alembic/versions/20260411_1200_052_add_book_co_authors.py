"""Add co_authors column to books table

Revision ID: 20260411_1200_052
Revises: 20260330_0100_051
Create Date: 2026-04-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260411_1200_052'
down_revision = '20260330_0100_051'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Stored as a JSON array of strings, e.g. '["Jane Doe", "John Smith"]'
    op.add_column('books', sa.Column('co_authors', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('books', 'co_authors')
