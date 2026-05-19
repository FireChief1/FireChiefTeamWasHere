"""MCP server exposing safe, workspace-scoped file and test tools.

This server is the security boundary for agent-generated code. Every path is
confined to the workspace root (no path traversal), and the only command that
can be executed is pytest, under a timeout. The workflow nodes act as MCP
clients of this server; the LLM never calls these tools directly.

Run as a standalone MCP server (stdio transport):

    MCP_WORKSPACE_ROOT=/path/to/workspace python -m app.mcp_servers.workspace_server
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("workspace")

_GENERATED_REPO_IGNORES = (
    "__pycache__/",
    "*.py[cod]",
    ".coverage",
    ".pytest_cache/",
)


def _workspace_root() -> Path:
    """Return the workspace root from the environment.

    Raises:
        RuntimeError: If MCP_WORKSPACE_ROOT is not set.
    """
    root = os.environ.get("MCP_WORKSPACE_ROOT")
    if not root:
        raise RuntimeError("MCP_WORKSPACE_ROOT is not set")
    return Path(root).resolve()


def _safe_path(rel_path: str) -> Path:
    """Resolve a path and verify it stays within the workspace root.

    Args:
        rel_path: A path relative to the workspace root.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: If the resolved path escapes the workspace root.
    """
    root = _workspace_root()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes the workspace: {rel_path}")
    return target


@mcp.tool()
def write_file(rel_path: str, content: str) -> str:
    """Write text content to a file inside the workspace.

    Args:
        rel_path: The file path, relative to the workspace root.
        content: The text to write.

    Returns:
        A confirmation message.
    """
    target = _safe_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {len(content)} chars to {rel_path}"


@mcp.tool()
def read_file(rel_path: str) -> str:
    """Read a text file from inside the workspace.

    Args:
        rel_path: The file path, relative to the workspace root.

    Returns:
        The file's contents.
    """
    return _safe_path(rel_path).read_text()


@mcp.tool()
def run_pytest(rel_dir: str, timeout: int = 30) -> str:
    """Run pytest in a workspace directory under a hard timeout.

    Only pytest may be executed; this is the single allowed command.

    Args:
        rel_dir: The directory to test, relative to the workspace root.
        timeout: Maximum seconds before the run is killed.

    Returns:
        The combined stdout and stderr of the pytest run.
    """
    target = _safe_path(rel_dir)
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "-q", "--tb=short", "-p", "no:cacheprovider",
            ],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT: test execution exceeded the time limit"
    return proc.stdout + proc.stderr


def _ensure_gitignore(target: Path) -> None:
    """Ensure generated task repositories do not commit test artefacts."""
    gitignore = target / ".gitignore"
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    missing = [entry for entry in _GENERATED_REPO_IGNORES if entry not in existing]
    if not missing:
        return

    prefix = "\n" if existing else ""
    gitignore.write_text(
        "\n".join(existing) + prefix + "\n".join(missing) + "\n"
    )


def _git_failure(message: str, branch: str = "") -> str:
    """Serialize an unsuccessful git integration result."""
    return json.dumps(
        {
            "committed": False,
            "branch": branch,
            "message": message,
        }
    )


def _git_success(message: str, branch: str) -> str:
    """Serialize a successful git integration result."""
    return json.dumps(
        {
            "committed": True,
            "branch": branch,
            "message": message,
        }
    )


def _git_stderr(result: subprocess.CompletedProcess[str]) -> str:
    """Return a compact git error string."""
    return (result.stderr or result.stdout or "").strip()


@mcp.tool()
def git_commit(rel_dir: str, message: str, branch: str) -> str:
    """Initialize a git repo if needed and commit a workspace directory.

    Args:
        rel_dir: The directory to commit, relative to the workspace root.
        message: The commit message.
        branch: The feature branch to commit on.

    Returns:
        A status message describing the commit result.
    """
    target = _safe_path(rel_dir)
    _ensure_gitignore(target)

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=str(target), capture_output=True, text=True
        )

    if not (target / ".git").exists():
        init = git("init", "-q")
        if init.returncode != 0:
            return _git_failure(f"git init failed: {_git_stderr(init)}")

    try:
        selected_branch = _next_available_branch(git, branch)
    except RuntimeError as exc:
        return _git_failure(str(exc))
    checkout = git("checkout", "-q", "-b", selected_branch)
    if checkout.returncode != 0:
        return _git_failure(
            f"git checkout failed: {_git_stderr(checkout)}",
            selected_branch,
        )

    add = git("add", "-A")
    if add.returncode != 0:
        return _git_failure(
            f"git add failed: {_git_stderr(add)}",
            selected_branch,
        )

    result = git("commit", "-q", "-m", message)
    if result.returncode == 0:
        return _git_success(f"committed on {selected_branch}: {message}", selected_branch)
    return _git_failure(
        f"commit skipped ({_git_stderr(result) or 'nothing to commit'})",
        selected_branch,
    )


def _next_available_branch(
    git: Callable[..., subprocess.CompletedProcess[str]],
    branch: str,
    *,
    max_attempts: int = 100,
) -> str:
    """Return `branch` or a numeric suffix that is not already a local branch."""
    for index in range(max_attempts):
        candidate = branch if index == 0 else f"{branch}-{index + 1}"
        result = git(
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{candidate}",
        )
        if result.returncode != 0:
            return candidate
    raise RuntimeError(f"could not find an available branch name for {branch}")


if __name__ == "__main__":
    mcp.run()
