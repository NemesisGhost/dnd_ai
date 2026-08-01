# ADR 0004: Use an event-assisted state model rather than event sourcing

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

*Stub — to be written.* The reasoning behind this decision currently lives in [PLAN.md §2.5](../PLAN.md#25-event-assisted-state-model) and [DATABASE_CONVENTIONS.md §13-§14](../DATABASE_CONVENTIONS.md#13-timeline-state-conventions) and has not yet been extracted into a standalone record.

## Decision

Typed state tables provide fast current-state reads; events provide causality and history. Significant state changes reference the event that caused them, and event plus state update commit atomically. Replaying every event is never required for routine queries.

## Consequences

*Stub — to be written.*

## References

- [PLAN.md §2.5](../PLAN.md#25-event-assisted-state-model) and [DATABASE_CONVENTIONS.md §13-§14](../DATABASE_CONVENTIONS.md#13-timeline-state-conventions)
