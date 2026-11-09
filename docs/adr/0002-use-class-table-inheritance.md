# ADR 0002: Use class-table inheritance for entity subtypes

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

Characters, locations and other entity subtypes share identity and provenance but require different structured fields. A shared UUID and foreign-key chain preserve one identity without EAV or PostgreSQL native inheritance.

## Decision

Entity subtypes use class-table inheritance rooted at `core.entities`, with each subtype reusing the parent UUID as its own primary key and foreign key. PostgreSQL native `INHERITS` is not used for core domain tables.

## Consequences

Subtype creation must create each required ancestor in one transaction. Constraints and joins are explicit; a subtype does not generate another UUID.

## References

- [PLAN.md §2.2](../README.md) and [DATABASE_CONVENTIONS.md §7](../DATABASE_CONVENTIONS.md#7-table-inheritance-conventions)
