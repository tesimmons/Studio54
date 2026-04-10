"""Add notification profiles table

Revision ID: 20260219_0100_031
Revises: 20260213_0100_030
Create Date: 2026-02-19

Adds notification_profiles table for webhook/Discord/Slack notifications.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = '20260219_0100_031'
down_revision = '20260213_0100_030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notification_profiles',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('provider', sa.String(20), nullable=False, server_default='webhook'),
        sa.Column('webhook_url_encrypted', sa.Text(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('events', JSONB, nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_notification_profiles_name', 'notification_profiles', ['name'])


def downgrade() -> None:
    op.drop_index('ix_notification_profiles_name')
    op.drop_table('notification_profiles')
