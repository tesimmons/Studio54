"""Add associate_and_organize job type

Revision ID: 20260213_0100_030
Revises: 20260212_0100_029
Create Date: 2026-02-13

Note: job_type is stored as varchar, not a native PostgreSQL enum.
The new value 'associate_and_organize' is added to the Python JobType enum
in file_organization_job.py. No schema change needed.
"""

revision = '20260213_0100_030'
down_revision = '20260212_0100_029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # job_type column is varchar - new enum values are handled in Python code
    pass


def downgrade() -> None:
    pass
