"""Planner agent — runs once to produce a sprint plan from a project description."""

from harness.claude_session import call_claude, fresh_session_id
from harness.config import config
from harness.events import bus, make_stream_callback, make_tool_callback, handle_streaming_result
from harness.prompts.planner import PLANNER_SYSTEM
from harness.utils import parse_sprint_plan


def run_planner(project_description: str, workspace: str) -> tuple[str, list[dict]]:
    """Generate a sprint plan from a project description."""
    bus.emit("agent_start", agent="planner")

    session_id = fresh_session_id()

    prompt = (
        "Generate a sprint plan for the following project. "
        "You may research online if needed, but your response MUST end with "
        "the sprint plan between ---BEGIN SPRINT PLAN--- and ---END SPRINT PLAN--- markers.\n\n"
        f"PROJECT: {project_description}\n\n"
        "Output the sprint plan now."
    )

    result = call_claude(
        prompt=prompt,
        session_id=session_id,
        system_prompt=PLANNER_SYSTEM,
        workspace=workspace,
        is_first_turn=True,
        timeout=config.get_timeout("planner"),
        model=config.get_model("planner"),
        on_chunk=make_stream_callback("planner"),
        on_tool_use=make_tool_callback("planner"),
    )

    response = handle_streaming_result(result, "planner")
    bus.emit("agent_done", agent="planner")

    vision, sprints = parse_sprint_plan(response)

    bus.emit("log", source="Planner",
             message=f"Produced {len(sprints)} sprint(s)")

    return vision, sprints
