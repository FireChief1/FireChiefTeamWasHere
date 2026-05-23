# Refactoring Heuristics

Refactoring should reduce risk or unlock a clear next change. It should not be
mixed into unrelated feature work unless the feature cannot be implemented
safely without it.

## Good Reasons To Refactor

Refactor when:

- A file has multiple responsibilities that change independently.
- A bug fix would require duplicating logic.
- Tests need a smaller unit boundary to verify behavior.
- A workflow step is difficult to reason about because IO and policy are mixed.
- The same condition or validation appears in several places.

## Reasons To Wait

Wait when:

- There are no tests around the behavior.
- The code is ugly but stable and unrelated to the requested change.
- The refactor would touch many files without changing risk.
- The project is in the middle of a failing workflow or release.
- The proposed abstraction only names a pattern without removing complexity.

## Safe Refactor Sequence

Use this order:

1. Characterize current behavior with focused tests.
2. Extract the smallest coherent function/module.
3. Keep public behavior and file ownership stable.
4. Run tests after each meaningful move.
5. Update docs only for changed architecture, not every internal move.

## Blast Radius Check

Before editing, identify:

- User-facing behavior affected.
- Files/modules touched.
- Tests that prove no regression.
- Fallback plan if the refactor fails.

If blast radius is high and confidence is low, propose the refactor instead of
making it in the same task.

## Good Example

Splitting a large `nodes.py` into `analyst_step.py`, `developer_step.py`,
`qa_step.py`, and `reviewer_step.py` is useful when tests can target each node
and workflow imports stay stable through a facade.

## Bad Example

Renaming packages, changing prompts, altering QA behavior, and redesigning UI
in one refactor makes failures hard to diagnose.
