# SOLID Principles For Agents

SOLID is a diagnostic lens. Use it to find coupling and change-risk, not as a
reason to add classes everywhere.

## Single Responsibility Principle

A unit should have one reason to change. In practice, split code when one file
mixes unrelated change drivers such as UI rendering, data persistence, network
calls, and domain rules.

Good: a parser module parses input, while a service module decides what to do
with parsed data.

Bad: splitting every two-line helper into a class because "SRP".

## Open Closed Principle

Prefer extension points when there are known variants. Do not invent plugin
systems for hypothetical future cases.

Good: route profile-specific QA through a small dispatcher when profiles
already exist.

Bad: add abstract factories before the second implementation exists.

## Liskov Substitution Principle

Subtypes must preserve expectations. If a subclass changes return shape,
throws surprising errors, or ignores required behavior, composition may be
safer than inheritance.

Good: reviewer agents all return the same `ReviewOutput` schema.

Bad: a special reviewer returns prose while the workflow expects structured
findings.

## Interface Segregation Principle

Consumers should depend on the smallest behavior they need. Large interfaces
force unrelated modules to implement irrelevant methods.

Good: a project file writer exposes `write_file`, while a git service exposes
`git_status` and `git_diff`.

Bad: one `ProjectTools` interface forces every test double to implement search,
read, write, git, and shell commands for a test that only writes one file.

## Dependency Inversion Principle

High-level policy should not depend directly on volatile details. Use small
ports when external services make testing or replacement hard.

Good: node logic calls a bounded MCP client rather than shelling out directly.

Bad: business rules call subprocess, environment variables, and database code
directly.

## Agent Decision Rule

Before applying SOLID, ask:

1. What change is likely?
2. What code would break together?
3. Can a smaller function/module solve the problem?
4. Is there a test that benefits from the abstraction?

If the answer is unclear, keep the simpler design and document the risk.
