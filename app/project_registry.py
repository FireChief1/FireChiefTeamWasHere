"""Postgres-backed Project Mode registry and checkpoints."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

import psycopg
from loguru import logger

from app.config import settings

_MAX_PROJECTS = 30
_MAX_CHECKPOINTS = 20

_PROJECT_COLUMNS = (
    "id",
    "created_at",
    "updated_at",
    "last_opened_at",
    "name",
    "path",
    "project_brief",
    "project_stack",
    "project_entrypoints",
    "project_test_commands",
    "project_risks",
    "project_brief_files",
    "git_status",
    "last_task",
    "last_status",
)
_CHECKPOINT_COLUMNS = (
    "id",
    "project_id",
    "created_at",
    "task_id",
    "task",
    "status",
    "task_profile",
    "project_summary",
    "project_brief",
    "project_stack",
    "project_entrypoints",
    "project_test_commands",
    "project_risks",
    "planned_files",
    "written_files",
    "integration_preview_only",
    "integration_diff",
    "tests_passed",
    "tests_failed",
)
_TIMELINE_COLUMNS = (
    "id",
    "project_id",
    "created_at",
    "kind",
    "title",
    "body",
    "metadata",
)
_MEMORY_COLUMNS = (
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "kind",
    "content",
    "source_event_ids",
    "importance",
    "metadata",
    "active",
    "dedupe_key",
)

_PROJECTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    project_brief TEXT NOT NULL,
    project_stack TEXT NOT NULL,
    project_entrypoints TEXT NOT NULL,
    project_test_commands TEXT NOT NULL,
    project_risks TEXT NOT NULL,
    project_brief_files TEXT NOT NULL,
    git_status TEXT NOT NULL,
    last_task TEXT NOT NULL,
    last_status TEXT NOT NULL
)
"""
_PROJECT_COLUMN_DEFINITIONS = {
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
    "last_opened_at": "TEXT NOT NULL DEFAULT ''",
    "name": "TEXT NOT NULL DEFAULT ''",
    "path": "TEXT NOT NULL DEFAULT ''",
    "project_brief": "TEXT NOT NULL DEFAULT ''",
    "project_stack": "TEXT NOT NULL DEFAULT '[]'",
    "project_entrypoints": "TEXT NOT NULL DEFAULT '[]'",
    "project_test_commands": "TEXT NOT NULL DEFAULT '[]'",
    "project_risks": "TEXT NOT NULL DEFAULT '[]'",
    "project_brief_files": "TEXT NOT NULL DEFAULT '[]'",
    "git_status": "TEXT NOT NULL DEFAULT ''",
    "last_task": "TEXT NOT NULL DEFAULT ''",
    "last_status": "TEXT NOT NULL DEFAULT ''",
}
_CHECKPOINTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_checkpoints (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    task_profile TEXT NOT NULL,
    project_summary TEXT NOT NULL,
    project_brief TEXT NOT NULL,
    project_stack TEXT NOT NULL,
    project_entrypoints TEXT NOT NULL,
    project_test_commands TEXT NOT NULL,
    project_risks TEXT NOT NULL,
    planned_files TEXT NOT NULL,
    written_files TEXT NOT NULL,
    integration_preview_only BOOLEAN NOT NULL,
    integration_diff TEXT NOT NULL,
    tests_passed INTEGER NOT NULL,
    tests_failed INTEGER NOT NULL
)
"""
_CHECKPOINT_COLUMN_DEFINITIONS = {
    "project_id": "INTEGER REFERENCES projects(id) ON DELETE CASCADE",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "task_id": "TEXT NOT NULL DEFAULT ''",
    "task": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT ''",
    "task_profile": "TEXT NOT NULL DEFAULT ''",
    "project_summary": "TEXT NOT NULL DEFAULT ''",
    "project_brief": "TEXT NOT NULL DEFAULT ''",
    "project_stack": "TEXT NOT NULL DEFAULT '[]'",
    "project_entrypoints": "TEXT NOT NULL DEFAULT '[]'",
    "project_test_commands": "TEXT NOT NULL DEFAULT '[]'",
    "project_risks": "TEXT NOT NULL DEFAULT '[]'",
    "planned_files": "TEXT NOT NULL DEFAULT '[]'",
    "written_files": "TEXT NOT NULL DEFAULT '[]'",
    "integration_preview_only": "BOOLEAN NOT NULL DEFAULT FALSE",
    "integration_diff": "TEXT NOT NULL DEFAULT ''",
    "tests_passed": "INTEGER NOT NULL DEFAULT 0",
    "tests_failed": "INTEGER NOT NULL DEFAULT 0",
}
_CHECKPOINT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_project_checkpoints_project_created
ON project_checkpoints (project_id, id DESC)
"""
_TIMELINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_timeline_events (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    metadata TEXT NOT NULL
)
"""
_TIMELINE_COLUMN_DEFINITIONS = {
    "project_id": "INTEGER REFERENCES projects(id) ON DELETE CASCADE",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "kind": "TEXT NOT NULL DEFAULT ''",
    "title": "TEXT NOT NULL DEFAULT ''",
    "body": "TEXT NOT NULL DEFAULT ''",
    "metadata": "TEXT NOT NULL DEFAULT '{}'",
}
_TIMELINE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_project_timeline_project_created
ON project_timeline_events (project_id, id DESC)
"""
_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_memory_chunks (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source_event_ids TEXT NOT NULL,
    importance INTEGER NOT NULL,
    metadata TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    dedupe_key TEXT NOT NULL
)
"""
_MEMORY_COLUMN_DEFINITIONS = {
    "project_id": "INTEGER REFERENCES projects(id) ON DELETE CASCADE",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
    "kind": "TEXT NOT NULL DEFAULT ''",
    "content": "TEXT NOT NULL DEFAULT ''",
    "source_event_ids": "TEXT NOT NULL DEFAULT '[]'",
    "importance": "INTEGER NOT NULL DEFAULT 1",
    "metadata": "TEXT NOT NULL DEFAULT '{}'",
    "active": "BOOLEAN NOT NULL DEFAULT TRUE",
    "dedupe_key": "TEXT NOT NULL DEFAULT ''",
}
_MEMORY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_project_memory_project_updated
ON project_memory_chunks (project_id, active, importance DESC, id DESC)
"""
_MEMORY_DEDUPE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_project_memory_dedupe
ON project_memory_chunks (project_id, dedupe_key)
"""
_PROJECT_PATH_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_path
ON projects (path)
"""


