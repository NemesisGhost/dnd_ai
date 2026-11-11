# ADR 0006: AI proposes changes but does not own canon

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

Generated suggestions can conflict with established history or user authority. Human-controlled canon requires an explicit validation and approval boundary.

## Decision

AI agents never write directly to canonical tables. They submit proposed changes that pass through validation and, for high-impact categories, explicit approval before becoming normal domain commands. Automatic-approval categories are enumerated explicitly, not decided ad hoc.

## Consequences

AI output is a proposal with provenance. Only normal authorized commands promote it; automatic approval requires an explicitly approved category and cannot be invented by a caller.

## References

- [PLAN.md §18.2](../README.md) and [DATABASE_CONVENTIONS.md §17](../DATABASE_CONVENTIONS.md#17-ai-data-conventions)
