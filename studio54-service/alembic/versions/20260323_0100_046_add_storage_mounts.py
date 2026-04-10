"""Add storage_mounts table for dynamic volume mount management

Revision ID: 20260323_0100_046
Revises: 20260322_0200_045
Create Date: 2026-03-23 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260323_0100_046'
down_revision = '20260322_0200_045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create storage_mounts table
    op.create_table(
        'storage_mounts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('host_path', sa.Text(), nullable=False, unique=True),
        sa.Column('container_path', sa.Text(), nullable=False, unique=True),
        sa.Column('read_only', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('mount_type', sa.String(20), nullable=False, server_default='generic'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('status', sa.String(50), nullable=False, server_default='applied'),
        sa.Column('last_applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()')),
    )
    op.create_index('idx_storage_mounts_mount_type', 'storage_mounts', ['mount_type'])
    op.create_index('idx_storage_mounts_status', 'storage_mounts', ['status'])
    op.create_index('idx_storage_mounts_is_system', 'storage_mounts', ['is_system'])

    # Seed with existing default mounts
    op.execute(sa.text("""
        INSERT INTO storage_mounts (name, host_path, container_path, read_only, mount_type, is_system, is_active, status, last_applied_at)
        VALUES
            ('Music Library', '${MUSIC_LIBRARY_PATH:-/music}', '/music', false, 'music', false, true, 'applied', now()),
            ('Downloads', '${SABNZBD_DOWNLOAD_DIR:-/downloads/music}', '${SABNZBD_DOWNLOAD_DIR:-/downloads/music}', false, 'generic', true, true, 'applied', now()),
            ('Logs', '${STUDIO54_DATA_DIR:-/docker/studio54}/logs', '/app/logs', false, 'generic', true, true, 'applied', now()),
            ('Docker Socket', '/var/run/docker.sock', '/var/run/docker.sock', true, 'generic', true, true, 'applied', now()),
            ('Compose File', './docker-compose.yml', '/app/compose/docker-compose.yml', false, 'generic', true, true, 'applied', now()),
            ('Environment File', '../.env', '/app/compose/.env', true, 'generic', true, true, 'applied', now())
    """))


def downgrade() -> None:
    op.drop_index('idx_storage_mounts_is_system', 'storage_mounts')
    op.drop_index('idx_storage_mounts_status', 'storage_mounts')
    op.drop_index('idx_storage_mounts_mount_type', 'storage_mounts')
    op.drop_table('storage_mounts')
