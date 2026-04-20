# app/tasks/tests/test_deduplicate_task.py
import pytest

def test_duplicate_recycle_model_importable():
    from app.models.duplicate_recycle import DuplicateRecycle
    assert DuplicateRecycle.__tablename__ == "duplicate_recycle_bin"
