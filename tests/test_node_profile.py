"""Tests for the Node.js (node_js) profile: validation and structural QA."""

from __future__ import annotations

from app.graph.code_validation import validate_code_files
from app.graph.node_qa import node_qa_update


def test_node_validation_accepts_multi_file_js():
    error = validate_code_files(
        {
            "stack.js": "export class Stack {}\n",
            "package.json": '{"type":"module"}\n',
        },
        profile="node_js",
    )
    assert error is None


def test_node_validation_requires_at_least_one_script():
    error = validate_code_files({"package.json": "{}\n"}, profile="node_js")
    assert error is not None
    assert "at least one JavaScript" in error


def test_node_validation_rejects_unsupported_suffix():
    error = validate_code_files({"main.py": "print(1)\n"}, profile="node_js")
    assert error is not None
    assert "unsupported filename" in error


def test_node_qa_passes_for_exported_balanced_module():
    update = node_qa_update(
        {"code": {"adder.js": "export function add(a, b) { return a + b; }\n"}}
    )
    assert update["test_results"].failed == 0
    assert update["test_results"].passed > 0
    assert "review_feedback" not in update


def test_node_qa_flags_missing_export_and_unbalanced_braces():
    update = node_qa_update(
        {"code": {"broken.js": "function add(a, b) { return a + b;\n"}}
    )
    results = update["test_results"]
    assert results.failed > 0
    # A failure folds into review feedback as a BLOCKER for the fix loop.
    feedback = update["review_feedback"]
    assert any(item.severity == "BLOCKER" for item in feedback)
