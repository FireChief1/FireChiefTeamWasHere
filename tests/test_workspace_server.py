"""Tests for workspace MCP server helpers."""

from __future__ import annotations

import json
import subprocess

from app.mcp_servers.workspace_server import _ensure_gitignore, git_commit


def test_ensure_gitignore_adds_generated_test_artifact_patterns(tmp_path):
    _ensure_gitignore(tmp_path)

    gitignore = (tmp_path / ".gitignore").read_text()

    assert "__pycache__/" in gitignore
    assert "*.py[cod]" in gitignore
    assert ".coverage" in gitignore
    assert ".pytest_cache/" in gitignore


def test_ensure_gitignore_preserves_existing_entries(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("custom.log\n")

    _ensure_gitignore(tmp_path)

    assert gitignore.read_text().startswith("custom.log\n")


def test_git_commit_ignores_generated_test_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Pytest")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "pytest@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Pytest")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "pytest@example.com")

    task_dir = tmp_path / "task-git"
    pycache = task_dir / "__pycache__"
    pycache.mkdir(parents=True)
    (task_dir / "adder.py").write_text("def add(a, b):\n    return a + b\n")
    (task_dir / ".coverage").write_text("coverage data")
    (pycache / "adder.pyc").write_bytes(b"compiled")

    result = json.loads(
        git_commit("task-git", "feat: add generated code", "feat/task-git")
    )
    files = subprocess.run(
        ["git", "ls-files"],
        cwd=task_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=task_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert result["committed"] is True
    assert result["branch"] == "feat/task-git"
    assert result["message"] == "committed on feat/task-git: feat: add generated code"
    assert branch == "feat/task-git"
    assert "adder.py" in files
    assert ".gitignore" in files
    assert ".coverage" not in files
    assert "__pycache__/adder.pyc" not in files


def test_git_commit_uses_suffix_when_branch_already_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Pytest")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "pytest@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Pytest")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "pytest@example.com")

    task_dir = tmp_path / "task-git"
    task_dir.mkdir()
    (task_dir / "adder.py").write_text("def add(a, b):\n    return a + b\n")
    first = json.loads(
        git_commit("task-git", "feat: add generated code", "feat/task-git")
    )

    (task_dir / "adder.py").write_text("def add(a, b):\n    return a + b + 0\n")
    second = json.loads(
        git_commit("task-git", "feat: adjust generated code", "feat/task-git")
    )

    assert first["committed"] is True
    assert first["branch"] == "feat/task-git"
    assert second["committed"] is True
    assert second["branch"] == "feat/task-git-2"
