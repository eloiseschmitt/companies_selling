# AGENTS.md

## Project Overview

- Main language: Python
- Framework: FastAPI
- Database: SQLite by default
- Architecture style: pragmatic, feature-oriented
- Goal: maintainable, readable, low-complexity code

This project values simplicity and clarity over architectural purity.

---

# Core Principles

## Prefer simplicity

- Keep implementations straightforward
- Avoid unnecessary abstractions
- Avoid premature optimization
- Prefer explicit code over clever code
- Reuse existing project patterns before introducing new ones

## Minimize changes

- Make the smallest reasonable change solving the problem
- Avoid broad refactors unless explicitly requested
- Do not rewrite working code without a strong reason

## Dependencies

- Prefer Python standard library first
- External dependencies are allowed only with clear justification
- Do not introduce heavy frameworks or utility libraries unnecessarily

---

# Architecture Guidelines

## Business logic

Business logic must not live directly inside:
- Django views
- serializers
- forms
- model methods containing complex orchestration

Prefer dedicated service functions/modules.

Recommended pattern:

```python
# services/user_creation.py

def create_user(...):
    ...
```

# Commit Rules

After completing a modification, always propose a git commit message following Conventional Commits.

Format:

<type>: short summary

Optional body:
- explain why the change was made
- summarize important implementation details
- mention limitations if relevant

Allowed commit types:
- feat
- fix
- refactor
- test
- docs
- chore

Examples:

feat: add CSV export for invoices

fix: handle missing user profile in dashboard view

refactor: simplify invoice generation flow

Keep commit titles concise and descriptive.

Avoid:
- vague messages
- overly long titles
- generic commits like "update code"

# README.md
Feel free to update this file with any relevant information.