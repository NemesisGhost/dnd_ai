# Phase 6 Verification Checklist

Records the verification performed for Phase 6 (Events and interactions) per [PLAN.md §23](PLAN.md#23-delivery-phases) and the exit-review process in [§23.1](PLAN.md#231-phase-exit-review). Delivered as five independently reviewed increments — the same practice Phase 5 established — each migrated to AWS `dev`, `alembic check`-verified, tested, and committed before the next began. No multi-pass correction history like Phase 5's: each increment's own verification loop caught its bugs before commit (see "Bugs and Gaps Found" below), and no defect surfaced afterward that required reopening a prior increment.

## Exit Criteria

- [x] **A player action can resolve into an event and atomic state changes.** `perform_interaction()` + `resolve_check()` (`src/dnd_ai/commands/interactions.py`) run the full vertical slice: a party member attempts to pick a lock on a conditional route, the check succeeds, `world.conditional_route_requirement_satisfied()` confirms the match, and `resolve_check()` records a `narrative.events` row, a `narrative.event_effects` row, and opens `campaign.area_connection_state`, all in one transaction. `tests/scenario/test_resolve_conditional_route_check.py::test_a_successful_lockpick_check_opens_the_route_and_records_an_event` proves this through actual application code, not hand-written SQL.
- [x] **Current state and event history remain consistent.** The same test verifies `area_connection_state.last_event_id` points at the event that produced it, and `narrative.event_effects` records the same transition (`connection_status_id`, previous/new value) the state row now reflects. A failed or non-matching check (`test_a_failed_lockpick_check_does_not_open_the_route_or_record_an_event`) leaves no event and no state row — nothing is recorded that didn't actually happen.
- [x] **A branch inherits parent events only through its branch point; a parent event after that point is absent from the branch's effective history, with a scenario test proving the exclusion.** `campaign.effective_events()` (revision 059), proven by `tests/scenario/test_branch_effective_history.py` with a three-level branch chain specifically built to exercise the case a single-level branch cannot (each ancestor bounded by its *immediate child's* branch point, not the target's own).
- [x] **A branch-event reference must identify an event from its parent timeline at or before the declared branch world time; cross-timeline and post-branch references are rejected by the database.** `campaign.timelines.branch_event_id` (revision 058) plus the extended `campaign.enforce_timeline_branch()`, proven by `tests/database/test_timeline_branch_event.py` (valid at-or-before reference accepted; wrong-timeline and after-branch-point references rejected).
- [x] **A failure partway through a multi-domain command leaves no partial write — proven by a test that forces the failure, not by inspecting the transaction boundary.** Proven twice, at two different points in the phase: `tests/database/test_event_state_atomicity.py` (increment 1) shows the *schema* supports it with a hand-written transaction; `tests/scenario/test_resolve_conditional_route_check.py::test_a_failure_partway_through_resolve_check_leaves_no_partial_write` (increment 5) re-proves it through the real `resolve_check()` command, injecting a fault after the check result and event have already been written inside the same transaction and confirming — from an independent connection — that neither survived.

## First-Time Obligations ([§23](PLAN.md#23-delivery-phases))

- [x] **First full exercise of rule 6** (CLAUDE.md §5) **and of the transaction boundary** (SYSTEM_ARCHITECTURE.md §7) — increment 5, `src/dnd_ai/commands`, the first application-layer code in this repository.
- [x] **Close Phase 3's branch-history deferral** — `campaign.timelines.branch_event_id` (increment 1, revision 058).
- [x] **Close Phase 5's interaction/event placeholders** — `knowledge.entity_knowledge.learned_source`/`knowledge.party_discoveries.discovery_method` replaced with real FK provenance (increment 3, revision 063); `last_event_id` added to the five Phase-5 dungeon-state tables (increment 1, revision 060).
- [x] **Wire up conditional-route evaluation** — structured check requirements and `world.conditional_route_requirement_satisfied()` (increment 4, revision 064); the actual state transition wired through `resolve_check()` (increment 5).
- [ ] **"Likely the first deployable," if outbox processing lands here** — not built. PLAN.md's own wording is conditional ("likely... if"), not a phase exit criterion; no exit criterion above names the outbox or a deployable. Deferred, tracked as an open question for whichever phase actually needs post-commit async work (embeddings, Discord/Foundry notification, search-index refresh) — none of which Phase 6's deliverables require. Not a blocker under the stop-loss rule in §23.1.

**Increment 6 (encounters/combat) does not belong to this phase.** The original increment roadmap flagged this as needing revisiting; PLAN.md §23's phase list is unambiguous — `narrative.encounters`/`.encounter_participants`/`.encounter_rounds`/`.encounter_turns`/`interaction.combat_actions` are listed under **Phase 9** ("Items, inventory, encounters, and Foundry synchronization"), not Phase 6. §17's table only describes the schema shape; it is not phase-scoped. Phase 6 closes at increment 5.

## What Was Built

Eight revisions (057–064), 15 new tables, one new function (`campaign.effective_events()`), one new decision function (`world.conditional_route_requirement_satisfied()`), 6 columns added to previously-existing tables, and the first `src/dnd_ai/commands` application code (no schema change).

| Revision / change | Delivers |
|---|---|
| `057_narrative_events` | `narrative` schema tables: `.event_statuses`/`.event_types`/`.event_participant_roles` (seeded lookups), `.events` (entity-rooted CTI), `.event_participants`, `.event_locations`, `.event_causes`, `.event_effects` (reuses `knowledge.knowledge_items`' at-most-one-typed-target pattern), `.event_observations` — each with its own world-consistency trigger |
| `058_timeline_branch_event` | `campaign.timelines.branch_event_id`; extends (`CREATE OR REPLACE`, not a new trigger) `campaign.enforce_timeline_branch()` to validate it belongs to the parent timeline and occurs at or before the branch world time |
| `059_branch_effective_history` | `campaign.effective_events(p_timeline_id) RETURNS SETOF narrative.events` — recursive CTE bounding each ancestor by its immediate child's branch point |
| `060_state_event_provenance` | `last_event_id` on the five Phase-5 dungeon-domain `campaign.*_state` tables |
| `061_interaction_domain` | `interaction` schema: `.interaction_types` (seeded), `.interactions` (not entity-rooted — a high-volume log record), `.actions`, `.targets`, `.check_requests`, `.check_results`, `.consequences`, `.external_messages`; `check_requests` validates ability/skill choices against the world's ruleset allow-list via the existing `rules.ruleset_allowed_for_world()` |
| `062_event_cause_interaction` | `narrative.event_causes.cause_interaction_id`, closing revision 057's own documented placeholder now that `interaction.interactions` exists; CHECK widened to exactly-one-of-three |
| `063_knowledge_source_provenance` | Drops `knowledge.entity_knowledge.learned_source`/`knowledge.party_discoveries.discovery_method` (free-text placeholders from Phase 5 revision 041); adds `learned_via_interaction_id`/`learned_via_event_id` and `discovered_via_interaction_id`/`discovered_via_event_id` |
| `064_conditional_route_evaluation` | `world.area_connections.required_check_kind`/`required_ability_id`/`required_skill_id`/`required_difficulty` (structured, machine-checkable condition, gated by the ruleset allow-list); `interaction.check_requests.target_id`; `world.conditional_route_requirement_satisfied(area_connection_id, check_result_id)` — pure read-only decision function, deliberately not state-mutating |
| `src/dnd_ai/commands` (no revision) | `record_event()`, `perform_interaction()`, `resolve_check()` — the first application-layer command handlers, each owning its own transaction via `engine.begin()`; `resolve_check()` calls `world.conditional_route_requirement_satisfied()` and, when satisfied, records the event, the `event_effects` row, and the state change together |

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

| Obligation | Result |
|---|---|
| Object ownership | All 15 new tables owned by `migration_owner` via schema-level default privileges (revision 001); no new schema was created (`narrative` and `interaction` schemas already existed — `narrative` from revision 057's own migration, `interaction` likewise) |
| Default privileges | Inherited from the same schema-level defaults every prior phase's tables use; no new privilege grant was needed |
| Seed idempotency | `narrative.event_statuses` (4 rows), `.event_types` (19 rows), `.event_participant_roles` (7 rows), `interaction.interaction_types` (13 rows) all seeded with `ON CONFLICT (code) DO NOTHING`, same pattern as every prior lookup |
| Constraint tests | 1,339 tests total, up from 1,153 at Phase 5's close — 1,251 after increment 1, 1,314 after increment 2, 1,320 after increment 3, 1,333 after increment 4, 1,339 after increment 5. Every nontrivial CHECK/trigger added in this phase has a positive and a negative test (§32.1) |
| Comments and FK indexes | Zero tables without a comment; every foreign key indexed, including partial indexes for nullable FKs, verified by the existing `test_schema_documentation.py`/`test_every_foreign_key_is_indexed` machinery, which needed no changes to cover the new tables |
| Downgrade | Verified per increment: `alembic downgrade <previous-head> → upgrade head` against AWS `dev` after each of the four schema-bearing increments (1–4); increment 5 added no migration, so its verification was `alembic check` (no diff) plus the full test suite |
| CI green | Each increment's local verification loop (migrate → `alembic check` → downgrade/upgrade round trip → targeted tests → `ruff format`/`ruff check`/`mypy src` → full suite) was run against AWS `dev` before commit; this branch has not yet been pushed or opened as a PR (per explicit instruction), so GitHub Actions confirmation is outstanding until that happens |

## Bugs and Gaps Found

1. **A trigger didn't short-circuit on NULL, masking a CHECK's error** (increment 2). `interaction.enforce_check_request_ruleset_allowed()` looked up `rules.abilities`/`rules.skills` unconditionally, so a request with neither `ability_id` nor `skill_id` set raised the trigger's own "not allowed for world" error before `ck_check_requests_kind_reference` could report the real problem — the same class of bug Phase 5's `enforce_party_discovery_world()` had. Fixed with the same idiom: return early when both reference columns are NULL. Found by `test_an_ability_check_requires_ability_id`.
2. **A `make_timeline()` factory change broke a populated-upgrade test** (increment 1). Adding `branch_event_id` to the shared factory and always including it in the INSERT broke `test_phase5_populated_upgrade.py`, which deliberately runs against a database pinned at a pre-`branch_event_id` revision. Fixed by omitting the column from the INSERT entirely when the parameter is `None`, rather than sending `NULL` — a schema-version-agnostic factory, not a special case for one test.
3. **Two `CREATE INDEX` statements were missing from a migration** (increment 4). `locations.py` declared `Index()` objects for `required_ability_id`/`required_skill_id` but the migration's `upgrade()` never created them — caught immediately by `alembic check` reporting `New upgrade operations detected` before any test ran.
4. **`resolve_check()` updated typed state but never wrote the `event_effects` row `PLAN.md`'s deliverable list names** (increment 5, found in this exit review rather than during increment 5's own development). `narrative.event_effects`' own comment (revision 057) states common effects should update the corresponding typed state table in the same transaction — `resolve_check()` did the state update but not the effect record itself. Fixed by having `_open_area_connection()` insert the `event_effects` row (`target_component = 'connection_status_id'`, previous/new value, effective world time) alongside the state upsert, and extended the positive scenario test to assert it.

None of these were schema-design defects — three were caught by the same verification loop (`alembic check`, targeted tests, full suite) every prior phase used, and the fourth was a deliverable-completeness gap caught by re-reading the phase's own exit criteria against what had actually been built, before declaring the phase done.

## Verification commands and results

Run per increment, against the deployed AWS `dev` RDS instance (ingress opened via `scripts/aws-db-allow-my-ip.sh open --environment dev` before each session, closed after):

```bash
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check                 # no diff, every increment
uv run alembic -c database/alembic.ini downgrade <prev-head>  # increments 1-4 only
uv run alembic -c database/alembic.ini upgrade head
uv run pytest <targeted new test files> -v
uv run ruff format --check . && uv run ruff check . && uv run mypy src
uv run pytest tests/unit tests/database tests/scenario -q     # full suite, every increment
```

Final full-suite result (after the increment-5 `event_effects` follow-up fix): **1,339 passed**, `alembic check` clean, `ruff format --check`/`ruff check`/`mypy src` all clean.
