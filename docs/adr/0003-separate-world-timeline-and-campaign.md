# ADR 0003: Separate world, timeline, and campaign

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

A setting can host multiple campaigns and alternative histories. Combining world definitions, timeline state and the game played by one group would couple unrelated campaigns and prevent bounded branches.

## Decision

A world holds persistent setting definitions, a timeline holds one evolving history of that world, and a campaign is a game played within one timeline. Multiple campaigns may share a timeline; a timeline may branch from another at a defined event or world time, inheriting parent history only up to the branch point.

## Consequences

World, timeline and campaign remain separate identities. Branch inheritance stops at its branch point; campaign authority does not imply shared-world authority.

## References

- [PLAN.md §2.3](../README.md) and [DOMAIN_MODEL.md](../DOMAIN_MODEL.md)
