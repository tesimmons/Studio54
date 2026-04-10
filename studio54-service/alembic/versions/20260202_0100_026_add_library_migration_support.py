"""Add library migration support

Revision ID: 20260202_0100_026
Revises: 20260129_0100_025
Create Date: 2026-02-02

Adds support for library migration jobs:
- source_library_path_id: Source library for migration
- destination_library_path_id: Destination library for migration
- files_with_mbid: Count of files that already had MBID
- files_mbid_fetched: Count of files where MBID was looked up
- files_metadata_corrected: Count of files with metadata corrected
- files_validated: Count of files successfully validated
- followup_job_id: Reference to Ponder fingerprint follow-up job

Also updates the job_type enum to include LIBRARY_MIGRATION and MIGRATION_FINGERPRINT.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '20260202_0100_026'
down_revision = '20260129_0100_025'
branch_labels = None
depends_on = None


def upgrade():
    # Note: job_type is VARCHAR(50), not an enum, so no enum modification needed
    # The new job types (library_migration, migration_fingerprint) are just string values

    # Source and destination library references for migration jobs
    op.add_column('file_organization_jobs',
        sa.Column('source_library_path_id', UUID(as_uuid=True), nullable=True,
                  comment='Source library path for migration jobs'))

    op.add_column('file_organization_jobs',
        sa.Column('destination_library_path_id', UUID(as_uuid=True), nullable=True,
                  comment='Destination library path for migration jobs'))

    # Migration statistics columns
    op.add_column('file_organization_jobs',
        sa.Column('files_with_mbid', sa.Integer(), nullable=True, server_default='0',
                  comment='Count of files that already had MBID'))

    op.add_column('file_organization_jobs',
        sa.Column('files_mbid_fetched', sa.Integer(), nullable=True, server_default='0',
                  comment='Count of files where MBID was looked up from MusicBrainz'))

    op.add_column('file_organization_jobs',
        sa.Column('files_metadata_corrected', sa.Integer(), nullable=True, server_default='0',
                  comment='Count of files with metadata corrected to match MusicBrainz'))

    op.add_column('file_organization_jobs',
        sa.Column('files_validated', sa.Integer(), nullable=True, server_default='0',
                  comment='Count of files successfully validated'))

    op.add_column('file_organization_jobs',
        sa.Column('followup_job_id', UUID(as_uuid=True), nullable=True,
                  comment='Reference to Ponder fingerprint follow-up job'))

    # Add foreign key constraints
    op.create_foreign_key(
        'fk_file_org_jobs_source_library',
        'file_organization_jobs',
        'library_paths',
        ['source_library_path_id'],
        ['id'],
        ondelete='CASCADE'
    )

    op.create_foreign_key(
        'fk_file_org_jobs_dest_library',
        'file_organization_jobs',
        'library_paths',
        ['destination_library_path_id'],
        ['id'],
        ondelete='CASCADE'
    )

    op.create_foreign_key(
        'fk_file_org_jobs_followup',
        'file_organization_jobs',
        'file_organization_jobs',
        ['followup_job_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Add indexes for migration job queries
    op.create_index(
        'idx_file_org_jobs_source_library',
        'file_organization_jobs',
        ['source_library_path_id']
    )

    op.create_index(
        'idx_file_org_jobs_dest_library',
        'file_organization_jobs',
        ['destination_library_path_id']
    )

    op.create_index(
        'idx_file_org_jobs_followup',
        'file_organization_jobs',
        ['followup_job_id']
    )


def downgrade():
    # Drop indexes
    op.drop_index('idx_file_org_jobs_followup', 'file_organization_jobs')
    op.drop_index('idx_file_org_jobs_dest_library', 'file_organization_jobs')
    op.drop_index('idx_file_org_jobs_source_library', 'file_organization_jobs')

    # Drop foreign key constraints
    op.drop_constraint('fk_file_org_jobs_followup', 'file_organization_jobs', type_='foreignkey')
    op.drop_constraint('fk_file_org_jobs_dest_library', 'file_organization_jobs', type_='foreignkey')
    op.drop_constraint('fk_file_org_jobs_source_library', 'file_organization_jobs', type_='foreignkey')

    # Drop columns
    op.drop_column('file_organization_jobs', 'followup_job_id')
    op.drop_column('file_organization_jobs', 'files_validated')
    op.drop_column('file_organization_jobs', 'files_metadata_corrected')
    op.drop_column('file_organization_jobs', 'files_mbid_fetched')
    op.drop_column('file_organization_jobs', 'files_with_mbid')
    op.drop_column('file_organization_jobs', 'destination_library_path_id')
    op.drop_column('file_organization_jobs', 'source_library_path_id')

    # Note: PostgreSQL doesn't support removing enum values easily
    # The enum values will remain but won't be used
