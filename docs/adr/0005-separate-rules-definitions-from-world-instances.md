# ADR 0005: Separate rules definitions from world instances

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

Reusable rules must be versioned independently of a particular world object or character. A rules definition describes a kind; a world instance has identity, ownership, provenance and state.

## Decision

Reusable mechanical definitions live in the `rules` schema and identify their ruleset and version. Particular objects, creatures, and places in a world are entities in the `world` and `character` schemas. A longsword is a definition; the Blade of Saint Orra is an instance.

## Consequences

Rules content stays ruleset/version aware. World instances refer to definitions without turning reusable definitions into campaign state.

## References

- [PLAN.md §6.1](../README.md) and [PLAN.md §12.1](../README.md)
