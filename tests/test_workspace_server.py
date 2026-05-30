"""Tests for workspace MCP server helpers."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.mcp_servers.workspace_server import (
    _ensure_gitignore,
    file_exists,
    git_commit,
    git_diff,
    git_status,
    list_files,
    root_path,
    run_node_tests,
    search_text,
)

_HAS_NODE = shutil.which("node") is not None


def _scaffold_node_task(root, module_src: str, test_src: str) -> str:
    """Write a Node task dir (module + package.json + test) and return rel dir."""
    task = root / "task-node"
    task.mkdir()
    (task / "adder.js").write_text(module_src, encoding="utf-8")
    (task / "package.json").write_text('{\n  "type": "module"\n}\n', encoding="utf-8")
    (task / "generated.test.mjs").write_text(test_src, encoding="utf-8")
    return "task-node"


_PASSING_TEST = (
    "import test from 'node:test';\n"
    "import assert from 'node:assert/strict';\n"
    "import { add } from './adder.js';\n"
    "test('adds', () => { assert.equal(add(2, 3), 5); });\n"
)


def test_run_node_tests_reports_available_false_without_node(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "app.mcp_servers.workspace_server.shutil.which", lambda _name: None
    )
    rel = _scaffold_node_task(tmp_path, "export function add(a,b){return a+b;}\n", _PASSING_TEST)
    report = json.loads(run_node_tests(rel))
    assert report["available"] is False


@pytest.mark.skipif(not _HAS_NODE, reason="node not installed")
def test_run_node_tests_passes_for_a_valid_module(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    rel = _scaffold_node_task(tmp_path, "export function add(a,b){return a+b;}\n", _PASSING_TEST)
    report = json.loads(run_node_tests(rel))
    assert report["available"] is True
    assert report["passed"] >= 1
    assert report["failed"] == 0


@pytest.mark.skipif(not _HAS_NODE, reason="node not installed")
def test_run_node_tests_reports_failing_assertions(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    failing = _PASSING_TEST.replace("add(2, 3), 5", "add(2, 3), 6")
    rel = _scaffold_node_task(tmp_path, "export function add(a,b){return a+b;}\n", failing)
    report = json.loads(run_node_tests(rel))
    assert report["available"] is True
    assert report["failed"] >= 1


@pytest.mark.skipif(not _HAS_NODE, reason="node not installed")
def test_run_node_tests_reports_syntax_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    rel = _scaffold_node_task(tmp_path, "export function add(a,b){ return a+ ;}\n", _PASSING_TEST)
    report = json.loads(run_node_tests(rel))
    assert report["available"] is True
    assert report["failed"] >= 1
    assert "Syntax errors" in report["output"]


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


def test_list_files_returns_text_files_and_skips_project_noise(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("# Demo\n")
    (tmp_path / "index.html").write_text("<!doctype html><html></html>\n")
    (tmp_path / "style.css").write_text("body { color: black; }\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('hi')\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("print('ignored')\n")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").write_text("{}\n")
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "task.py").write_text("print('generated')\n")
    (tmp_path / "image.png").write_bytes(b"png")

    assert json.loads(list_files()) == ["README.md", "app/main.py", "index.html", "style.css"]


def test_root_path_reports_effective_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))

    assert root_path() == str(tmp_path.resolve())


def test_file_exists_stays_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "index.html").write_text("<!doctype html><html></html>\n")

    assert file_exists("index.html") is True
    assert file_exists("missing.html") is False


def test_search_text_returns_bounded_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("Project mode\nProject intake\n")
    (tmp_path / "notes.txt").write_text("Nothing here\n")

    matches = json.loads(search_text("project", max_matches=1))

    assert matches == [
        {"file": "README.md", "line": 1, "text": "Project mode"}
    ]


def test_search_text_escapes_invalid_regex(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("literal [ pattern\n")

    matches = json.loads(search_text("[", max_matches=5))

    assert matches == [
        {"file": "README.md", "line": 1, "text": "literal [ pattern"}
    ]


def test_git_status_and_diff_report_missing_project_path(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(missing))

    assert "path does not exist" in git_status()
    assert "path does not exist" in git_diff()


def test_git_status_and_diff_report_non_git_project_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(tmp_path))

    assert "not a git repository" in git_status()
    assert "not a git repository" in git_diff()


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
