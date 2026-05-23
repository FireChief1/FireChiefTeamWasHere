"""Tests for Project Mode brief extraction."""

from __future__ import annotations

from contextlib import asynccontextmanager

import app.graph.project_brief as project_brief
from app.graph.project_brief import (
    build_project_brief,
    candidate_config_files,
    project_brief_node,
)


def test_candidate_config_files_selects_manifests_without_noise():
    files = [
        "README.md",
        "package.json",
        "src/main.ts",
        "backend/App.csproj",
        "docs/notes.md",
    ]

    assert candidate_config_files(files) == ["package.json", "backend/App.csproj"]


def test_build_project_brief_detects_python_stack_and_dirty_git():
    brief = build_project_brief(
        files=[
            "pyproject.toml",
            "app/ui/streamlit_app.py",
            "app/graph/workflow.py",
            "tests/test_workflow.py",
        ],
        configs={
            "pyproject.toml": """
[project]
dependencies = ["streamlit", "langgraph", "langchain", "mcp", "pytest"]
"""
        },
        git_status="## main...origin/main\n M app/graph/workflow.py\n",
        project_path="/tmp/example",
    )

    assert "Python" in brief["stack"]
    assert "Streamlit" in brief["stack"]
    assert "LangGraph" in brief["stack"]
    assert "streamlit run app/ui/streamlit_app.py" in brief["entrypoints"]
    assert "python -m pytest" in brief["test_commands"]
    assert any("uncommitted changes" in risk for risk in brief["risks"])
    assert "Project brief for /tmp/example" in brief["summary"]


def test_build_project_brief_detects_node_static_web_stack():
    brief = build_project_brief(
        files=["package.json", "index.html", "src/App.tsx"],
        configs={
            "package.json": """
{
  "scripts": {"dev": "vite", "test": "vitest run"},
  "dependencies": {"@vitejs/plugin-react": "latest", "react": "latest"},
  "devDependencies": {"typescript": "latest", "vitest": "latest"}
}
"""
        },
        git_status="not a git repository: /tmp/site",
        project_path="/tmp/site",
    )

    assert "Node.js" in brief["stack"]
    assert "React" in brief["stack"]
    assert "Vite" in brief["stack"]
    assert "TypeScript" in brief["stack"]
    assert "npm run dev" in brief["entrypoints"]
    assert "npm test" in brief["test_commands"]
    assert any("not a git repository" in risk for risk in brief["risks"])


async def test_project_brief_node_is_noop_outside_project_mode(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("project tools should not be opened")

    monkeypatch.setattr(project_brief, "project_tools", fail_if_called)

    assert await project_brief_node({"task": "x", "mode": "generate"}) == {}


async def test_project_brief_node_reads_config_files(monkeypatch, tmp_path):
    class FakeProjectTools:
        async def read_file(self, rel_path):
            assert rel_path == "package.json"
            return '{"scripts": {"test": "vitest run"}, "dependencies": {"vite": "*"}}'

    @asynccontextmanager
    async def fake_project_tools(root):
        assert root == tmp_path.resolve()
        yield FakeProjectTools()

    monkeypatch.setattr(project_brief, "project_tools", fake_project_tools)

    update = await project_brief_node(
        {
            "task": "HTML sayfası",
            "mode": "project",
            "project_path": str(tmp_path),
            "project_files": ["package.json", "index.html"],
            "project_git_status": "## main\n",
        }
    )

    assert update["project_stack"] == ["Static HTML", "Node.js", "Vite"]
    assert update["project_test_commands"] == ["npm test"]
    assert update["project_brief_files"] == ["package.json"]
    assert "Project brief" in update["project_brief"]
