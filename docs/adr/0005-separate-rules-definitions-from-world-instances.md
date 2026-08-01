# ADR 0005: Separate rules definitions from world instances

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

*Stub — to be written.* The reasoning behind this decision currently lives in [PLAN.md §6.1](../PLAN.md#61-ruleset-separation) and [PLAN.md §12.1](../PLAN.md#121-definitions-and-instances) and has not yet been extracted into a standalone record.

## Decision

Reusable mechanical definitions live in the `rules` schema and identify their ruleset and version. Particular objects, creatures, and places in a world are entities in the `world` and `character` schemas. A longsword is a definition; the Blade of Saint Orra is an instance.

## Consequences

*Stub — to be written.*

## References

- [PLAN.md §6.1](../PLAN.md#61-ruleset-separation) and [PLAN.md §12.1](../PLAN.md#121-definitions-and-instances)
