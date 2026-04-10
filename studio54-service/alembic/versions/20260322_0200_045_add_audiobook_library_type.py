"""Add audiobook library type and models (Author, Series, Book, Chapter)

Revision ID: 20260322_0200_045
Revises: 20260322_0100_044
Create Date: 2026-03-22 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260322_0200_045'
down_revision = '20260322_0100_044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add library_type to library_paths
    op.add_column('library_paths', sa.Column('library_type', sa.String(20), nullable=False, server_default='music'))
    op.create_index('idx_library_paths_library_type', 'library_paths', ['library_type'])

    # 2. Add library_type to library_files
    op.add_column('library_files', sa.Column('library_type', sa.String(20), nullable=False, server_default='music'))
    op.create_index('idx_library_files_library_type', 'library_files', ['library_type'])

    # 3. Create authors table
    op.create_table(
        'authors',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('musicbrainz_id', sa.String(36), unique=True, nullable=False),
        sa.Column('is_monitored', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('quality_profile_id', UUID(as_uuid=True), sa.ForeignKey('quality_profiles.id'), nullable=True),
        sa.Column('monitor_type', sa.String(30), nullable=False, server_default='none'),
        sa.Column('root_folder_path', sa.Text(), nullable=True),
        sa.Column('overview', sa.Text(), nullable=True),
        sa.Column('genre', sa.String(255), nullable=True),
        sa.Column('country', sa.String(100), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('import_source', sa.String(50), nullable=True),
        sa.Column('studio54_library_path_id', UUID(as_uuid=True), sa.ForeignKey('library_paths.id'), nullable=True),
        sa.Column('book_count', sa.Integer(), server_default='0'),
        sa.Column('series_count', sa.Integer(), server_default='0'),
        sa.Column('chapter_count', sa.Integer(), server_default='0'),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_authors_name', 'authors', ['name'])
    op.create_index('idx_authors_musicbrainz_id', 'authors', ['musicbrainz_id'])

    # 4. Create series table
    op.create_table(
        'series',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('author_id', UUID(as_uuid=True), sa.ForeignKey('authors.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('musicbrainz_series_id', sa.String(36), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('total_expected_books', sa.Integer(), nullable=True),
        sa.Column('monitored', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('cover_art_url', sa.Text(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_series_author_id', 'series', ['author_id'])
    op.create_index('idx_series_name', 'series', ['name'])
    op.create_index('idx_series_musicbrainz_series_id', 'series', ['musicbrainz_series_id'])

    # 5. Create books table
    op.create_table(
        'books',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('author_id', UUID(as_uuid=True), sa.ForeignKey('authors.id', ondelete='CASCADE'), nullable=False),
        sa.Column('series_id', UUID(as_uuid=True), sa.ForeignKey('series.id', ondelete='SET NULL'), nullable=True),
        sa.Column('series_position', sa.Integer(), nullable=True),
        sa.Column('related_series', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('musicbrainz_id', sa.String(36), unique=True, nullable=False),
        sa.Column('release_mbid', sa.String(36), nullable=True),
        sa.Column('release_date', sa.Date(), nullable=True),
        sa.Column('album_type', sa.String(50), nullable=True),
        sa.Column('secondary_types', sa.Text(), nullable=True),
        sa.Column('chapter_count', sa.Integer(), server_default='0'),
        sa.Column('status', sa.Enum('WANTED', 'SEARCHING', 'DOWNLOADING', 'DOWNLOADED', 'FAILED', name='bookstatus'), nullable=False, server_default='WANTED'),
        sa.Column('monitored', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('cover_art_url', sa.Text(), nullable=True),
        sa.Column('custom_folder_path', sa.Text(), nullable=True),
        sa.Column('last_search_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quality_meets_cutoff', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('searched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('downloaded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_books_author_id', 'books', ['author_id'])
    op.create_index('idx_books_series_id', 'books', ['series_id'])
    op.create_index('idx_books_title', 'books', ['title'])
    op.create_index('idx_books_musicbrainz_id', 'books', ['musicbrainz_id'])
    op.create_index('idx_books_status', 'books', ['status'])
    op.create_index('idx_books_release_mbid', 'books', ['release_mbid'])

    # 6. Create chapters table
    op.create_table(
        'chapters',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('book_id', UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('musicbrainz_id', sa.String(36), nullable=True),
        sa.Column('chapter_number', sa.Integer(), nullable=True),
        sa.Column('disc_number', sa.Integer(), server_default='1'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('has_file', sa.Boolean(), server_default='false'),
        sa.Column('file_path', sa.Text(), nullable=True),
        sa.Column('play_count', sa.Integer(), server_default='0'),
        sa.Column('last_played_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_chapters_book_id', 'chapters', ['book_id'])
    op.create_index('idx_chapters_musicbrainz_id', 'chapters', ['musicbrainz_id'])
    op.create_index('idx_chapters_file_path', 'chapters', ['file_path'])

    # 7. Modify download_queue: add book_id, author_id, library_type; make album_id nullable
    op.alter_column('download_queue', 'album_id', nullable=True)
    op.add_column('download_queue', sa.Column('book_id', UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=True))
    op.add_column('download_queue', sa.Column('author_id', UUID(as_uuid=True), sa.ForeignKey('authors.id', ondelete='CASCADE'), nullable=True))
    op.add_column('download_queue', sa.Column('library_type', sa.String(20), nullable=False, server_default='music'))
    op.create_index('idx_download_queue_book_id', 'download_queue', ['book_id'])
    op.create_index('idx_download_queue_author_id', 'download_queue', ['author_id'])


def downgrade() -> None:
    # Remove download_queue additions
    op.drop_index('idx_download_queue_author_id', 'download_queue')
    op.drop_index('idx_download_queue_book_id', 'download_queue')
    op.drop_column('download_queue', 'library_type')
    op.drop_column('download_queue', 'author_id')
    op.drop_column('download_queue', 'book_id')
    op.alter_column('download_queue', 'album_id', nullable=False)

    # Drop tables in reverse order
    op.drop_table('chapters')
    op.drop_table('books')
    op.execute("DROP TYPE IF EXISTS bookstatus")
    op.drop_table('series')
    op.drop_table('authors')

    # Remove library_type columns
    op.drop_index('idx_library_files_library_type', 'library_files')
    op.drop_column('library_files', 'library_type')
    op.drop_index('idx_library_paths_library_type', 'library_paths')
    op.drop_column('library_paths', 'library_type')
