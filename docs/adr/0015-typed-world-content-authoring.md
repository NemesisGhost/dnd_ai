# ADR 0015: Typed world-content authoring (Phase 15.1)

- **Status**: Accepted
- **Date**: 2026-10-04
- **Builds on**: [ADR 0014](0014-world-authoring-authority.md) (authority), [ADR 0003](0003-separate-world-timeline-and-campaign.md) (world, timeline, campaign), [ADR 0004](0004-use-event-assisted-state.md) (state needs a causal event).
- **Related**: [ENTITY_LIFECYCLE.md](../ENTITY_LIFECYCLE.md) §3, §21.1; [PLAN.md](../PLAN.md) Phase 15.

## Context

Phase 14 delivered the authoring kernel: the canon-lifecycle commands, optimistic row versions, idempotency stores, `available_actions`/`blocked_actions`, and portal primitives. It created no way to author world content, because a generic entity writer is forbidden. Phase 15 in the roadmap covers two different kinds of work:

- **Definition authoring**: world-scoped `core.entities` subtypes that need typed create/update commands on top of the lifecycle kernel.
- **Campaign operations**: sessions, events, corrections, quest progress, knowledge reveal, inventory, character state. These are timeline-scoped, need a causal event (rule 6), and mostly need world-time selection, which has no authoring surface.

## Decision

1. **Phase 15 is delivered in two parts.** **15.1** (this ADR) is GM world-content *definitions*. **15.2** is campaign operations, on its own branch. PLAN.md's 15.8 exit scenario and 15.9 exit criteria close only after 15.2.
2. **15.1 covers** locations (ten non-dungeon categories), organizations (six types) and religions, NPC identity, quest definitions (stages, objectives), knowledge-item definitions, and the structural references among them. It adds no timeline-state, event, or per-knower writes.
3. **Authority reuses campaign-scoped `canon.edit`** (ADR 0014 decision 2). No new capability or world capability. World scope is derived from the campaign, never from the request. Human principals only; Foundry, machine, and service principals are refused. The command re-checks, under lock, world active, campaign active, the actor's open membership and unrevoked role rows (`FOR SHARE`), and `canon.edit`.
4. **Edit model.** Definitions are mutated in place, only while lifecycle is `active` and canon status is `draft` or `canon`. `proposed`/`approved` records cannot be edited (return to draft first), so an approved record cannot change before publish. Every real edit bumps `row_version` (through the root `core.entities` UPDATE even when only subtype fields change) and writes one `updated` audit row with bounded `{field: {from, to}}`. An identical resubmission is a no-op: no update, no version bump, no audit row. A meaning change on canon uses the existing supersede flow. Entity type (category) is immutable after creation.
5. **Type-specific publish and archive preconditions** are a hook beside the eligibility registry, consulted by both the commands and the read model: a location's parent, an organization's parent/HQ/religion, an NPC's origin, a quest's targets and completeness, and a knowledge item's subject must be `canon` to publish; an NPC with active user-character relationships cannot be archived.
6. **Reference eligibility.** A record may be *newly* referenced only if it is in the same world, has the expected type, is lifecycle `active`, and has canon status `draft`, `proposed`, `approved`, or `canon`. Every other reason (nonexistent, other world, wrong type, archived, rejected, superseded) is one non-disclosing `<field>_invalid` code. Existing references to later-archived records are preserved.
7. **State commands refuse draft and archived targets** (non-disclosing), so routine drafts cannot reach players through movement, reveal, advance, transfer, or event participation. Lifecycle commands also lock the campaign row `FOR SHARE` and re-check it is active.
8. **Relationship authoring is deferred.** *(Resolved by [ADR 0017](0017-world-relationship-lifecycle-and-projection.md): a version and an archive lifecycle, and projection to readers who can see the whole edge.)* `world.relationships` has no canon status or `row_version`, so a new edge between canon records would be immediately visible. Whether to add those columns or to restrict edges to canon endpoints is decided by an ADR at the start of 15.2. Organization memberships, offices, employment, ownership, family, and political relationships are 15.2.
9. **One migration**: `113_organization_hierarchy_cycle_guard` — a trigger mirroring the location containment guard, because parent reassignment becomes a user action.
10. **Authoring reads are `Cache-Control: no-store`** through one middleware for authenticated responses.
11. **Residual risk accepted:** a change to a role's capability set (`security.roles` / `role_capabilities`) is an operator-level catalog change and is not serialized against an in-flight authoring command.

## Alternatives considered

- **A generic `CreateEntityDraft` / entity editor.** Rejected (PLAN.md §14.1, ENTITY_LIFECYCLE §21.1): it would accept arbitrary attributes and bypass per-type validation.
- **A new world-level content capability.** Rejected: a second authority over the same records produces contradictory previews. Revisit in Phase 16 for multi-GM worlds.
- **Versioned definitions (a new row per edit).** Rejected for 15.1: supersession already exists for meaning changes and a revision store is 15G.
- **Authoring timeline state with definitions.** Rejected: collapses definition and state (rule 5) and needs causal events (rule 6).

## Consequences

- A definition edited or created from a branch campaign is visible, subject to lifecycle gating, in every campaign on the world. This is the existing model.
- Each authored type carries its own request, response, command, route, and read model. Shared code is limited to policy, locking, source-and-root insertion, and diff/audit construction.
- Adding a type to the lifecycle eligibility registry requires read-side gating on every surface that type appears on, delivered in the same checkpoint.
- Portal editors are independently reloadable routes. There are no editing modals.

## References

- [PLAN.md](../PLAN.md) Phase 15 · [ENTITY_LIFECYCLE.md](../ENTITY_LIFECYCLE.md) · [SYSTEM_ARCHITECTURE.md](../architecture/SYSTEM_ARCHITECTURE.md) §7.1 · [UI_DESIGN.md](../UI_DESIGN.md) §4.6
