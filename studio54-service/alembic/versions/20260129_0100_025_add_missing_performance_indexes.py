"""Add missing performance indexes

Revision ID: 20260129_0100_025
Revises: 20260127_0100_024
Create Date: 2026-01-29

Adds missing composite indexes identified during performance analysis:
- Composite index on file_organization_jobs(status, job_type)
- Composite index on file_organization_jobs(library_path_id, status)
- Composite index on library_files(library_path_id, organization_status)

Note: idx_file_org_jobs_heartbeat already exists from migration 021
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260129_0100_025'
down_revision = '20260127_0100_024'
branch_labels = None
depends_on = None


def upgrade():
    # Composite index for queries filtering by status AND job_type
    # Used frequently in jobs.py list_organization_jobs and get_job_stats
    op.create_index(
        'idx_file_org_jobs_status_type',
        'file_organization_jobs',
        ['status', 'job_type']
    )

    # Composite index for library-specific job queries
    # Used in file_management.py when listing jobs for a specific library
    op.create_index(
        'idx_file_org_jobs_library_status',
        'file_organization_jobs',
        ['library_path_id', 'status']
    )

    # Composite index for library_files queries by library and organization status
    # Used frequently in organization_tasks.py when processing files
    op.create_index(
        'idx_library_files_path_org_status',
        'library_files',
        ['library_path_id', 'organization_status']
    )


def downgrade():
    # Drop indexes in reverse order
    op.drop_index('idx_library_files_path_org_status', 'library_files')
    op.drop_index('idx_file_org_jobs_library_status', 'file_organization_jobs')
    op.drop_index('idx_file_org_jobs_status_type', 'file_organization_jobs')
