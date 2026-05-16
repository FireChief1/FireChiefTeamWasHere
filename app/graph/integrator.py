"""The Integrator node.

The Integrator is deterministic. It runs only after a SUCCESS result. It
writes the final code into the task workspace and makes a local git commit on
a feature branch. It never pushes to a remote -- pushing is a human-gated
action performed from the UI.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings
from app.graph.error_boundary import node_error_boundary
from app.graph.state import AgentState


@node_error_boundary
async def integrator_node(state: AgentState) -> dict[str, Any]:
    """Write the final code and make a local git commit on a feature branch."""
    task_dir = settings.workspace_dir / f"task-{state['task_id']}"
    task_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in (state.get("code") or {}).items():
        (task_dir / filename).write_text(content)

    branch = f"feat/task-{state['task_id']}"
    await asyncio.to_thread(_git_commit, task_dir, branch, state["task"])
    logger.info(f"integrator: committed code to local branch '{branch}'")
    return {}


def _git_commit(task_dir: Path, branch: str, task: str) -> None:
    """Initialize a local git repo if needed and commit the task directory."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(task_dir),
            capture_output=True,
            text=True,
        )

    if not (task_dir / ".git").exists():
        git("init", "-q")
        git("checkout", "-q", "-b", branch)
    git("add", "-A")
    subject = task.strip().splitlines()[0][:60]
    git("commit", "-q", "-m", f"feat: {subject}")
