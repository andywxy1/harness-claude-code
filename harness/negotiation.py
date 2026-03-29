"""Phase 1: Contract Negotiation between Generator and Evaluator."""

import threading
from pathlib import Path

from harness.claude_session import call_claude, fresh_session_id
from harness.config import config
from harness.events import bus, make_stream_callback, make_tool_callback, handle_streaming_result
from harness.prompts.negotiation import NEG_GEN_SYSTEM, NEG_EVAL_SYSTEM
from harness.utils import parse_agreed, ensure_orchestrator_dir


def _call_gen(prompt, session_id, workspace, is_first, model, timeout, allowed_tools=""):
    """Call generator with streaming."""
    result = call_claude(
        prompt=prompt, session_id=session_id, system_prompt=NEG_GEN_SYSTEM,
        workspace=workspace, is_first_turn=is_first,
        model=model, timeout=timeout,
        allowed_tools=allowed_tools,
        on_chunk=make_stream_callback("generator"),
        on_tool_use=make_tool_callback("generator") if allowed_tools != "" else None,
    )
    return handle_streaming_result(result, "generator")


def _call_eval(prompt, session_id, workspace, is_first, model, timeout, allowed_tools=""):
    """Call evaluator with streaming."""
    result = call_claude(
        prompt=prompt, session_id=session_id, system_prompt=NEG_EVAL_SYSTEM,
        workspace=workspace, is_first_turn=is_first,
        model=model, timeout=timeout,
        allowed_tools=allowed_tools,
        on_chunk=make_stream_callback("evaluator"),
        on_tool_use=make_tool_callback("evaluator") if allowed_tools != "" else None,
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

    is_first_sprint = sprint_num <= 1
    tools_setting = "" if is_first_sprint else None  # None = all tools allowed

    last_full_proposal = ""
    round_num = 1
    contract_lengths = []
    eval_is_first = True  # tracks whether evaluator's next call is first turn

    if not is_first_sprint:
        # Sprint 2+: parallel codebase exploration
        eval_exploration = [None]

        def explore_evaluator():
            eval_exploration[0] = call_claude(
                prompt=(
                    "Explore the existing codebase. Understand the architecture, "
                    "file structure, tech stack, and what has been built so far. "
                    "Do NOT produce any analysis or critique. Just say 'Ready.' "
                    "when you are done exploring."
                ),
                session_id=eval_session,
                system_prompt=NEG_EVAL_SYSTEM,
                workspace=workspace,
                is_first_turn=True,
                model=eval_model, timeout=neg_timeout,
                on_chunk=make_stream_callback("evaluator"),
                on_tool_use=make_tool_callback("evaluator"),
            )

        # Start evaluator exploration in background
        eval_thread = threading.Thread(target=explore_evaluator)
        eval_thread.start()
        bus.emit("log", source="Negotiation",
                 message="Evaluator exploring codebase in parallel...")

        # Generator explores + proposes on main thread
        bus.emit("agent_start", agent="generator")
        contract = _call_gen(
            prompt=(
                f"## Project Vision\n{project_vision}\n\n"
                f"## Sprint {sprint_num} Direction (from planner)\n{planner_direction}\n\n"
                "Explore the existing codebase first to understand what has been built. "
                "Then propose a detailed sprint contract with features, acceptance criteria, "
                "and test definitions. Be creative and thorough."
            ),
            session_id=gen_session, workspace=workspace, is_first=True,
            model=gen_model, timeout=neg_timeout, allowed_tools=tools_setting,
        )
        bus.emit("agent_done", agent="generator")

        # Wait for evaluator exploration to finish
        eval_thread.join()
        handle_streaming_result(eval_exploration[0], "evaluator")
        bus.emit("log", source="Negotiation",
                 message="Evaluator ready (codebase loaded)")

        last_full_proposal = contract
        eval_is_first = False  # evaluator already had its first turn

        # First evaluator critique — resume session (already has codebase context)
        bus.emit("agent_start", agent="evaluator")
        eval_response = _call_eval(
            prompt=(
                f"Here is the generator's contract proposal:\n\n{contract}\n\n"
                "Review this contract for rigor, testability, and completeness. "
                "You already explored the codebase — use that knowledge to evaluate "
                "whether the proposal is realistic and complete. "
                "If the contract meets all criteria, say AGREED on its own line. "
                "Otherwise, say PROPOSING and provide your critique and suggestions."
            ),
            session_id=eval_session, workspace=workspace, is_first=False,
            model=eval_model, timeout=neg_timeout, allowed_tools=tools_setting,
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
                model=gen_model, timeout=neg_timeout, allowed_tools=tools_setting,
            )
            bus.emit("agent_done", agent="generator")

            if parse_agreed(confirm_response):
                contract = confirm_response
                bus.emit("negotiation_round", round=round_num,
                         speaker="generator", agreed=True)
                # Skip the while loop entirely — jump to contract resolution
                round_num = -1  # sentinel: already resolved
            else:
                bus.emit("negotiation_round", round=round_num,
                         speaker="generator", agreed=False)
                contract = confirm_response
                round_num += 1
        else:
            # Generator revises based on evaluator feedback
            bus.emit("agent_start", agent="generator")
            gen_response = _call_gen(
                prompt=(
                    f"The evaluator has critiqued your contract:\n\n{eval_response}\n\n"
                    "Revise your contract to address the evaluator's feedback. "
                    "If you accept all changes, produce the updated contract and say AGREED "
                    "if you believe it's ready. Otherwise say PROPOSING with your revised contract."
                ),
                session_id=gen_session, workspace=workspace, is_first=False,
                model=gen_model, timeout=neg_timeout, allowed_tools=tools_setting,
            )
            bus.emit("agent_done", agent="generator")

            contract = gen_response
            if len(gen_response) > 500:
                last_full_proposal = gen_response
            bus.emit("negotiation_round", round=round_num,
                     speaker="generator", agreed=parse_agreed(gen_response))
            round_num += 1

    else:
        # Sprint 1: no tools, no exploration
        bus.emit("agent_start", agent="generator")
        contract = _call_gen(
            prompt=(
                f"## Project Vision\n{project_vision}\n\n"
                f"## Sprint {sprint_num} Direction (from planner)\n{planner_direction}\n\n"
                "Based on the above direction, propose a detailed sprint contract with "
                "features, acceptance criteria, and test definitions. Be creative and thorough."
            ),
            session_id=gen_session, workspace=workspace, is_first=True,
            model=gen_model, timeout=neg_timeout, allowed_tools=tools_setting,
        )
        bus.emit("agent_done", agent="generator")
        last_full_proposal = contract

    while round_num > 0:
        # Safety cap
        if round_num > config.get_max_negotiation_rounds():
            bus.emit("log", source="Negotiation",
                     message=f"Safety cap reached ({round_num} rounds). Force-accepting last proposal.")
            break

        # Evaluator critiques
        bus.emit("agent_start", agent="evaluator")
        eval_prompt = (
            f"Here is the generator's contract proposal:\n\n{contract}\n\n"
            "Review this contract for rigor, testability, and completeness. "
            "As a user advocate, flag anything missing that a real user would expect. "
            "If the contract meets all criteria, say AGREED on its own line. "
            "Otherwise, say PROPOSING and provide your critique and suggestions."
        ) if eval_is_first else (
            f"The generator has revised the contract:\n\n{contract}\n\n"
            "Review the revisions. Does the contract now meet all criteria? "
            "If yes, say AGREED on its own line. "
            "Otherwise, say PROPOSING and explain what still needs work."
        )

        eval_response = _call_eval(
            prompt=eval_prompt,
            session_id=eval_session, workspace=workspace,
            is_first=eval_is_first,
            model=eval_model, timeout=neg_timeout, allowed_tools=tools_setting,
        )
        eval_is_first = False  # subsequent turns are never first
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
                model=gen_model, timeout=neg_timeout, allowed_tools=tools_setting,
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
            model=gen_model, timeout=neg_timeout, allowed_tools=tools_setting,
        )
        bus.emit("agent_done", agent="generator")

        contract = gen_response
        if len(gen_response) > 500:
            last_full_proposal = gen_response
        bus.emit("negotiation_round", round=round_num,
                 speaker="generator", agreed=parse_agreed(gen_response))
        round_num += 1

        # Stall detection
        contract_lengths.append(len(contract))
        if len(contract_lengths) >= 3:
            recent = contract_lengths[-3:]
            avg = sum(recent) / 3
            if all(abs(l - avg) / max(avg, 1) < 0.05 for l in recent):
                bus.emit("log", source="Negotiation", message="Stall detected — contracts not changing significantly")

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
    import hashlib
    contract_hash = hashlib.sha256(resolved_contract.encode()).hexdigest()[:16]
    bus.emit("contract_agreed", sprint=sprint_num, text=resolved_contract, hash=contract_hash)
    (orch_dir / "contract.hash").write_text(contract_hash, encoding="utf-8")

    return resolved_contract
