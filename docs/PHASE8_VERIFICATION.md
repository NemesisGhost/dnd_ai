# Phase 8 Verification Checklist

Records the verification performed for Phase 8 (Relationships and organizations) per [PLAN.md §23](PLAN.md#23-delivery-phases) and the exit-review process in [§23.1](PLAN.md#231-phase-exit-review). Delivered as a single revision (075) covering this phase's full scope: the universal relationship model, specialized relationships, the organization/business/government/religious-organization/military-unit/political-faction CTI hierarchy, the religion/religious-affiliation distinction, and the two timeline-state tables (`campaign.organization_state`/`campaign.relationship_state`) `DATABASE_MODEL.md §17` had already named but no earlier phase built. Two application-layer commands (`src/dnd_ai/commands/relationships.py`): `evolve_relationship_reaction()` and `update_organization_status()`.

## Exit Criteria

- [x] **NPC and faction reactions can evolve from events.** `evolve_relationship_reaction()` records a `narrative.events` row (`relationship_changed`), updates `campaign.relationship_state` to match, and links the two through a `narrative.event_effects` row (`target_relationship_id`) — all in one transaction, per CLAUDE.md rule 6. `tests/scenario/test_relationship_reactions.py::test_an_event_changes_a_factions_subjective_reaction` proves this through actual application code: a criminal-organization faction's `affinity`/`trust`/`emotional_tone` toward the party changes in response to a recorded event, while the authored `world.relationship_perspectives` baseline (asserted separately) is left untouched — proving the definition/timeline-state split, not just the mutation. `update_organization_status()` proves the organization half of the same claim (`test_an_event_changes_an_organizations_operational_status` — a faction banned as a result of an event).
- [x] **Shared and subjective relationship data are separate.** `campaign.relationship_state` reuses `campaign.quest_state`'s nullable-dimension idiom: `perspective_holder_entity_id IS NULL` is the relationship's shared/objective status; set, it is one participant's own current reaction — enforced structurally by two partial unique indexes (`ux_relationship_state_timeline_relationship_no_holder`/`_holder`), not by convention alone. `tests/database/test_relationships_and_organizations.py::test_shared_and_per_holder_relationship_state_can_coexist` and `tests/scenario/test_relationship_reactions.py::test_shared_and_subjective_relationship_state_evolve_independently` both prove the two rows exist independently and can diverge (e.g. the shared status remains `active` while one participant's own reaction moves to `estranged`).

## First-Time Obligations ([§23.1](PLAN.md#231-phase-exit-review))

- **First CTI chain rooted at a non-entity table.** `world.organization_memberships`/`.employment_relationships`/`.ownership_relationships`/`.family_relationships`/`.political_relationships` share their primary key with `world.relationships`, not `core.entities` — the same class-table-inheritance mechanism used everywhere else, applied for the first time to a structural (not entity-rooted) parent. `world.sync_organization_membership_period()`'s world-agreement checks resolve the shared world through `world.relationships.world_id` rather than `core.entities`, since the parent row itself has no entity to look up.
- **First `EXCLUDE USING gist` outside `campaign` schema.** `world.organization_memberships` reuses the exact ADR 0010 interval-overlap pattern `campaign.party_memberships`/`.character_location_history` established (ck_..._open_ended_agrees/lower_bound_finite/period_not_empty CHECKs, a derived `INT8RANGE`, an exclusion constraint), proving the pattern generalizes beyond the tables that originated it.
- **First two-tier organization classification.** `world.organizations.organization_type_id` (a lookup covering all nine domain-model subtypes) and the five CTI leaf tables it optionally sits alongside are deliberately independent — an organization can be fully described by the lookup value alone (guild/criminal_organization/secret_society/other) or additionally specialized into a typed leaf table when one exists. `core.enforce_entity_subtype()` (unmodified — it already worked generically off `core.entity_types` ancestry) enforces which combinations are valid; `tests/database/test_relationships_and_organizations.py::test_a_business_subtype_requires_the_business_entity_type` proves the negative case (a bare 'organization'-typed entity cannot receive a `world.businesses` row).
- **Deferred items coming due:** `interaction.consequences.resulting_relationship_state_id` and `narrative.event_effects.target_relationship_id` — both explicitly documented as "Phase 8's job" by revision 073's own comments (Phase 7). Closed here, extending the at-most-one-target `CHECK` to seven columns.

## What Was Built

