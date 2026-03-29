"""Utility functions for git, file operations, and report parsing."""

import subprocess
import re
from pathlib import Path


def git_commit(workspace: str, message: str):
    """Stage all changes and commit."""
    subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=workspace,
        capture_output=True,
    )


def git_init(workspace: str):
    """Initialize a git repo if one doesn't exist."""
    git_dir = Path(workspace) / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=workspace, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=workspace,
            capture_output=True,
        )


def parse_eval_report(report: str) -> tuple[str, str]:
    """Parse evaluator report for pass/fail and reason.

    Returns:
        Tuple of (status, reason) where status is "PASS" or "FAIL".
    """
    upper = report.upper()

    # Check for contract test failures
    if "STATUS: FAIL" in upper:
        return "FAIL", "Contract tests failing"

    # Check for P0/P1 blockers
    if "[P0" in report:
        return "FAIL", "P0 blocker found"
    if "[P1" in report:
        return "FAIL", "P1 major issues found"

    # Check for explicit overall pass
    # Look for PASS in the overall assessment section
    assessment_match = re.search(
        r"overall assessment[:\s]*\n?\s*(PASS|FAIL)",
        report,
        re.IGNORECASE,
    )
    if assessment_match:
        verdict = assessment_match.group(1).upper()
        if verdict == "PASS":
            return "PASS", "All tests pass, product acceptable"
        else:
            return "FAIL", "Evaluator overall assessment: FAIL"

    return "FAIL", "Evaluator did not explicitly PASS"


def extract_failure_keys(report: str) -> list[str]:
    """Extract unique failure identifiers from an eval report.

    Looks for FAIL lines and extracts a normalized key for each
    to track repeated failures across cycles.
    """
    failures = []

    for line in report.split("\n"):
        line_stripped = line.strip()

        # Match lines with FAIL, or P0/P1 severity markers
        is_failure = (
            "FAIL" in line_stripped.upper()
            or "[P0" in line_stripped
            or "[P1" in line_stripped
        )
        if is_failure:
            # Normalize: lowercase, strip whitespace, take first 80 chars
            key = re.sub(r"\s+", " ", line_stripped.lower())[:80]
            if key and key not in failures:
                failures.append(key)

    return failures


def parse_sprint_plan(plan_text: str) -> tuple[str, list[dict]]:
    """Parse planner output into vision + list of sprint specs.

    Returns:
        Tuple of (vision_text, list_of_sprint_dicts).
        Each sprint dict has 'number', 'name', and 'description'.
    """
    vision = ""
    sprints = []

    # Extract content between markers if present
    plan_body = plan_text
    begin_match = re.search(r"---BEGIN SPRINT PLAN---", plan_text)
    end_match = re.search(r"---END SPRINT PLAN---", plan_text)
    if begin_match and end_match:
        plan_body = plan_text[begin_match.end():end_match.start()]

    # Extract vision
    vision_match = re.search(
        r"## Project Vision\s*\n(.*?)(?=\n## Sprint|\Z)",
        plan_body,
        re.DOTALL,
    )
    if vision_match:
        vision = vision_match.group(1).strip()

    # Extract sprints
    sprint_pattern = re.compile(
        r"## Sprint (\d+):\s*(.+?)\n(.*?)(?=\n## Sprint \d+|\Z)",
        re.DOTALL,
    )
    for match in sprint_pattern.finditer(plan_body):
        sprints.append({
            "number": int(match.group(1)),
            "name": match.group(2).strip(),
            "description": match.group(3).strip(),
        })

    return vision, sprints


def parse_agreed(response: str) -> bool:
    """Check if a negotiation response contains AGREED (without PROPOSING)."""
    has_agreed = bool(re.search(r"^AGREED\s*$", response, re.MULTILINE))
    has_proposing = bool(re.search(r"^PROPOSING\s*$", response, re.MULTILINE))
    return has_agreed and not has_proposing


def ensure_orchestrator_dir(workspace: str) -> Path:
    """Create and return the .orchestrator directory."""
    orch_dir = Path(workspace) / ".orchestrator"
    orch_dir.mkdir(parents=True, exist_ok=True)
    return orch_dir
