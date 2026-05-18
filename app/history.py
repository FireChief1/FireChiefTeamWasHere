"""Persistent history of workflow runs, stored in a local SQLite database.

Each finished run is summarized into one row. SQLite is part of the Python
standard library, so this needs no server, no Docker, and no extra dependency
-- the database is a single file under the workspace directory, which is
git-ignored. SQLite's file locking also makes concurrent writes safe.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any

from loguru import logger

from app.config import settings

_DB_FILE = settings.workspace_dir / "history.db"
_MAX_ENTRIES = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    iterations INTEGER NOT NULL,
    files TEXT NOT NULL,
    tests_passed INTEGER NOT NULL,
    tests_failed INTEGER NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    """Open the history database, creating the file and schema if needed."""
    _DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(_DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute(_SCHEMA)
    connection.commit()
    return connection


def record_run(state: dict[str, Any]) -> None:
    """Append a summary of a finished workflow run to the history database.

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
        with closing(_connect()) as connection, connection:
            connection.execute(
                "INSERT INTO runs (timestamp, task_id, task, status, "
                "iterations, files, tests_passed, tests_failed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
    except sqlite3.Error as exc:
        logger.warning(f"could not write run history: {exc}")


def load_history() -> list[dict[str, Any]]:
    """Load past workflow runs, most recent first.

    Returns:
        Up to the 50 most recent run records, or an empty list if the
        database cannot be read.
    """
    try:
        with closing(_connect()) as connection:
            rows = connection.execute(
                "SELECT timestamp, task_id, task, status, iterations, "
                "files, tests_passed, tests_failed FROM runs "
                "ORDER BY id DESC LIMIT ?",
                (_MAX_ENTRIES,),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning(f"could not read run history: {exc}")
        return []
    return [
        {
            "timestamp": row["timestamp"],
            "task_id": row["task_id"],
            "task": row["task"],
            "status": row["status"],
            "iterations": row["iterations"],
            "files": json.loads(row["files"]),
            "tests_passed": row["tests_passed"],
            "tests_failed": row["tests_failed"],
        }
        for row in rows
    ]
