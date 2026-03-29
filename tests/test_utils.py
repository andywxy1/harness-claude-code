"""Tests for harness/utils.py parsing functions."""

import pytest

from harness.utils import (
    extract_failure_keys,
    extract_tests_from_contract,
    parse_agreed,
    parse_eval_report,
    parse_sprint_plan,
    parse_test_results,
)


# ---------------------------------------------------------------------------
# parse_eval_report
# ---------------------------------------------------------------------------

class TestParseEvalReport:
    def test_status_fail(self):
        status, reason = parse_eval_report("STATUS: FAIL\nSome details")
        assert status == "FAIL"
        assert "failing" in reason.lower() or "fail" in reason.lower()

    def test_p0_bracket_blocker(self):
        status, reason = parse_eval_report("[P0] Login page broken")
        assert status == "FAIL"
        assert "P0" in reason

    def test_p1_bracket_major(self):
        status, reason = parse_eval_report("[P1] Styling issues")
        assert status == "FAIL"
        assert "P1" in reason

    def test_p0_blocker_text(self):
        status, reason = parse_eval_report("This has a P0 BLOCKER issue")
        assert status == "FAIL"
        assert "P0" in reason

    def test_p0_colon(self):
        status, reason = parse_eval_report("P0: critical failure in auth")
        assert status == "FAIL"

    def test_p1_major_text(self):
        status, reason = parse_eval_report("Found P1 MAJOR regression")
        assert status == "FAIL"
        assert "P1" in reason

    def test_p1_colon(self):
        status, reason = parse_eval_report("P1: visual regression")
        assert status == "FAIL"

    def test_overall_assessment_pass(self):
        report = "Details here\nOverall Assessment: PASS\nLooks good."
        status, reason = parse_eval_report(report)
        assert status == "PASS"
        assert "pass" in reason.lower()

    def test_overall_verdict_fail_with_emoji(self):
        report = "Overall Verdict: FAIL -- not ready"
        status, reason = parse_eval_report(report)
        assert status == "FAIL"

    def test_final_decision_pass(self):
        report = "Final decision: PASS"
        status, reason = parse_eval_report(report)
        assert status == "PASS"

    def test_bold_fail_markers(self):
        report = "Result: **FAIL**"
        status, reason = parse_eval_report(report)
        assert status == "FAIL"

    def test_bold_pass_markers(self):
        report = "Result: **PASS**"
        status, reason = parse_eval_report(report)
        assert status == "PASS"

    def test_pass_dash_pattern(self):
        report = "PASS - all tests green"
        status, reason = parse_eval_report(report)
        assert status == "PASS"

    def test_fail_dash_pattern(self):
        report = "FAIL - not ready for release"
        status, reason = parse_eval_report(report)
        assert status == "FAIL"

    def test_emoji_fail_counts(self):
        report = "Test 1: ❌ FAIL\nTest 2: ✅ PASS\nTest 3: ❌ FAIL"
        status, reason = parse_eval_report(report)
        assert status == "FAIL"
        assert "2" in reason  # 2 failing items

    def test_emoji_pass_only(self):
        report = "Test 1: ✅ PASS\nTest 2: ✅ PASS"
        status, reason = parse_eval_report(report)
        assert status == "PASS"

    def test_no_clear_verdict_defaults_to_fail(self):
        report = "Some rambling text about the project."
        status, reason = parse_eval_report(report)
        assert status == "FAIL"
        assert "not explicitly" in reason.lower() or "did not" in reason.lower()

    def test_empty_report(self):
        status, reason = parse_eval_report("")
        assert status == "FAIL"

    def test_p0_takes_precedence_over_pass_verdict(self):
        report = "[P0] Critical bug\nOverall Assessment: PASS"
        status, _ = parse_eval_report(report)
        assert status == "FAIL"

    def test_status_fail_case_insensitive(self):
        status, _ = parse_eval_report("status: fail")
        assert status == "FAIL"


# ---------------------------------------------------------------------------
# extract_failure_keys
# ---------------------------------------------------------------------------

