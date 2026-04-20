"""Add duplicate_recycle_bin table

Revision ID: 20260419_0300_060
Revises: 20260419_0200_059
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = '20260419_0300_060'
down_revision = '20260419_0200_059'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'duplicate_recycle_bin',
        sa.Column('id', PGUUID(as_uuid=True), primary_key=True),
        sa.Column('musicbrainz_trackid', sa.String(36), nullable=False),
        sa.Column('original_file_path', sa.Text(), nullable=False),
        sa.Column('staging_file_path', sa.Text(), nullable=False),
        sa.Column('kept_file_path', sa.Text(), nullable=False),
        sa.Column('removed_bitrate_kbps', sa.Integer(), nullable=True),
        sa.Column('removed_format', sa.String(20), nullable=True),
        sa.Column('kept_bitrate_kbps', sa.Integer(), nullable=True),
        sa.Column('kept_format', sa.String(20), nullable=True),
        sa.Column('recycled_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(30), nullable=False,
                  server_default='pending_review'),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_dup_recycle_status', 'duplicate_recycle_bin', ['status'])
    op.create_index('ix_dup_recycle_expires', 'duplicate_recycle_bin', ['expires_at'])
    op.create_index('ix_dup_recycle_trackid', 'duplicate_recycle_bin', ['musicbrainz_trackid'])

    # Note: job_type column uses VARCHAR (not a native PostgreSQL enum type),
    # so no ALTER TYPE is needed — the new 'deduplicate' value is accepted automatically.


def downgrade():
    op.drop_table('duplicate_recycle_bin')
