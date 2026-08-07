# Phase 7 Verification Checklist

Records the verification performed for Phase 7 (Quests and knowledge) per [PLAN.md §23](PLAN.md#23-delivery-phases) and the exit-review process in [§23.1](PLAN.md#231-phase-exit-review). Delivered as a single revision (073) covering both this phase's deliverables: the quest domain in full, and the knowledge-domain gaps Phase 5's pulled-forward slice (revision 041) explicitly deferred here. One application-layer command, `advance_objective()`, was added alongside it.

## Exit Criteria

- [x] **Dungeon events can advance or fail quest objectives.** `src/dnd_ai/commands/quests.py`'s `advance_objective()` records a `narrative.events` row (`objective_completed`/`objective_failed`), updates `campaign.objective_state` to match, and links the two through a `narrative.event_effects` row (`target_quest_objective_id`) — all in one transaction, per CLAUDE.md rule 6. `tests/scenario/test_quest_advancement.py` proves both outcomes through actual application code: `test_an_event_completes_a_quest_objective` and `test_an_event_fails_a_quest_objective` build a concrete dungeon scenario (an `activate_mechanism` objective tied to an area interactable) and verify the recorded event, the updated state row's `last_event_id`, and the effect row's `previous_value`/`new_value`. `test_advancing_an_already_terminal_objective_is_rejected` proves the command itself guards against re-advancing a completed/failed/skipped/superseded objective (no database-level irreversibility trigger exists for this yet — see "Deliberate scoping decisions" below).
- [x] **Party knowledge differs from canonical truth.** This was already representable since Phase 5 (`knowledge.knowledge_items.truth_status_id` is the canonical answer; `knowledge.entity_knowledge`/`.party_discoveries` record what a knower or party actually believes) but had no test proving the divergence itself. `tests/database/test_party_knowledge_divergence.py` proves it directly: a knowledge item is canonically `false`, a party fully believes it (`awareness_level = 'aware'`, `confidence = 95`), and the party's discovery record exists independently of that canonical status. A second test exercises this phase's own new `knowledge.information_transfers` table to show a source knower's already-false belief distorted further on the way to a recipient (`modified_interpretation` differing from the source's own `interpretation`) — the mechanism this criterion's "differs from canonical truth" is meant to support (rumor propagation, misinformation).

## First-Time Obligations ([§23](PLAN.md#23-delivery-phases))

- **Close Phase 5's knowledge-domain deferral.** `knowledge.knowledge_versions`, `.information_transfers`, `.expertise_domains`/`.character_expertise`, `.public_knowledge`, and temporal validity on `knowledge_items` — all named explicitly in `DATABASE_MODEL.md §15`'s "Explicit Phase 5 / Phase 7 boundary" note — are delivered by revision 073. `knowledge.entity_knowledge.knowledge_version_id` (nullable) additionally closes revision 041's own "nothing to version yet" placeholder.
- **Close a forward-reference placeholder revision 061 (Phase 6) left for this phase.** `interaction.consequences.resulting_quest_objective_state_id` gives `quest_change` consequences a typed outcome reference, matching the FK pattern `resulting_event_id`/`resulting_party_discovery_id` already use. `relationship_change` remains unaddressed — that is Phase 8's domain, not this one's.
- **First quest-domain scenario test.** `docs/DATABASE_CONVENTIONS.md §32.2` names "quest advancement" as a required scenario test category; `tests/scenario/test_quest_advancement.py` is the first test satisfying it (the category could not be proven before `narrative.quests`/`campaign.objective_state` existed).

## What Was Built

One revision (073), 18 new tables, 1 new command module (`src/dnd_ai/commands/quests.py`, one command: `advance_objective()`), 12 new trigger functions, 4 new seeded lookups (~35 rows), 2 new `narrative.event_types` seed rows, and 5 columns added to four previously-existing tables.

