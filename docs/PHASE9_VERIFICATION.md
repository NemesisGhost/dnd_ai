# Phase 9 Verification Checklist

Records the verification performed for Phase 9 (Items, inventory, encounters, and Foundry integration contracts) per [PLAN.md §23](PLAN.md#23-delivery-phases) and the exit-review process in [§23.1](PLAN.md#231-phase-exit-review). Phase 9 is the first phase developed entirely under the local-first loop ([§23.0](PLAN.md#230-verification-policy), [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md)): every migration/round trip below was proven against a local PostgreSQL 18 server first, with the CI run against the deployed `dev` RDS instance closing the phase, not merely accompanying it.

**Replan (2026-08-09), before delivery.** Phase 9's original exit criterion — "Foundry combat can update persistent character and world state" — required proving that claim against a live deployable, per [§30.8](PLAN.md#308-per-phase-deployment-expectations): an actual Foundry-facing surface reachable through the application API on ECS Fargate behind the ALB in `dev`. No FastAPI service, container image, or Fargate/ALB Terraform exists yet in this project, and standing one up mid-phase would have either rushed the API layer or blocked item/encounter delivery on infrastructure unrelated to either domain. [PLAN.md](PLAN.md#phase-9-items-inventory-encounters-and-foundry-integration-contracts) was revised before this phase's schema work began: Phase 9 now closes on the database model, external identifiers, synchronization state, and command layer — everything provable locally and in CI without a live deployable — plus the *adapter-facing contract* an adapter will call once one exists. The live criterion moved to two new phases: Phase 10 (Core API and playable vertical slice) stands up the API deployable itself; Phase 11 (Foundry MVP) is where it is actually exercised against Foundry. The former Phase 10 (AI and Discord integration) and Phase 11 (Import tools) were renumbered to Phase 12 and Phase 13, with their own scope unchanged.

Delivered as three revisions, each independently migrated, tested, and `alembic check`-clean before the next began:

- **077_item_domain** — item definitions/instances, inventory, ownership, attunement, and per-knower identification.
- **078_encounter_domain** — encounters, participants, rounds, turns, and combat actions.
- **079_integration_domain** — external systems, external identifiers, synchronization jobs/state, and delivery attempts.

## Exit Criteria

- [x] **Item ownership and possession are distinct and independently queryable.** `campaign.item_ownership` (legal owner, nullable for unclaimed treasure) and `campaign.inventory_entries` (current holder/container/location) are separate tables, each with its own same-world guard and one-current-row-per-(timeline, item) uniqueness — proven by `tests/database/test_item_domain.py`'s ownership/inventory sections, and by `campaign.character_inventory` (a read view joining both) correctly reporting `is_owned_by_holder = false` when the two diverge (a borrowed or stolen item).
- [x] **Combat resolved through `resolve_combat_turn` updates persistent character state through a causal event, entirely through the command layer.** `tests/scenario/test_encounter_commands.py::test_a_damaging_combat_turn_updates_persistent_character_state` drives the real command end-to-end: `campaign.character_state.current_hit_points` changes, a `narrative.events` row (`combat_damage_dealt`) is recorded citing the encounter via `narrative.event_causes.cause_encounter_id`, and a `narrative.event_effects` row links the two — all in one transaction (CLAUDE.md rule 6). `test_a_miss_leaves_character_state_and_events_untouched` proves the companion claim from `DATABASE_MODEL.md §12.3` ("not every attack roll needs a permanent world event"): a miss updates only the turn/combat_action record, nothing persistent.
- [x] **An external system's identifier for a world entity, and a synchronization job's lifecycle, are representable and round-trip through `integration.*` without any client writing PostgreSQL directly.** `tests/scenario/test_foundry_sync_commands.py::test_an_inbound_foundry_combat_payload_updates_persistent_state` drives `apply_foundry_combat_sync()` — an adapter-facing command that itself calls the *real* `resolve_combat_turn()`, never a raw table write — and verifies the resulting `integration.sync_jobs` row (`completed`, `resulting_event_id` set), `integration.delivery_attempts` row, `integration.sync_state` row (`synced`), and the underlying character-state change all agree. `test_re_registering_the_same_external_actor_is_idempotent` proves `map_external_identifier()`'s upsert behavior.
- [x] ~~Foundry combat can update persistent character and world state~~ — moved to Phase 11 (Foundry MVP), where it is provable against a live deployment. The claim above is the same mutation, proven short of "live."

## First-Time Obligations ([§23.1](PLAN.md#231-phase-exit-review))

- **First entirely local-first phase.** Every migration/round trip below ran against local PostgreSQL 18 first; the CI run against `dev` RDS is what closes the phase, not what merely confirms it (§23.0).
- **First `integration` schema tables.** The schema itself existed since revision 001 (seeded, default privileges wired) but held no tables until revision 079. `integration.external_systems` is the first world-scoped-but-not-entity-rooted "configuration/connection" table in the project — deliberately not entity-rooted (no in-fiction discoverable identity) and not a lookup (a real per-world connection record, not a shared classification).
- **First table with a genuinely open-ended, per-caller-varying classification left as free TEXT instead of a CHECK-constrained set or a lookup table**: `external_kind`/`job_type` (`integration.external_identifiers`/`.sync_jobs`). Every other small classification in this project (rarity, action_kind, encounter status, ...) is a fixed, closed, D&D-rules-driven set; the external-system vocabulary genuinely varies per adapter (Foundry's actor/scene/journal/token is not Discord's), so forcing one shared enum now would either be wrong for most systems or need to keep growing. Documented as a deliberate scoping decision in revision 079's docstring, with the criteria for promoting it to a lookup later.
- **First reuse of the interaction domain's plain-TEXT-status convention outside `interaction` itself**: `narrative.encounters.status`/`.encounter_participants.side`/`.outcome` and `interaction.combat_actions.action_kind` follow `interaction.interactions.status`'s TEXT+CHECK shape rather than `narrative.events.event_status_id`'s lookup-table shape — encounters sit structurally closer to interactions (high-volume, session-scoped, not entity-rooted) than to the permanent-history events table, and the migration's docstring records that reasoning explicitly since it cuts against the schema's more common lookup-table default.
- **First "at-most-one-of-two-typed-targets where one target type is itself not entity-rooted."** Every earlier at-most-one-typed-target column (`narrative.event_effects`, `knowledge.knowledge_items`, `interaction.targets`, `narrative.quest_objectives`) targets only entity-rooted rows. `integration.sync_jobs`/`.sync_state` and `narrative.event_causes.cause_encounter_id` are the first to target `narrative.encounters`, which has no `core.entities` row at all — each guard function resolves the encounter's world through `campaign.timelines` instead of `core.entities`, the same indirection `world.enforce_relationship_participant_world()` (Phase 8) used for its own non-entity-rooted parent.
- **Deferred items coming due:** `rules.item_definitions` (named "deferred to Phase 9" since Phase 4/`DATABASE_MODEL.md §11`), `campaign.item_ownership` (named in Phase 8's `world.ownership_relationships` comment as "the future Phase 9 item domain"), and the `world.area_spawn_definitions`/creature-instance gap `DATABASE_MODEL.md §9.2` flagged Phase 9 (encounters) as "the natural first consumer" of — **not** built this phase either: no exit criterion required it, and `narrative.encounter_participants.participant_entity_id` accepting any `core.entities` row (an NPC, a player character) was sufficient for every exit criterion above without inventing creature-instance/stat-block scope ahead of a concrete caller. Recorded here as still-deferred, not silently dropped.
- **First cross-phase plan revision made *before* delivery** rather than as a post-hoc correction pass — see the replan note above. The three renumbered/new phase entries in `PLAN.md` are the template for any future scope move discovered mid-phase.

## What Was Built

| Revision | Delivers |
|---|---|
| `077_item_domain` | `rules.item_categories` (lookup)/`.item_definitions` (ruleset-version-scoped, provenance columns, `properties_jsonb`); `world.item_instances` (entity-rooted, ruleset-allowance guard reusing `rules.ruleset_allowed_for_world()` from revision 029)/`.item_containers` (1:1 extension, not a second CTI leaf); `campaign.item_state`/`.item_ownership`/`.inventory_entries`/`.item_attunements` (all timeline-scoped, same-world + `enforce_state_event_timeline()` guards); `knowledge.item_identification`; `campaign.character_inventory` (read view, not autogenerate-tracked); 2 new `narrative.event_types` rows (`item_transferred`, `item_identified`) |
| `078_encounter_domain` | `narrative.encounters` (not entity-rooted)/`.encounter_participants`/`.encounter_rounds`/`.encounter_turns`; `interaction.combat_actions` (sibling of `.check_requests` under `.actions`); `narrative.event_causes.cause_encounter_id` (fourth cause type, extending revision 062's exactly-one-of CHECK); 1 new `narrative.event_types` row (`combat_damage_dealt`) |
| `079_integration_domain` | `integration.external_systems`/`.external_identifiers`/`.sync_jobs`/`.sync_state`/`.delivery_attempts` — first tables in the `integration` schema |
| Command layer | `src/dnd_ai/commands/items.py` (`transfer_item_possession()`, `identify_item()`); `src/dnd_ai/commands/encounters.py` (`start_encounter()`, `resolve_combat_turn()`, `end_encounter()`); `src/dnd_ai/commands/integration.py` (`register_external_system()`, `map_external_identifier()`, `apply_foundry_combat_sync()`) |
| Application metadata | `src/dnd_ai/persistence/tables/items.py` (9 tables), `.encounters.py` (5 tables, spanning `narrative`/`interaction`), `.integration.py` (5 tables) — all new modules; `narrative.py` extended (`event_causes.cause_encounter_id` + its index) |

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

| Obligation | Result |
|---|---|
| Object ownership | All 19 new tables added to `tests/database/test_role_grants.py`'s `MANAGED_TABLES`; the schema-driven completeness tripwire (`test_managed_tables_covers_every_table_in_every_managed_schema`) passes with no gaps for any of the three revisions. |
| Default privileges | Verified per-table by the same tripwire-guarded suite — `app_read_write`/`app_read_only` grants confirmed on all 19 new tables (no `GRANT` statements in any of the three migrations; default privileges from revision 001 covered them automatically). |
| Seed idempotency | `rules.item_categories` (15 rows, `ON CONFLICT (code) DO NOTHING`); 2 rows into pre-existing `narrative.event_types` (`item_transferred`/`item_identified`) and 1 more (`combat_damage_dealt`) — all `ON CONFLICT (code) DO NOTHING`. No seed data in revision 079 (`integration.*` has no lookup tables). |
| Constraint tests | Every nontrivial CHECK/trigger/unique-index has a positive and negative test — see "Test counts" below and each revision's `tests/database/test_*_domain.py`. |
| Comments and FK indexes | Zero tables without a comment; every FK indexed at creation. Caught and fixed during verification (not left for a later pass): a missing `core.enforce_immutable_columns('ruleset_version_id')` trigger on `rules.item_definitions` (`test_every_rule_table_with_a_ruleset_version_id_column_protects_it`), two `server_default` text-cast mismatches (`'common'` vs. `'common'::text`, same for `identification_level`), a missing `narrative.py` `Index()` declaration for `event_causes.cause_encounter_id` (alembic wanted to drop an index Core didn't know about), and a missing `COMMENT ON COLUMN campaign.item_state.last_event_id` the migration itself had never set despite Core declaring one. All four are documented in "Bugs found while verifying" below. |
| Downgrade | Verified individually for all three revisions against local PostgreSQL 18: `alembic downgrade <previous> → upgrade head`, `alembic check` clean before and after, for 077→076, 078→077, and 079→078. |
| Local/`dev` agreement | Both PostgreSQL 18.x (per the closed [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md) gate) — no version-specific behavior used by any of the three revisions. |
| CI green | See "Verification status" below. |

### Test counts

Phase 8's closing baseline was 2,058 tests. Phase 9 added 221 (`tests/database/test_item_domain.py`, `test_encounter_domain.py`, `test_integration_domain.py`; `tests/scenario/test_item_commands.py`, `test_encounter_commands.py`, `test_foundry_sync_commands.py`; plus `test_role_grants.py`'s per-table parametrization and `test_persistence_tables_package.py`'s three new domain-module entries). **2,279 tests collected.**

## Verification commands and results

Run against a local PostgreSQL 18 server (per [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup)):

```bash
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check                        # no diff, all three revisions
uv run alembic -c database/alembic.ini downgrade 078_encounter_domain
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check                        # no diff, after the round trip
uv run ruff format --check . && uv run ruff check . && uv run mypy src
uv run pytest tests/unit tests/database tests/scenario -q            # 2,279 collected
```

(The same up/down/check round trip was additionally run per-revision — 077→076, 078→077 — during development, each clean before moving to the next increment.)

**Result:** `alembic upgrade head` clean; `alembic check` clean in every case above, for every revision; downgrade/upgrade round trips clean; seed idempotency (re-running each migration's seed statements a second time produced no duplicate rows); `ruff format --check`/`ruff check`/`mypy src` all clean; **2,279 tests collected, all passing** against local PostgreSQL 18.

### Bugs found while verifying

Distinguished from schema-design defects per this project's own convention — all four were caught by existing cross-phase invariant tests (not new tests written for this phase), confirming those tests still do their job against new tables:

- **Missing `ruleset_version_id` immutability trigger on `rules.item_definitions`.** `test_every_rule_table_with_a_ruleset_version_id_column_protects_it` (table-driven off the live schema, not a hand-maintained list) caught that revision 077's original draft never attached `core.enforce_immutable_columns('ruleset_version_id')`, the policy every other ruleset-scoped rule-content table has carried since revisions 030/033/036. Fixed by adding the trigger directly at table creation (revision 077 postdates that policy, so there was no reason to defer it the way revisions 033/036 originally had to).
- **Two `server_default` text-cast mismatches.** `rules.item_definitions.rarity` and `knowledge.item_identification.identification_level` were declared in `src/dnd_ai/persistence/tables/items.py` as `server_default=text("'common'")`/`text("'unidentified'")`, but PostgreSQL normalizes a text column's string default to include an explicit `::text` cast — every other TEXT-with-default column in this project already reflects that. `test_metadata_server_default_matches_live_schema` caught both. Fixed by adding the cast to match the live schema's normalized form.
- **`narrative.py` missing an `Index()` declaration for `event_causes.cause_encounter_id`.** The migration correctly created a partial index; the Core metadata module didn't declare a matching `Index()` object, so `alembic check` saw an index in the database that Core's metadata didn't know about and proposed removing it. Fixed by adding the missing `Index()`, matching `cause_event_id`/`cause_interaction_id`'s existing shape.
- **Missing `COMMENT ON COLUMN campaign.item_state.last_event_id`.** Core declared a comment for this column (copied from `campaign.character_state`'s precedent); the migration never actually set it via `COMMENT ON COLUMN`. `alembic check` caught the mismatch as a `modify_comment` operation. Fixed by adding the missing statement to the migration, text matched exactly to Core's declaration.

No test-runner, fixture-framework, or CI-mechanism changes were made — every fix above is a production schema/metadata change.

## Verification status

- All local verification above ran and passed against local PostgreSQL 18: three migrations applied cleanly from `076_relationships_and_orgs` through `079_integration_domain`, `alembic check` clean at every step, three independent downgrade/upgrade round trips, seed idempotency, the full `tests/unit`/`tests/database`/`tests/scenario` suite (2,279 tests), `ruff format --check`/`ruff check`/`mypy src` all clean.
- Pushed to `phase9/items-encounters-integration`, PR [#21](https://github.com/NemesisGhost/dnd_ai/pull/21).
- This PR's exact head commit (`e60654a`) has a confirmed green CI run against the deployed `dev` RDS instance, polled via `scripts/wait_for_ci.py` to actual completion — run [`31312394682`](https://github.com/NemesisGhost/dnd_ai/actions/runs/31312394682), `PASS`.
- **Phase 9 is complete**, on its replanned scope (database model, external identifiers, synchronization state, and command layer — no live deployable, per the replan note above). The PR's exact head commit has a confirmed green CI run, closing the bar every prior phase has been held to. The PR has not yet been merged to `main` — that is the user's call, not something done automatically as part of this verification.
