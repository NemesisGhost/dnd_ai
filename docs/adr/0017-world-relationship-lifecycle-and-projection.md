# ADR 0017: World relationships get a version and an archive lifecycle, and are shown only when the reader can see the whole edge

- **Status**: Accepted
- **Date**: 2026-10-06
- **Builds on**: [ADR 0015](0015-typed-world-content-authoring.md), whose decision 8 deferred relationship authoring until it was decided whether `world.relationships` needs canon status and a version or should be restricted to canon endpoints.
- **Decision record**: D-18 of the Phase 15 completion plan (option a).

## Context

`world.relationships` is a shared, objective record of how entities are connected (family, employment, ownership, alliance, adjacency and so on). It has participants, optional subtype rows, authored perspectives (how each participant sees it), and event-driven timeline state (`campaign.relationship_state`). Until Phase 15.3A-2a nothing authored it through a command: it had no `row_version`, no lifecycle and no author, and any edge to canon records would have been visible the moment it existed. Characters, places, organizations and religions are lifecycle-managed definitions; an edge between a published record and a draft one must not leak the draft.

## Decision

1. **A relationship gets what every authored aggregate has**: `row_version` (optimistic concurrency, bumped by `core.bump_row_version()`), an operational lifecycle (`lifecycle_status_id`, `active` or `archived`, with `archived_at`) and `created_by_user_id`. It does **not** get a canon status: an edge is not a definition that is reviewed and published, and a separate approval track for edges would only duplicate the approval of the records it connects.
2. **Projection.** A reader who cannot edit canon sees a relationship only when (a) it is active, (b) every participant is independently discoverable by that reader (the rule the world list and detail already applied), and (c) its subtype does not say it is private (`is_public` on ownership and on organization membership). Anything else is the same not-found as a nonexistent relationship, so a response never reveals that an edge or a participant was filtered. An editor sees every edge, archived and private ones included. The NPC portrayal context ignores archived edges.
3. **What is fixed and what may change.** A relationship's kind (family, employment, ownership, political, or a plain connection), its type and its participants are fixed when it is created (participants are append-only in the schema). The description, its start, and its kind's typed fields may be edited; it can be ended at a world time (which must follow its start), archived, and restored. To change who is connected, end or archive it and create another.
4. **Lock order.** The participants' entities `FOR SHARE` in id order, then the relationship row `FOR UPDATE`. Every command names the relationship's `expected_row_version`. Creating a relationship with a participant that a concurrent archive removed fails, and a state change waits for an archive and then refuses an archived relationship (`evolve_relationship_reaction` now checks the lifecycle under its existing lock).
5. **Draft participants are allowed.** Drafts are routine in the authoring model; an edge to a draft is simply unseen by readers until the draft is published.
6. **Perspectives are baseline definitions, not state.** An authored perspective is a participant's stable baseline view; it is written by an editor against the relationship version. The current, event-driven view remains `campaign.relationship_state`.
7. **No revision snapshots.** A relationship is not a `core.entities` row, so the canonical revision history (`core.entity_revisions`) does not apply to it; its audit rows (content redacted) and its version are its history for now.

## Alternatives considered

- **Full canon status for edges** (draft, proposed, approved, canon). Rejected: it adds a review track for a record whose visibility is already bounded by the records it connects, and every read would need a third visibility rule.
- **Only allow edges between canon endpoints.** Rejected: it would force a publish order on authors (publish everything, then connect it) and still would not give edges a version or a way to retire them.
- **Hard-delete edges.** Rejected: perspectives, state rows and events refer to them, and history must survive; archiving is reversible and hides the edge from readers just as well.

## Consequences

- Existing relationships become `active` at version 1 with no recorded author.
- Reads that list or open a relationship gained a reader/editor switch; the one other reader of relationships (the NPC portrayal context) filters archived edges.
- Membership in an organization, its offices and status, and routes between locations build on this kernel in the following checkpoints (15.3A-2b, 15.3A-2c).
- Edge-level revision history and bulk edge operations are deferred.

## References

- [ENTITY_LIFECYCLE.md](../ENTITY_LIFECYCLE.md) (relationship commands), [DATABASE_MODEL.md](../architecture/DATABASE_MODEL.md) section 10
- [ADR 0015](0015-typed-world-content-authoring.md) decision 8, [ADR 0014](0014-world-authoring-authority.md)
