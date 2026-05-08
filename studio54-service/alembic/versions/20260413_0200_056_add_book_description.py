"""Add description column to books table

Revision ID: 20260413_0200_056
Revises: 20260413_0100_055
Create Date: 2026-04-13

Stores the book synopsis / dust-jacket description fetched from
Hardcover (primary) or OpenLibrary Works endpoint (fallback).
"""
from alembic import op
import sqlalchemy as sa

revision = '20260413_0200_056'
down_revision = '20260413_0100_055'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('books', sa.Column('description', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('books', 'description')