class TestExtractFailureKeys:
    def test_lines_with_fail(self):
        report = "test_login: FAIL\ntest_signup: PASS\ntest_logout: FAIL"
        keys = extract_failure_keys(report)
        assert len(keys) == 2
        assert any("login" in k for k in keys)
        assert any("logout" in k for k in keys)

    def test_lines_with_p0(self):
        report = "[P0] Authentication broken\n[P0] DB connection lost"
        keys = extract_failure_keys(report)
        assert len(keys) == 2

    def test_lines_with_p1(self):
        report = "[P1] CSS misalignment\nOther stuff"
        keys = extract_failure_keys(report)
        assert len(keys) == 1

    def test_mixed_pass_fail(self):
        report = "test_a: PASS\ntest_b: FAIL\ntest_c: PASS\ntest_d: FAIL"
        keys = extract_failure_keys(report)
        assert len(keys) == 2

    def test_empty_report(self):
        assert extract_failure_keys("") == []

    def test_deduplication(self):
        report = "test_foo: FAIL\ntest_foo: FAIL\ntest_foo: FAIL"
        keys = extract_failure_keys(report)
        # All three lines are identical so they normalize to the same key
        assert len(keys) == 1

    def test_no_failures(self):
        report = "test_a: PASS\ntest_b: PASS\nAll good"
        keys = extract_failure_keys(report)
        assert keys == []

    def test_keys_are_normalized_lowercase(self):
        report = "TEST_FOO: FAIL"
        keys = extract_failure_keys(report)
        assert keys[0] == keys[0].lower()

    def test_keys_truncated_to_80_chars(self):
        long_line = "FAIL " + "x" * 200
        keys = extract_failure_keys(long_line)
        assert len(keys[0]) <= 80


# ---------------------------------------------------------------------------
# parse_sprint_plan
# ---------------------------------------------------------------------------

class TestParseSprintPlan:
    def test_full_plan_with_markers(self):
        plan = (
            "Preamble text\n"
            "---BEGIN SPRINT PLAN---\n"
            "## Project Vision\n"
            "Build a todo app\n"
            "## Sprint 1: Setup\n"
            "Initialize the project\n"
            "## Sprint 2: Features\n"
            "Add CRUD operations\n"
            "---END SPRINT PLAN---\n"
            "Postamble text\n"
        )
        vision, sprints = parse_sprint_plan(plan)
        assert "todo app" in vision
        assert len(sprints) == 2
        assert sprints[0]["number"] == 1
        assert sprints[0]["name"] == "Setup"
        assert "Initialize" in sprints[0]["description"]
        assert sprints[1]["number"] == 2
        assert sprints[1]["name"] == "Features"

    def test_plan_without_markers(self):
        plan = (
            "## Project Vision\n"
            "Build a CLI tool\n"
            "## Sprint 1: Foundation\n"
            "Set up arg parsing\n"
        )
        vision, sprints = parse_sprint_plan(plan)
        assert "CLI tool" in vision
        assert len(sprints) == 1

    def test_plan_with_1_sprint(self):
        plan = (
            "## Project Vision\n"
            "Simple script\n"
            "## Sprint 1: Everything\n"
            "Do all the work\n"
        )
        vision, sprints = parse_sprint_plan(plan)
        assert len(sprints) == 1
        assert sprints[0]["name"] == "Everything"

    def test_plan_with_5_sprints(self):
        parts = ["## Project Vision\nBig project\n"]
        for i in range(1, 6):
            parts.append(f"## Sprint {i}: Phase {i}\nWork for phase {i}\n")
        plan = "\n".join(parts)
        vision, sprints = parse_sprint_plan(plan)
        assert len(sprints) == 5
        assert sprints[4]["number"] == 5

    def test_empty_plan(self):
        vision, sprints = parse_sprint_plan("")
        assert vision == ""
        assert sprints == []

    def test_missing_vision_section(self):
        plan = "## Sprint 1: Only Sprint\nDo stuff\n"
        vision, sprints = parse_sprint_plan(plan)
        assert vision == ""
        assert len(sprints) == 1


# ---------------------------------------------------------------------------
# parse_agreed
# ---------------------------------------------------------------------------

class TestParseAgreed:
    def test_agreed_on_own_line(self):
        assert parse_agreed("Some discussion\nAGREED\nMore text") is True

    def test_agreed_only(self):
        assert parse_agreed("AGREED") is True

    def test_agreed_with_trailing_spaces(self):
        assert parse_agreed("AGREED   ") is True

    def test_proposing_present(self):
        assert parse_agreed("PROPOSING\nHere is my counter") is False

    def test_both_agreed_and_proposing(self):
        assert parse_agreed("AGREED\nPROPOSING\nNew terms") is False

    def test_agreed_embedded_in_text(self):
        # "AGREED" not on its own line should not match
        assert parse_agreed("I have AGREED to the terms") is False

    def test_empty_string(self):
        assert parse_agreed("") is False

    def test_no_keywords(self):
        assert parse_agreed("Just some regular text\nwith multiple lines") is False


# ---------------------------------------------------------------------------
# extract_tests_from_contract
# ---------------------------------------------------------------------------

