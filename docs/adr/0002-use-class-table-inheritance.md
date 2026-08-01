# ADR 0002: Use class-table inheritance for entity subtypes

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

*Stub — to be written.* The reasoning behind this decision currently lives in [PLAN.md §2.2](../PLAN.md#22-use-class-table-inheritance) and [DATABASE_CONVENTIONS.md §7](../DATABASE_CONVENTIONS.md#7-table-inheritance-conventions) and has not yet been extracted into a standalone record.

## Decision

Entity subtypes use class-table inheritance rooted at `core.entities`, with each subtype reusing the parent UUID as its own primary key and foreign key. PostgreSQL native `INHERITS` is not used for core domain tables.

## Consequences

*Stub — to be written.*

## References

- [PLAN.md §2.2](../PLAN.md#22-use-class-table-inheritance) and [DATABASE_CONVENTIONS.md §7](../DATABASE_CONVENTIONS.md#7-table-inheritance-conventions)
