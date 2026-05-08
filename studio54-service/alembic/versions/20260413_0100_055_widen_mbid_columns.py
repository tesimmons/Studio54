"""Widen musicbrainz_id columns on albums and tracks to VARCHAR(100)

Revision ID: 20260413_0100_055
Revises: 20260412_0200_054
Create Date: 2026-04-13

local-{uuid4()} stubs are 42 chars (6 + 1 + 36), which exceeds the original
VARCHAR(36) constraint and caused StringDataRightTruncation errors during
Phase 5 stub creation. Artists already use VARCHAR(100); aligning albums and
tracks to the same width.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260413_0100_055'
down_revision = '20260412_0200_054'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('albums', 'musicbrainz_id',
                    existing_type=sa.String(36),
                    type_=sa.String(100),
                    existing_nullable=False)
    op.alter_column('tracks', 'musicbrainz_id',
                    existing_type=sa.String(36),
                    type_=sa.String(100),
                    existing_nullable=True)


def downgrade():
    op.alter_column('tracks', 'musicbrainz_id',
                    existing_type=sa.String(100),
                    type_=sa.String(36),
                    existing_nullable=True)
    op.alter_column('albums', 'musicbrainz_id',
                    existing_type=sa.String(100),
                    type_=sa.String(36),
                    existing_nullable=False)
