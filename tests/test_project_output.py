"""Tests for Project Mode diff preview helpers."""

from __future__ import annotations

from app.graph.project_output import (
    apply_project_files,
    preview_project_files,
    unified_file_diff,
)


def test_unified_file_diff_marks_new_files():
    diff = unified_file_diff("index.html", None, "<!doctype html>\n")

    assert "--- /dev/null" in diff
    assert "+++ index.html" in diff
    assert "+<!doctype html>" in diff


async def test_preview_project_files_reports_create_modify_and_unchanged(tmp_path):
    (tmp_path / "about.html").write_text("old\n")
    (tmp_path / "same.html").write_text("same\n")

    preview = await preview_project_files(
        str(tmp_path),
        {
            "index.html": "new\n",
            "about.html": "new about\n",
            "same.html": "same\n",
        },
    )

    assert preview["integration_file_actions"] == [
        {"file": "index.html", "action": "create"},
        {"file": "about.html", "action": "modify"},
        {"file": "same.html", "action": "unchanged"},
    ]
    assert "--- /dev/null" in preview["integration_diff"]
    assert "--- about.html" in preview["integration_diff"]
    assert "same.html" not in preview["integration_diff"]


async def test_apply_project_files_writes_generated_files(tmp_path):
    result = await apply_project_files(
        str(tmp_path),
        {"index.html": "<!doctype html><html></html>\n"},
    )

    assert result["integration_written_files"] == ["index.html"]
    assert (tmp_path / "index.html").read_text() == "<!doctype html><html></html>\n"
