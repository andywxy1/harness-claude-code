"""Main orchestrator — runs the full project lifecycle.

Planner (once) → [Negotiation → Implementation → Evaluation] per sprint → Final Review
"""

from pathlib import Path

from harness.planner import run_planner
from harness.negotiation import negotiate_contract
from harness.implementation import implement_and_evaluate
from harness.review import run_final_review
from harness.utils import git_init, git_commit, ensure_orchestrator_dir


def run_project(project_description: str, workspace: str):
    """Execute the full Harness Claude pipeline.

    1. Planner runs once, produces sprint plan
    2. For each sprint:
       a. Generator and Evaluator negotiate a contract
       b. Generator implements, Evaluator tests
       c. Fix cycles until all pass (or rollback to renegotiation)
    3. Final review of entire codebase

    Args:
        project_description: Free-text description of what to build.
        workspace: Path to the project directory.
    """
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace = str(workspace_path)

    # Initialize git if needed
    git_init(workspace)
    ensure_orchestrator_dir(workspace)

    print("=" * 60)
    print("  HARNESS CLAUDE")
    print("=" * 60)
    print(f"Project: {project_description}")
    print(f"Workspace: {workspace}")
    print("=" * 60)

    # ── Phase 0: Planning ──
    print("\n" + "=" * 60)
    print("  PHASE 0: PLANNING")
    print("=" * 60)

    vision, sprints = run_planner(project_description, workspace)

    if not sprints:
        print("[Orchestrator] ERROR: Planner produced no sprints. Aborting.")
        return

    print(f"\n[Orchestrator] Project vision: {vision[:200]}...")
    print(f"[Orchestrator] {len(sprints)} sprint(s) planned:")
    for s in sprints:
        print(f"  Sprint {s['number']}: {s['name']}")

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

    for sprint in sprints:
        sprint_num = sprint["number"]
        sprint_name = sprint["name"]
        sprint_direction = sprint["description"]

        print("\n" + "=" * 60)
        print(f"  SPRINT {sprint_num}: {sprint_name}")
        print("=" * 60)

        # Phase 1: Negotiate contract
        print(f"\n--- Phase 1: Contract Negotiation ---")
        contract = negotiate_contract(
            planner_direction=sprint_direction,
            project_vision=vision,
            sprint_num=sprint_num,
            workspace=workspace,
        )

        # Phase 2: Implement and evaluate
        print(f"\n--- Phase 2: Implementation + Evaluation ---")
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

        print(f"\n[Orchestrator] Sprint {sprint_num} ({sprint_name}) COMPLETE")

    # ── Final Review ──
    print("\n" + "=" * 60)
    print("  FINAL REVIEW")
    print("=" * 60)

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

    print("\n" + "=" * 60)
    print("  PROJECT COMPLETE")
    print("=" * 60)
    print(f"Workspace: {workspace}")
    print(f"Summary: {summary_path}")
    print("=" * 60)
