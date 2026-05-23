# Overengineering Guards

Agents should optimize for maintainability, not architectural theater.
Patterns are useful only when they reduce real change cost.

## Red Flags

Pause before adding:

- Abstract base classes with one implementation.
- Repository/service/use-case layers for simple CRUD or static content.
- Dependency injection containers in small scripts.
- Event buses without multiple producers/consumers.
- Microservices or queues for a single-process app.
- Generic plugin systems before a second plugin exists.

## Simpler Alternatives

Prefer:

- A clear function over a class.
- A module boundary over a framework.
- A data class or Pydantic model over a custom hierarchy.
- A small dispatcher over a full strategy framework.
- A README note over a configuration system.

## Decision Test

An abstraction is justified when it does at least one of these:

- Removes meaningful duplication.
- Isolates a volatile dependency.
- Makes important behavior testable.
- Encodes a real domain boundary.
- Supports existing variants already present in the code.

If none apply, keep the design direct.

## Project Mode Advice

When asked for next improvements, prefer the smallest safe step. A practical
sequence is: document how to run, add a basic test, isolate risky IO, then
consider larger architecture.

## Bad Recommendation

"Move this one-page site to Clean Architecture with controllers, repositories,
entities, and services."

## Good Recommendation

"Keep the page simple; add semantic HTML, a small stylesheet, and a manual
preview checklist. Revisit architecture only if it becomes a multi-page app."
