# ADR 0007: Separate knowledge from objective truth

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

*Stub — to be written.* The reasoning behind this decision currently lives in [PLAN.md §15.2](../PLAN.md#152-truth-and-belief) and [DATABASE_CONVENTIONS.md §15](../DATABASE_CONVENTIONS.md#15-knowledge-and-visibility-conventions) and has not yet been extracted into a standalone record.

## Decision

A knowledge item stores the canonical claim and its truth status. What a given knower is aware of, believes, and is willing to share is recorded per knower. Discovery is never a global boolean flag on the object itself, and a false belief is valid game data that must not be overwritten with canonical truth.

## Consequences

*Stub — to be written.*

## References

- [PLAN.md §15.2](../PLAN.md#152-truth-and-belief) and [DATABASE_CONVENTIONS.md §15](../DATABASE_CONVENTIONS.md#15-knowledge-and-visibility-conventions)
