# Test Strategy

Testing strategy should match the project's risk and shape. Do not add heavy
test infrastructure before identifying what behavior needs protection.

## Choose The Right Level

Use unit tests for pure logic, parsing, routing, validation, and deterministic
helpers.

Use integration tests when multiple modules must cooperate, such as workflow
nodes, persistence, or MCP boundaries.

Use end-to-end or browser checks for user-visible flows, static UI previews,
and app navigation.

## Project Review Signals

When reviewing a project, detect:

- Existing test framework and commands.
- Whether tests require services such as Postgres, Docker, or Ollama.
- Whether tests are fast enough to run by default.
- Which manual checks are needed when no automated test exists.

## Safe Test Additions

For small changes:

- Add focused regression tests near the changed behavior.
- Prefer deterministic tests over model calls.
- Mock LLM agents and MCP tools for workflow-level tests.
- Keep service-backed tests skippable when the service is unavailable.

## Avoid

- Adding broad end-to-end tests for a one-line helper.
- Requiring live LLM calls in ordinary unit tests.
- Treating skipped-only test runs as success.
- Claiming verification passed when only static analysis ran.

## Reporting

Always report:

- Commands run.
- Pass/fail/skip counts.
- Services that were unavailable.
- Remaining manual verification, if any.
