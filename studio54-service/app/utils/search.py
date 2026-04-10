"""
Fuzzy search utilities using PostgreSQL pg_trgm trigram similarity.
"""

from sqlalchemy import func, literal, or_
from sqlalchemy.sql import ColumnElement


def fuzzy_search_filter(column, search_term: str, threshold: float = 0.2):
    """
    Build a trigram similarity + ILIKE combo filter for fuzzy search.

    Returns a tuple of (filter_clause, similarity_score) where:
    - filter_clause: OR of similarity >= threshold and ILIKE substring match
    - similarity_score: trigram similarity score for ordering by relevance

    Args:
        column: SQLAlchemy column to search against
        search_term: The user's search string
        threshold: Minimum trigram similarity (0.0-1.0). Default 0.2 is
                   permissive enough for short names (AC/DC, MGMT).
    """
    lower_col = func.lower(column)
    lower_term = search_term.lower()

    similarity_score = func.similarity(lower_col, literal(lower_term))
    ilike_match = column.ilike(f"%{search_term}%")
    similarity_match = similarity_score >= threshold

    filter_clause = or_(similarity_match, ilike_match)

    return filter_clause, similarity_score
