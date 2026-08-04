# Phase 4 Verification Checklist

Verifies Phase 4 (Rules and shared characters) per [PLAN.md §23](PLAN.md#23-delivery-phases), following the exit review in [§23.1](PLAN.md#231-phase-exit-review). The sections below record the phase's original exit review, its first corrections pass, the revision-031–034 closeout pass, the revision-035–036 pass that cleared the two final-schema blockers and three verification obligations a post-closeout review found ("Second closeout"), and the revision-037 pass that closes the character-language integrity defect and three verification gaps a final review of revision 036 found ("Third closeout"). Phase 4 is complete; [PHASE4_REMAINING_ISSUES.md](PHASE4_REMAINING_ISSUES.md) is now a closed historical record.

## Exit Criteria

- [x] NPC and PC use the same mechanical model — both are, structurally, a `character.characters` row plus a marker subtype (`character.npcs` / `character.player_characters`), proven in `test_characters.py::test_npc_and_player_character_both_extend_characters`
- [x] A character sheet can be assembled from structured data — the seeded ruleset (§6 below) supplies real classes, species, spells, and features a build can reference; `test_character_builds.py` exercises ability scores, multiclass levels, proficiencies, and spellcasting profiles against it
- [x] A subtype row cannot exist without its parent `core.entities` row, cannot use a primary key of its own, and cannot attach to a parent of the wrong entity type — each rejected by the database, each with a negative test (`test_characters.py`, verbatim test names matching the criterion's own wording)

All verified against the deployed AWS `dev` RDS instance, per [§23.0](PLAN.md#230-aws-verification-policy): full downgrade-to-`base` and upgrade-to-`head` round trip through all 22 revisions, `alembic check` clean, 523 tests passing.

## Preceded by a documentation reconciliation

Before writing schema, a real drift between `PLAN.md` and `docs/architecture/DATABASE_MODEL.md` was found and fixed: `DATABASE_MODEL.md`'s per-domain table lists were a compressed sketch, `PLAN.md`'s per-phase prose had grown ~40 additional table mentions neither document cross-referenced, and 7 tables built in Phases 1–3 had never been added to `DATABASE_MODEL.md` at all. `DATABASE_MODEL.md` is now the explicit schema source of truth (`CLAUDE.md`'s documentation map updated to say so); `PLAN.md` is corrected to match; `README.md`'s schema-flavored sections are marked illustrative. `DATABASE_MODEL.md` §25 records every reconciliation judgment call made, including a few flagged as genuinely uncertain for the phase that actually owns them to revisit. See the "Make DATABASE_MODEL.md the primary source of truth" commit for the full account — it is not repeated here since it precedes this phase's own schema work rather than being part of it.

## What Was Built

Ten revisions, 34 tables, one seed migration.

| Revision | Delivers |
|---|---|
| `013_rulesets` | `rules.rulesets`, `rules.ruleset_versions` (at most one current version per ruleset) |
| `014_ruleset_content` | Eight ruleset-version-scoped lookups generated from one shared shape (abilities, species, damage types, conditions, creature types, languages, proficiency types, resource definitions), plus `rules.skills` (governing ability cross-checked) |
| `015_ruleset_classes` | `rules.classes`, `rules.subclasses` (class agreement enforced), `rules.features` (independently nullable class/subclass/species associations), `rules.feats`, `rules.spells` |
| `016_close_ruleset_refs` | `rules.world_rulesets`; closes `core.worlds.default_ruleset_id` (deferred Phase 2) and `campaign.campaigns.ruleset_id` (deferred Phase 3), both trigger-checked against `world_rulesets` |
| `017_characters` | `character.characters` → `character.npcs` / `character.player_characters`, wired to Phase 2's `core.enforce_entity_subtype()`; the three `core.entity_types` rows |
| `018_party_membership_char` | Closes Phase 3's deferral: `party_memberships.member_entity_id` must be a `character.characters` row |
| `019_character_shared_data` | `character_descriptions`, `character_languages`, `character_senses`, `character_movements` |
| `020_character_builds` | `character_builds` (one current per character), `character_ability_scores`, `character_class_levels` (multiclass-capable, subclass-checked), `character_proficiencies` (exactly-one-target CHECK), `character_features`, `character_spellcasting_profiles`, `character_known_spells`, `character_prepared_spells` |
| `021_character_timeline_state` | `campaign.character_state`, `.character_conditions`, `.character_resources` — one shared world-agreement trigger function across all three |
| `022_seed_ruleset` | One ruleset ("D&D 5e (2024)"), one current version, and real cross-referenced content: 6 abilities, 18 skills, 2 species, 13 damage types, 14 conditions, 14 creature types, 10 languages, 5 proficiency types, 5 resource kinds, 2 classes, 2 subclasses, 2 feats, 5 spells, 3 features |

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

| Obligation | Result |
|---|---|
| Object ownership | All 34 tables owned by `migration_owner` |
| Default privileges | `app_read_write`/`app_read_only` asserted per-table in `test_role_grants.py`, now covering all 34 new tables |
| Seed idempotency | Re-ran `022`'s `upgrade()` a second time directly against an already-seeded database: zero new rows, zero errors. First seed content with real cross-references (skills→abilities, subclasses/features→classes, spells→damage types) rather than flat codes — see "Bugs and Gaps Found" for what that surfaced |
| Constraint tests | 523 tests total (up from 327 at Phase 3 exit) |
| Comments and FK indexes | Zero tables without a comment; `test_every_foreign_key_is_indexed` clean after fixing three gaps (below) |
| Downgrade | Full round trip to `base` and back through all 30 revisions (22 original + 8 corrective), confirmed again after the corrections review |
| CI green | Confirmed by GitHub Actions run [`30755760409`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30755760409): ephemeral database create, migrate to head, full downgrade/upgrade round trip, structured-seed checks, `alembic check`, formatting, Ruff, mypy, all 612 tests, and cleanup passed against AWS `dev`. |

## Bugs and Gaps Found

1. **Three more foreign keys missing their §19.1 index**: `campaign.character_conditions.character_id`, `campaign.character_resources.character_id`, `character.character_spellcasting_profiles.class_id`. Same class of gap as Phase 3's three — tables with no natural composite index happening to cover a given column. `test_every_foreign_key_is_indexed` caught all three.
2. **Phase 3 test fixtures broke against the new party-membership enforcement.** `018_party_membership_char` requires `member_entity_id` to be an actual character; Phase 3's `test_party_memberships.py` built members as bare `core.entities` rows via `make_entity`. Fixed by adding `make_character()` to `tests/factories.py` and switching the fixture to it — this is expected, intentional breakage (the whole point of the revision), not a regression.
3. **`make_ruleset_for_world()` always set `is_default = true`.** A second call for a world that already had an allowed ruleset collided with `ux_world_rulesets_one_default_per_world`. Fixed to default `is_default` based on whether the world already has a `world_rulesets` row, with an explicit override still available.
4. **`make_character()` always used the bare `character` entity type.** Tests that then tried to also insert a `character.npcs` or `character.player_characters` row for it were correctly rejected by `core.enforce_entity_subtype()` — the entity wasn't typed as an NPC or PC. Not a schema bug; the test helper needed an `entity_type_code` parameter, since a caller building an NPC needs the entity created as one from the start.
5. **A test entity-type code used a hyphen.** `ck_entity_types_code_format` requires `^[a-z][a-z0-9_]*$` (underscore, no hyphens) — `"non-character-type"` fixed to `"non_character_type"`.
6. **A column comment drifted between a migration and `tables.py`** (same class of gap Phase 3 hit once): `campaign.character_state`'s table comment text differed by a few words between the two, caught by `alembic check`.

None of these were schema-design defects — all six were test/tooling bugs found and fixed before they could hide a real one.

## Deliberate Scoping Decisions

- **NPC portrayal and simulation apparatus is deferred to Phase 10.** `character.npc_portrayal_profiles`, `.npc_characteristics`, `.npc_goals`, `.npc_routines`, `.npc_routine_steps`, `.npc_preferences`, `.npc_boundaries`, `.npc_disclosure_rules`, `.npc_agent_assignments`, `character.character_controllers`, `security.character_permissions`, `campaign.npc_goal_state`, `campaign.npc_emotional_state` — none of these appear in Phase 4's own Deliver/exit-criteria text, and Phase 10 is what actually builds the AI agents and control assignment they serve. `character.npcs` itself is built now, deliberately minimal.
- **`character.character_religious_affiliations` is deferred to Phase 8**, which builds `world.religions`.
- **`campaign.character_location_history` is deferred to Phase 5** (locations) and **`campaign.character_inventory` to Phase 9** (items) — both already recorded as deferred in `PLAN.md` §7.3 before this phase started.
- **`rules.item_definitions` is deferred to Phase 9**, which explicitly owns "item definitions and instances" together.
- **No event-linked history on the three timeline-state tables.** `DATABASE_MODEL.md` §17's general shape calls for `effective_from_event_id`/`effective_to_event_id`, but `narrative.events` doesn't exist until Phase 6. Each table is a single mutable current row per `(timeline, character)` instead, enforced by its primary key; Phase 6 is expected to add event linkage without needing to change these tables' shape, since atomicity is a transaction-boundary guarantee the command layer provides, not a column.
- **Cross-ruleset-version checks originally stopped at ability scores and class levels.** Revision 026 superseded that original scope cut. Revisions 032 and 033 then closed the proficiency-type and parent-update gaps found in the next review; the active register tracks only the later revision-034 findings.
- **`size_category` is a CHECK, not a lookup table.** The six D&D size categories are a fixed, universal vocabulary unlike canon/lifecycle status or ability names, which the conventions' "lookup tables over ENUM" guidance targets because they vary by ruleset or need GM extension.
- **`character.character_senses.sense_type` and `character.character_movements.movement_type` are free text**, not lookups — this project has no documented controlled vocabulary for either, and inventing one unprompted risked recreating the exact drift the pre-phase reconciliation just fixed.

## Corrections review (2026-08-02)

A follow-up review of the Phase 4 schema — after the exit criteria above were already met — found integrity gaps that the exit criteria didn't happen to exercise. Eight forward-only revisions closed that initial set, none touching the 22 already-applied migrations:

| Revision | Closes |
|---|---|
| `023_session_world_time_period` | `campaign.sessions` had world-time endpoints but no derived `INT8RANGE`, unlike `party_memberships`. Added `world_time_period`, half-open `[start, end)`, unbounded upper for open-ended, `NULL` for unscheduled — same contract as [ADR 0010](adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md), deliberately without an exclusion constraint (sessions may overlap). |
| `024_campaign_ruleset_version` | `campaign.campaigns.ruleset_id` pinned a ruleset *family*, not the specific *version* a build pins to — not reproducible if the family later gained a second current version. Renamed to `ruleset_version_id`, referencing `rules.ruleset_versions` directly. The ruleset row's code changed from `dnd5e_2024` to `dnd5e` (an UPDATE, not a migration edit). Revision 034 later completed the family/version display-data separation. |
| `025_rules_provenance_canon` | No rule-content table carried `source_id`/`canon_status_id`, contradicting `rules.rulesets`' own comment and [DATABASE_CONVENTIONS.md §16](DATABASE_CONVENTIONS.md#16-canon-and-provenance-conventions). Added both to all 16 rule tables, `canon_status_id` defaulted to `'canon'` via `rules.default_canon_status_id()` (a plain subquery is not a valid column default in PostgreSQL) — official content needs no per-row boilerplate; homebrew overrides it explicitly. |
| `026_ruleset_version_checks` | Revision 020's own docstring recorded proficiencies/features/spellcasting-vs-build ruleset-version checks as a deliberate scope cut. Closed it, plus classes/primary-ability, features/class-subclass-species, and spells/damage-type, all by trigger (the established pattern for cross-row checks a CHECK can't express). |
| `027_world_ruleset_default` | `rules.world_rulesets.is_default` and `core.worlds.default_ruleset_id` were two independent representations of one fact with nothing keeping them in sync. Removed `is_default`; `default_ruleset_id` is now the sole source of truth. Added a trigger rejecting removal of a `world_rulesets` association still relied on by a world's default or a campaign's pinned version. |
| `028_build_timeline_state` | `character_builds.is_current` was one global flag per character — unable to represent the same character built differently on two timelines after a branch. Moved active-build selection to `campaign.character_state.character_build_id` (timeline-scoped, matching where combat state already lives); dropped `is_current` outright. |
| `029_character_corrections` | Five smaller gaps: `current_hit_points` could exceed `maximum_hit_points`; `transformed_into_id` wasn't checked against the character's own world; `rules.spells.code` had no format CHECK unlike every sibling; a proficiency's target column could disagree with its `proficiency_type_id`, and the same semantic proficiency could be granted twice; and a character's species/build/conditions/resources were never checked against `rules.world_rulesets` for its own world. |
| `030_parent_scope_immutable` | Same-world/same-scope triggers validate a child row when it's written, but nothing stopped a *parent's* scope column (`core.world_times.sort_key`/`world_id`, `core.entities.world_id`, `campaign.timelines.world_id`, `campaign.parties.world_id`, `campaign.campaigns.timeline_id`) from changing under already-valid children. Made all five immutable by trigger — a generic `core.enforce_immutable_columns()`, the same reusable-function shape as `core.enforce_entity_subtype()`. |

Verified the same way as the original Phase 4 exit: full `downgrade base` → `upgrade head` round trip through all 30 revisions against the deployed AWS `dev` instance, `alembic check` clean, every new invariant covered by a positive and negative test (`tests/database/test_phase4_corrections.py`, 47 tests), expanded seed verification covering all 14 Phase 4 structured YAML files with cross-reference and value assertions plus a true double re-invocation of revision 022's own `upgrade()` proving idempotency (`tests/database/test_seed_idempotency.py`), and a `database/seeds/frozen_manifest.json` + test guarding those 14 files against future silent edits. The subsequent GitHub Actions run passed all 612 tests.

Two deviations from the corrections request, both reasoned rather than oversights:

- **`rules.rulesets` / `rules.ruleset_versions`' `canon_status_id`, and every rule-content table's, got a database-level `DEFAULT` of `'canon'`** rather than being caller-mandatory like `core.entities.canon_status_id`. The overwhelming majority of rule content is officially authored; requiring every future INSERT (including every test fixture) to look up and pass the status explicitly was pure friction for that common case, and a default doesn't weaken the column's meaning — homebrew/proposed content still overrides it. `core.entities` intentionally has no such default since its callers must always decide both canon and lifecycle status as policy; rule content is a narrower case.
- **Alembic comment comparison documentation** — `tests/database/test_schema_documentation.py` still claimed `compare_comments=False`, even though the Alembic environment enables comment comparison. That stale test-module docstring was corrected during the final documentation reconciliation.

## Closeout (2026-08-02)

The seven issues found in the revision-030 review were closed by four forward-only revisions (none touching the 30 already-applied migrations):

| Revision | Closes |
|---|---|
| `031_world_ruleset_full_protect` | §1. `rules.enforce_world_ruleset_still_in_use()` (revision 027) protected only a world's default and a campaign's pin. Added the four remaining dependency categories — character species, character build, applied condition, tracked resource — and fixed the function to `RETURN NEW` on a permitted `UPDATE` (it previously always `RETURN OLD`, silently discarding a permitted repoint). |
| `032_proficiency_type_version` | §3. `character.enforce_proficiency_ruleset_version()` (revision 026) checked a proficiency's skill/saving-throw target against its build's ruleset version but never `proficiency_type_id` itself. Added that check. |
| `033_rules_identity_immutable` | §2. Every ruleset-version-consistency trigger (revisions 014, 015, 020, 026, 029) validated only the child row's own insert/update, so a parent's identity could still change out from under already-valid children. Made the parent side of every such invariant immutable, reusing `core.enforce_immutable_columns()` (revision 030) — extended in the same revision to allow a `NULL` -> value transition (a column being set, not changed), which revision 029's own add-column-then-backfill pattern for `proficiency_types.target_kind` depends on. |
| `034_ruleset_family_neutral` | §5. The seeded ruleset family's code was already edition-neutral (`dnd5e`, revision 024) but its `display_name`/`description` still named "2024" at the family level. Moved the edition-specific text to the version row; the family row is now edition-neutral display data only. |

Two items needed no schema change:

- **§4 (SQLAlchemy canon-status default drift).** `tables.py` declared `rules.rulesets.canon_status_id`'s default as a bare subquery; the live schema had always used `rules.default_canon_status_id()` (revision 025). Fixed the Python declaration to match. Since `alembic check` doesn't compare server defaults, added a generic test (`test_metadata_server_default_matches_live_schema`, parametrized over every `text()`-valued server default in the metadata) that diffs the declared default against `information_schema.columns.column_default` for the live column — this closes the whole class of drift, not just this one instance.
- **§6 (rule-source enforcement).** Resolved as an application-command obligation, not a database constraint: there's no schema concept of content *origin* independent of canon status, and no `commands/` layer exists yet to validate against. `DATABASE_CONVENTIONS.md` §16.2 and `DATABASE_MODEL.md` §8 now say so explicitly, rather than describing nullable `source_id` as database-enforced provenance.

Plus a CI fix outside the migration set:

- **§7 (CI cleanup masking).** `.github/workflows/ci.yml`'s cleanup step appended `|| true` to both the ephemeral-database drop and the security-group ingress revocation, so either could fail while the job stayed green. Both are now always attempted, each result captured, and the step fails after both if either failed — with `::error::` annotations identifying which one.

Verified the same way as the corrections pass: full `downgrade base` → `upgrade head` round trip (through all 34 revisions) against a throwaway database on the deployed AWS `dev` instance, `alembic check` clean, `ruff format --check`/`ruff check`/`mypy src` clean, 218 focused tests in `tests/database/test_phase4_remaining_issues.py` (including the world-ruleset repoint-actually-takes-effect case and the NULL-transition case the immutability fix depends on), seed idempotency green (`test_seed_idempotency.py`, including its in-process replay of revisions 022/024/029), and the full suite — 830 tests (up from 612) — green against AWS `dev`. This proves the tested single-transaction paths; it does not claim coverage for the concurrency and missing negative/value/failure cases in the post-closeout register.

The push-triggered GitHub Actions run [`30765722355`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30765722355) independently passed both jobs, including the full migration round trip, all 830 tests, database cleanup, and ingress revocation.

## Post-closeout review (2026-08-02)

A review of commit `257325f` found that the revision-031 allow-list checks are not safe against concurrent dependency creation and deletion/repointing under `READ COMMITTED`, and revision 033 omits `rules.creature_types`, `rules.languages`, and `rules.feats` from the model's rule-definition identity-immutability policy. It also found three unfulfilled verification criteria: the proficiency-type mismatch has no negative update test, revision 034's final seeded family/version values are not directly asserted, and CI cleanup's combined failure behavior has no safe simulated failure-path test.

## Second closeout (2026-08-02)

Both schema blockers and all three verification obligations from the post-closeout review are closed, by two more forward-only revisions plus test/script additions (none touching the 34 already-applied migrations):

| Revision | Closes |
|---|---|
| `035_world_ruleset_concurrency` | §1. Every "is this ruleset allowed for this world" check (`rules.ruleset_allowed_for_world()` shared by species/build/condition/resource, plus `core.enforce_world_default_ruleset_allowed()` and `campaign.enforce_campaign_ruleset_allowed()`) now takes a `SELECT ... FOR SHARE` lock on the specific `rules.world_rulesets` row before deciding, closing the `READ COMMITTED` race with a concurrent delete/repoint (which needs an exclusive lock on that same row, acquired automatically before revision 031's trigger runs). Documented why a single, always-same-row lock cannot deadlock. |
| `036_remaining_rules_immutable` | §2. Attaches `core.enforce_immutable_columns()` to `rules.creature_types`, `rules.languages`, and `rules.feats` — the three rule-definition tables revision 033's own enumeration (built by grepping for an existing cross-version invariant) missed, since nothing currently reads their `ruleset_version_id` as a parent. The identity policy applies regardless. |

Verification obligations closed without new migrations:

- **§3.** `test_updating_a_proficiencys_type_to_a_different_version_is_rejected` starts from a valid proficiency, updates `proficiency_type_id` to a type from a different ruleset version inside a `SAVEPOINT` (so the expected failure doesn't poison the rest of the test's transaction), asserts rejection, and re-reads the row to prove it is unchanged.
- **§4.** `test_seeded_ruleset_family_and_version_are_edition_neutral` (`test_seed_idempotency.py`) directly asserts `rules.rulesets` code `dnd5e`/display name `D&D 5e`/a non-edition-specific description, and `rules.ruleset_versions` version label `2024` with the edition-specific description moved there.
- **§5.** `scripts/ci_cleanup.py` extracts the cleanup step's combine-and-report logic into `run_cleanup(drop_database, revoke_ingress)`, wired to the real operations by `main()` and to fake success/failure callables by `tests/unit/test_ci_cleanup.py` — all four combinations (both succeed, each fails alone, both fail) are exercised without ever touching AWS. `.github/workflows/ci.yml`'s cleanup step now just calls the script.

Also added: `test_every_rule_table_with_a_ruleset_version_id_column_protects_it`, a table-driven test built off `information_schema` (not a hand-maintained list) asserting every `rules.*` table with a `ruleset_version_id` column has an immutability trigger covering it — the mechanism that would have caught revision 033's omission automatically, and now guards against a future rule-content table repeating it.

Verified the same way as the first closeout pass: full `downgrade base` → `upgrade head` round trip (through all 36 revisions) against a throwaway database on the deployed AWS `dev` instance, `alembic check` clean, `ruff format --check`/`ruff check`/`mypy src` clean, seed idempotency green, and the full suite — 847 tests (up from 830) — green against AWS `dev`. The two-connection concurrency tests follow `test_party_memberships.py`'s established pattern (committed setup under a unique slug, a short `lock_timeout` on the side that must block, explicit teardown) and cover all six dependency categories for the delete race plus one repoint race, reasoned in the test module as sufficient coverage of the underlying (table/row-level, not category-specific) locking mechanism rather than a gap.

The push-triggered GitHub Actions workflow independently confirmed that result in
run [`30771818049`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30771818049):
migration through revision 036, full downgrade/upgrade, seed verification,
`alembic check`, formatting, Ruff, mypy, all 847 tests, database removal, and
ingress revocation passed.

`DATABASE_MODEL.md` §8's two temporary implementation-gap notes (immutability coverage, allow-list concurrency) are removed now that both are true without qualification.

## Final review after revision 036 (2026-08-02)

A review of commit `f154f49` accepted the revision-035 and revision-036 corrections
but found one dependency category that the preceding allow-list reviews had not
enumerated: `character.character_languages`. The association can reference a
language from a ruleset family the character's world does not allow, does not block
removal or repointing of an allow-list row it uses, and does not participate in the
shared-lock protocol during concurrent creation.

The same review found three narrower verification gaps: the concurrency suite does
not let an already-waiting mutation resume naturally after the creator commits;
the cleanup unit suite does not assert `main()` exits with status 1 on failure; and
the ruleset-family seed test does not assert revision 034's exact edition-neutral
family description.

These are active closeout work, not failures of run `30771818049`: the workflow
proved the behavior exercised by the committed suite, while the review identified
final-schema and coverage paths that suite does not exercise. Acceptance criteria
and the completion gate are in
[PHASE4_REMAINING_ISSUES.md](PHASE4_REMAINING_ISSUES.md).

## Third closeout (2026-08-02)

The one schema blocker and three focused verification gaps from the final review of
revision 036 are closed, by one more forward-only revision plus test additions
(none touching the 36 already-applied migrations):

| Revision | Closes |
|---|---|
| `037_character_language_ruleset` | §1. `character.character_languages` was the one dependency category revisions 029/031/035 never enumerated. A new `character.enforce_character_language_ruleset_allowed()` trigger (`BEFORE INSERT OR UPDATE`, shaped exactly like revision 029's species/build checks) rejects a language whose ruleset family the character's world does not allow, calling the same `rules.ruleset_allowed_for_world()` helper — and therefore inheriting its revision-035 `FOR SHARE` lock — with no new locking code. `rules.enforce_world_ruleset_still_in_use()` (revision 031) gained a seventh usage check so removing or repointing an allow-list association a character's language depends on is rejected the same way the other six categories already were. The table comment (both the live `COMMENT ON TABLE` and `tables.py`'s metadata) was updated to describe the enforcement, keeping `alembic check` clean. |

Verification obligations closed without new migrations:

- **§2.** `test_a_blocked_language_removal_resumes_and_is_rejected_once_the_creator_commits` closes the gap the revision-035/036 `lock_timeout` tests left: a real second thread (no `lock_timeout`) issues the allow-list `DELETE`, a bounded poll of `pg_stat_activity` proves it is genuinely waiting on the dependent-creator's `FOR SHARE` lock (not just slow), the creator commits, and the *same* blocked statement — not a retry in a new transaction — is proven to resume and be rejected, with a bounded `thread.join` so a failed assertion cannot hang the suite. Exercised once, for the newly added character-language category; the underlying lock is table/row-level, not category-specific, matching the reasoning already recorded for the six-category delete-race coverage above.
- **§3.** `tests/unit/test_ci_cleanup.py` gained three tests patching `ci_cleanup.drop_ephemeral_database`/`ci_cleanup._revoke_real_ingress` (the module-level names `main()` actually calls) to prove `main()` itself — not just `run_cleanup()` — raises `SystemExit(0)` on success and `SystemExit(1)` when either operation fails, without touching AWS.
- **§4.** `test_seeded_ruleset_family_and_version_are_edition_neutral` now asserts the exact revision-034 family description text (`"The fifth-edition Dungeons & Dragons ruleset family, spanning multiple published editions (e.g. 2014, 2024)."`) rather than only the absence of the old edition-specific string, so a different wrong wording would also fail it.

Positive/negative character-language enforcement coverage lives in `tests/database/test_character_language_integrity.py`, while reverse-dependency and concurrency coverage lives in `tests/database/test_world_ruleset_dependency_and_concurrency.py`: a character may know languages from one or several allowed ruleset families; a language from a disallowed family is rejected on both insert and update (the update case proven via a `SAVEPOINT` to show the existing row is unchanged); removing or repointing an allow-list association a character's language depends on is rejected; and two-connection tests prove character-language creation blocks both concurrent removal and concurrent repointing. The concurrency teardown also normalizes its generated ruleset code consistently, so those test rulesets are removed rather than left for the ephemeral-database drop.

Also fixed a pre-existing test that the new enforcement correctly broke: `test_character_shared_data.py::test_a_character_may_know_more_than_one_language` built its languages from a bare `make_ruleset_version()` (no world association), which the new trigger now — correctly — rejects. Changed to `make_ruleset_version_for_world()`, matching how every other rule-content fixture in that world already provisions content.

Verified the same way as the prior closeout passes: full `downgrade base` → `upgrade head` round trip (through all 37 revisions) against a throwaway database on the deployed AWS `dev` instance, `alembic check` clean (confirmed only after adding the table-comment update above — the first pass correctly caught the comment-only drift between `tables.py` and the live schema), `ruff format --check`/`ruff check`/`mypy src` clean, seed idempotency green, and the full suite — 858 tests (up from 847) — green against AWS `dev`.

The push-triggered GitHub Actions workflow independently confirmed that result in
run [`30776286733`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30776286733):
migration through revision 037, full downgrade/upgrade round trip, seed verification,
`alembic check`, formatting, Ruff, mypy, all 858 tests, database removal, and
ingress revocation passed.

## Outstanding

Carried forward, still open:

- **Orphaned KMS key** (`5a359a0a-4d30-4c00-925f-2dfad6e5820d`) from the Phase 1 teardown.
- **No `CREATEDB`-capable test role.** The ephemeral-database mechanism works today via the RDS master user (proven repeatedly, including throughout this corrections review); a dedicated, narrower login role is still worth adding before running it unattended in prod-adjacent environments — see [INFRASTRUCTURE.md §11 item 8](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies).
- **`iam_auth_db_users` duplicates the login-role list** in `001_bootstrap.py`.
- **No remote Terraform state**, and `staging`/`prod` unbuilt.

Phase 4 is complete; [PHASE4_REMAINING_ISSUES.md](PHASE4_REMAINING_ISSUES.md) is a closed historical record. Phase 5 (Locations and dungeon play) is also complete, including its formal-verification closeout — see [PHASE5_VERIFICATION.md](PHASE5_VERIFICATION.md) ([PHASE5_REMAINING_ISSUES.md](PHASE5_REMAINING_ISSUES.md) is now a closed historical record). Both the Phase 6 repository-context modularization gate and the Phase 5 formal-correctness gate are closed; Phase 6 is current.
