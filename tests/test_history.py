"""Tests for the Postgres-backed run history.

These tests need the Postgres container running (docker compose up -d). When
the database is unreachable they are skipped, so the rest of the suite still
runs without Docker.
"""

from __future__ import annotations

import psycopg
import pytest

from app.config import settings
from app.history import load_history, record_run


def _postgres_available() -> bool:
    """Return True if the history database can be reached."""
    try:
        psycopg.connect(settings.database_url, connect_timeout=3).close()
    except psycopg.Error:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="Postgres database is not reachable"
)


def test_history_records_and_loads_a_run():
    marker = "pytest-history-marker"
    record_run(
        {"task": marker, "task_id": "test-1", "status": "SUCCESS", "iteration": 1}
    )
    history = load_history()
    assert any(entry["task"] == marker for entry in history)


def test_history_returns_most_recent_first():
    record_run(
        {"task": "older run", "task_id": "old", "status": "SUCCESS", "iteration": 0}
    )
    record_run(
        {"task": "newer run", "task_id": "new", "status": "FAILED", "iteration": 2}
    )
    history = load_history()
    old_index = next(i for i, e in enumerate(history) if e["task"] == "older run")
    new_index = next(i for i, e in enumerate(history) if e["task"] == "newer run")
    assert new_index < old_index