class ProjectRecord(TypedDict):
    """A registered project shown in the sidebar."""

    id: int
    created_at: str
    updated_at: str
    last_opened_at: str
    name: str
    path: str
    project_brief: str
    project_stack: list[str]
    project_entrypoints: list[str]
    project_test_commands: list[str]
    project_risks: list[str]
    project_brief_files: list[str]
    git_status: str
    last_task: str
    last_status: str


class ProjectCheckpoint(TypedDict):
    """A saved Project Mode run checkpoint."""

    id: int
    project_id: int
    created_at: str
    task_id: str
    task: str
    status: str
    task_profile: str
    project_summary: str
    project_brief: str
    project_stack: list[str]
    project_entrypoints: list[str]
    project_test_commands: list[str]
    project_risks: list[str]
    planned_files: list[str]
    written_files: list[str]
    integration_preview_only: bool
    integration_diff: str
    tests_passed: int
    tests_failed: int


class ProjectTimelineEvent(TypedDict):
    """A persisted project conversation/timeline event."""

    id: int
    project_id: int
    created_at: str
    kind: str
    title: str
    body: str
    metadata: dict[str, object]


class ProjectMemoryChunk(TypedDict):
    """A compacted, retrievable memory item for one project."""

    id: int
    project_id: int
    created_at: str
    updated_at: str
    kind: str
    content: str
    source_event_ids: list[int]
    importance: int
    metadata: dict[str, object]
    active: bool
    dedupe_key: str


