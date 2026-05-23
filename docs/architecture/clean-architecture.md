# Clean Architecture Guidance

Clean Architecture is a boundary discipline, not a folder-naming ritual. Use
it when the project has real business rules, external adapters, and enough
change pressure to justify explicit boundaries.

## When To Use It

Use Clean Architecture when the code has durable domain rules that should not
depend on UI, database, framework, or transport details.

Good signals:

- Business rules are reused by more than one entrypoint.
- The framework/database is likely to change or has already changed.
- Tests need to exercise use cases without booting the whole app.
- Side effects make the core behavior hard to reason about.

Avoid introducing Clean Architecture just because the project is growing. A
small static site, script, demo, or CRUD app may only need simple modules and
clear names.

## Dependency Direction

Dependencies should point inward:

- UI/controllers call application use cases.
- Use cases depend on domain concepts and ports/interfaces.
- Infrastructure implements ports/interfaces.
- Domain logic does not import framework, database, HTTP, or CLI modules.

If a domain object imports Streamlit, FastAPI, SQLAlchemy, Django, Firebase, or
filesystem code, the boundary is inverted.

## Practical Layers

A practical small-project version can use four layers:

- `domain`: entities, value objects, pure rules.
- `application`: use cases, orchestration, ports.
- `infrastructure`: database, HTTP clients, filesystem, framework adapters.
- `presentation`: Streamlit/FastAPI/CLI/UI entrypoints.

Do not create these folders unless they reduce real confusion. A single module
with pure functions is better than empty architecture ceremony.

## Review Checklist

When reviewing architecture, ask:

- What is the domain rule that must remain stable?
- Which dependencies are volatile implementation details?
- Can the core behavior be tested without external services?
- Are interfaces introduced because there are multiple implementations, or only
  because a pattern was remembered?
- Does the change reduce coupling now, or only add indirection?

## Good Move

Move payment calculation rules into a pure `domain/pricing.py` module and let
the API adapter call it. The rule becomes testable without HTTP or database
setup.

## Bad Move

Create `entities`, `use_cases`, `repositories`, and `controllers` for a
single-page static HTML task. That adds ceremony without protecting any real
business rule.
