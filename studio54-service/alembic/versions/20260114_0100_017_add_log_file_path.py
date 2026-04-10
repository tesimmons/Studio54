"""Add log_file_path to file_organization_jobs

Revision ID: 20260114_0100_017
Revises: 016
Create Date: 2026-01-14 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260114_0100_017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade():
    # Add log_file_path column
    op.add_column('file_organization_jobs', 
        sa.Column('log_file_path', sa.Text(), nullable=True)
    )


def downgrade():
    op.drop_column('file_organization_jobs', 'log_file_path')
