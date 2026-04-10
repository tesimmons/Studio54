"""add track file path

Revision ID: 010
Revises: 009
Create Date: 2026-01-02 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None

def upgrade():
    """Add file_path column to tracks table for storing actual file locations"""
    op.add_column('tracks', sa.Column('file_path', sa.Text(), nullable=True))

    # Add index for file_path lookups
    op.create_index('ix_tracks_file_path', 'tracks', ['file_path'], unique=False)

def downgrade():
    """Remove file_path column from tracks table"""
    op.drop_index('ix_tracks_file_path', table_name='tracks')
    op.drop_column('tracks', 'file_path')
