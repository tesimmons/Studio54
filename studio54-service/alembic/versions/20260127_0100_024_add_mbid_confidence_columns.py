"""Add MBID confidence scoring columns

Revision ID: 20260127_0100_024
Revises: 20260125_0300_023
Create Date: 2026-01-27

Adds columns to track MBID validation confidence:
- mbid_confidence_score: 0-100 score from MBIDConfidenceScorer
- mbid_confidence_level: high/medium/low/very_low
- mbid_last_validation: timestamp of last metadata validation
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260127_0100_024'
down_revision = '20260125_0300_023'
branch_labels = None
depends_on = None


def upgrade():
    # Add MBID confidence columns to library_files
    op.add_column('library_files',
        sa.Column('mbid_confidence_score', sa.Integer(), nullable=True,
                  comment='Confidence score 0-100 from MBID metadata validation'))

    op.add_column('library_files',
        sa.Column('mbid_confidence_level', sa.String(20), nullable=True,
                  comment='Confidence level: high, medium, low, very_low'))

    op.add_column('library_files',
        sa.Column('mbid_last_validation', sa.DateTime(timezone=True), nullable=True,
                  comment='Last time MBID metadata was validated against MusicBrainz'))

    # Create index for filtering by confidence level
    op.create_index('idx_library_files_mbid_confidence', 'library_files', ['mbid_confidence_level'])


def downgrade():
    # Drop index
    op.drop_index('idx_library_files_mbid_confidence', 'library_files')

    # Drop columns
    op.drop_column('library_files', 'mbid_last_validation')
    op.drop_column('library_files', 'mbid_confidence_level')
    op.drop_column('library_files', 'mbid_confidence_score')
