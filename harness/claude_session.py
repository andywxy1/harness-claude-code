"""Wrapper for calling Claude Code CLI with session management."""

import json
import subprocess
import uuid
from typing import Callable


def fresh_session_id() -> str:
    return str(uuid.uuid4())


def call_claude(
    prompt: str,
    session_id: str,
    system_prompt: str,
    workspace: str,
    is_first_turn: bool = False,
    timeout: int = 600,
    allowed_tools: str | None = None,
    model: str = "opus",
    on_chunk: Callable[[str], None] | None = None,
    on_tool_use: Callable[[dict], None] | None = None,
) -> str | dict:
    """Call Claude Code CLI with session support.

    Args:
        prompt: The user prompt to send.
        session_id: UUID for session tracking.
        system_prompt: Appended system prompt for role behavior.
        workspace: Working directory for the claude process.
        is_first_turn: If True, creates new session. If False, resumes.
        timeout: Max seconds to wait for response.
        allowed_tools: Comma-separated tool names, or empty string to disable all tools.
        model: Model to use (e.g. "opus", "sonnet", "haiku").
        on_chunk: Optional callback for streaming. When provided, each text
            chunk from the assistant is passed to this function as it arrives.
        on_tool_use: Optional callback for tool events. When provided and
            streaming is active, tool_use and tool_result events are parsed
            and passed as dicts with keys: tool, input_preview, status.

    Returns:
        When on_chunk is None: the text response from Claude (str).
        When on_chunk is provided: a dict with keys "text" (str) and
        "usage" (dict | None with input_tokens, output_tokens, cost).
    """
    cmd = [
        "claude",
        "-p", prompt,
        "--append-system-prompt", system_prompt,
        "--dangerously-skip-permissions",
        "--model", model,
    ]

    if allowed_tools is not None:
        cmd.extend(["--allowedTools", allowed_tools])

    if is_first_turn:
        cmd.extend(["--session-id", session_id])
    else:
        cmd.extend(["--resume", session_id])

    # --- Non-streaming path (backward compatible) ---
    if on_chunk is None:
        result = subprocess.run(
            cmd,
            input="",
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

    # --- Streaming path ---
    cmd.extend(["--output-format", "stream-json", "--verbose"])

    accumulated_text = ""
    usage = None

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=workspace,
    )

    # Close stdin immediately (equivalent to piping empty string).
    proc.stdin.close()

    try:
        # Read stdout line-by-line for real-time streaming.
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "assistant":
                # Assistant message with content blocks.
                for block in msg.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        chunk = block.get("text", "")
                        if chunk:
                            on_chunk(chunk)
                            accumulated_text += chunk

            elif msg_type == "content_block_delta":
                # Incremental text delta within a stream.
                delta = msg.get("delta", {})
                if delta.get("type") == "text_delta":
                    chunk = delta.get("text", "")
                    if chunk:
                        on_chunk(chunk)
                        accumulated_text += chunk

            # --- Tool use events ---
            if on_tool_use:
                # Check assistant messages for tool_use content blocks
                if msg_type == "assistant":
                    for block in msg.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_input = json.dumps(block.get("input", {}))
                            on_tool_use({
                                "tool": tool_name,
                                "input_preview": tool_input[:150],
                                "status": "started",
                            })

                # content_block_start with tool_use type
                elif msg_type == "content_block_start":
                    cb = msg.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        tool_name = cb.get("name", "unknown")
                        tool_input = json.dumps(cb.get("input", {}))
                        on_tool_use({
                            "tool": tool_name,
                            "input_preview": tool_input[:150],
                            "status": "started",
                        })

                # Tool result messages indicate completion
                elif msg_type == "tool_result":
                    tool_name = msg.get("tool_name", msg.get("name", "unknown"))
                    on_tool_use({
                        "tool": tool_name,
                        "input_preview": "",
                        "status": "completed",
                    })

            if msg_type == "result":
                # Final summary message with usage info.
                result_data = msg.get("result", msg)
                usage_raw = result_data.get("usage")
                if usage_raw:
                    usage = {
                        "input_tokens": usage_raw.get("input_tokens"),
                        "output_tokens": usage_raw.get("output_tokens"),
                        "cost": result_data.get("cost_usd") or usage_raw.get("cost"),
                    }
                # Result may also carry final text if we missed deltas.
                if not accumulated_text:
                    for block in result_data.get("content", []):
                        if block.get("type") == "text":
                            accumulated_text += block.get("text", "")

            # Ignore "system", "hook", and any other message types.

        proc.wait(timeout=timeout)

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except Exception:
        proc.kill()
        proc.wait()
        raise
    finally:
        # Ensure file descriptors are closed.
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

    return {"text": accumulated_text.strip(), "usage": usage}
