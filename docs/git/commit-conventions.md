# Commit Message Conventions

This project follows the **Conventional Commits** specification. Commit messages must be machine-parseable, human-readable, and informative enough to use git history as a changelog.

## Message Structure

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

- **type** — what kind of change (required)
- **scope** — area of the codebase affected (optional)
- **subject** — short summary, imperative mood (required)
- **body** — detailed explanation of *why*, not *what* (optional)
- **footer** — references to issues, breaking change notes (optional)

## Commit Types

**Rule:** Use one of these standard types.

| Type | Use For |
|------|---------|
| `feat` | A new user-facing feature |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `style` | Formatting, whitespace, no logic changes |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `test` | Adding or fixing tests |
| `chore` | Build process, tooling, dependency updates |
| `ci` | CI/CD pipeline changes |
| `revert` | Reverting a previous commit |

## Subject Line Rules

**Rule:** The subject line:
1. Starts with a lowercase letter
2. Uses imperative mood (`add` not `added`)
3. Does NOT end with a period
4. Stays under 72 characters

**Why:** Imperative mood matches `git`'s own conventions (e.g., "Merge branch X"). Brevity makes `git log --oneline` readable.

**Good:**
```
feat(agents): add reviewer agent with structured output
fix(pool): handle connection error in fallback chain
docs(readme): update installation instructions
refactor(graph): split workflow builder into smaller functions
```

**Bad:**
```
Added a reviewer agent.         # past tense, period, no type
FEAT: NEW AGENT                 # uppercase, no scope
fix bug                         # too vague
```

## When to Use Scope

**Rule:** Use scope when the change is localized to one area. Omit it when changes span the codebase.

**Why:** Scope helps readers grep for changes in their area of interest.

**Good scopes for this project:**
- `agents` — agent implementations
- `graph` — LangGraph workflow
- `pool` — LLM backend pool
- `mcp` — MCP tool integration
- `rag` — retrieval pipeline
- `ui` — Streamlit interface
- `docs` — documentation
- `ci` — continuous integration

## Body Section

**Rule:** Write a body for any non-trivial change. The body explains:
- **Why** the change was made
- What the change does (only if not obvious from the subject)
- Tradeoffs considered
- Side effects to be aware of

**Why:** Six months later, the body is the only context you have.

**Good:**
```
fix(pool): mark node unhealthy after 3 consecutive failures

Previously, a single transient error was treated the same as a
hard failure. This caused the pool to repeatedly retry against
a node that was clearly down, increasing latency for all users.

Now we track consecutive failures per node and skip it for 30s
after the third failure. Recovery happens automatically via the
health check loop.
```

**Bad:**
```
fix(pool): fix bug

(no body, no context, useless in 6 months)
```

## Subject and Body Together

**Rule:** Subject is one line. Body is separated by a blank line. Wrap body at 72 characters.

**Why:** Tools like `git log` and email handle wrapped text correctly. Long lines look broken in narrow terminals.

**Good:**
```
feat(rag): add per-agent retriever profiles

Different agents need different context. Reviewer agents benefit
from coding standards and review checklists; developer agents
need code examples and design patterns.

This change introduces a `RetrieverProfile` that maps an agent
role to a set of document filters. The default profile is
preserved for unspecified roles.

Closes #42
```

## Breaking Changes

**Rule:** Breaking changes must be flagged with `!` after the type/scope OR via a `BREAKING CHANGE:` footer.

**Why:** Consumers need to know when their integration may break.

**Good:**
```
feat(pool)!: rename Capability.REASONER to Capability.GENERAL

BREAKING CHANGE: Capability.REASONER has been renamed to
Capability.GENERAL to reflect its broader usage. Update any
direct references in custom agent code.

Migration:
  - Capability.REASONER  →  Capability.GENERAL
```

## Footers

**Rule:** Use footers for:
- Referencing issues: `Closes #42`, `Fixes #100`, `Related: #50`
- Co-authors: `Co-Authored-By: Name <email>`
- Breaking changes: `BREAKING CHANGE: <description>`

**Good:**
```
fix(ui): correct streaming response handling in chat panel

The streaming response was being concatenated incorrectly when
the model emitted a partial UTF-8 sequence. Buffer until valid
boundaries before rendering.

Fixes #128
Co-Authored-By: Alice <alice@example.com>
```

## Atomic Commits

**Rule:** Each commit should represent one logical change. If you can't describe the commit without using "and", split it.

**Why:** Atomic commits are easy to review, easy to revert, and easy to cherry-pick.

**Good (separated):**
```
feat(agents): add security agent
test(agents): add tests for security agent
docs(security): document security agent behavior
```

**Bad (kitchen-sink):**
```
feat: add security agent, fix pool bug, update docs, and rename Capability
```

## When to Commit

**Rule:** Commit early, commit often. Push at least once per day. Never go to bed with uncommitted work.

**Why:** Local commits are cheap and reversible. Lost work is expensive.

## Branching

**Rule:** Feature branches use the format `<type>/<short-description>`.

**Good:**
```
feat/reviewer-agent
fix/pool-fallback-error
docs/rag-architecture
refactor/split-workflow-builder
```

## Pull Request Title and Description

**Rule:** PR titles follow the same Conventional Commits format. PR descriptions include:
- What changed and why
- Testing performed
- Screenshots for UI changes
- Issues closed

**Good PR template:**
```
## Summary
Brief description of the change.

## Why
Motivation: what problem this solves, what option was chosen and why.

## Changes
- Bullet list of significant changes

## Testing
- How the change was tested
- New tests added

## Screenshots / Demo
(for UI or behavior changes)

Closes #42
```

## Commit Message Examples (Project-Specific)

```
feat(graph): add conditional edge from supervisor to developer
feat(pool): implement circuit breaker for unhealthy nodes
feat(mcp): wire up filesystem server with workspace restriction
feat(rag): add chunking strategy for python source files
feat(ui): show pipeline state matrix with real-time updates

fix(pool): release semaphore on early return path
fix(agents): handle empty plan from analyst gracefully
fix(rag): correct embedding dimension mismatch on reingest

refactor(graph): extract routing logic into separate module
refactor(agents): unify agent base class signature

docs(architecture): add capability-based routing rationale
docs(setup): document NVIDIA driver installation on Ubuntu

test(pool): add tests for failover behavior under load
test(integration): add end-to-end pipeline test

chore(deps): bump langchain to 0.3.0
chore(ruff): adopt new lint ruleset
```

## What Not to Do

| Bad Commit | Why It's Bad |
|------------|--------------|
| `WIP` | No information |
| `fix typo` | What typo? Where? |
| `update` | What was updated? |
| `Done.` | Done with what? |
| `Asked by manager` | Why is this in the code? |
| `final fix really final this time` | Trust issues, no useful info |
| `🚀✨🎉 ship it` | Emojis without info |

## Verification

The project uses a commit-msg hook to enforce these conventions. The hook rejects commits that:
- Don't match the `<type>(<scope>): <subject>` pattern
- Have subjects over 72 characters
- Have subjects in past tense or with trailing punctuation

Install hooks with:
```bash
pre-commit install --hook-type commit-msg
```
