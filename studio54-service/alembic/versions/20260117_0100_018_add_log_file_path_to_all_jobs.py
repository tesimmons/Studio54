"""Add log_file_path to all job tables

Revision ID: 20260117_0100_018
Revises: 20260114_0100_017
Create Date: 2026-01-17 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260117_0100_018'
down_revision = '20260114_0100_017'
branch_labels = None
depends_on = None


def upgrade():
    # Add log_file_path to job_states
    op.add_column('job_states',
        sa.Column('log_file_path', sa.Text(), nullable=True)
    )

    # Add log_file_path to scan_jobs
    op.add_column('scan_jobs',
        sa.Column('log_file_path', sa.Text(), nullable=True)
    )

    # Add log_file_path to library_import_jobs
    op.add_column('library_import_jobs',
        sa.Column('log_file_path', sa.Text(), nullable=True)
    )


def downgrade():
    op.drop_column('job_states', 'log_file_path')
    op.drop_column('scan_jobs', 'log_file_path')
    op.drop_column('library_import_jobs', 'log_file_path')
