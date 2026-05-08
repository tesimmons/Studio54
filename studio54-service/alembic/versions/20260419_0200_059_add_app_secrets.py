"""Add app_secrets table for DB-managed encryption key

Revision ID: 20260419_0200_059
Revises: 20260418_0100_058
Create Date: 2026-04-19

Stores the Fernet encryption key in the database so it survives container
restarts without requiring STUDIO54_ENCRYPTION_KEY in the environment.
Seeds from STUDIO54_ENCRYPTION_KEY env var if present.
"""
import os
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision = '20260419_0200_059'
down_revision = '20260418_0100_058'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_secrets',
        sa.Column('key', sa.String(255), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    existing_key = os.getenv("STUDIO54_ENCRYPTION_KEY", "").strip()
    if existing_key:
        conn = op.get_bind()
        conn.execute(
            text("INSERT INTO app_secrets (key, value) VALUES ('encryption_key', :val)"),
            {"val": existing_key}
        )


def downgrade():
    op.drop_table('app_secrets')
