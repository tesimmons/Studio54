"""add_media_management_config

Revision ID: 011
Revises: 010
Create Date: 2026-01-03 05:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    """Create media_management_config table."""
    op.create_table(
        'media_management_config',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),

        # File naming templates
        sa.Column('artist_folder_template', sa.Text, nullable=False, server_default='{Artist Name}'),
        sa.Column('album_folder_template', sa.Text, nullable=False, server_default='{Album Title} ({Release Year})'),
        sa.Column('track_file_template', sa.Text, nullable=False, server_default='{Artist Name} - {Album Title} - {track:00} - {Track Title}'),
        sa.Column('multi_disc_track_template', sa.Text, nullable=False, server_default='{disc:0}-{track:00} - {Track Title}'),

        # File organization settings
        sa.Column('music_library_path', sa.Text, nullable=False, server_default='/music'),
        sa.Column('colon_replacement', sa.String(20), nullable=False, server_default='smart'),
        sa.Column('rename_tracks', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('replace_existing_files', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('use_hardlinks', sa.Boolean, nullable=False, server_default='false'),

        # Recycle bin settings
        sa.Column('recycle_bin_path', sa.Text, nullable=True),
        sa.Column('recycle_bin_cleanup_days', sa.Integer, nullable=False, server_default='30'),
        sa.Column('auto_cleanup_recycle_bin', sa.Boolean, nullable=False, server_default='true'),

        # Import behavior
        sa.Column('minimum_file_size_mb', sa.Integer, nullable=False, server_default='1'),
        sa.Column('skip_free_space_check', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('minimum_free_space_mb', sa.Integer, nullable=False, server_default='100'),
        sa.Column('import_extra_files', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('extra_file_extensions', sa.Text, nullable=False, server_default='jpg,png,jpeg,lrc,txt,pdf,log,cue'),

        # Folder management
        sa.Column('create_empty_artist_folders', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('delete_empty_folders', sa.Boolean, nullable=False, server_default='true'),

        # Unix permissions
        sa.Column('set_permissions_linux', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('chmod_folder', sa.String(10), nullable=True, server_default='755'),
        sa.Column('chmod_file', sa.String(10), nullable=True, server_default='644'),
        sa.Column('chown_group', sa.String(50), nullable=True),

        # Quality preferences
        sa.Column('upgrade_allowed', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('prefer_lossless', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('minimum_quality_score', sa.Integer, nullable=False, server_default='128'),

        # Timestamps
        sa.Column('created_at', sa.String, nullable=False),
        sa.Column('updated_at', sa.String, nullable=False),
    )


def downgrade():
    """Drop media_management_config table."""
    op.drop_table('media_management_config')
