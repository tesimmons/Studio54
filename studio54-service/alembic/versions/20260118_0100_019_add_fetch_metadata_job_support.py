"""Add fetch_metadata job support

Revision ID: 20260118_0100_019
Revises: 20260117_0100_018
Create Date: 2026-01-18 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '20260118_0100_019'
down_revision = '20260117_0100_018'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to file_organization_jobs for tracking files without MBID
    op.add_column('file_organization_jobs',
        sa.Column('files_without_mbid', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('file_organization_jobs',
        sa.Column('files_without_mbid_json', sa.Text(), nullable=True))
    op.add_column('file_organization_jobs',
        sa.Column('parent_job_id', UUID(as_uuid=True), nullable=True))
    op.add_column('file_organization_jobs',
        sa.Column('summary_report_path', sa.Text(), nullable=True))

    # Add foreign key constraint for parent_job_id
    op.create_foreign_key(
        'fk_file_org_jobs_parent_job_id',
        'file_organization_jobs',
        'file_organization_jobs',
        ['parent_job_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Create index on parent_job_id for faster lookups
    op.create_index('idx_file_org_jobs_parent_job', 'file_organization_jobs', ['parent_job_id'])


def downgrade():
    # Drop index first
    op.drop_index('idx_file_org_jobs_parent_job', 'file_organization_jobs')

    # Drop foreign key constraint
    op.drop_constraint('fk_file_org_jobs_parent_job_id', 'file_organization_jobs', type_='foreignkey')

    # Drop columns
    op.drop_column('file_organization_jobs', 'summary_report_path')
    op.drop_column('file_organization_jobs', 'parent_job_id')
    op.drop_column('file_organization_jobs', 'files_without_mbid_json')
    op.drop_column('file_organization_jobs', 'files_without_mbid')
