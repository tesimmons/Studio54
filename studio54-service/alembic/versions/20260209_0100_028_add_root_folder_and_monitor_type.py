"""Add root folder and monitor type support

Revision ID: 20260209_0100_028
Revises: 20260203_0100_027
Create Date: 2026-02-09

Adds Lidarr-style workflow support:
- library_paths: is_root_folder, free_space_bytes
- artists: monitor_type
- albums: last_search_time, quality_meets_cutoff (if not already present)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '20260209_0100_028'
down_revision = '20260203_0100_027'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_root_folder and free_space_bytes to library_paths
    op.add_column('library_paths', sa.Column('is_root_folder', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('library_paths', sa.Column('free_space_bytes', sa.BigInteger(), nullable=True))

    # Add monitor_type to artists
    op.add_column('artists', sa.Column('monitor_type', sa.String(30), nullable=False, server_default='all_albums'))

    # Add last_search_time and quality_meets_cutoff to albums if not already present
    # These were referenced in search_tasks.py but may not have been added by migration 027
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('albums')]

    if 'last_search_time' not in existing_columns:
        op.add_column('albums', sa.Column('last_search_time', sa.DateTime(timezone=True), nullable=True))

    if 'quality_meets_cutoff' not in existing_columns:
        op.add_column('albums', sa.Column('quality_meets_cutoff', sa.Boolean(), nullable=False, server_default='true'))


def downgrade():
    # Remove columns in reverse order
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    albums_columns = [c['name'] for c in inspector.get_columns('albums')]
    if 'quality_meets_cutoff' in albums_columns:
        op.drop_column('albums', 'quality_meets_cutoff')
    if 'last_search_time' in albums_columns:
        op.drop_column('albums', 'last_search_time')

    op.drop_column('artists', 'monitor_type')
    op.drop_column('library_paths', 'free_space_bytes')
    op.drop_column('library_paths', 'is_root_folder')
