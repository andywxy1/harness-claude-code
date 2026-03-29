"""Main orchestrator — runs the full project lifecycle.

Supports two modes:
- Sprint mode: Planner splits into sprints, each gets negotiation + implementation + evaluation
- One-pass mode: Planner splits for structure, ONE contract covers everything,
  generator builds it all, evaluator tests adversarially at the end

Saves state to .orchestrator/project-state.json at every phase transition
so projects can be resumed after crashes.
"""

import re
import shutil
from pathlib import Path

from harness.events import bus
from harness.planner import run_planner
from harness.negotiation import negotiate_contract
from harness.implementation import implement_and_evaluate
from harness.review import run_final_review
from harness.state import save_state, load_state, has_state, make_initial_state
from harness.utils import (
    git_init, git_commit, ensure_orchestrator_dir,
    extract_tests_from_contract,
)


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


def _setup_workspace(workspace: str, web: bool = True, port: int = 8420) -> str | None:
    """Common workspace setup for both modes. Returns resolved workspace path or None on error."""
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
        return None

    if not shutil.which("git"):
        bus.emit("log", source="Orchestrator",
                 message="WARNING: git not found.")

    if not shutil.which("claude"):
        bus.emit("error",
                 message="Claude Code CLI not found. Install: https://claude.ai/code")
        return None

    bus.set_audit_log(Path(workspace) / ".orchestrator" / "events.jsonl")

    if web:
        from harness.web import start_web_server
        start_web_server(port)

    # Build skill/agent registries
    from harness.scanner import build_skill_registry, build_agent_registry
    from harness.config import config as harness_config
    selected_skills = harness_config.get_selected_skills()
    selected_agents = harness_config.get_selected_agents()
    if selected_skills:
        build_skill_registry(selected_skills, workspace)
        bus.emit("log", source="Orchestrator",
                 message=f"Skill registry: {len(selected_skills)} skills loaded")
    if selected_agents:
        build_agent_registry(selected_agents, workspace)
        bus.emit("log", source="Orchestrator",
                 message=f"Agent registry: {len(selected_agents)} agents loaded")

    return workspace


# ═══════════════════════════════════════════════════════════
#  SPRINT MODE (existing)
# ═══════════════════════════════════════════════════════════

def run_project(project_description: str, workspace: str,
                web: bool = True, port: int = 8420):
    """Execute the full Harness Claude pipeline — sprint mode."""
    workspace = _setup_workspace(workspace, web, port)
    if workspace is None:
        return

    bus.emit("log", source="Orchestrator", message=f"Mode: Sprint")
    bus.emit("log", source="Orchestrator", message=f"Project: {project_description}")
    bus.emit("log", source="Orchestrator", message=f"Workspace: {workspace}")

    # Planning
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

    state = make_initial_state(project_description, vision, sprints)
    state["mode"] = "sprint"
    save_state(workspace, state)

    _execute_sprints(workspace, state)


