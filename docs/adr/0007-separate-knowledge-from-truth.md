# ADR 0007: Separate knowledge from objective truth

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

A fact may be true but unknown, or believed but false. Different characters, parties and organizations can hold different beliefs about the same subject.

## Decision

A knowledge item stores the canonical claim and its truth status. What a given knower is aware of, believes, and is willing to share is recorded per knower. Discovery is never a global boolean flag on the object itself, and a false belief is valid game data that must not be overwritten with canonical truth.

## Consequences

Knowledge and belief are per knower. Discovery is not a boolean on the object, and audience filtering must happen before retrieval results or AI context are exposed.

## References

- [PLAN.md §15.2](../README.md) and [DATABASE_CONVENTIONS.md §15](../DATABASE_CONVENTIONS.md#15-knowledge-and-visibility-conventions)
