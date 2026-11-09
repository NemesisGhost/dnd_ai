# ADR 0004: Use an event-assisted state model rather than event sourcing

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

The platform needs fast current-state reads and causal history without requiring every query to replay all events. Typed state and recorded events serve different purposes.

## Decision

Typed state tables provide fast current-state reads; events provide causality and history. Significant state changes reference the event that caused them, and event plus state update commit atomically. Replaying every event is never required for routine queries.

## Consequences

Significant state changes and their causal events commit atomically. Historical event records do not replace current-state tables, and projection code must honor branch limits.

## References

- [PLAN.md §2.5](../README.md) and [DATABASE_CONVENTIONS.md §13-§14](../DATABASE_CONVENTIONS.md#13-timeline-state-conventions)