def open_project(path: str | Path, name: str | None = None) -> ProjectRecord | None:
    """Create or touch a project registry entry in Postgres."""
    resolved = _resolve_path(path)
    now = _now()
    project_name = name or _project_name(resolved)
    empty_json = "[]"
    values = (
        now,
        now,
        now,
        project_name,
        str(resolved),
        "",
        empty_json,
        empty_json,
        empty_json,
        empty_json,
        empty_json,
        "",
        "",
        "",
    )
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO projects (
                    created_at, updated_at, last_opened_at, name, path,
                    project_brief, project_stack, project_entrypoints,
                    project_test_commands, project_risks, project_brief_files,
                    git_status, last_task, last_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (path) DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    last_opened_at = EXCLUDED.last_opened_at
                RETURNING {", ".join(_PROJECT_COLUMNS)}
                """,
                values,
            )
            row = cursor.fetchone()
    except psycopg.Error as exc:
        logger.warning(f"could not open project registry entry: {exc}")
        return None
    return _project_from_row(row) if row is not None else None


def rename_project(path: str | Path, new_name: str) -> ProjectRecord | None:
    """Rename a registered project."""
    resolved = _resolve_path(path)
    clean_name = new_name.strip()
    if not clean_name:
        return load_project(resolved)

    now = _now()
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE projects
                SET name = %s, updated_at = %s, last_opened_at = %s
                WHERE path = %s
                RETURNING {", ".join(_PROJECT_COLUMNS)}
                """,
                (clean_name, now, now, str(resolved)),
            )
            row = cursor.fetchone()
            if row is not None:
                _insert_timeline_event(
                    cursor,
                    project_id=int(row[0]),
                    kind="project_renamed",
                    title="Project renamed",
                    body=f"Project renamed to {clean_name}.",
                    metadata={"name": clean_name},
                )
    except psycopg.Error as exc:
        logger.warning(f"could not rename project: {exc}")
        return None
    return _project_from_row(row) if row is not None else None


def delete_project(path: str | Path) -> bool:
    """Delete a project registry entry and its checkpoints/timeline events."""
    resolved = _resolve_path(path)
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM projects WHERE path = %s", (str(resolved),))
            return cursor.rowcount > 0
    except psycopg.Error as exc:
        logger.warning(f"could not delete project registry entry: {exc}")
        return False


def load_projects(limit: int = _MAX_PROJECTS) -> list[ProjectRecord]:
    """Load registered projects, most recently opened first."""
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(_PROJECT_COLUMNS)}
                FROM projects
                ORDER BY last_opened_at DESC, updated_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        logger.warning(f"could not load project registry: {exc}")
        return []
    return [_project_from_row(row) for row in rows]


def load_project(path: str | Path) -> ProjectRecord | None:
    """Load one registered project by path."""
    resolved = _resolve_path(path)
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(_PROJECT_COLUMNS)} FROM projects WHERE path = %s",
                (str(resolved),),
            )
            row = cursor.fetchone()
    except psycopg.Error as exc:
        logger.warning(f"could not load project registry entry: {exc}")
        return None
    return _project_from_row(row) if row is not None else None


def load_project_checkpoints(
    path: str | Path, limit: int = _MAX_CHECKPOINTS
) -> list[ProjectCheckpoint]:
    """Load recent checkpoints for a project path."""
    resolved = _resolve_path(path)
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(f"c.{column}" for column in _CHECKPOINT_COLUMNS)}
                FROM project_checkpoints c
                JOIN projects p ON p.id = c.project_id
                WHERE p.path = %s
                ORDER BY c.id DESC
                LIMIT %s
                """,
                (str(resolved), limit),
            )
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        logger.warning(f"could not load project checkpoints: {exc}")
        return []
    return [_checkpoint_from_row(row) for row in rows]


def load_project_timeline(
    path: str | Path, limit: int = _MAX_CHECKPOINTS
) -> list[ProjectTimelineEvent]:
    """Load recent project timeline events, most recent first."""
    resolved = _resolve_path(path)
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(f"e.{column}" for column in _TIMELINE_COLUMNS)}
                FROM project_timeline_events e
                JOIN projects p ON p.id = e.project_id
                WHERE p.path = %s
                ORDER BY e.id DESC
                LIMIT %s
                """,
                (str(resolved), limit),
            )
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        logger.warning(f"could not load project timeline: {exc}")
        return []
    return [_timeline_from_row(row) for row in rows]


