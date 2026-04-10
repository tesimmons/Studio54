"""Add unlinked_files table for tracking files that couldn't be linked to tracks

Revision ID: 20260307_0200_036
Revises: 20260307_0100_035
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260307_0200_036'
down_revision = '20260307_0100_035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'unlinked_files',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('library_file_id', UUID(as_uuid=True), sa.ForeignKey('library_files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('artist', sa.Text(), nullable=True),
        sa.Column('album', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('musicbrainz_trackid', sa.String(36), nullable=True),
        sa.Column('reason', sa.String(100), nullable=False),
        sa.Column('reason_detail', sa.Text(), nullable=True),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('file_organization_jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('library_file_id', name='uq_unlinked_files_library_file_id'),
    )
    op.create_index('idx_unlinked_files_reason', 'unlinked_files', ['reason'])
    op.create_index('idx_unlinked_files_library_file', 'unlinked_files', ['library_file_id'])
    op.create_index('idx_unlinked_files_resolved', 'unlinked_files', ['resolved_at'])


def downgrade() -> None:
    op.drop_index('idx_unlinked_files_resolved', table_name='unlinked_files')
    op.drop_index('idx_unlinked_files_library_file', table_name='unlinked_files')
    op.drop_index('idx_unlinked_files_reason', table_name='unlinked_files')
    op.drop_table('unlinked_files')
