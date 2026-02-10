"""Shared fixtures for tests."""

import pytest
from unittest.mock import MagicMock


def make_model(
    model_name: str,
    source_file: str = "test.csv",
    specifications: dict | None = None,
    raw_specifications: dict | None = None,
    model_id: int = 1,
    category: str = "Коммутаторы",
) -> MagicMock:
    """Create a mock Model object for testing (avoids DB dependency)."""
    m = MagicMock()
    m.id = model_id
    m.model_name = model_name
    m.source_file = source_file
    m.specifications = specifications if specifications is not None else {}
    m.raw_specifications = raw_specifications
    m.category = category
    return m
