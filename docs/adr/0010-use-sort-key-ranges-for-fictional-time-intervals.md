# ADR 0010: Use sort-key ranges for fictional-time intervals

- **Status**: Accepted
- **Date**: 2026-08-01

## Context

The platform represents fictional chronology with `core.world_times`. Each row has a stable UUID, calendar-aware display fields, a precision, and a required `BIGINT sort_key` used to order moments within a world.

Phase 3 introduces the first temporal records that must reject overlaps: party memberships. Endpoint UUIDs preserve the identity and meaning of each world time, but PostgreSQL cannot apply the range-overlap operator to a pair of foreign keys. Conversely, storing only numeric endpoints would discard their calendar, precision, label, and provenance.

The interval contract also needs to settle boundary behavior, open-ended membership, timeline scoping, and correction semantics before migration code makes those decisions implicitly.

## Decision

Fictional-time validity intervals use all of the following:

- `effective_from_world_time_id`, required and referencing `core.world_times`.
- `effective_to_world_time_id`, nullable and referencing `core.world_times`.
- A database-maintained `INT8RANGE` built from the referenced rows' `sort_key` values.
- Half-open bounds: `[from, to)`. The start is included; the end is excluded.
- A finite start. A `NULL` end becomes an unbounded upper range and means the interval is still current.
- A trigger that validates both endpoints belong to the subject's world, requires `to.sort_key > from.sort_key`, and overwrites the stored range from those values. The client never supplies an authoritative range independently of the endpoint IDs.

Party membership is timeline-scoped because membership can diverge after a timeline branch. Its non-overlap key is `(timeline_id, party_id, member_entity_id, effective_period)`:

```sql
EXCLUDE USING gist (
    timeline_id WITH =,
    party_id WITH =,
    member_entity_id WITH =,
    effective_period WITH &&
)
```

The migration that first adds this constraint enables `btree_gist` beforehand so GiST can apply equality to UUID keys.

A real join, departure, disappearance, or return creates or closes a membership period. An update to an elapsed period is an administrative correction, not a new narrative occurrence; it must record old and new endpoints in `audit.change_log` and re-run all interval validation. Phase 6 adds causal event references for narrative membership changes once `narrative.events` exists.

## Consequences

**Easier**

- PostgreSQL can reject overlapping memberships atomically, including races between concurrent writers.
- Adjacent intervals are unambiguous: one membership can end exactly when another begins.
- Open-ended current membership needs no sentinel value.
- World-time identity and display metadata remain available through foreign keys.
- Timeline membership cannot leak directly from one branch into another.

**Harder**

- The range duplicates endpoint ordering data and therefore requires a trigger to keep it derived and trustworthy.
- Writes must read the referenced `core.world_times` rows to validate world agreement and build the range.
- Effective-state resolution must later combine branch ancestry with timeline-local membership rows; Phase 3 stores the correct structure but does not yet deliver the general branch-history resolver.

**Foreclosed**

- Membership intervals cannot use real-world `TIMESTAMPTZ`; fictional time and system time remain separate.
- Callers cannot choose arbitrary inclusive/exclusive bounds.
- A party's membership cannot be modeled as global mutable data shared by every timeline.

## Verification status

Implemented and verified. Phase 3 exit tests prove boundary adjacency, overlap rejection, open-ended behavior, world agreement, and timeline scoping of `campaign.party_memberships` rows against the deployed AWS `dev` database (`tests/database/test_party_memberships.py`; see [PHASE3_VERIFICATION.md](../PHASE3_VERIFICATION.md)). A Phase 4 corrections revision (023) applied the same derived-range half of this contract to `campaign.sessions` — endpoints, half-open bounds, and an unbounded upper range for open-ended cases — deliberately without the exclusion constraint, since overlapping sessions are legitimate; see `tests/database/test_session_chronology.py` (redistributed from the former `test_phase4_corrections.py` monolith during the Phase 6 entry-gate modularization — see [DEVELOPMENT.md §2.1](../DEVELOPMENT.md#21-keep-source-and-tests-bounded-by-domain)) and [DATABASE_MODEL.md §6.4](../architecture/DATABASE_MODEL.md#64-sessions).

## References

- [DATABASE_CONVENTIONS.md §12](../DATABASE_CONVENTIONS.md#12-temporal-conventions)
- [DATABASE_MODEL.md §6.3](../architecture/DATABASE_MODEL.md#63-parties-and-membership)
- [PLAN.md §5.4](../PLAN.md#54-parties)
- [PLAN.md Phase 3](../PLAN.md#phase-3-timelines-and-campaigns)
- [ADR 0003](0003-separate-world-timeline-and-campaign.md)
