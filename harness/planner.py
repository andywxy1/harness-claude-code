"""Planner agent — runs once to produce a sprint plan from a project description."""

from harness.claude_session import call_claude, fresh_session_id
from harness.prompts.planner import PLANNER_SYSTEM
from harness.utils import parse_sprint_plan


def run_planner(project_description: str, workspace: str) -> tuple[str, list[dict]]:
    """Generate a sprint plan from a project description.

    Calls Claude once with the project description and parses the
    response into a vision statement and list of sprint specs.

    Args:
        project_description: Free-text description of the project.
        workspace: Working directory for the Claude process.

    Returns:
        Tuple of (vision, sprints) where vision is a string and
        sprints is a list of dicts with 'number', 'name', 'description'.
    """
    print("[Planner] Starting sprint planning...")

    session_id = fresh_session_id()

    print("[Planner] Calling Claude to generate sprint plan...")
    response = call_claude(
        prompt=project_description,
        session_id=session_id,
        system_prompt=PLANNER_SYSTEM,
        workspace=workspace,
        is_first_turn=True,
    )

    print("[Planner] Parsing sprint plan...")
    vision, sprints = parse_sprint_plan(response)

    print(f"[Planner] Done — vision extracted, {len(sprints)} sprint(s) planned.")
    return vision, sprints
