"""Utility functions for git, file operations, and report parsing."""

import subprocess
import re
from pathlib import Path


def git_commit(workspace: str, message: str):
    """Stage all changes and commit."""
    result1 = subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True)
    if result1.returncode != 0:
        from harness.events import bus
        bus.emit("log", source="Git", message=f"git add failed: {result1.stderr.decode()[:200]}")
        return
    result2 = subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=workspace, capture_output=True,
    )
    if result2.returncode != 0:
        stderr = result2.stderr.decode()[:200] if result2.stderr else ""
        if "nothing to commit" not in stderr:
            from harness.events import bus
            bus.emit("log", source="Git", message=f"git commit failed: {stderr}")


def git_init(workspace: str):
    """Initialize a git repo if one doesn't exist."""
    git_dir = Path(workspace) / ".git"
    if not git_dir.exists():
        result = subprocess.run(["git", "init"], cwd=workspace, capture_output=True)
        if result.returncode != 0:
            from harness.events import bus
            bus.emit("log", source="Git", message=f"git init failed: {result.stderr.decode()[:200]}")
            return
        subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=workspace, capture_output=True,
        )


def parse_eval_report(report: str) -> tuple[str, str]:
    """Parse evaluator report for pass/fail and reason.

    Returns:
        Tuple of (status, reason) where status is "PASS" or "FAIL".
    """
    upper = report.upper()

    # Check for P0/P1 blockers anywhere in report
    if "[P0" in report or "P0 BLOCKER" in upper or "P0:" in upper:
        return "FAIL", "P0 blocker found"
    if "[P1" in report or "P1 MAJOR" in upper or "P1:" in upper:
        return "FAIL", "P1 major issues found"

    # Check for explicit FAIL markers
    if "STATUS: FAIL" in upper:
        return "FAIL", "Contract tests failing"

    # Check for verdict/assessment sections — flexible matching
    verdict_patterns = [
        r"(?:overall|final)\s*(?:verdict|assessment|decision)[:\s|]*[^\n]*?(PASS|FAIL)",
        r"(?:PASS|FAIL)\s*[—–-]\s*(?:all|do not|ready|not ready)",
        r"\*\*(?:PASS|FAIL)\*\*",
    ]
    for pattern in verdict_patterns:
        match = re.search(pattern, report, re.IGNORECASE)
        if match:
            text = match.group(0).upper()
            if "FAIL" in text:
                return "FAIL", "Evaluator verdict: FAIL"
            if "PASS" in text:
                return "PASS", "All tests pass, product acceptable"

    # Count PASS/FAIL occurrences as last resort
    fail_count = upper.count("❌ FAIL") + upper.count("STATUS: FAIL")
    pass_count = upper.count("✅ PASS") + upper.count("STATUS: PASS")

    if fail_count > 0:
        return "FAIL", f"Found {fail_count} failing item(s)"
    if pass_count > 0 and fail_count == 0:
        return "PASS", "All items passing"

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


def extract_tests_from_contract(contract: str) -> list[dict]:
    """Extract test names/descriptions from a contract.

    Looks for test function signatures like:
    - `def test_something():` or `test_something`
    - Lines starting with test names in backticks
    - Numbered test items

    Returns list of dicts: [{"name": "test_name", "description": "what it tests"}]
    """
    tests: list[dict] = []
    seen_names: set[str] = set()

    for line in contract.split("\n"):
        stripped = line.strip()

        # Python test function definitions: def test_foo():
        m = re.match(r"def\s+(test_\w+)\s*\(", stripped)
        if m:
            name = m.group(1)
            if name not in seen_names:
                seen_names.add(name)
                tests.append({"name": name, "description": name.replace("_", " ")})
            continue

        # Backtick test names: `test_something` possibly followed by description
        m = re.search(r"`(test_\w+)`(?:\s*[:\-–—]\s*(.+))?", stripped)
        if m:
            name = m.group(1)
            desc = m.group(2).strip() if m.group(2) else name.replace("_", " ")
            if name not in seen_names:
                seen_names.add(name)
                tests.append({"name": name, "description": desc})
            continue

        # Numbered items: 1. test_something - description
        m = re.match(r"\d+[\.\)]\s+(test_\w+)(?:\s*[:\-–—]\s*(.+))?", stripped)
        if m:
            name = m.group(1)
            desc = m.group(2).strip() if m.group(2) else name.replace("_", " ")
            if name not in seen_names:
                seen_names.add(name)
                tests.append({"name": name, "description": desc})
            continue

        # Lines containing test_ followed by descriptive text (bullet points etc.)
        m = re.match(r"[-*]\s+(test_\w+)(?:\s*[:\-–—]\s*(.+))?", stripped)
        if m:
            name = m.group(1)
            desc = m.group(2).strip() if m.group(2) else name.replace("_", " ")
            if name not in seen_names:
                seen_names.add(name)
                tests.append({"name": name, "description": desc})
            continue

    return tests


def parse_test_results(report: str) -> list[dict]:
    """Extract which tests passed/failed from an eval report.

    Returns list of dicts: [{"name": "test_name", "status": "PASS"|"FAIL"|"SKIP", "detail": "..."}]
    """
    results: list[dict] = []
    seen_names: set[str] = set()

    for line in report.split("\n"):
        stripped = line.strip()

        # Match patterns like: test_foo ... PASS, ✅ test_foo, ❌ test_foo - reason
        # Also: test_foo: PASS, test_foo — FAIL — detail
        m = re.search(r"(test_\w+)", stripped)
        if not m:
            continue

        name = m.group(1)
        if name in seen_names:
            continue

        upper = stripped.upper()

        # Determine status from the line
        if "SKIP" in upper or "SKIPPED" in upper:
            status = "SKIP"
        elif "FAIL" in upper or "❌" in stripped or "[P0" in stripped or "[P1" in stripped:
            status = "FAIL"
        elif "PASS" in upper or "✅" in stripped or "✓" in stripped:
            status = "PASS"
        else:
            # Line mentions a test but no clear status — skip it
            continue

        seen_names.add(name)

        # Extract detail: anything after the status keyword or after a dash/colon
        detail = ""
        detail_match = re.search(
            r"(?:PASS|FAIL|SKIP|✅|❌|✓)\s*[:\-–—]?\s*(.+)",
            stripped,
            re.IGNORECASE,
        )
        if detail_match:
            detail = detail_match.group(1).strip()

        results.append({"name": name, "status": status, "detail": detail})

    return results


def ensure_orchestrator_dir(workspace: str) -> Path:
    """Create and return the .orchestrator directory."""
    orch_dir = Path(workspace) / ".orchestrator"
    orch_dir.mkdir(parents=True, exist_ok=True)
    return orch_dir
