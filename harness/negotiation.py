"""Phase 1: Contract Negotiation between Generator and Evaluator."""

from harness.claude_session import call_claude, fresh_session_id
from harness.events import bus
from harness.prompts.negotiation import NEG_GEN_SYSTEM, NEG_EVAL_SYSTEM
from harness.utils import parse_agreed, ensure_orchestrator_dir


def negotiate_contract(
    planner_direction: str,
    project_vision: str,
    sprint_num: int,
    workspace: str,
) -> str:
    """Run generator/evaluator negotiation until both agree on a contract."""
    gen_session = fresh_session_id()
    eval_session = fresh_session_id()

    # Generator proposes initial contract
    bus.emit("agent_start", agent="generator")

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

    bus.emit("agent_output", agent="generator", text=contract)
    bus.emit("agent_done", agent="generator")

    round_num = 1

    while True:
        # Evaluator critiques
        bus.emit("agent_start", agent="evaluator")

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
        bus.emit("agent_output", agent="evaluator", text=eval_response)
        bus.emit("agent_done", agent="evaluator")
        bus.emit("negotiation_round", round=round_num,
                 speaker="evaluator", agreed=eval_agreed)

        if eval_agreed:
            # Confirm generator also agrees
            bus.emit("agent_start", agent="generator")
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
            bus.emit("agent_output", agent="generator", text=confirm_response)
            bus.emit("agent_done", agent="generator")

            if parse_agreed(confirm_response):
                bus.emit("negotiation_round", round=round_num,
                         speaker="generator", agreed=True)
                break
            else:
                bus.emit("negotiation_round", round=round_num,
                         speaker="generator", agreed=False)
                contract = confirm_response
                round_num += 1
                continue

        # Generator revises
        bus.emit("agent_start", agent="generator")
        gen_response = call_claude(
            prompt=(
                f"The evaluator has critiqued your contract:\n\n{eval_response}\n\n"
                "Revise your contract to address the evaluator's feedback. "
                "If you accept all changes, produce the updated contract and say AGREED "
                "if you believe it's ready. Otherwise say PROPOSING with your revised contract."
            ),
            session_id=gen_session,
            system_prompt=NEG_GEN_SYSTEM,
            workspace=workspace,
            is_first_turn=False,
        )

        contract = gen_response
        bus.emit("agent_output", agent="generator", text=gen_response)
        bus.emit("agent_done", agent="generator")
        bus.emit("negotiation_round", round=round_num,
                 speaker="generator", agreed=parse_agreed(gen_response))
        round_num += 1

    # Write final contract
    orch_dir = ensure_orchestrator_dir(workspace)
    contract_path = orch_dir / "contract.md"
    contract_path.write_text(contract, encoding="utf-8")
    bus.emit("contract_agreed", sprint=sprint_num, text=contract)

    return contract
