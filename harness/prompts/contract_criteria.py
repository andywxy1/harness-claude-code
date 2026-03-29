CONTRACT_CRITERIA = """
## What a Complete Sprint Contract Looks Like

A contract is ready for AGREED only when it meets ALL of these:

### Structure
- Every feature has: Description, Acceptance Criteria, Tests
- Features are numbered and independent where possible
- An "Out of Scope" section lists what was discussed but deferred

### Descriptions
- Each describes WHAT and WHY, not HOW to implement
- A new engineer who has never seen the codebase could read it
  and understand what to build without asking questions
- No ambiguous words: "appropriate", "nice", "handles well", "works properly"
  — replace with exact behavior

### Acceptance Criteria
- Every criterion is binary — it either passes or it doesn't
- Criteria use exact values: specific status codes, exact error messages,
  pixel breakpoints, character limits, time thresholds
- Each feature has criteria for:
  - Happy path (normal usage)
  - Error states (bad input, missing data, unauthorized)
  - Edge cases (empty, maximum, concurrent, duplicate)
  - If interactive: loading states, disabled states, responsive behavior

### Tests
- Every acceptance criterion has at least one test
- Tests are written as function signatures with docstrings that describe:
  - Setup: what state needs to exist before the test
  - Action: exact input or interaction
  - Assertion: exact expected output or state change
- Tests are specific enough that two engineers would write
  the same assertions independently
- Tests cover: happy path, error cases, edge cases, and any
  user-facing behavior from the acceptance criteria

### Scope
- The contract is achievable in one sprint — not a wishlist
- Features are prioritized: must-have vs nice-to-have
  (nice-to-have can be dropped if sprint runs long)
- No feature depends on work from a future sprint

### Exit Criteria Section
- A clear statement at the bottom:
  "This sprint is COMPLETE when: all tests pass, all P0/P1 issues
   from product evaluation are resolved, and the application runs
   without errors"

If ANY of the above is missing or weak, the contract is not ready.
Do not say AGREED until all criteria are met."""
