"""Tests for the pure helper functions used by the workflow nodes."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

import app.graph.analyst_step as analyst_step
import app.graph.developer_step as developer_step
import app.graph.project_intake as project_intake
import app.graph.rag_step as rag_step
from app.agents.analyst import PlanOutput
from app.agents.developer import CodeFile, CodeOutput
from app.agents.project_context import project_context_section
from app.graph.advisory_qa import advisory_qa_update as _advisory_qa_update
from app.graph.code_utils import strip_code_fences as _strip_code_fences
from app.graph.code_validation import validate_code_files as _validate_code_files
from app.graph.nodes import (
    _clean_developer_approach,
    _clean_plan,
    analyst_node,
    developer_node,
    rag_node,
    task_classifier_node,
)
from app.graph.project_intake import (
    project_focus_terms as _project_focus_terms,
)
from app.graph.project_intake import project_intake_node
from app.graph.project_intake import (
    project_relevant_files as _project_relevant_files,
)
from app.graph.project_intake import project_summary as _project_summary
from app.graph.pytest_utils import build_test_imports as _build_test_imports
from app.graph.pytest_utils import count_pattern as _count
from app.graph.pytest_utils import parse_pytest as _parse_pytest
from app.graph.pytest_utils import public_names as _public_names
from app.graph.static_web_qa import broken_local_asset_refs as _broken_local_asset_refs
from app.graph.static_web_qa import static_web_qa_update as _static_web_qa_update
from app.rag.retriever import RetrievalResult, RetrievedChunk


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("```python\ncode\n```", "code"),
        ("```\ncode\n```", "code"),
        ("plain code", "plain code"),
        ("def f():\n    pass", "def f():\n    pass"),
    ],
)
def test_strip_code_fences(raw, expected):
    assert _strip_code_fences(raw) == expected


@pytest.mark.parametrize(
    "pattern,text,expected",
    [
        (r"(\d+) passed", "5 passed", 5),
        (r"(\d+) failed", "no match here", 0),
        (r"(\d+) passed", "16 passed, 2 failed", 16),
    ],
)
def test_count(pattern, text, expected):
    assert _count(pattern, text) == expected


def test_public_names_extracts_classes_and_functions():
    code = "class Foo:\n    pass\n\n\ndef bar():\n    pass\n"
    assert _public_names(code) == ["Foo", "bar"]


def test_public_names_excludes_private_names():
    code = "def _hidden():\n    pass\n\n\ndef visible():\n    pass\n"
    assert _public_names(code) == ["visible"]


def test_public_names_returns_empty_on_a_syntax_error():
    assert _public_names("def broken(:\n") == []


def test_build_test_imports_adds_missing_imports():
    header = _build_test_imports(
        "def test_x(): pass", {"calc.py": "def add(): pass"}
    )
    assert "import pytest" in header
    assert "from calc import add" in header


def test_build_test_imports_skips_imports_already_present():
    test_code = "import pytest\nfrom calc import add\n\ndef test_x(): pass"
    header = _build_test_imports(test_code, {"calc.py": "def add(): pass"})
    assert header == ""


def test_parse_pytest_reads_pass_and_fail_counts():
    results = _parse_pytest("16 passed, 2 failed in 0.1s")
    assert results.passed == 16
    assert results.failed == 2
    assert results.total == 18


def test_parse_pytest_treats_a_timeout_as_a_failure():
    results = _parse_pytest("TIMEOUT: test execution exceeded the time limit")
    assert results.failed == 1
    assert results.passed == 0


def test_parse_pytest_treats_no_tests_as_a_failure():
    results = _parse_pytest("no tests ran in 0.01s")
    assert results.failed == 1
    assert results.passed == 0
    assert results.total == 1


def test_parse_pytest_treats_skipped_only_runs_as_a_failure():
    results = _parse_pytest("1 skipped in 0.01s")
    assert results.failed == 1
    assert results.passed == 0
    assert results.total == 1


def test_validate_code_files_accepts_a_simple_python_module():
    assert _validate_code_files({"calculator.py": "def add(a, b):\n    return a + b\n"}) is None


def test_validate_code_files_rejects_empty_output():
    assert "no source files" in (_validate_code_files({}) or "")


def test_validate_code_files_rejects_unsupported_filenames():
    error = _validate_code_files({"src/calculator.py": "def add():\n    return 1\n"})
    assert error is not None
    assert "unsupported filename" in error


def test_validate_code_files_rejects_syntax_errors():
    error = _validate_code_files({"calculator.py": "def broken(:\n"})
    assert error is not None
    assert "invalid Python" in error


def test_validate_code_files_accepts_static_web_artifacts():
    error = _validate_code_files(
        {
            "index.html": (
                "<!doctype html><html><head><title>Cars</title></head>"
                "<body><h1>Arabalar</h1></body></html>"
            ),
            "assets/style.css": "body { font-family: sans-serif; }",
        },
        profile="static_web",
    )

    assert error is None


def test_validate_code_files_rejects_unsafe_static_web_paths():
    error = _validate_code_files(
        {"../index.html": "<!doctype html><html></html>"},
        profile="static_web",
    )

    assert error is not None
    assert "unsafe project filename" in error


def test_validate_code_files_rejects_static_web_without_html():
    error = _validate_code_files({"style.css": "body {}"}, profile="static_web")

    assert error is not None
    assert "at least one HTML file" in error


def test_validate_code_files_accepts_project_advisory_output():
    error = _validate_code_files(
        {
            "PROJECT_PROPOSAL.md": (
                "# Observations\n\n"
                "- Existing page content should be preserved.\n\n"
                "# Next Steps\n\n"
                "1. Add scoped styling after preview."
            )
        },
        profile="project",
    )

    assert error is None


def test_validate_code_files_accepts_docs_markdown_output():
    error = _validate_code_files(
        {"README.md": "# Usage\n\n- Run `python -m pytest`."},
        profile="docs",
    )

    assert error is None


def test_validate_code_files_rejects_project_source_artifacts():
    error = _validate_code_files(
        {"index.html": "<!doctype html><html><body>x</body></html>"},
        profile="project",
    )

    assert error is not None
    assert "PROJECT_PROPOSAL.md" in error


def test_clean_plan_removes_blank_steps():
    assert _clean_plan(["  first  ", "", "   ", "second"]) == ["first", "second"]


def test_clean_developer_approach_replaces_format_label():
    assert (
        _clean_developer_approach("markdown", "Produced a grounded proposal.")
        == "Produced a grounded proposal."
    )


def test_project_focus_terms_remove_generic_words():
    terms = _project_focus_terms("Projeyi workflow ve integrator state için geliştir")

    assert "projeyi" not in terms
    assert "workflow" in terms
    assert "integrator" in terms
    assert "state" in terms


def test_project_relevant_files_prefers_matches_then_fallbacks():
    files = ["README.md", "app/graph/nodes.py", "app/ui/streamlit_app.py"]
    matches = [{"file": "app/graph/nodes.py", "line": 10, "text": "project"}]

    assert _project_relevant_files(files, matches) == [
        "app/graph/nodes.py",
        "README.md",
        "app/ui/streamlit_app.py",
    ]


def test_project_summary_reports_non_git_without_dirty_state():
    summary = _project_summary(
        files=[],
        matches=[],
        relevant_files=[],
        git_status="not a git repository: /tmp/example",
    )

    assert "a non-git folder" in summary
    assert "dirty git tree" not in summary


def test_project_context_section_is_empty_outside_project_mode():
    assert project_context_section({"task": "x", "mode": "generate"}) == ""


def test_project_context_section_includes_project_intake_fields():
    section = project_context_section(
        {
            "task": "x",
            "mode": "project",
            "task_profile": "python",
            "project_summary": "Scanned files.",
            "project_relevant_files": ["app/graph/nodes.py"],
            "project_search_matches": [
                {
                    "file": "app/graph/nodes.py",
                    "line": 10,
                    "text": "project intake",
                }
            ],
            "project_git_status": "## main\n M app/graph/nodes.py",
            "project_git_diff": " app/graph/nodes.py | 10 +++++",
        }
    )

    assert "PROJECT CONTEXT" in section
    assert "Scanned files." in section
    assert "app/graph/nodes.py:10: project intake" in section
    assert "GIT STATUS" in section


def test_project_context_section_includes_project_brief_fields():
    section = project_context_section(
        {
            "task": "x",
            "mode": "project",
            "task_profile": "python",
            "project_brief": "Project brief: Python app.",
            "project_stack": ["Python", "Streamlit"],
            "project_entrypoints": ["streamlit run app/ui/streamlit_app.py"],
            "project_test_commands": ["python -m pytest"],
            "project_risks": ["dirty git tree"],
        }
    )

    assert "PROJECT BRIEF" in section
    assert "Python app" in section
    assert "streamlit run app/ui/streamlit_app.py" in section
    assert "python -m pytest" in section
    assert "dirty git tree" in section


def test_project_context_section_includes_project_memory():
    section = project_context_section(
        {
            "task": "x",
            "mode": "project",
            "task_profile": "python",
            "project_memory": "Last task: [SUCCESS] stabilize Project Mode.",
        }
    )

    assert "PROJECT MEMORY" in section
    assert "stabilize Project Mode" in section


def test_project_context_section_includes_file_excerpts():
    section = project_context_section(
        {
            "task": "Analyze this project",
            "mode": "project",
            "task_profile": "project",
            "project_file_excerpts": [
                {
                    "file": "index.html",
                    "content": "<title>Space Journey</title><h1>Stars</h1>",
                    "truncated": False,
                }
            ],
        }
    )

    assert "RELEVANT FILE EXCERPTS" in section
    assert "preserve existing intent" in section
    assert "Space Journey" in section


def test_project_context_section_marks_static_web_artifacts_as_output():
    section = project_context_section(
        {
            "task": "Basit HTML sayfası oluştur",
            "mode": "project",
            "task_profile": "static_web",
            "project_summary": "Scanned files.",
            "project_relevant_files": ["app/agents/static_web_developer.py"],
        }
    )

    assert "TASK PROFILE" in section
    assert "static_web" in section
    assert "OUTPUT RULE" in section
    assert "index.html" in section
    assert "context only" in section


async def test_project_intake_node_is_noop_outside_project_mode(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("project tools should not be opened")

    monkeypatch.setattr(project_intake, "project_tools", fail_if_called)

    assert await project_intake_node({"task": "x", "mode": "generate"}) == {}


async def test_project_intake_node_collects_repository_context(monkeypatch, tmp_path):
    class FakeProjectTools:
        async def root_path(self):
            return str(tmp_path.resolve())

        async def list_files(self, max_files=200):
            assert max_files == 250
            return [
                "README.md",
                "app/graph/nodes.py",
                "app/ui/streamlit_app.py",
            ]

        async def search_text(self, pattern, max_matches=50):
            assert "workflow" in pattern
            assert max_matches == 60
            return [
                {
                    "file": "app/graph/nodes.py",
                    "line": 12,
                    "text": "workflow project intake",
                }
            ]

        async def read_file(self, filename):
            return f"content from {filename}"

        async def git_status(self):
            return "## main...origin/main\n M app/graph/nodes.py\n"

        async def git_diff(self, max_chars=6000):
            assert max_chars == 6000
            return " app/graph/nodes.py | 10 +++++\n"

    @asynccontextmanager
    async def fake_project_tools(root):
        assert root == tmp_path.resolve()
        yield FakeProjectTools()

    monkeypatch.setattr(project_intake, "project_tools", fake_project_tools)

    update = await project_intake_node(
        {
            "task": "workflow project intake",
            "mode": "project",
            "project_path": str(tmp_path),
        }
    )

    assert update["project_files"] == [
        "README.md",
        "app/graph/nodes.py",
        "app/ui/streamlit_app.py",
    ]
    assert update["project_relevant_files"][0] == "app/graph/nodes.py"
    assert update["project_search_matches"][0]["line"] == 12
    assert update["project_path"] == str(tmp_path.resolve())
    assert update["project_mcp_root"] == str(tmp_path.resolve())
    assert update["project_path_mismatch"] is False
    assert "a dirty git tree" in update["project_summary"]
    assert update["project_focus_terms"] == ["workflow", "intake"]
    assert update["project_file_excerpts"][0] == {
        "file": "app/graph/nodes.py",
        "content": "content from app/graph/nodes.py",
        "truncated": False,
    }


async def test_project_intake_node_aborts_when_mcp_root_differs(
    monkeypatch, tmp_path
):
    selected = tmp_path / "selected"
    selected.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    class FakeProjectTools:
        async def root_path(self):
            return str(other)

        async def list_files(self, max_files=200):
            raise AssertionError("intake should stop before scanning files")

    @asynccontextmanager
    async def fake_project_tools(root):
        assert root == selected.resolve()
        yield FakeProjectTools()

    monkeypatch.setattr(project_intake, "project_tools", fake_project_tools)

    update = await project_intake_node(
        {
            "task": "Basit HTML sayfası oluştur",
            "mode": "project",
            "project_path": str(selected),
        }
    )

    assert update["status"] == "FAILED"
    assert update["should_abort"] is True
    assert update["project_path_mismatch"] is True
    assert update["project_path"] == str(selected.resolve())
    assert update["project_mcp_root"] == str(other.resolve())
    assert "Project path mismatch" in update["node_error"]


async def test_task_classifier_node_selects_static_web_profile():
    update = await task_classifier_node(
        {"task": "Basit HTML sayfası yaz", "mode": "project"}
    )

    assert update["task_profile"] == "static_web"
    assert "static web" in update["task_profile_reason"]


async def test_task_classifier_node_selects_static_web_for_create_word():
    update = await task_classifier_node(
        {"task": "Basit bir HTML sayfası oluştur", "mode": "project"}
    )

    assert update["task_profile"] == "static_web"


async def test_task_classifier_node_selects_project_for_turkish_analysis():
    update = await task_classifier_node(
        {"task": "Bu projeyi analiz et ve güvenli öneri çıkar", "mode": "project"}
    )

    assert update["task_profile"] == "project"


async def test_task_classifier_node_keeps_html_analysis_advisory():
    update = await task_classifier_node(
        {"task": "Bu HTML projesini incele ve riskleri çıkar", "mode": "project"}
    )

    assert update["task_profile"] == "project"


async def test_task_classifier_node_selects_static_when_html_change_is_explicit():
    update = await task_classifier_node(
        {"task": "Mevcut HTML sayfasını değiştir", "mode": "project"}
    )

    assert update["task_profile"] == "static_web"


async def test_task_classifier_node_selects_project_for_learn_project():
    update = await task_classifier_node(
        {"task": "Bu projeyi detaylı öğren", "mode": "project"}
    )

    assert update["task_profile"] == "project"


async def test_task_classifier_node_selects_python_for_student_class_request():
    update = await task_classifier_node(
        {"task": "bir python class yaz ve öğrenciler için olsun", "mode": "project"}
    )

    assert update["task_profile"] == "python"
    assert "Python/code artifact" in update["task_profile_reason"]


async def test_task_classifier_node_uses_router_implementation_signal_for_python_artifact():
    update = await task_classifier_node(
        {
            "task": "python sınıfı öğrenciler için olsun",
            "mode": "project",
            "project_chat_intent": "implementation",
            "project_chat_action": "modify_project",
        }
    )

    assert update["task_profile"] == "python"
    assert "routed this as implementation" in update["task_profile_reason"]


async def test_task_classifier_node_treats_python_artifact_as_code_in_project_mode():
    update = await task_classifier_node(
        {"task": "öğrenci bilgisi tutan class olsun", "mode": "project"}
    )

    assert update["task_profile"] == "python"
    assert "Python/code artifact" in update["task_profile_reason"]


async def test_task_classifier_node_does_not_match_student_as_learn_project():
    update = await task_classifier_node(
        {"task": "öğrenci bilgisi tutan class yaz", "mode": "project"}
    )

    assert update["task_profile"] == "python"


async def test_task_classifier_node_keeps_ambiguous_project_chat_advisory():
    update = await task_classifier_node({"task": "sen kimsin", "mode": "project"})

    assert update["task_profile"] == "project"
    assert "ambiguous chat" in update["task_profile_reason"]


async def test_task_classifier_node_keeps_broad_project_fix_advisory():
    update = await task_classifier_node(
        {"task": "Projeyi düzelt", "mode": "project"}
    )

    assert update["task_profile"] == "project"


async def test_developer_node_uses_static_web_agent_for_static_profile(monkeypatch):
    async def fail_python_developer(self, state):
        raise AssertionError("Python developer should not run")

    async def static_developer(self, state):
        return CodeOutput(
            approach="Create an HTML artifact.",
            assumptions=[],
            files=[
                CodeFile(
                    filename="index.html",
                    content=(
                        "<!doctype html><html><head><title>Arabalar</title></head>"
                        "<body><h1>Arabalar</h1></body></html>"
                    ),
                )
            ],
            summary="Created a cars page.",
        )

    monkeypatch.setattr(developer_step, "get_pool", lambda: object())
    monkeypatch.setattr(developer_step.DeveloperAgent, "run", fail_python_developer)
    monkeypatch.setattr(
        developer_step.StaticWebDeveloperAgent,
        "run",
        static_developer,
    )

    update = await developer_node(
        {
            "task": "Basit bir HTML sayfası oluştur",
            "task_profile": "static_web",
        }
    )

    assert update["code"] == {
        "index.html": (
            "<!doctype html><html><head><title>Arabalar</title></head>"
            "<body><h1>Arabalar</h1></body></html>"
        )
    }
    assert "node_error" not in update


async def test_developer_node_uses_project_advisor_for_project_profile(monkeypatch):
    async def fail_python_developer(self, state):
        raise AssertionError("Python developer should not run")

    async def project_advisor(self, state):
        return CodeOutput(
            approach="Analyze the existing project without changing artifacts.",
            assumptions=["The task asks for a proposal, not implementation."],
            files=[
                CodeFile(
                    filename="PROJECT_PROPOSAL.md",
                    content=(
                        "# Observations\n\n"
                        "- Existing `index.html` content is the source of truth.\n\n"
                        "# Risks\n\n"
                        "- No git repository is present.\n\n"
                        "# Next Steps\n\n"
                        "1. Preserve the current page topic before styling changes."
                    ),
                )
            ],
            summary="Produced a grounded project proposal.",
        )

    monkeypatch.setattr(developer_step, "get_pool", lambda: object())
    monkeypatch.setattr(developer_step.DeveloperAgent, "run", fail_python_developer)
    monkeypatch.setattr(developer_step.ProjectAdvisorAgent, "run", project_advisor)

    update = await developer_node(
        {
            "task": "Analyze this project in Project Mode",
            "task_profile": "project",
        }
    )

    assert set(update["code"]) == {"PROJECT_PROPOSAL.md"}
    assert "node_error" not in update


async def test_developer_node_uses_project_advisory_fallback(monkeypatch):
    async def invalid_project_advisor(self, state):
        return CodeOutput(
            approach="Rewrite the page.",
            assumptions=[],
            files=[
                CodeFile(
                    filename="index.html",
                    content="<h1>Generic replacement</h1>",
                )
            ],
            summary="Returned the wrong artifact.",
        )

    monkeypatch.setattr(developer_step, "get_pool", lambda: object())
    monkeypatch.setattr(developer_step.ProjectAdvisorAgent, "run", invalid_project_advisor)

    update = await developer_node(
        {
            "task": "Projeyi kısaca analiz et ve sonraki güvenli adımı öner.",
            "task_profile": "project",
            "project_summary": "Scanned one static HTML page.",
            "project_relevant_files": ["index.html"],
            "project_risks": ["Selected folder is not a git repository."],
            "project_file_excerpts": [
                {
                    "file": "index.html",
                    "content": (
                        "<title>Exploring Space</title>"
                        "<h1>Welcome to the World of Space</h1>"
                    ),
                }
            ],
        }
    )

    assert set(update["code"]) == {"PROJECT_PROPOSAL.md"}
    assert "Exploring Space" in update["code"]["PROJECT_PROPOSAL.md"]
    assert (
        "Selected folder is not a git repository"
        in update["code"]["PROJECT_PROPOSAL.md"]
    )
    assert "node_error" not in update


async def test_developer_node_uses_docs_advisor_for_docs_profile(monkeypatch):
    async def fail_python_developer(self, state):
        raise AssertionError("Python developer should not run")

    async def fail_project_advisor(self, state):
        raise AssertionError("Project advisor should not run for docs profile")

    async def docs_advisor(self, state):
        return CodeOutput(
            approach="Update documentation from observed context.",
            assumptions=[],
            files=[
                CodeFile(
                    filename="README.md",
                    content="# Usage\n\n- Run `python -m pytest` before committing.",
                )
            ],
            summary="Updated README guidance.",
        )

    monkeypatch.setattr(developer_step, "get_pool", lambda: object())
    monkeypatch.setattr(developer_step.DeveloperAgent, "run", fail_python_developer)
    monkeypatch.setattr(developer_step.ProjectAdvisorAgent, "run", fail_project_advisor)
    monkeypatch.setattr(developer_step.DocsAdvisorAgent, "run", docs_advisor)

    update = await developer_node(
        {
            "task": "README dokümantasyonunu güncelle",
            "task_profile": "docs",
        }
    )

    assert set(update["code"]) == {"README.md"}
    assert "node_error" not in update


async def test_developer_node_repairs_invalid_python_with_validation_feedback(
    monkeypatch,
):
    calls = []

    async def developer_run(self, state):
        calls.append(state)
        if len(calls) == 1:
            return CodeOutput(
                approach="Create the counting function.",
                assumptions=[],
                files=[
                    CodeFile(
                        filename="counting.py",
                        content="def count_to_100(:\n",
                    )
                ],
                summary="Returned invalid Python.",
            )

        feedback = state.get("review_feedback") or []
        assert state["code"] == {"counting.py": "def count_to_100(:\n"}
        assert feedback
        assert "failed deterministic validation" in feedback[-1].issue
        assert "invalid Python" in feedback[-1].issue
        return CodeOutput(
            approach="Fixed the syntax error.",
            assumptions=[],
            files=[
                CodeFile(
                    filename="counting.py",
                    content=(
                        "def count_to_100() -> None:\n"
                        "    \"\"\"Print numbers from 1 to 100.\"\"\"\n"
                        "    for number in range(1, 101):\n"
                        "        print(number)\n\n\n"
                        "if __name__ == \"__main__\":\n"
                        "    count_to_100()\n"
                    ),
                )
            ],
            summary="Fixed counting function.",
        )

    monkeypatch.setattr(developer_step, "get_pool", lambda: object())
    monkeypatch.setattr(developer_step.DeveloperAgent, "run", developer_run)

    update = await developer_node(
        {
            "task": "Yeni bir Python dosyası oluştur, 1-100'e kadar saysın.",
            "task_profile": "python",
        }
    )

    assert update["code"]["counting.py"].startswith("def count_to_100")
    assert update["dev_repair_attempted"] is True
    assert "node_error" not in update
    assert len(calls) == 2


async def test_developer_node_exposes_rejected_code_after_failed_repair(monkeypatch):
    async def developer_run(self, state):
        return CodeOutput(
            approach="Create broken code.",
            assumptions=[],
            files=[
                CodeFile(
                    filename="counting.py",
                    content="def count_to_100(:\n",
                )
            ],
            summary="Returned invalid Python.",
        )

    monkeypatch.setattr(developer_step, "get_pool", lambda: object())
    monkeypatch.setattr(developer_step.DeveloperAgent, "run", developer_run)

    update = await developer_node(
        {
            "task": "Yeni bir Python dosyası oluştur, 1-100'e kadar saysın.",
            "task_profile": "python",
        }
    )

    assert update["status"] == "FAILED"
    assert update["should_abort"] is True
    assert update["dev_repair_attempted"] is True
    assert "invalid Python" in update["dev_validation_error"]
    assert update["dev_rejected_code"] == {"counting.py": "def count_to_100(:\n"}


def test_static_web_qa_passes_complete_page(tmp_path):
    update = _static_web_qa_update(
        {
            "task": "Basit HTML sayfası yaz",
            "task_profile": "static_web",
            "project_path": str(tmp_path),
            "code": {
                "index.html": (
                    "<!doctype html><html><head><title>Arabalar</title></head>"
                    "<body><h1>Arabalar</h1></body></html>"
                )
            },
        }
    )

    assert update["test_results"].failed == 0
    assert update["test_results"].passed > 0


def test_static_web_qa_reports_broken_local_asset(tmp_path):
    failures = _broken_local_asset_refs(
        {
            "index.html": (
                "<!doctype html><html><head><title>x</title>"
                "<link rel='stylesheet' href='missing.css'></head>"
                "<body><h1>x</h1></body></html>"
            )
        },
        str(tmp_path),
    )

    assert failures == ["index.html -> missing.css"]


def test_static_web_qa_reports_escaping_local_asset(tmp_path):
    failures = _broken_local_asset_refs(
        {
            "index.html": (
                "<!doctype html><html><head><title>x</title>"
                "<link rel='stylesheet' href='../outside.css'></head>"
                "<body><h1>x</h1></body></html>"
            )
        },
        str(tmp_path),
    )

    assert failures == ["index.html -> ../outside.css (escapes project folder)"]


def test_advisory_qa_passes_grounded_project_proposal():
    update = _advisory_qa_update(
        {
            "task_profile": "project",
            "project_file_excerpts": [
                {
                    "file": "index.html",
                    "content": "<title>Exploring Space</title><h1>Space</h1>",
                }
            ],
            "code": {
                "PROJECT_PROPOSAL.md": (
                    "# Observations\n\n"
                    "- Existing page content is about space.\n\n"
                    "# Risks\n\n"
                    "- Folder is not a git repository.\n\n"
                    "# Next Steps\n\n"
                    "1. Add styling only after diff preview."
                )
            },
        }
    )

    assert update["test_results"].failed == 0


def test_advisory_qa_requires_observed_project_subject_when_available():
    update = _advisory_qa_update(
        {
            "task_profile": "project",
            "project_file_excerpts": [
                {
                    "file": "index.html",
                    "content": (
                        "<title>Exploring Space</title>"
                        "<h1>Welcome to the World of Space</h1>"
                    ),
                }
            ],
            "code": {
                "PROJECT_PROPOSAL.md": (
                    "# Observations\n\n"
                    "- This is a static HTML site.\n\n"
                    "# Next Steps\n\n"
                    "1. Add semantic HTML structure."
                )
            },
        }
    )

    assert update["test_results"].failed > 0
    assert "title or heading" in update["review_feedback"][0].issue


def test_advisory_qa_blocks_source_artifacts_for_project_profile():
    update = _advisory_qa_update(
        {
            "task_profile": "project",
            "code": {
                "index.html": (
                    "<!doctype html><html><body>Generic replacement</body></html>"
                )
            },
        }
    )

    assert update["test_results"].failed > 0
    assert update["review_feedback"][0].severity == "BLOCKER"


async def test_analyst_node_uses_fallback_when_plan_stays_empty(monkeypatch):
    async def empty_plan(self, state):
        return PlanOutput(steps=["", "   "])

    monkeypatch.setattr(analyst_step, "get_pool", lambda: object())
    monkeypatch.setattr(analyst_step.AnalystAgent, "run", empty_plan)

    update = await analyst_node({"task": "x"})

    assert update["plan"] == ["Implement directly from the task description."]


async def test_rag_node_reports_disabled_status():
    update = await rag_node({"task": "x", "use_rag": False})

    assert update["rag_status"] == "disabled"
    assert update["rag_chunk_count"] == 0


async def test_rag_node_reports_unavailable_status(monkeypatch):
    def unavailable(query, profile=None):
        return RetrievalResult(
            chunks=[],
            status="unavailable",
            message="RAG retrieval unavailable: boom",
        )

    monkeypatch.setattr(rag_step, "retrieve_with_status", unavailable)

    update = await rag_node({"task": "x"})

    assert update["rag_status"] == "unavailable"
    assert update["rag_chunk_count"] == 0
    assert "boom" in update["rag_message"]


async def test_rag_node_reports_retrieved_status(monkeypatch):
    def retrieved(query, profile=None):
        return RetrievalResult(
            chunks=[RetrievedChunk(text="Use type hints.", source="style.md")],
            status="retrieved",
            message="Retrieved 1 RAG chunk(s).",
        )

    monkeypatch.setattr(rag_step, "retrieve_with_status", retrieved)

    update = await rag_node({"task": "x"})

    assert update["rag_status"] == "retrieved"
    assert update["rag_chunk_count"] == 1
    assert update["rag_sources"] == ["style.md"]