def record_project_memory_chunk(
    *,
    project_path: str | Path,
    kind: str,
    content: str,
    source_event_ids: list[int] | None = None,
    importance: int = 1,
    metadata: dict[str, object] | None = None,
    dedupe_key: str = "",
) -> ProjectMemoryChunk | None:
    """Persist or update one compact project memory chunk."""
    clean_content = content.strip()
    if not clean_content:
        return None

    project = open_project(project_path)
    if project is None:
        return None

    now = _now()
    clean_kind = kind.strip() or "conversation"
    clean_dedupe_key = dedupe_key.strip() or _memory_dedupe_key(
        clean_kind,
        clean_content,
    )
    values = (
        project["id"],
        now,
        now,
        clean_kind,
        clean_content[:4000],
        json.dumps([int(item) for item in source_event_ids or []]),
        max(1, min(int(importance), 5)),
        json.dumps(metadata or {}),
        True,
        clean_dedupe_key,
    )
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO project_memory_chunks (
                    project_id, created_at, updated_at, kind, content,
                    source_event_ids, importance, metadata, active, dedupe_key
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, dedupe_key) DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    kind = EXCLUDED.kind,
                    content = EXCLUDED.content,
                    source_event_ids = EXCLUDED.source_event_ids,
                    importance = EXCLUDED.importance,
                    metadata = EXCLUDED.metadata,
                    active = TRUE
                RETURNING {", ".join(_MEMORY_COLUMNS)}
                """,
                values,
            )
            row = cursor.fetchone()
    except psycopg.Error as exc:
        logger.warning(f"could not record project memory chunk: {exc}")
        return None
    return _memory_from_row(row) if row is not None else None


def load_project_memory_chunks(
    path: str | Path,
    limit: int = 10,
    *,
    active_only: bool = True,
) -> list[ProjectMemoryChunk]:
    """Load recent compact project memory chunks."""
    resolved = _resolve_path(path)
    active_filter = "AND m.active = TRUE" if active_only else ""
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(f"m.{column}" for column in _MEMORY_COLUMNS)}
                FROM project_memory_chunks m
                JOIN projects p ON p.id = m.project_id
                WHERE p.path = %s
                {active_filter}
                ORDER BY m.importance DESC, m.id DESC
                LIMIT %s
                """,
                (str(resolved), limit),
            )
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        logger.warning(f"could not load project memory chunks: {exc}")
        return []
    return [_memory_from_row(row) for row in rows]


