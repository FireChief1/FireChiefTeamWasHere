# Code Review Checklist

This checklist defines what reviewer agents must verify when inspecting code produced by developer agents. Reviewers must check every applicable category and report any violations as structured feedback.

## Functional Correctness

**Rule:** The code must solve the problem stated in the task. Verify against the original requirements.

**Checks:**
- Does the function produce correct output for the described inputs?
- Are all required behaviors implemented?
- Are edge cases (empty inputs, zero, negative values, None) handled?
- Does the code handle boundary conditions (off-by-one, fence-post errors)?
- Does it match the expected API contract (parameter names, return types)?

**Example feedback:**
```
ISSUE: function returns -1 for negative inputs but task spec says
       it should raise ValueError. Add input validation at line 12.
```

## Naming Clarity

**Rule:** Names must follow the project's `naming-conventions.md` and describe intent without comments.

**Checks:**
- Variables and functions use `snake_case`.
- Classes use `PascalCase`.
- Constants use `UPPER_SNAKE_CASE`.
- Boolean names use `is_`, `has_`, `can_`, `should_` prefix.
- No cryptic abbreviations (`usr`, `cnt`, `tmp`).
- No generic names (`data`, `info`, `result`) where context is specific.
- Collection names are plural.

## Type Hints

**Rule:** All function signatures must have complete type hints. See `type-hints.md`.

**Checks:**
- Every parameter has a type hint (except `self`, `cls`).
- Return type is annotated (use `-> None` if no return).
- No use of `Any` without justification.
- Modern syntax: `list[X]` not `List[X]`, `X | None` not `Optional[X]`.
- Class attributes are typed.

## Docstrings

**Rule:** Public functions, classes, and modules need Google-style docstrings. See `docstring-standards.md`.

**Checks:**
- Module has a top-level docstring.
- Every public function has a one-line summary in imperative mood.
- `Args:`, `Returns:`, `Raises:` sections are present where applicable.
- Examples are provided for non-trivial functions.
- Docstrings explain *why* and *what*, not just *how* (which the code shows).

## Error Handling

**Rule:** Exceptions must be specific, informative, and propagated correctly. See `error-handling.md`.

**Checks:**
- No bare `except:` clauses.
- No `except Exception` without re-raise or logging.
- Custom exceptions inherit from a project base exception.
- Error messages include relevant context (which value, which file).
- Resources are released in `finally` or via context managers.
- Retries use exponential backoff, not bare `time.sleep` loops.

**Example feedback:**
```
ISSUE: line 45 catches `Exception` and silently passes. This swallows
       all errors including KeyboardInterrupt. Either re-raise or
       narrow the except clause to the specific exceptions you handle.
```

## Security

**Rule:** Code must not introduce security vulnerabilities. See `security-guidelines.md`.

**Checks:**
- User input is validated and sanitized before use.
- No SQL string concatenation; use parameterized queries.
- No `eval()`, `exec()`, or `pickle.loads` on untrusted data.
- File paths are validated to prevent path traversal.
- Subprocess calls use list args, not shell=True with user input.
- Secrets are not hardcoded; use environment variables or secret managers.
- HTTP timeouts are always set.
- No use of `random` for security purposes; use `secrets` module.

## Performance

**Rule:** Avoid obvious performance pitfalls. Premature optimization is bad; quadratic-when-it-should-be-linear is worse.

**Checks:**
- No nested loops where a set/dict lookup would suffice.
- No repeated database queries inside a loop (N+1 problem).
- Large iterables are processed lazily with generators when possible.
- String concatenation in loops uses `"".join()`, not `+=`.
- Network calls have timeouts.
- No blocking I/O inside async functions.

**Example feedback:**
```
ISSUE: line 23 checks membership against a list in a loop.
       Convert allowed_roles to a set on line 18 for O(1) lookup.
```

## Testing

**Rule:** New functions must have tests. See `pytest-patterns.md`.

**Checks:**
- A test file exists in `tests/` matching the module path.
- The happy path is tested.
- At least one edge case is tested (empty input, None, max size).
- Error paths are tested (parametrize with invalid inputs).
- Tests do not depend on each other (no shared mutable state).
- Mocks are used at the boundary, not for the unit under test.

## Code Smells

**Rule:** Flag patterns that signal deeper problems even if they "work".

**Checks:**
- Functions longer than 50 lines — consider splitting.
- Functions with more than 5 parameters — consider a dataclass or **kwargs.
- Cyclomatic complexity > 10 — too many branches.
- Deeply nested code (> 3 levels of indentation) — extract or invert.
- Magic numbers — replace with named constants.
- Duplicated code — extract a helper.
- Comments that explain *what* the code does — rewrite the code to be self-explanatory.
- TODO/FIXME comments without context — should reference an issue or have a date.

## API Design

**Rule:** Public APIs should be intuitive, hard to misuse, and consistent with the rest of the codebase.

**Checks:**
- Parameter order is consistent across related functions.
- Keyword-only arguments (`*,`) for boolean flags and optional config.
- Return types are consistent (e.g., don't return `User` sometimes and `dict` other times).
- Side effects are documented (writes, network calls, mutations).
- Functions either return a value OR mutate, not both.

## Concurrency

**Rule:** Concurrent code requires extra scrutiny. See `async-patterns.md`.

**Checks:**
- Async functions are `async def`, called with `await`.
- No blocking calls (`time.sleep`, sync `requests`, file I/O) inside async functions.
- Locks are used to protect shared mutable state.
- Tasks are awaited or explicitly given to a task group.
- Cancellation is handled gracefully (cleanup on `CancelledError`).
- No race conditions in increment/read patterns.

## Documentation

**Rule:** Code changes that affect behavior must update relevant documentation.

**Checks:**
- Public API changes are reflected in module docstrings.
- New configuration options are documented in `README.md` or `config.md`.
- Breaking changes are flagged in `CHANGELOG.md` if it exists.
- Examples in docstrings still work.

## Severity Levels

Reviewers must classify each finding by severity:

- **BLOCKER** — must fix before merge (security issue, broken functionality, no tests).
- **MAJOR** — should fix before merge (style violation, missing docstring, performance issue).
- **MINOR** — nice to fix (naming improvement, refactor suggestion).
- **INFO** — observation, no action required (questions, alternative approaches).

## Output Format

Reviewer feedback must be structured as JSON for downstream processing:

```json
{
  "severity": "MAJOR",
  "category": "naming",
  "file": "agents/developer.py",
  "line": 42,
  "issue": "Variable `tmp` is too generic. Suggest `partial_response`.",
  "suggestion": "Rename `tmp` to `partial_response`."
}
```
