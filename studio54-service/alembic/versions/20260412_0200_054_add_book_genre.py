"""add genre column to books

Revision ID: 20260412_0200_054
Revises: 20260412_0100_053
Create Date: 2026-04-12 02:00:00.000000

Stores the primary genre/subject for each audiobook, fetched from
OpenLibrary subjects during metadata refresh.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260412_0200_054'
down_revision = '20260412_0100_053'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('books', sa.Column('genre', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('books', 'genre')
