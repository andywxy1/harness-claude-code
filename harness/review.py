"""Final review — senior engineer checks the entire codebase after all sprints."""

from pathlib import Path

from harness.claude_session import call_claude, fresh_session_id
from harness.prompts.review import FINAL_REVIEW_SYSTEM
from harness.utils import ensure_orchestrator_dir


def run_final_review(workspace: str) -> str:
    """Run a comprehensive final review of the completed project.

    A fresh Claude session reviews the full codebase holistically,
    checking for integration issues, code quality, and end-to-end
    product completeness.

    Args:
        workspace: Path to the project workspace.

    Returns:
        The review report text.
    """
    orch_dir = ensure_orchestrator_dir(workspace)
    report_path = orch_dir / "final-review.md"

    session_id = fresh_session_id()
    system_prompt = FINAL_REVIEW_SYSTEM.format(report_path=str(report_path))

    print("[Final Review] Starting comprehensive codebase review...")

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
        timeout=900,  # longer timeout for full review
    )

    if report_path.exists():
        report = report_path.read_text(encoding="utf-8")
    else:
        report = response

    # Check verdict
    if "SHIP" in report.upper() and "FIX" not in report.upper().split("SHIP")[0][-20:]:
        print("[Final Review] Verdict: SHIP")
    else:
        print("[Final Review] Verdict: FIX — see report for details")

    print(f"[Final Review] Report written to {report_path}")
    return report
