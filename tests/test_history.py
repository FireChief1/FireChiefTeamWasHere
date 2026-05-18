"""Tests for the SQLite-backed run history."""

from __future__ import annotations

import app.history as history_module
from app.history import load_history, record_run


def test_history_records_and_loads_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(history_module, "_DB_FILE", tmp_path / "history.db")

    record_run({"task": "task one", "task_id": "a1", "status": "SUCCESS", "iteration": 1})
    record_run({"task": "task two", "task_id": "b2", "status": "FAILED", "iteration": 3})

    history = load_history()
    assert len(history) == 2
    # Most recent run is returned first.
    assert history[0]["task"] == "task two"
    assert history[0]["status"] == "FAILED"
    assert history[1]["task"] == "task one"


def test_load_history_is_empty_when_there_are_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(history_module, "_DB_FILE", tmp_path / "empty.db")
    assert load_history() == []
