"""Deterministic project brief extraction for Project Mode."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, TypedDict

from app.graph.error_boundary import node_error_boundary
from app.graph.project_intake import project_path_from_state
from app.graph.state import AgentState
from app.tools.mcp_client import project_tools


class ProjectBrief(TypedDict):
    """Compact facts about the selected project folder."""

    summary: str
    stack: list[str]
    entrypoints: list[str]
    test_commands: list[str]
    risks: list[str]
    files: list[str]


_CONFIG_BASENAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "next.config.ts",
}
_CONFIG_SUFFIXES = (".csproj", ".fsproj", ".sln")
_TEST_SCRIPT_HINTS = ("test", "spec", "e2e", "coverage", "pytest", "vitest", "jest")


@node_error_boundary
async def project_brief_node(state: AgentState) -> dict[str, Any]:
    """Build a deterministic brief of the selected project folder."""
    if state.get("mode") != "project" or state.get("should_abort"):
        return {}

    files = state.get("project_files") or []
    project_path = project_path_from_state(state)
    config_files = candidate_config_files(files)

    async with project_tools(project_path) as tools:
        configs: dict[str, str] = {}
        for filename in config_files:
            try:
                configs[filename] = await tools.read_file(filename)
            except Exception:
                continue

    brief = build_project_brief(
        files=files,
        configs=configs,
        git_status=state.get("project_git_status", ""),
        project_path=str(project_path),
        task_profile=state.get("task_profile"),
    )
    return {
        "project_brief": brief["summary"],
        "project_stack": brief["stack"],
        "project_entrypoints": brief["entrypoints"],
        "project_test_commands": brief["test_commands"],
        "project_risks": brief["risks"],
        "project_brief_files": brief["files"],
    }


def candidate_config_files(files: list[str]) -> list[str]:
    """Return config and manifest files worth reading for a project brief."""
    selected: list[str] = []
    for filename in files:
        path = Path(filename)
        if (
            path.name in _CONFIG_BASENAMES
            or path.suffix in _CONFIG_SUFFIXES
            or path.name.startswith(("vite.config.", "next.config."))
        ):
            _append_unique(selected, filename)
        if len(selected) >= 20:
            break
    return selected


def build_project_brief(
    *,
    files: list[str],
    configs: dict[str, str],
    git_status: str,
    project_path: str,
    task_profile: str | None = None,
) -> ProjectBrief:
    """Infer project stack, entrypoints, commands, and risks from files."""
    stack: list[str] = []
    entrypoints: list[str] = []
    test_commands: list[str] = []
    risks: list[str] = []

    _infer_from_filenames(files, stack, entrypoints, test_commands)
    _infer_from_configs(configs, stack, entrypoints, test_commands)
    _infer_git_risks(git_status, risks)

    if not files:
        risks.append(
            "No text-oriented files were found; the agent has little project "
            "context and should treat output as new artifacts."
        )
    if not test_commands:
        risks.append(
            "No obvious automated test command was detected; verification may "
            "need manual or project-specific commands."
        )
    if task_profile in {"docs", "project"}:
        risks.append(
            f"The {task_profile} task profile is advisory by default; it should "
            "produce markdown/text guidance unless the task is reclassified to "
            "a concrete artifact profile."
        )

    if not stack:
        stack.append("Unknown or mixed stack")
    if not entrypoints:
        entrypoints.append("No obvious runtime entrypoint detected")

    summary = _brief_summary(
        project_path=project_path,
        stack=stack,
        entrypoints=entrypoints,
        test_commands=test_commands,
        risks=risks,
    )
    return {
        "summary": summary,
        "stack": stack,
        "entrypoints": entrypoints,
        "test_commands": test_commands,
        "risks": risks,
        "files": list(configs.keys()),
    }


def _infer_from_filenames(
    files: list[str],
    stack: list[str],
    entrypoints: list[str],
    test_commands: list[str],
) -> None:
    """Infer broad project facts from relative filenames."""
    file_set = set(files)
    lower_files = {filename.casefold(): filename for filename in files}

    if any(filename.endswith(".py") for filename in files):
        _append_unique(stack, "Python")
    if any(filename.endswith((".js", ".jsx")) for filename in files):
        _append_unique(stack, "JavaScript")
    if any(filename.endswith((".ts", ".tsx")) for filename in files):
        _append_unique(stack, "TypeScript")
    if any(filename.endswith(".html") for filename in files):
        _append_unique(stack, "Static HTML")
    if any(filename.endswith((".csproj", ".sln")) for filename in files):
        _append_unique(stack, ".NET")
    if "Dockerfile" in file_set or any(
        Path(filename).name.startswith("docker-compose") for filename in files
    ):
        _append_unique(stack, "Docker")

    if "app/ui/streamlit_app.py" in file_set:
        _append_unique(entrypoints, "streamlit run app/ui/streamlit_app.py")
        _append_unique(stack, "Streamlit")
    for candidate in ("main.py", "app.py", "src/main.py"):
        if candidate in file_set:
            _append_unique(entrypoints, f"python {candidate}")
    if "index.html" in lower_files:
        _append_unique(entrypoints, "open index.html")

    if any(filename.startswith("tests/") for filename in files):
        _append_unique(test_commands, "python -m pytest")


def _infer_from_configs(
    configs: dict[str, str],
    stack: list[str],
    entrypoints: list[str],
    test_commands: list[str],
) -> None:
    """Infer project facts from manifest/config file contents."""
    for filename, content in configs.items():
        basename = Path(filename).name
        if basename == "package.json":
            _read_package_json(content, stack, entrypoints, test_commands)
        elif basename == "pyproject.toml":
            _read_pyproject(content, stack, entrypoints, test_commands)
        elif basename == "requirements.txt":
            _read_python_requirements(content, stack, test_commands)
        elif basename == "Cargo.toml":
            _append_unique(stack, "Rust")
            _append_unique(test_commands, "cargo test")
        elif basename == "go.mod":
            _append_unique(stack, "Go")
            _append_unique(test_commands, "go test ./...")
        elif basename in {"pom.xml", "build.gradle", "build.gradle.kts"}:
            _append_unique(stack, "Java/JVM")
            command = "mvn test" if basename == "pom.xml" else "gradle test"
            _append_unique(test_commands, command)
        elif Path(filename).suffix in {".csproj", ".fsproj", ".sln"}:
            _append_unique(stack, ".NET")
            _append_unique(test_commands, "dotnet test")
        elif basename.startswith("docker-compose") or basename == "Dockerfile":
            _append_unique(stack, "Docker")
        elif basename.startswith("vite.config"):
            _append_unique(stack, "Vite")
        elif basename.startswith("next.config"):
            _append_unique(stack, "Next.js")


def _read_package_json(
    content: str,
    stack: list[str],
    entrypoints: list[str],
    test_commands: list[str],
) -> None:
    """Read Node stack details from package.json."""
    try:
        package = json.loads(content)
    except json.JSONDecodeError:
        return
    if not isinstance(package, dict):
        return

    _append_unique(stack, "Node.js")
    scripts = package.get("scripts")
    if isinstance(scripts, dict):
        for name in ("dev", "start"):
            if isinstance(scripts.get(name), str):
                command = "npm start" if name == "start" else f"npm run {name}"
                _append_unique(entrypoints, command)
        for name, command in scripts.items():
            if not isinstance(name, str) or not isinstance(command, str):
                continue
            if any(hint in name.casefold() for hint in _TEST_SCRIPT_HINTS):
                _append_unique(
                    test_commands,
                    "npm test" if name == "test" else f"npm run {name}",
                )

    deps = _package_dependencies(package)
    _append_dependency_stack(deps, stack)


def _read_pyproject(
    content: str,
    stack: list[str],
    entrypoints: list[str],
    test_commands: list[str],
) -> None:
    """Read Python stack details from pyproject.toml."""
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return

    _append_unique(stack, "Python")
    project = data.get("project", {})
    dependencies: list[str] = []
    if isinstance(project, dict):
        raw_dependencies = project.get("dependencies", [])
        if isinstance(raw_dependencies, list):
            dependencies.extend(str(item) for item in raw_dependencies)
        scripts = project.get("scripts", {})
        if isinstance(scripts, dict):
            for name in scripts:
                if isinstance(name, str):
                    _append_unique(entrypoints, name)

    optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
    if isinstance(optional, dict):
        for values in optional.values():
            if isinstance(values, list):
                dependencies.extend(str(item) for item in values)

    dependency_text = "\n".join(dependencies).casefold()
    if "streamlit" in dependency_text:
        _append_unique(stack, "Streamlit")
    if "langgraph" in dependency_text:
        _append_unique(stack, "LangGraph")
    if "langchain" in dependency_text:
        _append_unique(stack, "LangChain")
    if "chromadb" in dependency_text:
        _append_unique(stack, "ChromaDB/RAG")
    if "mcp" in dependency_text:
        _append_unique(stack, "MCP")
    tool = data.get("tool", {})
    has_pytest_config = isinstance(tool, dict) and "pytest" in tool
    if "pytest" in dependency_text or has_pytest_config:
        _append_unique(test_commands, "python -m pytest")


def _read_python_requirements(
    content: str, stack: list[str], test_commands: list[str]
) -> None:
    """Read coarse Python framework hints from requirements.txt."""
    _append_unique(stack, "Python")
    text = content.casefold()
    if "streamlit" in text:
        _append_unique(stack, "Streamlit")
    if "fastapi" in text:
        _append_unique(stack, "FastAPI")
    if "django" in text:
        _append_unique(stack, "Django")
    if "flask" in text:
        _append_unique(stack, "Flask")
    if "pytest" in text:
        _append_unique(test_commands, "python -m pytest")


def _package_dependencies(package: dict[str, Any]) -> set[str]:
    """Return package dependency names in lowercase."""
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = package.get(key)
        if isinstance(value, dict):
            names.update(str(name).casefold() for name in value)
    return names


def _append_dependency_stack(deps: set[str], stack: list[str]) -> None:
    """Add framework labels from Node dependency names."""
    if "react" in deps:
        _append_unique(stack, "React")
    if "next" in deps:
        _append_unique(stack, "Next.js")
    if "vite" in deps or "@vitejs/plugin-react" in deps:
        _append_unique(stack, "Vite")
    if "typescript" in deps:
        _append_unique(stack, "TypeScript")
    if "tailwindcss" in deps:
        _append_unique(stack, "Tailwind CSS")
    if "vitest" in deps:
        _append_unique(stack, "Vitest")
    if "@playwright/test" in deps or "playwright" in deps:
        _append_unique(stack, "Playwright")


def _infer_git_risks(git_status: str, risks: list[str]) -> None:
    """Add git-state risks to the brief."""
    if not git_status:
        return
    if "not a git repository" in git_status:
        risks.append("Selected folder is not a git repository; git diff safety is limited.")
        return
    dirty_lines = [
        line
        for line in git_status.splitlines()
        if line.strip() and not line.startswith("## ")
    ]
    if dirty_lines:
        risks.append(
            "Selected repository has uncommitted changes; avoid mixing new "
            "agent output with existing work."
        )


def _brief_summary(
    *,
    project_path: str,
    stack: list[str],
    entrypoints: list[str],
    test_commands: list[str],
    risks: list[str],
) -> str:
    """Build the human-readable project brief summary."""
    stack_text = ", ".join(stack[:6])
    entry_text = ", ".join(entrypoints[:4])
    test_text = ", ".join(test_commands[:4]) if test_commands else "none detected"
    risk_text = "; ".join(risks[:3]) if risks else "no obvious project-level risks"
    return (
        f"Project brief for {project_path}: stack={stack_text}; "
        f"entrypoints={entry_text}; tests={test_text}; risks={risk_text}."
    )


def _append_unique(items: list[str], value: str) -> None:
    """Append a value once while preserving order."""
    if value not in items:
        items.append(value)
