"""Main orchestrator — runs the full project lifecycle.

Planner (once) → [Negotiation → Implementation → Evaluation] per sprint → Final Review
"""

from pathlib import Path

from harness.events import bus
from harness.planner import run_planner
from harness.negotiation import negotiate_contract
from harness.implementation import implement_and_evaluate
from harness.review import run_final_review
from harness.utils import git_init, git_commit, ensure_orchestrator_dir


def run_project(project_description: str, workspace: str, web: bool = True, port: int = 8420):
    """Execute the full Harness Claude pipeline.

    Args:
        project_description: Free-text description of what to build.
        workspace: Path to the project directory.
        web: Whether to start the web UI.
        port: Port for the web UI.
    """
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace = str(workspace_path)

    # Initialize git if needed
    git_init(workspace)
    ensure_orchestrator_dir(workspace)

    # Start web UI if requested
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

    bus.emit("log", source="Orchestrator",
             message=f"Vision: {vision[:200]}")
    bus.emit("log", source="Orchestrator",
             message=f"{len(sprints)} sprint(s) planned")

    # Save sprint plan
    orch_dir = ensure_orchestrator_dir(workspace)
    plan_path = orch_dir / "sprint-plan.md"
    plan_lines = [f"# Sprint Plan\n\n## Project Vision\n{vision}\n"]
    for s in sprints:
        plan_lines.append(f"\n## Sprint {s['number']}: {s['name']}\n{s['description']}\n")
    plan_path.write_text("\n".join(plan_lines), encoding="utf-8")

    git_commit(workspace, "Add sprint plan")

    # ── Execute each sprint ──
    completed_contracts = []
    total_sprints = len(sprints)

    for sprint in sprints:
        sprint_num = sprint["number"]
        sprint_name = sprint["name"]
        sprint_direction = sprint["description"]

        bus.emit("sprint_start", sprint=sprint_num, total=total_sprints, name=sprint_name)

        # Phase 1: Negotiate contract
        bus.emit("phase_change", phase="negotiation")
        contract = negotiate_contract(
            planner_direction=sprint_direction,
            project_vision=vision,
            sprint_num=sprint_num,
            workspace=workspace,
        )

        # Phase 2: Implement and evaluate
        bus.emit("phase_change", phase="implementation")
        final_contract = implement_and_evaluate(
            sprint_num=sprint_num,
            contract=contract,
            project_vision=vision,
            planner_direction=sprint_direction,
            workspace=workspace,
        )

        completed_contracts.append({
            "sprint": sprint_num,
            "name": sprint_name,
            "contract": final_contract,
        })

        bus.emit("sprint_complete", sprint=sprint_num, name=sprint_name)

    # ── Final Review ──
    bus.emit("phase_change", phase="review")
    review_report = run_final_review(workspace)

    # Save summary
    summary_path = orch_dir / "project-summary.md"
    summary_lines = [
        f"# Project Summary\n\n",
        f"## Description\n{project_description}\n\n",
        f"## Vision\n{vision}\n\n",
        f"## Sprints Completed: {len(completed_contracts)}\n",
    ]
    for c in completed_contracts:
        summary_lines.append(f"\n### Sprint {c['sprint']}: {c['name']}\n")
        summary_lines.append(f"Contract:\n{c['contract'][:500]}...\n")
    summary_lines.append(f"\n## Final Review\n{review_report[:1000]}...\n")
    summary_path.write_text("".join(summary_lines), encoding="utf-8")

    git_commit(workspace, "Project complete — final review")

    bus.emit("project_complete", summary_path=str(summary_path))
