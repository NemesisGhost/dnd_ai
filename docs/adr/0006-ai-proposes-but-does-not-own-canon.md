# ADR 0006: AI proposes changes but does not own canon

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

*Stub — to be written.* The reasoning behind this decision currently lives in [PLAN.md §18.2](../PLAN.md#182-controlled-mutation) and [DATABASE_CONVENTIONS.md §17](../DATABASE_CONVENTIONS.md#17-ai-data-conventions) and has not yet been extracted into a standalone record.

## Decision

AI agents never write directly to canonical tables. They submit proposed changes that pass through validation and, for high-impact categories, explicit approval before becoming normal domain commands. Automatic-approval categories are enumerated explicitly, not decided ad hoc.

## Consequences

*Stub — to be written.*

## References

- [PLAN.md §18.2](../PLAN.md#182-controlled-mutation) and [DATABASE_CONVENTIONS.md §17](../DATABASE_CONVENTIONS.md#17-ai-data-conventions)
