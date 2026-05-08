"""Add is_stub column to authors table

Revision ID: 20260414_0100_057
Revises: 20260413_0200_056
Create Date: 2026-04-14

The bulk-move-author endpoint creates stub Author rows with is_stub=True
when the target author doesn't exist in the DB. The column existed on
artists/albums/tracks (migration 053) but was missing from authors.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260414_0100_057'
down_revision = '20260413_0200_056'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('authors', sa.Column(
        'is_stub', sa.Boolean(), nullable=False, server_default='false'
    ))


def downgrade():
    op.drop_column('authors', 'is_stub')
