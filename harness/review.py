"""Final review — senior engineer checks the entire codebase after all sprints."""

from pathlib import Path

from harness.claude_session import call_claude, fresh_session_id
from harness.events import bus
from harness.prompts.review import FINAL_REVIEW_SYSTEM
from harness.utils import ensure_orchestrator_dir


def run_final_review(workspace: str) -> str:
    """Run a comprehensive final review of the completed project."""
    orch_dir = ensure_orchestrator_dir(workspace)
    report_path = orch_dir / "final-review.md"

    session_id = fresh_session_id()
    system_prompt = FINAL_REVIEW_SYSTEM.format(report_path=str(report_path))

    bus.emit("agent_start", agent="reviewer")

    response = call_claude(
        prompt=(
            "All sprints are complete. Review the ENTIRE codebase.\n\n"
            "1. Run the full test suite\n"
            "2. Check for integration issues across sprint boundaries\n"
            "3. Review code quality and architecture coherence\n"
            "4. Start the application and test the full user journey\n"
            "5. Write your report to " + str(report_path)
        ),
        session_id=session_id,
        system_prompt=system_prompt,
        workspace=workspace,
        is_first_turn=True,
        timeout=900,
    )

    bus.emit("agent_output", agent="reviewer", text=response)
    bus.emit("agent_done", agent="reviewer")

    if report_path.exists():
        report = report_path.read_text(encoding="utf-8")
    else:
        report = response

    verdict = "SHIP" if "SHIP" in report.upper() else "FIX"
    bus.emit("log", source="Review", message=f"Verdict: {verdict}")

    return report
