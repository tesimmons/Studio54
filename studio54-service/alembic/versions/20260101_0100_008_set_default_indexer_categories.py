"""set default indexer categories

Revision ID: 008
Revises: 007
Create Date: 2026-01-01 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Set default categories for existing indexers

    Updates indexers with NULL or [3000] categories to use the new default:
    [3010, 3040] (MP3 and lossless audio)
    """
    # Update indexers with NULL categories
    op.execute("""
        UPDATE indexers
        SET categories = '[3010, 3040]'::jsonb
        WHERE categories IS NULL OR categories = '[]'::jsonb
    """)

    # Update indexers with old default [3000] to new default [3010, 3040]
    op.execute("""
        UPDATE indexers
        SET categories = '[3010, 3040]'::jsonb
        WHERE categories = '[3000]'::jsonb
    """)


def downgrade() -> None:
    """
    Revert to old default category [3000] (all audio)
    """
    # Revert to old default [3000] for indexers with new default
    op.execute("""
        UPDATE indexers
        SET categories = '[3000]'::jsonb
        WHERE categories = '[3010, 3040]'::jsonb
    """)
