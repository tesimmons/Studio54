"""Add users table and playlist ownership columns

Revision ID: 20260314_0100_039
Revises: 20260310_0100_038
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import bcrypt

# revision identifiers
revision = '20260314_0100_039'
down_revision = '20260310_0100_038'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('username', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('role', sa.String(20), nullable=False, server_default='partygoer'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Seed default admin user (admin/admin, must change password)
    admin_hash = bcrypt.hashpw("admin".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    op.execute(
        sa.text(
            "INSERT INTO users (username, password_hash, display_name, role, is_active, must_change_password) "
            "VALUES (:username, :password_hash, :display_name, :role, true, true)"
        ).bindparams(
            username="admin",
            password_hash=admin_hash,
            display_name="Club Director",
            role="director",
        )
    )

    # Add playlist ownership columns
    op.add_column('playlists', sa.Column('user_id', UUID(as_uuid=True), nullable=True))
    op.add_column('playlists', sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('playlists', sa.Column('cover_art_url', sa.Text(), nullable=True))

    # Backfill existing playlists to admin user
    op.execute(
        sa.text(
            "UPDATE playlists SET user_id = (SELECT id FROM users WHERE username = 'admin' LIMIT 1) "
            "WHERE user_id IS NULL"
        )
    )

    # Now make user_id NOT NULL and add FK
    op.alter_column('playlists', 'user_id', nullable=False)
    op.create_foreign_key('fk_playlists_user_id', 'playlists', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_playlists_user_id', 'playlists', type_='foreignkey')
    op.drop_column('playlists', 'cover_art_url')
    op.drop_column('playlists', 'is_published')
    op.drop_column('playlists', 'user_id')
    op.drop_table('users')
