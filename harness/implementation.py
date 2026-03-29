"""Phase 2: Implementation + Evaluation cycles.

The generator is PERSISTENT (resumed) within a sprint so it remembers what
it tried. The evaluator is FRESH each cycle for unbiased assessment. If the
same failures repeat 3 times, we rollback to renegotiation.
"""

from pathlib import Path

from harness.claude_session import call_claude, fresh_session_id
from harness.events import bus
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
    """Wrap negotiate_contract with context about what failed."""
    failures_text = "\n".join(f"  - {f}" for f in repeated_failures)

    augmented_direction = (
        "RENEGOTIATION: The following features proved problematic during implementation:\n"
        f"{failures_text}\n\n"
        f"Original contract:\n{original_contract}\n\n"
        f"Evaluator report:\n{eval_report}\n\n"
        "Revise the contract to address these implementation realities.\n\n"
        f"Original planner direction:\n{planner_direction}"
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
    """Run implementation/evaluation cycles until the sprint passes."""
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
        # ── Generator turn (persistent session) ──
        bus.emit("impl_cycle", sprint=sprint_num, cycle=cycle, stage="generator")
        bus.emit("agent_start", agent="generator")

        if cycle == 1:
            gen_prompt = (
                f"## Sprint Contract\n{contract}\n\n"
                "Write tests first, then implement. Follow the contract. "
                "Run all tests yourself before creating the .done signal."
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
                "Fix the issues above. Review your code. Run all tests again. "
                "Only create the .done signal when all tests pass."
            )
            gen_response = call_claude(
                prompt=gen_prompt,
                session_id=gen_session,
                system_prompt=gen_system,
                workspace=workspace,
                is_first_turn=False,
            )

        bus.emit("agent_output", agent="generator", text=gen_response)
        bus.emit("agent_done", agent="generator")
        git_commit(workspace, f"Sprint {sprint_num} cycle {cycle} — generator")

        # ── Check done signal ──
        if not DONE_SIGNAL_PATH.exists():
            bus.emit("done_signal_missing", sprint=sprint_num, cycle=cycle)
            eval_failures = (
                "The .done signal file was not created. You MUST run all contract tests "
                "and only create the .done signal when they all pass. Run the tests now."
            )
            cycle += 1
            continue

        # ── Evaluator turn (fresh session) ──
        DONE_SIGNAL_PATH.unlink(missing_ok=True)
        EVAL_REPORT_PATH.unlink(missing_ok=True)

        bus.emit("impl_cycle", sprint=sprint_num, cycle=cycle, stage="evaluator")
        bus.emit("agent_start", agent="evaluator")

        eval_session = fresh_session_id()
        eval_response = call_claude(
            prompt=(
                f"## Sprint Contract\n{contract}\n\n"
                "Evaluate the implementation against this contract. "
                f"Write your report to {EVAL_REPORT}"
            ),
            session_id=eval_session,
            system_prompt=eval_system,
            workspace=workspace,
            is_first_turn=True,
        )

        bus.emit("agent_output", agent="evaluator", text=eval_response)
        bus.emit("agent_done", agent="evaluator")

        # Read eval report
        if EVAL_REPORT_PATH.exists():
            report = EVAL_REPORT_PATH.read_text(encoding="utf-8")
        else:
            report = eval_response

        status, reason = parse_eval_report(report)
        bus.emit("eval_result", sprint=sprint_num, cycle=cycle,
                 status=status, reason=reason, report=report)

        if status == "PASS":
            git_commit(workspace, f"Sprint {sprint_num} complete")
            return contract

        # ── Track repeated failures ──
        keys = extract_failure_keys(report)
        for key in keys:
            failure_tracker[key] = failure_tracker.get(key, 0) + 1

        repeated = [k for k, v in failure_tracker.items() if v >= 3]

        if repeated:
            bus.emit("rollback", sprint=sprint_num,
                     reason=f"Same failures repeated 3x: {repeated[:3]}")

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
