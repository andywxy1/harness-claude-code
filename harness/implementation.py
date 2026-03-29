"""Phase 2: Implementation + Evaluation cycles.

The generator is PERSISTENT (resumed) within a sprint so it remembers what
it tried. The evaluator is FRESH each cycle for unbiased assessment. If the
same failures repeat 3 times, we rollback to renegotiation.
"""

from pathlib import Path

from harness.claude_session import call_claude, fresh_session_id
from harness.prompts.implementation import IMPL_GEN_SYSTEM, IMPL_EVAL_SYSTEM
from harness.utils import git_commit, parse_eval_report, extract_failure_keys, ensure_orchestrator_dir
from harness.negotiation import negotiate_contract

DONE_SIGNAL = Path(".orchestrator/.done")
EVAL_REPORT = Path(".orchestrator/eval-report.md")


def renegotiate_contract(
    original_contract: str,
    eval_report: str,
    repeated_failures: list[str],
    project_vision: str,
    planner_direction: str,
    sprint_num: int,
    workspace: str,
) -> str:
    """Wrap negotiate_contract with context about what failed.

    Prepends failure context to planner_direction so the negotiation
    agents understand what proved problematic during implementation.
    """
    failures_text = "\n".join(f"  - {f}" for f in repeated_failures)

    augmented_direction = (
        "RENEGOTIATION: The following features proved problematic during implementation:\n"
        f"{failures_text}\n"
        f"Original contract: {original_contract}\n"
        f"Evaluator report: {eval_report}\n"
        "Revise the contract to address these implementation realities.\n\n"
        f"{planner_direction}"
    )

    return negotiate_contract(
        planner_direction=augmented_direction,
        project_vision=project_vision,
        sprint_num=sprint_num,
        workspace=workspace,
    )


def implement_and_evaluate(
    sprint_num: int,
    contract: str,
    project_vision: str,
    planner_direction: str,
    workspace: str,
) -> str:
    """Run implementation/evaluation cycles until the sprint passes.

    Args:
        sprint_num: Current sprint number.
        contract: The agreed-upon sprint contract.
        project_vision: The overall product vision.
        planner_direction: High-level sprint direction from the planner.
        workspace: Path to the project workspace.

    Returns:
        The final contract (may differ from input if renegotiation occurred).
    """
    ensure_orchestrator_dir(workspace)

    DONE_SIGNAL_PATH = Path(workspace) / DONE_SIGNAL
    EVAL_REPORT_PATH = Path(workspace) / EVAL_REPORT

    gen_session = fresh_session_id()
    gen_system = IMPL_GEN_SYSTEM.format(done_signal=str(DONE_SIGNAL))
    eval_system = IMPL_EVAL_SYSTEM.format(report_path=str(EVAL_REPORT))

    cycle = 1
    eval_failures = ""
    failure_tracker: dict[str, int] = {}

    while True:
        # --- Generator turn ---
        print(f"[Implementation] Sprint {sprint_num}, Cycle {cycle} — Generator working...")

        if cycle == 1:
            gen_prompt = (
                f"## Sprint Contract\n{contract}\n\n"
                "Write tests first, then implement. Follow the contract."
            )
            gen_response = call_claude(
                prompt=gen_prompt,
                session_id=gen_session,
                system_prompt=gen_system,
                workspace=workspace,
                is_first_turn=True,
            )
        else:
            gen_prompt = (
                f"## Sprint Contract\n{contract}\n\n"
                f"## Evaluator Failure Report\n{eval_failures}\n\n"
                "Fix the issues above. Run the tests again."
            )
            gen_response = call_claude(
                prompt=gen_prompt,
                session_id=gen_session,
                system_prompt=gen_system,
                workspace=workspace,
                is_first_turn=False,
            )

        print(f"[Implementation] Sprint {sprint_num}, Cycle {cycle} — Generator finished.")
        git_commit(workspace, f"Sprint {sprint_num} cycle {cycle} — generator")

        # --- Check done signal ---
        if not DONE_SIGNAL_PATH.exists():
            print(f"[Implementation] Warning: .done signal not found. Generator may not have run tests.")
            eval_failures = (
                "The .done signal file was not created. You MUST run all contract tests "
                "and only create the .done signal when they all pass. Run the tests now."
            )
            cycle += 1
            continue

        # --- Evaluator turn ---
        print(f"[Evaluation] Sprint {sprint_num}, Cycle {cycle} — Evaluator reviewing...")

        # Clean up done signal and old report before evaluation
        DONE_SIGNAL_PATH.unlink(missing_ok=True)
        EVAL_REPORT_PATH.unlink(missing_ok=True)

        eval_session = fresh_session_id()
        eval_prompt = f"## Sprint Contract\n{contract}\n\nEvaluate the implementation against this contract."

        eval_response = call_claude(
            prompt=eval_prompt,
            session_id=eval_session,
            system_prompt=eval_system,
            workspace=workspace,
            is_first_turn=True,
        )

        print(f"[Evaluation] Sprint {sprint_num}, Cycle {cycle} — Evaluator finished.")

        # --- Read eval report ---
        if EVAL_REPORT_PATH.exists():
            report = EVAL_REPORT_PATH.read_text(encoding="utf-8")
        else:
            report = eval_response

        # --- Parse result ---
        status, reason = parse_eval_report(report)

        if status == "PASS":
            git_commit(workspace, f"Sprint {sprint_num} complete")
            print(f"[Evaluation] Sprint {sprint_num} PASSED — {reason}")
            return contract

        # --- FAIL path ---
        print(f"[Evaluation] Sprint {sprint_num}, Cycle {cycle} FAILED — {reason}")

        # Track repeated failures
        keys = extract_failure_keys(report)
        for key in keys:
            failure_tracker[key] = failure_tracker.get(key, 0) + 1

        # Check for repeated failures (any key seen 3+ times)
        repeated = [k for k, v in failure_tracker.items() if v >= 3]

        if repeated:
            print(f"[Implementation] Repeated failures detected ({len(repeated)}). Rolling back to renegotiation...")
            contract = renegotiate_contract(
                original_contract=contract,
                eval_report=report,
                repeated_failures=repeated,
                project_vision=project_vision,
                planner_direction=planner_direction,
                sprint_num=sprint_num,
                workspace=workspace,
            )

            # Reset for fresh implementation attempt
            gen_session = fresh_session_id()
            cycle = 0
            failure_tracker.clear()
            eval_failures = ""
        else:
            eval_failures = report

        cycle += 1
