"""Tests for the bounded, model-driven project file discovery loop."""

from __future__ import annotations

from contextlib import asynccontextmanager

import app.graph.project_intake as project_intake
from app.graph.project_explore import ExploreDecision, explore_project_files


class _FakeTools:
    """Sandboxed-tools stand-in recording reads and serving canned content."""

    def __init__(self, contents: dict[str, str], matches=None):
        self._contents = contents
        self._matches = matches or []
        self.reads: list[str] = []
        self.searches: list[str] = []

    async def read_file(self, rel_path: str) -> str:
        self.reads.append(rel_path)
        if rel_path not in self._contents:
            raise FileNotFoundError(rel_path)
        return self._contents[rel_path]

    async def search_text(self, pattern: str, max_matches: int = 20):
        self.searches.append(pattern)
        return self._matches


def _decider(script):
    """Return a decide() that yields scripted decisions, then 'done'."""
    steps = iter(script)

    async def decide(_context: str) -> ExploreDecision:
        try:
            return next(steps)
        except StopIteration:
            return ExploreDecision(action="done")

    return decide


async def test_explore_reads_requested_files_then_stops():
    tools = _FakeTools({"app/core.py": "x = 1\n", "app/util.py": "y = 2\n"})
    decide = _decider(
        [
            ExploreDecision(action="read_file", target="app/core.py"),
            ExploreDecision(action="read_file", target="app/util.py"),
            ExploreDecision(action="done"),
        ]
    )

    excerpts = await explore_project_files(
        task="understand core",
        tools=tools,
        candidate_files=["app/core.py", "app/util.py"],
        seen_excerpts=[],
        max_steps=6,
        max_bytes=40000,
        decide=decide,
    )

    assert [e["file"] for e in excerpts] == ["app/core.py", "app/util.py"]
    assert tools.reads == ["app/core.py", "app/util.py"]


async def test_explore_skips_hallucinated_repeated_and_nontext_targets():
    tools = _FakeTools({"app/core.py": "x = 1\n"})
    decide = _decider(
        [
            ExploreDecision(action="read_file", target="does/not/exist.py"),  # not listed
            ExploreDecision(action="read_file", target="app/logo.png"),  # listed, non-text
            ExploreDecision(action="read_file", target="app/core.py"),  # already seen
            ExploreDecision(action="read_file", target="app/core.py"),  # repeat -> skip
        ]
    )

    excerpts = await explore_project_files(
        task="t",
        tools=tools,
        candidate_files=["app/core.py", "app/logo.png"],
        seen_excerpts=[{"file": "app/core.py", "content": "x = 1\n"}],
        max_steps=6,
        max_bytes=40000,
        decide=decide,
    )

    assert excerpts == []
    assert tools.reads == []  # nothing valid+new was read


async def test_explore_respects_byte_budget():
    tools = _FakeTools({"a.py": "A" * 5000, "b.py": "B" * 5000})
    decide = _decider(
        [
            ExploreDecision(action="read_file", target="a.py"),
            ExploreDecision(action="read_file", target="b.py"),
        ]
    )

    excerpts = await explore_project_files(
        task="t",
        tools=tools,
        candidate_files=["a.py", "b.py"],
        seen_excerpts=[],
        max_steps=6,
        max_bytes=1000,  # smaller than one excerpt -> stop after first read
        max_chars_per_file=1600,
        decide=decide,
    )

    assert [e["file"] for e in excerpts] == ["a.py"]


async def test_explore_is_noop_with_zero_budget():
    tools = _FakeTools({"a.py": "A\n"})
    excerpts = await explore_project_files(
        task="t",
        tools=tools,
        candidate_files=["a.py"],
        seen_excerpts=[],
        max_steps=0,
        max_bytes=40000,
        decide=_decider([ExploreDecision(action="read_file", target="a.py")]),
    )
    assert excerpts == []
    assert tools.reads == []


async def test_intake_merges_explored_files_when_enabled(monkeypatch, tmp_path):
    class FakeProjectTools:
        async def root_path(self):
            return str(tmp_path.resolve())

        async def list_files(self, max_files=200):
            return ["README.md", "app/core.py"]

        async def search_text(self, pattern, max_matches=50):
            return []

        async def read_file(self, filename):
            return f"content {filename}"

        async def git_status(self):
            return "## main...origin/main\n"

        async def git_diff(self, max_chars=6000):
            return ""

    @asynccontextmanager
    async def fake_project_tools(root):
        yield FakeProjectTools()

    async def fake_explore(**_kwargs):
        return [{"file": "app/core.py", "content": "explored", "truncated": False}]

    monkeypatch.setattr(project_intake, "project_tools", fake_project_tools)
    monkeypatch.setattr(project_intake, "explore_project_files", fake_explore)
    monkeypatch.setattr(project_intake.settings, "project_explore_enabled", True)

    update = await project_intake.project_intake_node(
        {"task": "do something useful", "mode": "project", "project_path": str(tmp_path)}
    )

    excerpt_files = {e["file"] for e in update["project_file_excerpts"]}
    assert "app/core.py" in excerpt_files
    assert "app/core.py" in update["project_relevant_files"]
