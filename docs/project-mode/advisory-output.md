# Project Mode Advisory Output

Project Mode has two different behaviors: advisory review and concrete
implementation. Keep them separate.

## Advisory Mode

Use advisory output when the user asks to analyze, inspect, review, understand,
or propose improvements for a project.

Advisory output should not modify source or artifact files. It should produce
`PROJECT_PROPOSAL.md` when routed through the project profile.

## Advisory Structure

Use this shape:

- Summary of what the project appears to be.
- Observations grounded in selected files.
- Risks and unknowns.
- Recommended next safe steps.
- Verification plan.

Do not invent files, commands, or test results. If the folder is not a git
repository, say that git safety is limited.

## Implementation Mode

Use implementation output when the user explicitly asks to create, change,
fix, refactor, style, test, commit, or apply a concrete change.

Implementation output may produce files, but Project Mode should still show a
diff preview first and require explicit apply before writing to the selected
folder.

## Grounding Rules

Use Project Intake and Project Brief as source-of-truth context:

- Preserve existing page/topic intent unless the user asks to replace it.
- Do not rewrite app internals when the selected target is a separate project.
- Mention dirty git state or missing tests as risks, not as blockers unless the
  requested change is unsafe.

## Good Advisory Response

"This appears to be a static HTML project with `index.html` as entrypoint. It
has no detected tests and is not a git repo. The safest next step is to add
README run instructions and initialize git before larger edits."

## Bad Advisory Response

"I updated `index.html`, added CSS, and created a new architecture" when the
user only asked to inspect the project.
