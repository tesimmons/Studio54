"""Add user_listening_sessions table

Revision ID: 20260503_0100_062
Revises: 20260426_0100_061
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260503_0100_062'
down_revision = '20260426_0100_061'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_listening_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_type', sa.String(10), nullable=False),
        sa.Column('book_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=True),
        sa.Column('series_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('series.id', ondelete='CASCADE'), nullable=True),
        sa.Column('chapter_queue', postgresql.JSON(astext_type=sa.Text()),
                  nullable=False, server_default='[]'),
        sa.Column('current_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pending_delete_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "(book_id IS NOT NULL AND series_id IS NULL) OR (book_id IS NULL AND series_id IS NOT NULL)",
            name="ck_uls_exactly_one_fk",
        ),
    )
    op.create_index(
        'uq_uls_user_book', 'user_listening_sessions',
        ['user_id', 'book_id'], unique=True,
        postgresql_where=sa.text('series_id IS NULL'),
    )
    op.create_index(
        'uq_uls_user_series', 'user_listening_sessions',
        ['user_id', 'series_id'], unique=True,
        postgresql_where=sa.text('book_id IS NULL'),
    )


def downgrade():
    op.drop_index('uq_uls_user_series', table_name='user_listening_sessions')
    op.drop_index('uq_uls_user_book', table_name='user_listening_sessions')
    op.drop_table('user_listening_sessions')
