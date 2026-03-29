"""Tests for harness/state.py persistence functions."""

import json
import pytest

from harness.state import (
    clear_state,
    has_state,
    load_state,
    make_initial_state,
    save_state,
)


class TestSaveLoadRoundTrip:
    def test_basic_round_trip(self, tmp_path):
        state = {"phase": "planned", "current_sprint": 1, "data": [1, 2, 3]}
        save_state(str(tmp_path), state)
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded["phase"] == "planned"
        assert loaded["current_sprint"] == 1
        assert loaded["data"] == [1, 2, 3]

    def test_updated_at_is_set(self, tmp_path):
        state = {"phase": "planned"}
        save_state(str(tmp_path), state)
        loaded = load_state(str(tmp_path))
        assert "updated_at" in loaded

    def test_overwrite_preserves_latest(self, tmp_path):
        save_state(str(tmp_path), {"version": 1})
        save_state(str(tmp_path), {"version": 2})
        loaded = load_state(str(tmp_path))
        assert loaded["version"] == 2

    def test_nested_data_survives(self, tmp_path):
        state = {
            "sprints": [{"number": 1, "name": "Setup"}],
            "contracts": {"1": "contract text"},
        }
        save_state(str(tmp_path), state)
        loaded = load_state(str(tmp_path))
        assert loaded["sprints"][0]["name"] == "Setup"
        assert loaded["contracts"]["1"] == "contract text"


class TestHasState:
    def test_empty_dir(self, tmp_path):
        assert has_state(str(tmp_path)) is False

    def test_after_save(self, tmp_path):
        save_state(str(tmp_path), {"phase": "planned"})
        assert has_state(str(tmp_path)) is True

    def test_after_clear(self, tmp_path):
        save_state(str(tmp_path), {"phase": "planned"})
        clear_state(str(tmp_path))
        assert has_state(str(tmp_path)) is False


class TestClearState:
    def test_clear_removes_file(self, tmp_path):
        save_state(str(tmp_path), {"phase": "planned"})
        clear_state(str(tmp_path))
        assert load_state(str(tmp_path)) is None or has_state(str(tmp_path)) is False

    def test_clear_on_empty_dir_no_error(self, tmp_path):
        # Should not raise even if no state file exists
        clear_state(str(tmp_path))

    def test_clear_twice_no_error(self, tmp_path):
        save_state(str(tmp_path), {"phase": "planned"})
        clear_state(str(tmp_path))
        clear_state(str(tmp_path))


class TestMakeInitialState:
    def test_produces_valid_structure(self):
        state = make_initial_state(
            project_description="Build a todo app",
            vision="A simple todo application",
            sprints=[
                {"number": 1, "name": "Setup", "description": "Init project"},
                {"number": 2, "name": "Features", "description": "Add CRUD"},
            ],
        )
        assert state["version"] == 1
        assert state["project_description"] == "Build a todo app"
        assert state["vision"] == "A simple todo application"
        assert len(state["sprints"]) == 2
        assert state["phase"] == "planned"
        assert state["current_sprint"] == 0
        assert state["current_sprint_phase"] is None
        assert state["completed_sprints"] == []
        assert state["contracts"] == {}
        assert state["deferred_items"] == []

    def test_empty_sprints(self):
        state = make_initial_state(
            project_description="Minimal",
            vision="Tiny",
            sprints=[],
        )
        assert state["sprints"] == []
        assert state["phase"] == "planned"

    def test_round_trip_with_save_load(self, tmp_path):
        state = make_initial_state(
            project_description="Test project",
            vision="Test vision",
            sprints=[{"number": 1, "name": "S1", "description": "Sprint 1"}],
        )
        save_state(str(tmp_path), state)
        loaded = load_state(str(tmp_path))
        assert loaded["project_description"] == "Test project"
        assert loaded["sprints"][0]["name"] == "S1"


class TestAtomicWrite:
    def test_backup_file_created(self, tmp_path):
        # First save creates the file, second save should create a backup
        save_state(str(tmp_path), {"version": 1})
        save_state(str(tmp_path), {"version": 2})
        bak = tmp_path / ".orchestrator" / "project-state.json.bak"
        assert bak.exists()
        bak_data = json.loads(bak.read_text(encoding="utf-8"))
        assert bak_data["version"] == 1

    def test_no_backup_on_first_save(self, tmp_path):
        save_state(str(tmp_path), {"version": 1})
        bak = tmp_path / ".orchestrator" / "project-state.json.bak"
        assert not bak.exists()

    def test_tmp_file_cleaned_up(self, tmp_path):
        save_state(str(tmp_path), {"version": 1})
        tmp_file = tmp_path / ".orchestrator" / "project-state.json.tmp"
        assert not tmp_file.exists()


class TestLoadFromBackup:
    def test_load_from_backup_when_main_corrupted(self, tmp_path):
        # Save valid state so backup exists
        save_state(str(tmp_path), {"version": 1, "data": "original"})
        save_state(str(tmp_path), {"version": 2, "data": "updated"})

        # Corrupt the main file
        main_path = tmp_path / ".orchestrator" / "project-state.json"
        main_path.write_text("NOT VALID JSON {{{", encoding="utf-8")

        # load_state should fall back to the backup
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["data"] == "original"

    def test_returns_none_when_both_corrupted(self, tmp_path):
        save_state(str(tmp_path), {"version": 1})
        save_state(str(tmp_path), {"version": 2})

        main_path = tmp_path / ".orchestrator" / "project-state.json"
        bak_path = tmp_path / ".orchestrator" / "project-state.json.bak"
        main_path.write_text("CORRUPT", encoding="utf-8")
        bak_path.write_text("ALSO CORRUPT", encoding="utf-8")

        loaded = load_state(str(tmp_path))
        assert loaded is None

    def test_returns_none_when_no_files(self, tmp_path):
        loaded = load_state(str(tmp_path))
        assert loaded is None
