# ADR 0001: Use PostgreSQL as the single source of truth

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

Durable world facts must outlive any cache, embedding index or generated summary. PostgreSQL provides relational constraints and atomic transactions across the connected domains.

## Decision

PostgreSQL stores all canonical world data. Embeddings, caches, search indexes, and generated summaries are derived systems and must never become the only authoritative copy of a world fact.

## Consequences

Derived stores may be rebuilt; writes to canon go through application commands and the database. External indexes are not an alternative authority.

## References

- [PLAN.md §2.1](../README.md) and [README.md § Design Philosophy](../../README.md#design-principles)