| Area | Delivers |
|---|---|
| Quest domain | `narrative.story_arcs` (not entity-rooted — a world-scoped grouping record, same reasoning as `world.area_connections`/`interaction.interactions`), `.quests` (entity-rooted, the one CTI subtype in this domain), `.quest_stages`, `.objective_types` (seeded lookup), `.quest_objectives` (at-most-one-of-five typed target, reusing the `knowledge_items`/`event_effects` pattern), `.objective_dependencies`, `.quest_participants`, `.quest_outcomes`, `.quest_rewards` |
| Quest state | `campaign.quest_statuses`/`campaign.objective_statuses` (seeded lookups), `campaign.quest_state`/`campaign.objective_state` — timeline-scoped with an additional nullable `party_id` dimension (partial unique indexes: one current row per `(timeline, target)` when `party_id IS NULL`, one per `(timeline, target, party)` when set) and `last_event_id` provenance reusing the shared `campaign.enforce_state_event_timeline()` guard (Phase 6 revision 066) directly, rather than a five-table retrofit |
| Knowledge expansion | `knowledge.knowledge_items.effective_from_world_time_id`/`.effective_to_world_time_id`/`.validity_period` (ADR 0010 shape, both endpoints nullable — ontological validity windows, no EXCLUDE constraint), `knowledge.knowledge_versions`, `knowledge.entity_knowledge.knowledge_version_id`, `knowledge.expertise_domains`/`.character_expertise`, `knowledge.information_transfers`, `knowledge.public_knowledge` |
| Forward-reference closures | `narrative.event_effects.target_quest_objective_id` (sixth column in the at-most-one-target pattern); `interaction.consequences.resulting_quest_objective_state_id` (closes revision 061's documented placeholder, quest half only) |
| Command layer | `src/dnd_ai/commands/quests.py`: `advance_objective()` — locks the current `campaign.objective_state` row, records the causing event, updates state, links via `event_effects`; rejects re-advancing an already-terminal objective |
| Application metadata | `src/dnd_ai/persistence/tables/{narrative,campaign,knowledge,interaction}.py` extended to declare all 18 new tables and 5 new/extended columns — `alembic check` compares this against the live database unconditionally |

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

| Obligation | Result |
|---|---|
| Object ownership | All 18 new tables added to `tests/database/test_role_grants.py`'s `MANAGED_TABLES`; the schema-driven tripwire test (`test_managed_tables_covers_every_table_in_every_managed_schema`, added by Phase 6's correction pass) caught the omission on first run and was used to verify completeness rather than manual inspection. |
| Default privileges | Inherited from the same schema-level defaults every prior phase's tables use; verified per-table by the same tripwire-guarded `test_role_grants.py`. |
| Seed idempotency | `narrative.objective_types` (10 rows), `campaign.quest_statuses` (7 rows), `campaign.objective_statuses` (7 rows), `knowledge.expertise_domains` (12 rows) all seeded with `ON CONFLICT (code) DO NOTHING`, same pattern as every prior lookup. Two additional `narrative.event_types` rows (`objective_completed`, `objective_failed`) seeded the same way into the pre-existing table. |
| Constraint tests | Every nontrivial CHECK/trigger added in this revision has a positive and a negative test (§32.1) — see "Test counts" below. |
| Comments and FK indexes | Zero tables without a comment. `test_every_foreign_key_is_indexed` (Phase 6's schema-documentation tripwire) caught three initially-missed indexes (`information_transfers.occurred_at_world_time_id`, `public_knowledge.known_since_world_time_id`, `story_arcs.source_id`) on first run; fixed and reverified. |
| Downgrade | Verified via `alembic downgrade 072_interaction_lifecycle_gaps → upgrade head` against AWS `dev`, twice (once mid-development after fixing a metadata gap), each followed by `alembic check` reporting no diff. |
| CI green | See "Verification status" below. |

### Test counts

Phase 6's closing baseline was **1,574 collected tests**. After revision 073: **1,759 tests** (+185), all passing against AWS `dev`.

## Verification commands and results

Run against the deployed AWS `dev` RDS instance (ingress opened via `scripts/aws-db-allow-my-ip.sh open --environment dev` before the session, closed after):

```bash
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check                       # no diff
uv run alembic -c database/alembic.ini downgrade 072_interaction_lifecycle_gaps
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check                       # no diff, after the round trip
uv run alembic -c database/alembic.ini heads                       # exactly one head
uv run ruff format --check . && uv run ruff check . && uv run mypy src
uv run pytest tests/unit tests/database tests/scenario -q          # full suite
```

Result: **1,759 passed**, one Alembic head (`073_quest_and_knowledge_domain`), `alembic check` clean before and after the downgrade/upgrade round trip (verified twice — once before, once after fixing a set of metadata-declaration gaps the first full test run surfaced), `ruff format --check`/`ruff check`/`mypy src` all clean.

### Bugs found while verifying this revision

Distinguished from schema-design defects per this project's own convention:

- The migration's local `_lookup_table()` helper (copied from the 041/057 pattern) omitted the `COMMENT ON COLUMN {table}.code` statement the shared pattern requires — `alembic check` caught the resulting comment drift on all four new lookup tables' `code` columns. Fixed by restoring the missing statement.
- Four columns declared in the migration with a `COMMENT ON COLUMN` (`campaign.quest_state.party_id`, `narrative.quest_stages.stage_type`, `narrative.quest_objectives.requirement_level`, `knowledge.knowledge_versions.distortion_type`) were missing the matching `comment=` argument in their `src/dnd_ai/persistence/tables/` metadata declarations — the inverse direction of the same class of drift, caught by the same `alembic check` comparison.
- `interaction.consequences`' table-level comment was updated in the migration (to reflect `resulting_quest_objective_state_id` closing its `quest_change` placeholder) after the migration had already been applied once during development — the DB retained the pre-edit comment until a downgrade/upgrade round trip actually replayed the corrected `upgrade()` function. Not a defect in the shipped migration (the final applied version is correct and was verified after the round trip), but a reminder that editing an already-applied revision's file requires re-running it, not just re-reading it.
- Three foreign-key columns (`information_transfers.occurred_at_world_time_id`, `public_knowledge.known_since_world_time_id`, `story_arcs.source_id`) were missing their conventions-§19.1-required index, caught by the existing `test_every_foreign_key_is_indexed` tripwire on first run.
- Two trigger-message assertions in `tests/database/test_quest_domain.py` originally expected the substring `"belongs to world"` (the phrasing several other world-agreement triggers in this schema use) but `campaign.enforce_quest_state_world()`/`enforce_objective_state_world()` phrase their rejection as `"does not match"` instead — a wording mismatch between the test and the trigger it was testing, not a functional gap. Fixed by matching the assertions to the actual (correct) trigger wording.
- The quest-advancement scenario test originally asserted `event_effects.new_value == '"completed"'` (a JSON-quoted string), not accounting for psycopg's automatic JSONB-to-Python-`str` deserialization on read. Fixed to assert the plain string, matching how the column is actually read back through the driver.

None of these were schema-design defects — each was either an omission caught by an existing tripwire test doing exactly its job, or a test asserting the wrong (rather than a missing) expectation.

## Verification status

All local verification above ran and passed against AWS `dev`. Not yet pushed, opened as a PR, or confirmed on CI — this section will be updated once that happens, following the same bar every prior phase has been held to: **do not describe Phase 7 as complete until this section says so.**