def resume_project(workspace: str, web: bool = True, port: int = 8420):
    """Resume a project from saved state (either mode)."""
    workspace_path = Path(workspace).resolve()
    workspace = str(workspace_path)

    if not has_state(workspace):
        bus.emit("error", message=f"No project state found in {workspace}")
        return

    state = load_state(workspace)
    if state is None:
        bus.emit("error", message="Failed to load project state.")
        return

    if web:
        from harness.web import start_web_server
        start_web_server(port)

    bus.set_audit_log(Path(workspace) / ".orchestrator" / "events.jsonl")

    bus.emit("log", source="Orchestrator",
             message=f"Resuming: {state['project_description'][:100]}")
    bus.emit("log", source="Orchestrator",
             message=f"Mode: {state.get('mode', 'sprint')}, "
                     f"Phase: {state['phase']}, Sprint: {state['current_sprint']}")

    if state["phase"] == "complete":
        bus.emit("log", source="Orchestrator", message="Project already complete.")
        return

    mode = state.get("mode", "sprint")
    if mode == "onepass":
        _execute_onepass(workspace, state)
    else:
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

        if sprint_num in completed_sprints:
            bus.emit("log", source="Orchestrator",
                     message=f"Sprint {sprint_num} already complete, skipping")
            continue

        # Augment with deferred items
        if deferred_items:
            deferred_text = "\n".join(f"  - {item}" for item in deferred_items)
            sprint_direction += (
                f"\n\nDEFERRED FROM PREVIOUS SPRINTS (consider including these "
                f"if they fit this sprint's scope):\n{deferred_text}"
            )

        bus.emit("sprint_start", sprint=sprint_num, total=total_sprints, name=sprint_name)

        # Negotiate contract
        contract = contracts.get(str(sprint_num))

        if contract is None:
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

            contracts[str(sprint_num)] = contract
            state["contracts"] = contracts

            # Manage deferred items
            new_deferred = _extract_deferred_items(contract)
            if new_deferred:
                deferred_items.extend(new_deferred)

            # Remove addressed items
            addressed = []
            for item in deferred_items:
                words = [w.lower() for w in item.split() if len(w) > 3]
                if words and sum(1 for w in words if w in contract.lower()) >= len(words) * 0.5:
                    addressed.append(item)
            for item in addressed:
                if item in deferred_items:
                    deferred_items.remove(item)
            if len(deferred_items) > 20:
                deferred_items = deferred_items[-20:]
            state["deferred_items"] = deferred_items

            save_state(workspace, state)
        else:
            bus.emit("log", source="Orchestrator",
                     message=f"Sprint {sprint_num} contract loaded from state")
            bus.emit("contract_agreed", sprint=sprint_num, text=contract)

        # Emit test checklist
        bus.emit("test_checklist", sprint=sprint_num,
                 tests=extract_tests_from_contract(contract))

        # Implement
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

        completed_sprints.add(sprint_num)
        state["completed_sprints"] = sorted(completed_sprints)
        contracts[str(sprint_num)] = final_contract
        state["contracts"] = contracts
        state["current_sprint_phase"] = None
        save_state(workspace, state)

        bus.emit("sprint_complete", sprint=sprint_num, name=sprint_name)

    # Final Review
    bus.emit("phase_change", phase="review")
    state["phase"] = "review"
    save_state(workspace, state)

    review_report = run_final_review(workspace)

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


# ═══════════════════════════════════════════════════════════
#  ONE-PASS MODE
# ═══════════════════════════════════════════════════════════

def run_project_onepass(project_description: str, workspace: str,
                        web: bool = True, port: int = 8420):
    """Execute Harness Claude in one-pass mode — one contract, one build, adversarial eval."""
    workspace = _setup_workspace(workspace, web, port)
    if workspace is None:
        return

    bus.emit("log", source="Orchestrator", message=f"Mode: One-Pass")
    bus.emit("log", source="Orchestrator", message=f"Project: {project_description}")
    bus.emit("log", source="Orchestrator", message=f"Workspace: {workspace}")

    # Planning — still splits into sprints for structure
    bus.emit("phase_change", phase="planning")
    vision, sprints = run_planner(project_description, workspace)

    if not sprints:
        bus.emit("error", message="Planner produced no sprints. Aborting.")
        return

    bus.emit("log", source="Orchestrator", message=f"Vision: {vision[:200]}")
    bus.emit("log", source="Orchestrator",
             message=f"{len(sprints)} phase(s) planned (one-pass: single contract)")

    # Save plan
    orch_dir = ensure_orchestrator_dir(workspace)
    plan_path = orch_dir / "sprint-plan.md"
    plan_lines = [f"# Project Plan (One-Pass)\n\n## Project Vision\n{vision}\n"]
    for s in sprints:
        plan_lines.append(f"\n## Phase {s['number']}: {s['name']}\n{s['description']}\n")
    plan_path.write_text("\n".join(plan_lines), encoding="utf-8")
    git_commit(workspace, "Add project plan")

    state = make_initial_state(project_description, vision, sprints)
    state["mode"] = "onepass"
    save_state(workspace, state)

    _execute_onepass(workspace, state)


