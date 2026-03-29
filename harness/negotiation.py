"""Phase 1: Contract Negotiation between Generator and Evaluator."""

from harness.claude_session import call_claude, fresh_session_id
from harness.prompts.negotiation import NEG_GEN_SYSTEM, NEG_EVAL_SYSTEM
from harness.utils import parse_agreed, ensure_orchestrator_dir


def negotiate_contract(
    planner_direction: str,
    project_vision: str,
    sprint_num: int,
    workspace: str,
) -> str:
    """Run generator/evaluator negotiation until both agree on a contract.

    The generator improvises a detailed contract from the planner's high-level
    direction. The evaluator critiques for rigor and testability, and can also
    propose new features as a user advocate. They iterate until consensus.

    Args:
        planner_direction: High-level sprint direction from the planner (2-4 sentences).
        project_vision: The overall product vision.
        sprint_num: Current sprint number.
        workspace: Path to the project workspace.

    Returns:
        The final agreed-upon contract text.
    """
    gen_session = fresh_session_id()
    eval_session = fresh_session_id()

    # --- Round 1: Generator proposes initial contract ---
    print(f"[Negotiation] Sprint {sprint_num} — Generator proposing initial contract...")

    gen_prompt = (
        f"## Project Vision\n{project_vision}\n\n"
        f"## Sprint {sprint_num} Direction (from planner)\n{planner_direction}\n\n"
        "Based on the above direction, propose a detailed sprint contract with "
        "features, acceptance criteria, and test definitions. Be creative and thorough."
    )

    contract = call_claude(
        prompt=gen_prompt,
        session_id=gen_session,
        system_prompt=NEG_GEN_SYSTEM,
        workspace=workspace,
        is_first_turn=True,
    )

    print(f"[Negotiation] Generator proposed initial contract.")

    round_num = 1

    while True:
        # --- Evaluator critiques ---
        print(f"[Negotiation] Round {round_num} — Evaluator reviewing...")

        eval_prompt = (
            f"Here is the generator's contract proposal:\n\n{contract}\n\n"
            "Review this contract for rigor, testability, and completeness. "
            "As a user advocate, flag anything missing that a real user would expect. "
            "If the contract meets all criteria, say AGREED on its own line. "
            "Otherwise, say PROPOSING and provide your critique and suggestions."
        ) if round_num == 1 else (
            f"The generator has revised the contract:\n\n{contract}\n\n"
            "Review the revisions. Does the contract now meet all criteria? "
            "If yes, say AGREED on its own line. "
            "Otherwise, say PROPOSING and explain what still needs work."
        )

        eval_response = call_claude(
            prompt=eval_prompt,
            session_id=eval_session,
            system_prompt=NEG_EVAL_SYSTEM,
            workspace=workspace,
            is_first_turn=(round_num == 1),
        )

        eval_agreed = parse_agreed(eval_response)

        if eval_agreed:
            # --- Confirm generator also agrees ---
            print(f"[Negotiation] Round {round_num} — Evaluator AGREED. Confirming with generator...")

            confirm_response = call_claude(
                prompt=(
                    "The evaluator has agreed to the contract as-is. "
                    "Do you also agree this is the final contract? "
                    "If yes, say AGREED on its own line. "
                    "If you want to make final changes, say PROPOSING and state them."
                ),
                session_id=gen_session,
                system_prompt=NEG_GEN_SYSTEM,
                workspace=workspace,
                is_first_turn=False,
            )

            if parse_agreed(confirm_response):
                print(f"[Negotiation] Both parties AGREED after {round_num} round(s).")
                break
            else:
                # Generator wants more changes — treat their response as a revised contract
                print(f"[Negotiation] Round {round_num} — Generator proposed further changes.")
                contract = confirm_response
                round_num += 1
                continue
        else:
            print(f"[Negotiation] Round {round_num} — Evaluator requesting changes.")

        # --- Generator revises ---
        print(f"[Negotiation] Round {round_num} — Generator revising...")

        revise_prompt = (
            f"The evaluator has critiqued your contract:\n\n{eval_response}\n\n"
            "Revise your contract to address the evaluator's feedback. "
            "If you accept all changes, produce the updated contract and say AGREED "
            "if you believe it's ready. Otherwise say PROPOSING with your revised contract."
        )

        gen_response = call_claude(
            prompt=revise_prompt,
            session_id=gen_session,
            system_prompt=NEG_GEN_SYSTEM,
            workspace=workspace,
            is_first_turn=False,
        )

        contract = gen_response
        print(f"[Negotiation] Round {round_num} — Generator revised contract.")
        round_num += 1

    # --- Write final contract ---
    orch_dir = ensure_orchestrator_dir(workspace)
    contract_path = orch_dir / "contract.md"
    contract_path.write_text(contract, encoding="utf-8")
    print(f"[Negotiation] Final contract written to {contract_path}")

    return contract