def record_project_checkpoint(state: dict[str, Any]) -> None:
    """Persist the final Project Mode state as a project checkpoint."""
    if state.get("mode") != "project" or not state.get("project_path"):
        return

    project = open_project(str(state["project_path"]))
    if project is None:
        return

    now = _now()
    test_results = state.get("test_results")
    tests_passed = int(getattr(test_results, "passed", 0) or 0)
    tests_failed = int(getattr(test_results, "failed", 0) or 0)
    project_update = (
        now,
        now,
        str(state.get("project_brief") or ""),
        _json_list(state.get("project_stack")),
        _json_list(state.get("project_entrypoints")),
        _json_list(state.get("project_test_commands")),
        _json_list(state.get("project_risks")),
        _json_list(state.get("project_brief_files")),
        str(state.get("project_git_status") or ""),
        str(state.get("task") or ""),
        str(state.get("status") or ""),
        project["id"],
    )
    checkpoint = (
        project["id"],
        now,
        str(state.get("task_id") or ""),
        str(state.get("task") or ""),
        str(state.get("status") or ""),
        str(state.get("task_profile") or ""),
        str(state.get("project_summary") or ""),
        str(state.get("project_brief") or ""),
        _json_list(state.get("project_stack")),
        _json_list(state.get("project_entrypoints")),
        _json_list(state.get("project_test_commands")),
        _json_list(state.get("project_risks")),
        _json_list(state.get("integration_planned_files")),
        _json_list(state.get("integration_written_files")),
        bool(state.get("integration_preview_only")),
        str(state.get("integration_diff") or ""),
        tests_passed,
        tests_failed,
    )
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE projects SET
                    updated_at = %s,
                    last_opened_at = %s,
                    project_brief = %s,
                    project_stack = %s,
                    project_entrypoints = %s,
                    project_test_commands = %s,
                    project_risks = %s,
                    project_brief_files = %s,
                    git_status = %s,
                    last_task = %s,
                    last_status = %s
                WHERE id = %s
                """,
                project_update,
            )
            cursor.execute(
                """
                INSERT INTO project_checkpoints (
                    project_id, created_at, task_id, task, status, task_profile,
                    project_summary, project_brief, project_stack,
                    project_entrypoints, project_test_commands, project_risks,
                    planned_files, written_files, integration_preview_only,
                    integration_diff, tests_passed, tests_failed
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                RETURNING id
                """,
                checkpoint,
            )
            checkpoint_row = cursor.fetchone()
            checkpoint_id = int(checkpoint_row[0]) if checkpoint_row is not None else 0
            _insert_timeline_event(
                cursor,
                project_id=project["id"],
                kind="checkpoint",
                title=f"{state.get('status') or 'UNKNOWN'} · {state.get('task_profile') or 'unknown'}",
                body=str(state.get("task") or ""),
                metadata={
                    "checkpoint_id": int(checkpoint_id),
                    "task_id": str(state.get("task_id") or ""),
                    "planned_files": list(state.get("integration_planned_files") or []),
                    "written_files": list(state.get("integration_written_files") or []),
                    "tests_passed": tests_passed,
                    "tests_failed": tests_failed,
                },
            )
    except psycopg.Error as exc:
        logger.warning(f"could not record project checkpoint: {exc}")


def record_project_apply(
    *,
    project_path: str | Path,
    task_id: str,
    written_files: list[str],
) -> None:
    """Persist a post-preview Project Mode apply action."""
    if not task_id:
        return

    resolved = _resolve_path(project_path)
    now = _now()
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM projects WHERE path = %s
                """,
                (str(resolved),),
            )
            project_row = cursor.fetchone()
            if project_row is None:
                return

            project_id = int(project_row[0])
            cursor.execute(
                """
                UPDATE project_checkpoints
                SET written_files = %s,
                    integration_preview_only = FALSE
                WHERE id = (
                    SELECT id FROM project_checkpoints
                    WHERE project_id = %s AND task_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                )
                RETURNING id
                """,
                (_json_list(written_files), project_id, task_id),
            )
            checkpoint_row = cursor.fetchone()
            checkpoint_id = int(checkpoint_row[0]) if checkpoint_row else 0
            cursor.execute(
                """
                UPDATE projects
                SET updated_at = %s,
                    last_opened_at = %s
                WHERE id = %s
                """,
                (now, now, project_id),
            )
            _insert_timeline_event(
                cursor,
                project_id=project_id,
                kind="project_apply",
                title="Project changes applied",
                body=", ".join(written_files) if written_files else "No files written.",
                metadata={
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "written_files": written_files,
                },
            )
    except psycopg.Error as exc:
        logger.warning(f"could not record project apply event: {exc}")


def record_project_message(
    *,
    project_path: str | Path,
    role: str,
    body: str,
    task_id: str = "",
    metadata: dict[str, object] | None = None,
) -> None:
    """Persist a user or assistant project conversation message."""
    clean_body = body.strip()
    if role not in {"user", "assistant"} or not clean_body:
        return

    project = open_project(project_path)
    if project is None:
        return

    event_metadata = dict(metadata or {})
    event_metadata["role"] = role
    if task_id:
        event_metadata["task_id"] = task_id

    try:
        with _connect() as connection, connection.cursor() as cursor:
            _insert_timeline_event(
                cursor,
                project_id=project["id"],
                kind=f"{role}_message",
                title="User message" if role == "user" else "Assistant response",
                body=clean_body,
                metadata=event_metadata,
            )
    except psycopg.Error as exc:
        logger.warning(f"could not record project message: {exc}")


