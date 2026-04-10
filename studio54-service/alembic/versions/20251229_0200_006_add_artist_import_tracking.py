"""Add artist import tracking fields

Revision ID: 006
Revises: 005
Create Date: 2025-12-29 02:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add import source tracking fields to artists table"""
    # Add import_source column
    op.add_column('artists', sa.Column('import_source', sa.String(50), nullable=True))

    # Add muse_library_id column
    op.add_column('artists', sa.Column('muse_library_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Add studio54_library_path_id column
    op.add_column('artists', sa.Column('studio54_library_path_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Add foreign key constraint for studio54_library_path_id
    op.create_foreign_key(
        'fk_artists_library_path',
        'artists',
        'library_paths',
        ['studio54_library_path_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove import source tracking fields from artists table"""
    # Drop foreign key constraint first
    op.drop_constraint('fk_artists_library_path', 'artists', type_='foreignkey')

    # Drop columns
    op.drop_column('artists', 'studio54_library_path_id')
    op.drop_column('artists', 'muse_library_id')
    op.drop_column('artists', 'import_source')
