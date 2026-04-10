"""Add user preferences column

Revision ID: 20260322_0100_044
Revises: 20260321_0100_043
Create Date: 2026-03-22 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '20260322_0100_044'
down_revision = '20260321_0100_043'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('preferences', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'preferences')
