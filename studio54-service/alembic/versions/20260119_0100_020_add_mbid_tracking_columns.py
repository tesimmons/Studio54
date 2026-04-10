"""Add MBID tracking columns to library_files

Revision ID: 20260119_0100_020
Revises: 20260118_0100_019
Create Date: 2026-01-19

Adds columns to track:
- Whether MBID is stored in file comments (mbid_in_file)
- Whether file has been organized (is_organized)
- Last MBID verification time (mbid_verified_at)
- Organization status (organization_status)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260119_0100_020'
down_revision = '20260118_0100_019'
branch_labels = None
depends_on = None


def upgrade():
    # Add MBID tracking columns to library_files
    op.add_column('library_files',
        sa.Column('mbid_in_file', sa.Boolean(), nullable=True, server_default='false',
                  comment='True if Recording MBID is written to file Comment tag'))

    op.add_column('library_files',
        sa.Column('is_organized', sa.Boolean(), nullable=True, server_default='false',
                  comment='True if file has been organized to correct location'))

    op.add_column('library_files',
        sa.Column('mbid_verified_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Last time MBID was verified in file comment'))

    op.add_column('library_files',
        sa.Column('organization_status', sa.String(50), nullable=True, server_default='unprocessed',
                  comment='Status: unprocessed, validated, needs_rename, needs_move, organized'))

    op.add_column('library_files',
        sa.Column('target_path', sa.Text(), nullable=True,
                  comment='Calculated ideal path based on MBID metadata'))

    op.add_column('library_files',
        sa.Column('last_organization_check', sa.DateTime(timezone=True), nullable=True,
                  comment='Last time organization was checked'))

    # Create indexes for common queries
    op.create_index('idx_library_files_mbid_in_file', 'library_files', ['mbid_in_file'])
    op.create_index('idx_library_files_is_organized', 'library_files', ['is_organized'])
    op.create_index('idx_library_files_org_status', 'library_files', ['organization_status'])


def downgrade():
    # Drop indexes first
    op.drop_index('idx_library_files_org_status', 'library_files')
    op.drop_index('idx_library_files_is_organized', 'library_files')
    op.drop_index('idx_library_files_mbid_in_file', 'library_files')

    # Drop columns
    op.drop_column('library_files', 'last_organization_check')
    op.drop_column('library_files', 'target_path')
    op.drop_column('library_files', 'organization_status')
    op.drop_column('library_files', 'mbid_verified_at')
    op.drop_column('library_files', 'is_organized')
    op.drop_column('library_files', 'mbid_in_file')
