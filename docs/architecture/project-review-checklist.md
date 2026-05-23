# Project Review Checklist

Use this checklist when a user asks to inspect a project, understand what is
inside, or propose the next safe improvement.

## Intake Order

Review in this order:

1. Identify project root and whether it is a git repository.
2. Detect stack, frameworks, package managers, and runtime entrypoints.
3. Find tests, lint commands, build commands, and CI signals.
4. Read small high-signal files: README, manifests, app entrypoints, config.
5. Inspect git status and diff before suggesting edits.
6. Summarize risks before proposing changes.

## What To Report

A useful project review includes:

- What the project appears to be.
- Main technologies and entrypoints.
- How to run or verify it, if detectable.
- Current risks: dirty git state, no tests, missing docs, unclear ownership.
- The next safest improvement and why it is safe.

## What Not To Do

Do not rewrite files during an advisory review. Do not invent file contents.
Do not claim tests pass unless they were run. Do not propose a large
architecture migration before checking whether the project has tests.

## Small Project Guidance

For small projects, prefer:

- README/run instructions.
- Basic git initialization if missing.
- One simple verification command or manual checklist.
- Minimal styling or structure changes only when explicitly requested.

Do not recommend Clean Architecture, dependency injection containers, or
multi-layer folders for a one-file static page unless the user asks for a
larger application.

## Output Shape

For advisory Project Mode output, use:

- Observations.
- Risks.
- Recommended next steps.
- Verification plan.

Keep it grounded in selected files and project brief facts.