def project_memory_summary(
    project: ProjectRecord | None,
    checkpoints: list[ProjectCheckpoint],
    timeline: list[ProjectTimelineEvent] | None = None,
    memory_chunks: list[ProjectMemoryChunk] | None = None,
) -> str:
    """Build a compact memory block for Project Mode prompts."""
    if project is None:
        return ""

    lines = [f"Known project: {project['name']} at {project['path']}."]
    if project["project_brief"]:
        lines.append(f"Last project brief: {project['project_brief']}")
    if project["project_stack"]:
        lines.append("Known stack: " + ", ".join(project["project_stack"][:8]))
    if project["project_entrypoints"]:
        lines.append(
            "Known entrypoints: " + ", ".join(project["project_entrypoints"][:6])
        )
    if project["project_test_commands"]:
        lines.append(
            "Known test commands: "
            + ", ".join(project["project_test_commands"][:6])
        )
    if project["project_risks"]:
        lines.append("Known risks: " + " | ".join(project["project_risks"][:5]))
    if project["last_task"]:
        lines.append(
            f"Last task: [{project['last_status'] or 'unknown'}] "
            f"{project['last_task']}"
        )
    if checkpoints:
        lines.append("Recent checkpoints:")
        for checkpoint in checkpoints[:5]:
            lines.append(
                f"- {checkpoint['created_at']} "
                f"[{checkpoint['status']}] {checkpoint['task'][:120]}"
            )
    if timeline:
        lines.append("Recent timeline:")
        for event in timeline[:5]:
            lines.append(
                f"- {event['created_at']} [{event['kind']}] "
                f"{event['title']}: {event['body'][:120]}"
            )
    if memory_chunks:
        lines.append("Compacted project memory:")
        for chunk in memory_chunks[:8]:
            lines.append(
                f"- [{chunk['kind']}; importance {chunk['importance']}] "
                f"{chunk['content'][:240]}"
            )
    return "\n".join(lines)


def _connect() -> psycopg.Connection:
    """Open a database connection and ensure project tables exist."""
    connection = psycopg.connect(settings.database_url, connect_timeout=5)
    with connection.cursor() as cursor:
        cursor.execute(_PROJECTS_SCHEMA)
        cursor.execute(_CHECKPOINTS_SCHEMA)
        cursor.execute(_TIMELINE_SCHEMA)
        cursor.execute(_MEMORY_SCHEMA)
        _ensure_columns(cursor, "projects", _PROJECT_COLUMN_DEFINITIONS)
        _ensure_columns(
            cursor,
            "project_checkpoints",
            _CHECKPOINT_COLUMN_DEFINITIONS,
        )
        _ensure_columns(
            cursor,
            "project_timeline_events",
            _TIMELINE_COLUMN_DEFINITIONS,
        )
        _ensure_columns(
            cursor,
            "project_memory_chunks",
            _MEMORY_COLUMN_DEFINITIONS,
        )
        cursor.execute(_PROJECT_PATH_INDEX)
        cursor.execute(_CHECKPOINT_INDEX)
        cursor.execute(_TIMELINE_INDEX)
        cursor.execute(_MEMORY_INDEX)
        cursor.execute(_MEMORY_DEDUPE_INDEX)
    connection.commit()
    return connection


def _resolve_path(path: str | Path) -> Path:
    """Return a normalized absolute project path."""
    return Path(path).expanduser().resolve()


def _project_name(path: Path) -> str:
    """Return a human-readable project name for a path."""
    return path.name or str(path)


def _now() -> str:
    """Return a compact local timestamp."""
    return datetime.now().isoformat(timespec="microseconds")


def _memory_dedupe_key(kind: str, content: str) -> str:
    """Return a stable dedupe key for a memory chunk."""
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def _ensure_columns(
    cursor: psycopg.Cursor, table: str, definitions: dict[str, str]
) -> None:
    """Add missing columns for lightweight forward-compatible migrations."""
    for column, definition in definitions.items():
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
        )


