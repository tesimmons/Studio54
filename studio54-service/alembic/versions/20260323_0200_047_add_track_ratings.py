"""Add per-user track_ratings table and average_rating column on tracks

Revision ID: 20260323_0200_047
Revises: 20260323_0100_046
Create Date: 2026-03-23 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260323_0200_047'
down_revision = '20260323_0100_046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create track_ratings table
    op.create_table(
        'track_ratings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('track_id', UUID(as_uuid=True), sa.ForeignKey('tracks.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', 'track_id', name='uq_track_ratings_user_track'),
    )

    # Add average_rating column to tracks
    op.add_column('tracks', sa.Column('average_rating', sa.Float(), nullable=True))

    # Data migration: copy existing track.rating values into track_ratings
    # for the first director user, then set average_rating = that rating
    conn = op.get_bind()

    # Find the first director user to attribute legacy ratings to
    director = conn.execute(
        sa.text("SELECT id FROM users WHERE role = 'director' ORDER BY created_at ASC LIMIT 1")
    ).fetchone()

    if director:
        director_id = director[0]
        # Insert a TrackRating row for each track that has a non-null rating
        conn.execute(
            sa.text("""
                INSERT INTO track_ratings (id, user_id, track_id, rating, created_at, updated_at)
                SELECT gen_random_uuid(), :director_id, id, rating, now(), now()
                FROM tracks
                WHERE rating IS NOT NULL
            """),
            {"director_id": director_id}
        )

    # Set average_rating = rating for all tracks that have a rating
    conn.execute(
        sa.text("UPDATE tracks SET average_rating = rating::float WHERE rating IS NOT NULL")
    )


def downgrade() -> None:
    op.drop_column('tracks', 'average_rating')
    op.drop_table('track_ratings')
