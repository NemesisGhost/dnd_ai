# ADR 0001: Use PostgreSQL as the single source of truth

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

*Stub — to be written.* The reasoning behind this decision currently lives in [PLAN.md §2.1](../PLAN.md#21-postgresql-is-the-source-of-truth) and [README.md § Design Philosophy](../../README.md#design-philosophy) and has not yet been extracted into a standalone record.

## Decision

PostgreSQL stores all canonical world data. Embeddings, caches, search indexes, and generated summaries are derived systems and must never become the only authoritative copy of a world fact.

## Consequences

*Stub — to be written.*

## References

- [PLAN.md §2.1](../PLAN.md#21-postgresql-is-the-source-of-truth) and [README.md § Design Philosophy](../../README.md#design-philosophy)