def _insert_timeline_event(
    cursor: psycopg.Cursor,
    *,
    project_id: int,
    kind: str,
    title: str,
    body: str,
    metadata: dict[str, object],
) -> None:
    """Insert a project timeline event using an existing transaction."""
    cursor.execute(
        """
        INSERT INTO project_timeline_events (
            project_id, created_at, kind, title, body, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            project_id,
            _now(),
            kind,
            title,
            body,
            json.dumps(metadata),
        ),
    )


def _json_list(value: object) -> str:
    """Serialize a list-like value to JSON text."""
    if isinstance(value, list):
        return json.dumps([str(item) for item in value])
    return "[]"


def _decode_list(raw: object) -> list[str]:
    """Decode a JSON text list, returning an empty list on bad data."""
    if not isinstance(raw, str):
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _decode_int_list(raw: object) -> list[int]:
    """Decode a JSON text list of ints, returning an empty list on bad data."""
    values = _decode_list(raw)
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except ValueError:
            continue
    return result


def _decode_dict(raw: object) -> dict[str, object]:
    """Decode a JSON text dict, returning an empty dict on bad data."""
    if not isinstance(raw, str):
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _project_from_row(row: tuple[Any, ...]) -> ProjectRecord:
    """Convert a database project row to a typed record."""
    return {
        "id": int(row[0]),
        "created_at": str(row[1]),
        "updated_at": str(row[2]),
        "last_opened_at": str(row[3]),
        "name": str(row[4]),
        "path": str(row[5]),
        "project_brief": str(row[6]),
        "project_stack": _decode_list(row[7]),
        "project_entrypoints": _decode_list(row[8]),
        "project_test_commands": _decode_list(row[9]),
        "project_risks": _decode_list(row[10]),
        "project_brief_files": _decode_list(row[11]),
        "git_status": str(row[12]),
        "last_task": str(row[13]),
        "last_status": str(row[14]),
    }


def _checkpoint_from_row(row: tuple[Any, ...]) -> ProjectCheckpoint:
    """Convert a database checkpoint row to a typed record."""
    return {
        "id": int(row[0]),
        "project_id": int(row[1]),
        "created_at": str(row[2]),
        "task_id": str(row[3]),
        "task": str(row[4]),
        "status": str(row[5]),
        "task_profile": str(row[6]),
        "project_summary": str(row[7]),
        "project_brief": str(row[8]),
        "project_stack": _decode_list(row[9]),
        "project_entrypoints": _decode_list(row[10]),
        "project_test_commands": _decode_list(row[11]),
        "project_risks": _decode_list(row[12]),
        "planned_files": _decode_list(row[13]),
        "written_files": _decode_list(row[14]),
        "integration_preview_only": bool(row[15]),
        "integration_diff": str(row[16]),
        "tests_passed": int(row[17]),
        "tests_failed": int(row[18]),
    }


def _timeline_from_row(row: tuple[Any, ...]) -> ProjectTimelineEvent:
    """Convert a database timeline row to a typed record."""
    metadata: dict[str, object] = {}
    if isinstance(row[6], str):
        try:
            raw_metadata = json.loads(row[6])
        except json.JSONDecodeError:
            raw_metadata = {}
        if isinstance(raw_metadata, dict):
            metadata = raw_metadata
    return {
        "id": int(row[0]),
        "project_id": int(row[1]),
        "created_at": str(row[2]),
        "kind": str(row[3]),
        "title": str(row[4]),
        "body": str(row[5]),
        "metadata": metadata,
    }


def _memory_from_row(row: tuple[Any, ...]) -> ProjectMemoryChunk:
    """Convert a database memory row to a typed record."""
    return {
        "id": int(row[0]),
        "project_id": int(row[1]),
        "created_at": str(row[2]),
        "updated_at": str(row[3]),
        "kind": str(row[4]),
        "content": str(row[5]),
        "source_event_ids": _decode_int_list(row[6]),
        "importance": int(row[7]),
        "metadata": _decode_dict(row[8]),
        "active": bool(row[9]),
        "dedupe_key": str(row[10]),
    }
