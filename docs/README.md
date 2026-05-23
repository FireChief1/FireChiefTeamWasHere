# Engineering Standards & Knowledge Base

This directory contains the documentation that powers the RAG (Retrieval-Augmented Generation) layer of the multi-agent code development system. The workflow retrieves relevant chunks for the task and passes that context to downstream agents.

## Document Structure

```
docs/
├── architecture.md            # System architecture (revised, resilience-hardened)
├── architecture-edge-cases.md # Failure-mode register (FMEA)
├── architecture/          # Architecture review and design decision guidance
│   ├── clean-architecture.md
│   ├── overengineering-guards.md
│   ├── project-review-checklist.md
│   ├── refactoring-heuristics.md
│   └── solid-principles.md
├── coding-standards/      # How code should be written
│   ├── python-style-guide.md
│   ├── naming-conventions.md
│   ├── docstring-standards.md
│   └── type-hints.md
├── code-review/           # What reviewers check
│   ├── review-checklist.md
│   └── common-issues.md
├── testing/               # Testing standards
│   ├── pytest-patterns.md
│   ├── test-design.md
│   └── test-strategy.md
├── frontend/              # Static web and UI quality guidance
│   ├── html-css-standards.md
│   ├── static-site-quality.md
│   ├── static-ui-quality.md
│   └── supply-chain-security.md
├── security/              # Security guidelines
│   └── security-guidelines.md
├── patterns/              # Design patterns
│   ├── async-patterns.md
│   ├── error-handling.md
│   └── design-patterns.md
├── project-mode/          # Project Mode output and file safety rules
│   ├── advisory-output.md
│   └── file-output-rules.md
└── git/                   # Version control
    └── commit-conventions.md
```

## How Agents Use This Knowledge

| Agent | Primary Documents |
|-------|-------------------|
| **Analyst** | design-patterns.md, async-patterns.md |
| **Developer** | python-style-guide.md, naming-conventions.md, type-hints.md, docstring-standards.md, design-patterns.md, async-patterns.md, error-handling.md, solid-principles.md, refactoring-heuristics.md |
| **Reviewer** | review-checklist.md, common-issues.md, python-style-guide.md, security-guidelines.md |
| **QA** | pytest-patterns.md, test-design.md |
| **Project Mode** | project-review-checklist.md, advisory-output.md, clean-architecture.md, overengineering-guards.md, file-output-rules.md |
| **Static Web / UI** | html-css-standards.md, static-site-quality.md, static-ui-quality.md, supply-chain-security.md |

## RAG Optimization Notes

All documents follow these conventions for optimal vector retrieval:

1. **Self-contained sections** — every `##` heading section can stand alone as a chunk.
2. **WHY → RULE → GOOD → BAD pattern** — concrete examples in every rule.
3. **Consistent terminology** — same concept uses the same words across docs.
4. **Keyword-rich** — natural inclusion of searchable terms.
5. **Code blocks tagged** — language hints for syntax-aware embeddings.

## Ingestion

```bash
python -m app.rag.ingest
```

This loads all markdown files into ChromaDB with `nomic-embed-text` embeddings.