**Revision 075:** 23 new tables (18 in `world`/`character` schema domain tables, 4 in `campaign` for timeline state, 1 `character.character_religious_affiliations`), 1 new command module (`src/dnd_ai/commands/relationships.py`, two commands: `evolve_relationship_reaction()`, `update_organization_status()`), 15 new trigger functions, 5 new seeded lookups (~49 rows), 2 new `narrative.event_types` seed rows, and 2 columns added to two previously-existing tables.

| Area | Delivers |
|---|---|
| Universal relationships | `world.relationship_types`/`.relationship_participant_roles` (seeded lookups), `.relationships` (not entity-rooted — same reasoning as `world.area_connections`/`interaction.interactions`/`narrative.story_arcs`), `.relationship_participants`, `.relationship_perspectives` (authored baseline, distinct from `campaign.relationship_state`) |
| Organizations | `world.organization_types` (seeded lookup), `.organizations` (entity-rooted CTI root), `.businesses`/`.governments`/`.military_units`/`.political_factions`/`.religious_organizations` (CTI leaves) |
| Religion | `world.religions` (entity-rooted, separate CTI chain), `character.character_religious_affiliations` |
| Specialized relationships | `world.organization_memberships` (ADR 0010 exclusion constraint), `.employment_relationships`, `.ownership_relationships`, `.family_relationships`, `.political_relationships` — all CTI leaves of `world.relationships` |
| Timeline state | `campaign.organization_statuses`/`.organization_state` (one row per timeline+organization), `campaign.relationship_statuses`/`.relationship_state` (nullable `perspective_holder_entity_id` dimension, same idiom as `quest_state.party_id`) |
| Forward-reference closures | `narrative.event_effects.target_relationship_id` (seventh column in the at-most-one-target pattern); `interaction.consequences.resulting_relationship_state_id` (closes revision 061's documented placeholder, relationship half) |
| Command layer | `src/dnd_ai/commands/relationships.py`: `evolve_relationship_reaction()`, `update_organization_status()` — lock the structural parent row first (same first-write concurrency guard `advance_objective()` established), record the causing event, update state, link via `event_effects` |
| Application metadata | New `src/dnd_ai/persistence/tables/relationships.py` (18 tables, all `world` schema) plus extensions to `campaign.py` (4 tables), `characters.py` (1 table), `narrative.py`/`interaction.py` (1 column each) — `alembic check` compares this against the live database unconditionally |

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

| Obligation | Result |
|---|---|
| Object ownership | All 23 new tables added to `tests/database/test_role_grants.py`'s `MANAGED_TABLES`; the schema-driven completeness tripwire (`test_managed_tables_covers_every_table_in_every_managed_schema`) passed with no gaps. |
| Default privileges | Verified per-table by the same tripwire-guarded `test_role_grants.py` — `app_read_write`/`app_read_only` grants confirmed on all 23 new tables. |
| Seed idempotency | `world.relationship_types` (13 rows), `.relationship_participant_roles` (15 rows), `.organization_types` (9 rows), `campaign.organization_statuses` (6 rows), `.relationship_statuses` (6 rows) all seeded with `ON CONFLICT (code) DO NOTHING`, the same pattern every prior lookup uses. Two rows into the pre-existing `narrative.event_types`: `relationship_changed`, `organization_status_changed`. |
| Constraint tests | Every nontrivial CHECK/trigger/exclusion-constraint added has a positive and negative test (§32.1) — see "Test counts" below and `tests/database/test_relationships_and_organizations.py`'s per-section coverage (same-world guards, the perspective/state "holder must be a participant" rule, the organization-parent self-reference and dissolved/founded ordering CHECKs, the membership exclusion constraint, the at-most-one-target extension, the two new partial unique indexes). |
| Comments and FK indexes | Zero tables without a comment. `test_every_foreign_key_is_indexed` caught six initially-missed indexes on first run (`world.relationships.started_world_time_id`/`.ended_world_time_id`, `world.organizations.founded_world_time_id`/`.dissolved_world_time_id`, `world.employment_relationships.effective_from_world_time_id`/`.effective_to_world_time_id`) — fixed in both the migration and the matching `src/dnd_ai/persistence/tables/relationships.py` declarations, and reverified. |
| Downgrade | Verified via `alembic downgrade 074_phase7_correction_pass → upgrade head` against AWS `dev`, followed by `alembic check` reporting no diff and `alembic heads` reporting exactly one head (`075_relationships_and_orgs`). |
| CI green | Not yet run — this phase has not been pushed to a branch or opened as a PR. See "Verification status" below. |

### Test counts

Phase 7's closing baseline was **1,799 collected tests**. After revision 075: **2,022 tests** (+223) — `tests/database/test_relationships_and_organizations.py` (49 cases), `tests/scenario/test_relationship_reactions.py` (5 cases), and the remainder from `test_role_grants.py`'s per-table parametrization (23 new tables × its existing grant/ownership/read-only test matrix) and `test_persistence_tables_package.py`'s new `relationships` domain-module entry. All passing against AWS `dev` after the fixes below.

## Verification commands and results

Run against the deployed AWS `dev` RDS instance (ingress opened via `scripts/aws-db-allow-my-ip.sh open --environment dev` before each session):

```bash
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check                       # no diff
uv run alembic -c database/alembic.ini downgrade 074_phase7_correction_pass
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check                       # no diff, after the round trip
uv run alembic -c database/alembic.ini heads                       # exactly one head
uv run ruff format --check . && uv run ruff check . && uv run mypy src
uv run pytest tests/unit -q                                        # 44 passed
uv run pytest tests/database -q                                    # 1958 passed (after fixes)
uv run pytest tests/scenario -q                                    # 20 passed
```

**Result:** `alembic upgrade head` clean; `alembic check` clean both before and after the downgrade/upgrade round trip; `alembic heads` reports exactly one head (`075_relationships_and_orgs`); `ruff format --check`/`ruff check`/`mypy src` all clean; **2,022 tests collected, all passing** (44 unit + 1,958 database + 20 scenario).

### Bugs found while verifying revision 075

Distinguished from schema-design defects per this project's own convention:

- **Six missing FK indexes** (conventions §19.1): `world.relationships.started_world_time_id`/`.ended_world_time_id`, `world.organizations.founded_world_time_id`/`.dissolved_world_time_id`, `world.employment_relationships.effective_from_world_time_id`/`.effective_to_world_time_id`. Caught by `test_every_foreign_key_is_indexed` on first run. Fixed in the migration and the matching Python metadata; reverified.
- **`_organization_subtype()`'s local migration helper did not escape embedded apostrophes when interpolating a table comment into `COMMENT ON TABLE ... IS '{comment}'`.** Two of its callers' comment text (businesses', governments') contain a possessive apostrophe (`"Phase 9's item domain"`, `"docs/PLAN.md's own example"`), which would have produced invalid SQL. Caught by code review before running against the database (not by a test — a malformed literal fails immediately at execution, so no test coverage gap is implied). Fixed by escaping (`comment.replace("'", "''")`) before interpolation, matching how every hand-written `COMMENT ON` statement elsewhere in the migration already doubles embedded apostrophes.
- **`tests/factories.py`'s `make_organization()` always resolved `core.entities.entity_type_id` to the bare `'organization'` type**, regardless of the `organization_type_code` argument — conflating the descriptive `world.organizations.organization_type_id` lookup with the separate CTI entity-type system. `core.enforce_entity_subtype()` correctly rejected the resulting mismatch (a bare `'organization'`-typed entity cannot receive a `world.businesses`/`.governments`/`.military_units`/`.political_factions`/`.religious_organizations` row), causing five test failures (`test_a_business_can_be_created` and its four siblings). Not a schema defect — the database enforced its own invariant correctly; the test factory was wrong. Fixed: `make_organization()` now resolves the entity type to the same code as `organization_type_code` when it names one of the five CTI-leaf subtypes, and to `'organization'` otherwise.
- **Four unrelated test failures during the first full run** (`test_a_blocked_language_removal_resumes_and_is_rejected_once_the_creator_commits`, and three `test_phase5_populated_upgrade.py` cases) were `psycopg.errors.ConnectionTimeout` against AWS RDS, occurring near the end of a ~30-minute single pytest session — consistent with this project's own documented experience of transient AWS-RDS connection faults (Phase 7's exit review notes one re-run for the same reason). Not reproduced on rerun; no code changes made for these. `scripts/aws-db-allow-my-ip.sh`'s ingress rule was also observed to close itself between separate `verify.sh` invocations (each stage opens on entry and closes on exit) — a session running several verification stages back-to-back must reopen it before any bare `alembic`/`psql` command issued outside `verify.sh` itself.

## Verification status

- All local verification above ran and passed against AWS `dev`: migration upgrade/downgrade/upgrade round trip with `alembic check` clean at every step and exactly one head, the full `tests/unit`/`tests/database`/`tests/scenario` suite (2,022 tests), `ruff format --check`/`ruff check`/`mypy src` all clean.
- **Not yet pushed to a remote branch or opened as a pull request, and CI has not run.** Every prior phase's verification file records a confirmed green CI run on the PR's exact final head as the closing condition for "complete." That step is the user's call, consistent with this project's convention of not pushing or opening PRs without being asked — implemented on local branch `agent/phase8-relationships-and-organizations`, not yet on `main`.
