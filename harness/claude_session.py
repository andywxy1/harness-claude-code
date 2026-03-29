"""Wrapper for calling Claude Code CLI with session management."""

import subprocess
import uuid
from pathlib import Path


def fresh_session_id() -> str:
    return str(uuid.uuid4())


def call_claude(
    prompt: str,
    session_id: str,
    system_prompt: str,
    workspace: str,
    is_first_turn: bool = False,
    timeout: int = 600,
) -> str:
    """Call Claude Code CLI with session support.

    Args:
        prompt: The user prompt to send.
        session_id: UUID for session tracking.
        system_prompt: Appended system prompt for role behavior.
        workspace: Working directory for the claude process.
        is_first_turn: If True, creates new session. If False, resumes.
        timeout: Max seconds to wait for response.

    Returns:
        The text response from Claude.
    """
    cmd = [
        "claude",
        "-p", prompt,
        "--append-system-prompt", system_prompt,
        "--dangerously-skip-permissions",
        "--model", "opus",
    ]

    if is_first_turn:
        cmd.extend(["--session-id", session_id])
    else:
        cmd.extend(["--resume", session_id])

    result = subprocess.run(
        cmd,
        input="",  # required for --append-system-prompt with --resume
        capture_output=True,
        text=True,
        cwd=workspace,
        timeout=timeout,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if stderr:
            print(f"  [claude stderr] {stderr[:300]}")

    return result.stdout.strip()
