"""Main orchestrator — runs the full project lifecycle.

Planner (once) -> [Negotiation -> Implementation -> Evaluation] per sprint -> Final Review

Saves state to .orchestrator/project-state.json at every phase transition
so projects can be resumed after crashes.
"""

import re
from pathlib import Path

from harness.events import bus
from harness.planner import run_planner
from harness.negotiation import negotiate_contract
from harness.implementation import implement_and_evaluate
from harness.review import run_final_review
from harness.state import save_state, load_state, has_state, make_initial_state
from harness.utils import git_init, git_commit, ensure_orchestrator_dir, extract_tests_from_contract


def _extract_deferred_items(contract: str) -> list[str]:
    """Extract 'Out of Scope' items from a sprint contract."""
    items = []
    match = re.search(
        r"(?:out of scope|deferred|future sprint)[s]?\s*\n(.*?)(?=\n##|\Z)",
        contract,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        section = match.group(1)
        for line in section.split("\n"):
            line = line.strip()
            if line and (line.startswith("-") or line.startswith("*")):
                item = line.lstrip("-* ").strip()
                if item and len(item) > 5:
                    items.append(item)
    return items


def run_project(project_description: str, workspace: str, web: bool = True, port: int = 8420):
    """Execute the full Harness Claude pipeline (fresh start)."""
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace = str(workspace_path)

    git_init(workspace)
    ensure_orchestrator_dir(workspace)

    # Validate workspace
    try:
        test_file = workspace_path / ".orchestrator" / ".write-test"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("test")
        test_file.unlink()
    except OSError as e:
        bus.emit("error", message=f"Workspace not writable: {e}")
        return

    # Check git is available
    import shutil
    if not shutil.which("git"):
        bus.emit("log", source="Orchestrator", message="WARNING: git not found. State tracking via git commits disabled.")

    # Check claude is available
    if not shutil.which("claude"):
        bus.emit("error", message="Claude Code CLI not found. Install it first: https://claude.ai/code")
        return

    bus.set_audit_log(Path(workspace) / ".orchestrator" / "events.jsonl")

    if web:
        from harness.web import start_web_server
        start_web_server(port)

    bus.emit("log", source="Orchestrator", message=f"Project: {project_description}")
    bus.emit("log", source="Orchestrator", message=f"Workspace: {workspace}")

    # ── Phase 0: Planning ──
    bus.emit("phase_change", phase="planning")

    vision, sprints = run_planner(project_description, workspace)

    if not sprints:
        bus.emit("error", message="Planner produced no sprints. Aborting.")
        return

    bus.emit("log", source="Orchestrator", message=f"Vision: {vision[:200]}")
    bus.emit("log", source="Orchestrator", message=f"{len(sprints)} sprint(s) planned")

    # Save sprint plan
    orch_dir = ensure_orchestrator_dir(workspace)
    plan_path = orch_dir / "sprint-plan.md"
    plan_lines = [f"# Sprint Plan\n\n## Project Vision\n{vision}\n"]
    for s in sprints:
        plan_lines.append(f"\n## Sprint {s['number']}: {s['name']}\n{s['description']}\n")
    plan_path.write_text("\n".join(plan_lines), encoding="utf-8")
    git_commit(workspace, "Add sprint plan")

    # Save initial state
    state = make_initial_state(project_description, vision, sprints)
    save_state(workspace, state)

    # Execute sprints
    _execute_sprints(workspace, state)


def resume_project(workspace: str, web: bool = True, port: int = 8420):
    """Resume a project from saved state."""
    workspace_path = Path(workspace).resolve()
    workspace = str(workspace_path)

    if not has_state(workspace):
        bus.emit("error", message=f"No project state found in {workspace}")
        return

    state = load_state(workspace)
    if state is None:
        bus.emit("error", message="Failed to load project state.")
        return

    ensure_orchestrator_dir(workspace)
    bus.set_audit_log(Path(workspace) / ".orchestrator" / "events.jsonl")

    if web:
        from harness.web import start_web_server
        start_web_server(port)

    bus.emit("log", source="Orchestrator",
             message=f"Resuming project: {state['project_description'][:100]}")
    bus.emit("log", source="Orchestrator",
             message=f"Phase: {state['phase']}, Sprint: {state['current_sprint']}")

    if state["phase"] == "complete":
        bus.emit("log", source="Orchestrator", message="Project already complete.")
        return

    _execute_sprints(workspace, state)


def _execute_sprints(workspace: str, state: dict):
    """Run (or resume) the sprint execution loop."""
    vision = state["vision"]
    sprints = state["sprints"]
    completed_sprints = set(state.get("completed_sprints", []))
    contracts = state.get("contracts", {})
    deferred_items = list(state.get("deferred_items", []))
    total_sprints = len(sprints)

    for sprint in sprints:
        sprint_num = sprint["number"]
        sprint_name = sprint["name"]
        sprint_direction = sprint["description"]

        # Skip already completed sprints
        if sprint_num in completed_sprints:
            bus.emit("log", source="Orchestrator",
                     message=f"Sprint {sprint_num} already complete, skipping")
            continue

        # Augment direction with deferred items
        if deferred_items:
            deferred_text = "\n".join(f"  - {item}" for item in deferred_items)
            sprint_direction += (
                f"\n\nDEFERRED FROM PREVIOUS SPRINTS (consider including these "
                f"if they fit this sprint's scope):\n{deferred_text}"
            )

        bus.emit("sprint_start", sprint=sprint_num, total=total_sprints, name=sprint_name)

        # ── Phase 1: Negotiation ──
        # Check if we already have a contract for this sprint (resuming mid-implementation)
        contract = contracts.get(str(sprint_num))

        if contract is None:
            # Need to negotiate
            bus.emit("phase_change", phase="negotiation")

            state["current_sprint"] = sprint_num
            state["current_sprint_phase"] = "negotiation"
            save_state(workspace, state)

            contract = negotiate_contract(
                planner_direction=sprint_direction,
                project_vision=vision,
                sprint_num=sprint_num,
                workspace=workspace,
            )

            # Save contract to state
            contracts[str(sprint_num)] = contract
            state["contracts"] = contracts

            # Extract deferred items
            new_deferred = _extract_deferred_items(contract)
            if new_deferred:
                deferred_items.extend(new_deferred)

            # Remove deferred items that were addressed in this sprint's contract
            addressed = []
            for item in deferred_items:
                # Check if key words from the deferred item appear in the contract
                words = [w.lower() for w in item.split() if len(w) > 3]
                if words and sum(1 for w in words if w in contract.lower()) >= len(words) * 0.5:
                    addressed.append(item)
            for item in addressed:
                if item in deferred_items:
                    deferred_items.remove(item)
            if addressed:
                bus.emit("log", source="Orchestrator",
                         message=f"Removed {len(addressed)} addressed deferred item(s)")

            # Cap at 20 most recent
            if len(deferred_items) > 20:
                deferred_items = deferred_items[-20:]

            state["deferred_items"] = deferred_items
            if new_deferred:
                bus.emit("log", source="Orchestrator",
                         message=f"Carried {len(new_deferred)} deferred item(s) to future sprints")

            save_state(workspace, state)
        else:
            bus.emit("log", source="Orchestrator",
                     message=f"Sprint {sprint_num} contract loaded from state")
            bus.emit("contract_agreed", sprint=sprint_num, text=contract)

        # Emit test checklist extracted from the contract
        bus.emit("test_checklist", sprint=sprint_num,
                 tests=extract_tests_from_contract(contract))

        # ── Phase 2: Implementation ──
        bus.emit("phase_change", phase="implementation")

        state["current_sprint_phase"] = "implementation"
        save_state(workspace, state)

        final_contract = implement_and_evaluate(
            sprint_num=sprint_num,
            contract=contract,
            project_vision=vision,
            planner_direction=sprint_direction,
            workspace=workspace,
        )

        # Mark sprint complete
        completed_sprints.add(sprint_num)
        state["completed_sprints"] = sorted(completed_sprints)
        contracts[str(sprint_num)] = final_contract
        state["contracts"] = contracts
        state["current_sprint_phase"] = None
        save_state(workspace, state)

        bus.emit("sprint_complete", sprint=sprint_num, name=sprint_name)

    # ── Final Review ──
    bus.emit("phase_change", phase="review")
    state["phase"] = "review"
    save_state(workspace, state)

    review_report = run_final_review(workspace)

    # Save summary
    orch_dir = ensure_orchestrator_dir(workspace)
    summary_path = orch_dir / "project-summary.md"
    summary_lines = [
        f"# Project Summary\n\n",
        f"## Description\n{state['project_description']}\n\n",
        f"## Vision\n{vision}\n\n",
        f"## Sprints Completed: {len(completed_sprints)}\n",
    ]
    for sn in sorted(completed_sprints):
        c = contracts.get(str(sn), "")
        summary_lines.append(f"\n### Sprint {sn}\n{c[:500]}...\n")
    summary_lines.append(f"\n## Final Review\n{review_report[:1000]}...\n")
    summary_path.write_text("".join(summary_lines), encoding="utf-8")

    git_commit(workspace, "Project complete — final review")

    state["phase"] = "complete"
    save_state(workspace, state)
    bus.emit("project_complete", summary_path=str(summary_path))