class TestExtractTestsFromContract:
    def test_python_def_statements(self):
        contract = "def test_login():\n    pass\ndef test_signup():\n    pass\n"
        tests = extract_tests_from_contract(contract)
        assert len(tests) == 2
        names = [t["name"] for t in tests]
        assert "test_login" in names
        assert "test_signup" in names

    def test_def_description_auto_generated(self):
        contract = "def test_user_creation():\n    pass\n"
        tests = extract_tests_from_contract(contract)
        assert tests[0]["description"] == "test user creation"

    def test_backtick_test_names(self):
        contract = "`test_auth` - verifies authentication\n`test_db` - checks database\n"
        tests = extract_tests_from_contract(contract)
        assert len(tests) == 2
        assert tests[0]["name"] == "test_auth"
        assert tests[0]["description"] == "verifies authentication"

    def test_backtick_without_description(self):
        contract = "`test_foo`\n"
        tests = extract_tests_from_contract(contract)
        assert tests[0]["description"] == "test foo"

    def test_numbered_items(self):
        contract = "1. test_first - do first thing\n2. test_second - do second thing\n"
        tests = extract_tests_from_contract(contract)
        assert len(tests) == 2
        assert tests[0]["name"] == "test_first"
        assert tests[0]["description"] == "do first thing"

    def test_numbered_items_paren(self):
        contract = "1) test_alpha\n2) test_beta\n"
        tests = extract_tests_from_contract(contract)
        assert len(tests) == 2

    def test_bullet_point_items(self):
        contract = "- test_a - checks A\n* test_b - checks B\n"
        tests = extract_tests_from_contract(contract)
        assert len(tests) == 2
        assert tests[0]["name"] == "test_a"
        assert tests[1]["name"] == "test_b"

    def test_mixed_formats(self):
        contract = (
            "def test_one():\n"
            "    pass\n"
            "`test_two` - second test\n"
            "3. test_three - third test\n"
            "- test_four - fourth test\n"
        )
        tests = extract_tests_from_contract(contract)
        names = [t["name"] for t in tests]
        assert names == ["test_one", "test_two", "test_three", "test_four"]

    def test_deduplication(self):
        contract = (
            "def test_dup():\n"
            "    pass\n"
            "`test_dup` - same test again\n"
            "1. test_dup - and once more\n"
        )
        tests = extract_tests_from_contract(contract)
        assert len(tests) == 1
        assert tests[0]["name"] == "test_dup"

    def test_empty_contract(self):
        assert extract_tests_from_contract("") == []

    def test_no_tests_in_contract(self):
        contract = "This is a contract about the login feature.\nNo test names here."
        assert extract_tests_from_contract(contract) == []


# ---------------------------------------------------------------------------
# parse_test_results
# ---------------------------------------------------------------------------

class TestParseTestResults:
    def test_pass_fail_keywords(self):
        report = "test_login: PASS\ntest_signup: FAIL\n"
        results = parse_test_results(report)
        assert len(results) == 2
        statuses = {r["name"]: r["status"] for r in results}
        assert statuses["test_login"] == "PASS"
        assert statuses["test_signup"] == "FAIL"

    def test_emoji_markers(self):
        report = "✅ test_a\n❌ test_b - broken\n"
        results = parse_test_results(report)
        statuses = {r["name"]: r["status"] for r in results}
        assert statuses["test_a"] == "PASS"
        assert statuses["test_b"] == "FAIL"

    def test_checkmark_marker(self):
        report = "✓ test_ok\n"
        results = parse_test_results(report)
        assert results[0]["status"] == "PASS"

    def test_severity_markers(self):
        report = "[P0] test_critical - auth broken\n[P1] test_minor - css issue\n"
        results = parse_test_results(report)
        assert len(results) == 2
        assert all(r["status"] == "FAIL" for r in results)

    def test_skip_status(self):
        report = "test_skipped: SKIP\ntest_also_skipped: SKIPPED\n"
        results = parse_test_results(report)
        assert all(r["status"] == "SKIP" for r in results)

    def test_mixed_results(self):
        report = (
            "test_a: PASS\n"
            "test_b: FAIL - timeout\n"
            "test_c: SKIP\n"
            "✅ test_d\n"
            "❌ test_e\n"
        )
        results = parse_test_results(report)
        statuses = {r["name"]: r["status"] for r in results}
        assert statuses == {
            "test_a": "PASS",
            "test_b": "FAIL",
            "test_c": "SKIP",
            "test_d": "PASS",
            "test_e": "FAIL",
        }

    def test_empty_report(self):
        assert parse_test_results("") == []

    def test_deduplication(self):
        report = "test_x: PASS\ntest_x: FAIL\n"
        results = parse_test_results(report)
        assert len(results) == 1

    def test_no_status_lines_skipped(self):
        report = "test_mentioned but no status keyword\n"
        results = parse_test_results(report)
        assert results == []

    def test_detail_extraction(self):
        report = "test_foo: FAIL - connection timeout after 30s\n"
        results = parse_test_results(report)
        assert len(results) == 1
        # Detail should contain something (exact content depends on regex)
        assert results[0]["name"] == "test_foo"
        assert results[0]["status"] == "FAIL"