def _execute_onepass(workspace: str, state: dict):
    """Execute one-pass mode: one negotiation, one implementation, adversarial eval."""
    vision = state["vision"]
    sprints = state["sprints"]
    contracts = state.get("contracts", {})

    # Build a combined direction from all sprint descriptions
    combined_direction = "This is a ONE-PASS project. Build everything in a single contract.\n\n"
    combined_direction += "The project has these phases (for ordering/structure, NOT separate sprints):\n\n"
    for s in sprints:
        combined_direction += f"### Phase {s['number']}: {s['name']}\n{s['description']}\n\n"
    combined_direction += (
        "Create ONE comprehensive contract covering ALL phases above. "
        "The generator will implement everything at once."
    )

    total_phases = len(sprints)

    # ── Phase 1: Negotiate ONE contract ──
    contract = contracts.get("onepass")

    if contract is None:
        bus.emit("sprint_start", sprint=1, total=1, name="Full Project")
        bus.emit("phase_change", phase="negotiation")

        state["current_sprint"] = 1
        state["current_sprint_phase"] = "negotiation"
        save_state(workspace, state)

        contract = negotiate_contract(
            planner_direction=combined_direction,
            project_vision=vision,
            sprint_num=1,
            workspace=workspace,
        )

        contracts["onepass"] = contract
        state["contracts"] = contracts
        save_state(workspace, state)
    else:
        bus.emit("sprint_start", sprint=1, total=1, name="Full Project")
        bus.emit("log", source="Orchestrator", message="Contract loaded from state")
        bus.emit("contract_agreed", sprint=1, text=contract)

    # Emit test checklist
    bus.emit("test_checklist", sprint=1,
             tests=extract_tests_from_contract(contract))

    # ── Phase 2: Implementation (build everything) ──
    bus.emit("phase_change", phase="implementation")
    state["current_sprint_phase"] = "implementation"
    save_state(workspace, state)

    from harness.config import config as harness_config
    from harness.implementation import implement_and_evaluate

    # Override timeout for one-pass mode
    original_timeout = harness_config.get_timeout("implementation")
    onepass_timeout = harness_config.get_timeout("implementation_onepass")
    harness_config.update_timeout("implementation", onepass_timeout)

    try:
        final_contract = implement_and_evaluate(
            sprint_num=1,
            contract=contract,
            project_vision=vision,
            planner_direction=combined_direction,
            workspace=workspace,
        )
    finally:
        # Restore original timeout
        harness_config.update_timeout("implementation", original_timeout)

    contracts["onepass"] = final_contract
    state["contracts"] = contracts
    state["completed_sprints"] = [1]
    state["current_sprint_phase"] = None
    save_state(workspace, state)

    bus.emit("sprint_complete", sprint=1, name="Full Project")

    # ── Final Review ──
    bus.emit("phase_change", phase="review")
    state["phase"] = "review"
    save_state(workspace, state)

    review_report = run_final_review(workspace)

    orch_dir = ensure_orchestrator_dir(workspace)
    summary_path = orch_dir / "project-summary.md"
    summary_lines = [
        f"# Project Summary (One-Pass)\n\n",
        f"## Description\n{state['project_description']}\n\n",
        f"## Vision\n{vision}\n\n",
        f"## Contract\n{final_contract[:1000]}...\n\n",
        f"## Final Review\n{review_report[:1000]}...\n",
    ]
    summary_path.write_text("".join(summary_lines), encoding="utf-8")

    git_commit(workspace, "Project complete — final review")
    state["phase"] = "complete"
    save_state(workspace, state)
    bus.emit("project_complete", summary_path=str(summary_path))
