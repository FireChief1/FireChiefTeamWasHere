"""Persistent history of workflow runs, stored in a Postgres database.

Postgres runs as a Docker container (see docker-compose.yml). If the database
is unreachable, the history feature degrades gracefully -- the panel is simply
empty and writes are skipped -- so the rest of the workflow is unaffected.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from loguru import logger

from app.config import settings

_MAX_ENTRIES = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id SERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    iterations INTEGER NOT NULL,
    files TEXT NOT NULL,
    tests_passed INTEGER NOT NULL,
    tests_failed INTEGER NOT NULL
)
"""


def _connect() -> psycopg.Connection:
    """Open a database connection and ensure the schema exists."""
    connection = psycopg.connect(settings.database_url, connect_timeout=5)
    with connection.cursor() as cursor:
        cursor.execute(_SCHEMA)
    connection.commit()
    return connection


def record_run(state: dict[str, Any]) -> None:
    """Append a summary of a finished workflow run to the database.

    Args:
        state: The final workflow state.
    """
    test_results = state.get("test_results")
    row = (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        str(state.get("task_id") or "?"),
        str(state.get("task") or ""),
        str(state.get("status") or "?"),
        int(state.get("iteration") or 0),
        json.dumps(list(state.get("code") or {})),
        test_results.passed if test_results else 0,
        test_results.failed if test_results else 0,
    )
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO runs (created_at, task_id, task, status, "
                "iterations, files, tests_passed, tests_failed) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                row,
            )
    except psycopg.Error as exc:
        logger.warning(f"could not write run history: {exc}")


def load_history() -> list[dict[str, Any]]:
    """Load past workflow runs, most recent first.

    Returns:
        Up to the 50 most recent run records, or an empty list if the
        database cannot be reached.
    """
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT created_at, task_id, task, status, iterations, "
                "files, tests_passed, tests_failed FROM runs "
                "ORDER BY id DESC LIMIT %s",
                (_MAX_ENTRIES,),
            )
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        logger.warning(f"could not read run history: {exc}")
        return []
    return [
        {
            "timestamp": row[0],
            "task_id": row[1],
            "task": row[2],
            "status": row[3],
            "iterations": row[4],
            "files": json.loads(row[5]),
            "tests_passed": row[6],
            "tests_failed": row[7],
        }
        for row in rows
    ]
