"""Phase 1: Contract Negotiation between Generator and Evaluator."""

from pathlib import Path

from harness.claude_session import call_claude, fresh_session_id
from harness.config import config
from harness.events import bus, make_stream_callback, make_tool_callback, handle_streaming_result
from harness.prompts.negotiation import NEG_GEN_SYSTEM, NEG_EVAL_SYSTEM
from harness.utils import parse_agreed, ensure_orchestrator_dir


def _call_gen(prompt, session_id, workspace, is_first, model, timeout):
    """Call generator with streaming. No tools — negotiation is text only."""
    result = call_claude(
        prompt=prompt, session_id=session_id, system_prompt=NEG_GEN_SYSTEM,
        workspace=workspace, is_first_turn=is_first,
        model=model, timeout=timeout,
        allowed_tools="",  # no tools during negotiation
        on_chunk=make_stream_callback("generator"),
    )
    return handle_streaming_result(result, "generator")


def _call_eval(prompt, session_id, workspace, is_first, model, timeout):
    """Call evaluator with streaming. No tools — negotiation is text only."""
    result = call_claude(
        prompt=prompt, session_id=session_id, system_prompt=NEG_EVAL_SYSTEM,
        workspace=workspace, is_first_turn=is_first,
        model=model, timeout=timeout,
        allowed_tools="",  # no tools during negotiation
        on_chunk=make_stream_callback("evaluator"),
    )
    return handle_streaming_result(result, "evaluator")


def negotiate_contract(
    planner_direction: str,
    project_vision: str,
    sprint_num: int,
    workspace: str,
) -> str:
    """Run generator/evaluator negotiation until both agree on a contract."""
    gen_session = fresh_session_id()
    eval_session = fresh_session_id()
    neg_timeout = config.get_timeout("negotiation")
    gen_model = config.get_model("negotiation_generator")
    eval_model = config.get_model("negotiation_evaluator")

    # Generator proposes initial contract
    bus.emit("agent_start", agent="generator")
    contract = _call_gen(
        prompt=(
            f"## Project Vision\n{project_vision}\n\n"
            f"## Sprint {sprint_num} Direction (from planner)\n{planner_direction}\n\n"
            "Based on the above direction, propose a detailed sprint contract with "
            "features, acceptance criteria, and test definitions. Be creative and thorough."
        ),
        session_id=gen_session, workspace=workspace, is_first=True,
        model=gen_model, timeout=neg_timeout,
    )
    bus.emit("agent_done", agent="generator")

    last_full_proposal = contract
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

        eval_response = _call_eval(
            prompt=eval_prompt,
            session_id=eval_session, workspace=workspace,
            is_first=(round_num == 1),
            model=eval_model, timeout=neg_timeout,
        )
        bus.emit("agent_done", agent="evaluator")

        eval_agreed = parse_agreed(eval_response)
        bus.emit("negotiation_round", round=round_num,
                 speaker="evaluator", agreed=eval_agreed)

        if eval_agreed:
            # Confirm generator also agrees — ask for FULL final contract
            bus.emit("agent_start", agent="generator")
            confirm_response = _call_gen(
                prompt=(
                    "The evaluator has agreed to the contract. "
                    "Do you also agree this is the final contract? "
                    "If yes, output the COMPLETE FINAL CONTRACT in full "
                    "(every feature, every acceptance criterion, every test — "
                    "the entire document, not just changes), followed by AGREED on its own line. "
                    "If you want to make final changes, say PROPOSING and state them."
                ),
                session_id=gen_session, workspace=workspace, is_first=False,
                model=gen_model, timeout=neg_timeout,
            )
            bus.emit("agent_done", agent="generator")

            if parse_agreed(confirm_response):
                contract = confirm_response
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
        gen_response = _call_gen(
            prompt=(
                f"The evaluator has critiqued your contract:\n\n{eval_response}\n\n"
                "Revise your contract to address the evaluator's feedback. "
                "If you accept all changes, produce the updated contract and say AGREED "
                "if you believe it's ready. Otherwise say PROPOSING with your revised contract."
            ),
            session_id=gen_session, workspace=workspace, is_first=False,
            model=gen_model, timeout=neg_timeout,
        )
        bus.emit("agent_done", agent="generator")

        contract = gen_response
        if len(gen_response) > 500:
            last_full_proposal = gen_response
        bus.emit("negotiation_round", round=round_num,
                 speaker="generator", agreed=parse_agreed(gen_response))
        round_num += 1

    # Resolve the final contract text
    orch_dir = ensure_orchestrator_dir(workspace)
    resolved_contract = contract

    # Check for contract files the generator may have written to disk
    possible_paths = [
        orch_dir / f"sprint-{sprint_num}-contract.md",
        orch_dir / "contract.md",
        Path(workspace) / "contract.md",
    ]
    for p in possible_paths:
        if p.exists():
            file_text = p.read_text(encoding="utf-8").strip()
            if len(file_text) > len(resolved_contract) + 50:
                resolved_contract = file_text
                break

    # Fallback to last full proposal if resolved is too short
    if len(resolved_contract) < 500:
        resolved_contract = last_full_proposal

    # Write final contract to canonical path
    contract_path = orch_dir / "contract.md"
    contract_path.write_text(resolved_contract, encoding="utf-8")
    bus.emit("contract_agreed", sprint=sprint_num, text=resolved_contract)

    return resolved_contract
