"""Add dj_requests table

Revision ID: 20260314_0200_040
Revises: 20260314_0100_039
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = '20260314_0200_040'
down_revision = '20260314_0100_039'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dj_requests',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('request_type', sa.String(20), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('artist_name', sa.String(500), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('response_note', sa.Text(), nullable=True),
        sa.Column('fulfilled_by_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_dj_requests_status', 'dj_requests', ['status'])
    op.create_index('ix_dj_requests_user_id', 'dj_requests', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_dj_requests_user_id')
    op.drop_index('ix_dj_requests_status')
    op.drop_table('dj_requests')
