"""Persistent project state — tracks progress so we can resume after crashes."""

import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone


STATE_FILE = ".orchestrator/project-state.json"


def _state_path(workspace: str) -> Path:
    return Path(workspace) / STATE_FILE


def save_state(workspace: str, state: dict):
    """Write project state to disk."""
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    bak = path.with_suffix(".json.bak")
    # Write to temp file
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    # Backup current state
    if path.exists():
        shutil.copy2(path, bak)
    # Atomic rename
    os.replace(tmp, path)


def load_state(workspace: str) -> dict | None:
    """Load project state from disk. Returns None if no state exists."""
    path = _state_path(workspace)
    bak = path.with_suffix(".json.bak")
    for p in [path, bak]:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return None


def has_state(workspace: str) -> bool:
    """Check if a resumable project state exists."""
    return _state_path(workspace).exists()


def clear_state(workspace: str):
    """Remove project state file."""
    path = _state_path(workspace)
    path.unlink(missing_ok=True)


def make_initial_state(
    project_description: str,
    vision: str,
    sprints: list[dict],
) -> dict:
    """Create the initial project state after planning."""
    return {
        "version": 1,
        "project_description": project_description,
        "vision": vision,
        "sprints": sprints,
        "phase": "planned",  # planned, negotiation, implementation, review, complete
        "current_sprint": 0,  # 0 = not started, 1+ = sprint number
        "current_sprint_phase": None,  # negotiation, implementation, or None
        "completed_sprints": [],  # list of sprint numbers
        "contracts": {},  # sprint_num -> contract text
        "deferred_items": [],
    }
