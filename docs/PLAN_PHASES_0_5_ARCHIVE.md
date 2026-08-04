# Archived Delivery Plans: Phases 0–5

These completed-phase plans were moved out of the active delivery plan to reduce routine context loading. They remain the historical statement of deliverables, exit criteria, and first-time obligations. Verification files are the source of evidence for what actually ran.

### Phase 0: Documentation and decision records

Deliver:

- `docs/PLAN.md`
- `docs/DOMAIN_MODEL.md`
- `docs/DATABASE_CONVENTIONS.md`
- `docs/ENTITY_LIFECYCLE.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`, `DATABASE_MODEL.md`, `DUNGEON_FLOW.md`
- `docs/DEVELOPMENT.md` — toolchain, repository layout, migration and test workflow
- `docs/INFRASTRUCTURE.md` — operating the deployed infrastructure
- later entity relationship diagrams
- command/API specifications
- state-resolution specification
- AI mutation-policy specification
- `docs/adr/` records extracted from [§2](PLAN.md#2-architectural-decisions) (currently stubs)

Exit criteria:

- Major domain boundaries agreed.
- Naming and inheritance strategy agreed.
- Timeline semantics agreed.
- Toolchain and repository layout decided, so implementation does not have to invent them.

### Phase 1: Database bootstrap

Deliver:

- PostgreSQL project structure
- migration framework
- schemas
- extensions
- shared domains
- seed infrastructure
- CI migration validation
- AWS infrastructure to host and reach the database (see [§29](PLAN.md#29-aws-terraform-deployment-plan-for-postgresql))

Exit criteria:

- Empty database can be created reproducibly.
- Migrations can run up and down in development.
- Schema validation runs in CI.
- A migration can be applied end-to-end against a deployed AWS RDS instance using only Terraform-managed infrastructure (no manual console steps).

**Complete.** All four criteria closed with live-AWS evidence; see [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md) for what was verified, the six defects that verification uncovered, and what remains outstanding. The step-by-step walkthrough — project skeleton, Alembic scaffold, bootstrap revision, shared domains, seed infrastructure, CI — is kept in [DEVELOPMENT.md §5](DEVELOPMENT.md#5-phase-1-walkthrough-complete) as the reference every later phase builds on.

### Phase 2: Core world platform

Deliver:

- worlds
- entity types
- entities
- names
- sources
- statuses
- tags
- calendars and world times
- users and basic security
- audit log

The table list is [§4.3](PLAN.md#43-foundation-tables); the canon statuses to seed are [§4.4](PLAN.md#44-canon-lifecycle); provenance requirements are [§4.5](PLAN.md#45-provenance).

Exit criteria:

- A world and an arbitrary entity can be created with provenance — the entity references a source, a canon status, and a lifecycle status, and `audit.change_log` records the creation.
- Creating an entity whose `entity_type_id` does not match its world, or whose canon status is not a seeded value, is rejected by the database, with a negative test proving it.
- `app_read_write` can read and write every table this phase creates; `app_read_only` can read them and is refused on write. Verified by connecting as those roles — not by reading grant statements.
- Re-running the phase's seeds produces no change: same rows, same values, no error. The seed-idempotency CI step is wired up and green.
- Every new table and non-obvious column carries a comment, and every foreign key is indexed.

First-time obligations (per [§23.1](PLAN.md#231-phase-exit-review)):

- **First phase to create tables**, so the first real test of the ownership chain in [ADR 0009](adr/0009-separate-owning-role-from-login-roles.md). `ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner` has never actually fired — Phase 1 created the entries but no tables to apply them to. If `SET ROLE migration_owner` is not holding, the tables come out owned by the connecting user and the application roles receive nothing. **This fails silently**: migrations succeed, tests using the admin connection pass, and only the application notices, much later. The third exit criterion above is what catches it, and it is the single most important check in this phase.
- **First phase to seed real lookup content**, so `apply_seed()` executes for the first time. It was rewritten during Phase 1 (bound parameters, JSON adaptation) but never once run. The seed-idempotency CI step deferred in [DEVELOPMENT.md §8](DEVELOPMENT.md#8-continuous-integration) comes due here.
- **Establishes the class-table inheritance root.** `core.entities` is the parent every later subtype hangs off, so the PK/FK pattern chosen here propagates to Phases 4, 5, 8, and 9. Note that Phase 2 delivers no subtypes of its own — the mechanism can be built and unit-tested here, but it is not fully exercised until Phase 4 (see that phase's first-time obligations).
- **First use of `audit.change_log`.** Phase 2 only needs creation events recorded; the causal-event rule (rule 6 in [CLAUDE.md](../CLAUDE.md#5-non-negotiable-architectural-rules)) is not fully exercised until Phase 6.

### Phase 3: Timelines and campaigns

Deliver:

- timelines
- campaign branching metadata
- campaigns
- parties
- memberships
- sessions
- timeline scoping for entity names, carried forward from Phase 2

Exit criteria:

- Two campaigns can share one timeline.
- A timeline can branch from another timeline. A root has neither a parent nor a branch point; in Phase 3, a branch requires both a parent and a branch world time.
- A world cannot have two primary timelines at once, and a branch cannot belong to a different world than its parent — each rejected by the database, each with a negative test.
- An entity name may remain world-global or be scoped to a same-world timeline; a cross-world timeline reference is rejected by the database.
- Party membership is timeline-scoped: a membership written to one sibling branch does not create a raw membership row in the other.
- A party membership cannot overlap itself within the same timeline and party. Negative tests cover bounded and open-ended overlaps; positive tests prove that adjacent `[from, to)` periods and a later return after a gap are accepted.
- Membership endpoints from the wrong world and intervals whose end is not later than their start are rejected by the database.
- Branch structure is verified in this phase; inherited-history isolation is explicitly recorded as unverified until Phase 6 supplies events and the effective-history query.

First-time obligations (per [§23.1](PLAN.md#231-phase-exit-review)):

- **First use of an exclusion constraint.** [§5.4](PLAN.md#54-parties), [DATABASE_CONVENTIONS.md §12.5](DATABASE_CONVENTIONS.md#125-overlap-prevention), and [ADR 0010](adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md) define the exact key and range semantics. PostgreSQL cannot build it without **`btree_gist`**; the revision that adds the constraint must enable the extension first and its downgrade must remove only objects the revision owns safely.
- **First forward references that must be deferred.** `campaign.timelines` wants an optional branch *event* ([§5.2](PLAN.md#52-timelines)) and `campaign.campaigns` a selected ruleset ([§5.3](PLAN.md#53-campaigns)), but `narrative.events` arrives in Phase 6 and `rules.rulesets` in Phase 4. Follow the precedent Phase 2 set with `worlds.default_calendar_id`: omit the column rather than adding an unconstrained UUID, and let the phase that creates the target table add the column together with its foreign key.
- **Close Phase 2's entity-name deferral.** Add optional timeline scoping to `core.entity_names` now that `campaign.timelines` exists, with a same-world guard and negative test. Global names keep a `NULL timeline_id`; do not force every existing name into the primary timeline.
- **Party membership has no character table to point at.** `character.characters` does not exist until Phase 4. Characters are entities, so membership can reference `core.entities` directly — but that means the database cannot yet tell a character from a location, and the check that a member is actually a character belongs with Phase 4.
- **Branch isolation cannot be fully proven here.** Rule 7 in [CLAUDE.md](../CLAUDE.md#5-non-negotiable-architectural-rules) — a timeline inherits parent history only up to its branch point — is the reason branching exists, but there is no history to inherit until events land in Phase 6. Phase 3 can prove the *structure* (a branch records its parent and branch point, and the world-agreement rule holds); it cannot prove the *isolation*. Say so rather than marking the criterion met, and see Phase 6.
- **Branch-point checks split across phases.** Phase 3 uses a trigger to enforce the parent/branch-time pairing and same-world rules because those compare across rows and tables. Validation against parent events and the actual no-leakage history query remain Phase 6 obligations; there are no events with which to prove either one here.

### Phase 4: Rules and shared characters

Deliver:

- initial D&D ruleset definitions
- deferred world-default and campaign-selected ruleset foreign keys
- characters
- NPCs
- PCs
- builds
- abilities
- classes
- proficiencies
- combat state
- conditions
- resources

Exit criteria:

- NPC and PC use the same mechanical model.
- A character sheet can be assembled from structured data.
- A subtype row cannot exist without its parent `core.entities` row, cannot use a primary key of its own, and cannot attach to a parent of the wrong entity type — each rejected by the database, each with a negative test.

First-time obligations (per [§23.1](PLAN.md#231-phase-exit-review)):

- **First real class-table inheritance subtypes** (`character.characters` → `character.npcs` / `character.player_characters`), so this is where the mechanism Phase 2 could only build in the abstract is actually exercised. Phase 2's "entity subtype consistency is enforceable" claim is only fully settled here. Get it right before Phases 5, 8, and 9 inherit the pattern.
- **Close the ruleset forward references.** Add `core.worlds.default_ruleset_id` (deferred in Phase 2) and `campaign.campaigns.ruleset_id` (deferred in Phase 3) together with real foreign keys and same-scope validation. Do not leave either as an unconstrained UUID.
- **Close Phase 3's temporary party-member reference.** Add database enforcement that every existing and new `campaign.party_memberships.member_entity_id` has a matching `character.characters` row. Include a negative test proving a location or other non-character entity cannot be a party member.
- **First substantial seed content** (the initial D&D ruleset), which is a much larger idempotency surface than Phase 2's lookup tables and the first seed data with real structure rather than flat codes.

**Corrections review.** A post-exit review of the initial Phase 4 schema found several integrity gaps: `campaign.sessions` had no derived fictional-time range; `character.character_builds.is_current` was a single global flag that could not represent a character built differently on two timelines after a branch; rule-content tables lacked the canon/provenance metadata §16 of [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) requires; several ruleset-version cross-references (classes/primary ability, features/class-subclass-species, spells/damage type, and every build-scoped association) were unenforced; `rules.world_rulesets.is_default` and `core.worlds.default_ruleset_id` could disagree; parent-scope identity columns (`core.world_times.sort_key`, `core.entities.world_id`, and similar) had no protection against being changed out from under already-valid children; and revision 022's seed content had no reproducibility guarantee against a later edit of its own YAML inputs. Eight forward-only revisions (023–030) plus a frozen-content manifest closed that initial set; see [PHASE4_VERIFICATION.md](PHASE4_VERIFICATION.md) for the full account and `tests/database/test_phase4_corrections.py` / `tests/database/test_seed_idempotency.py` for the tests.

**Closeout.** A review of the final revision-030 state found additional integrity, metadata, provenance-policy, and CI-cleanup defects. Revisions 031–034 closed those original findings; see [PHASE4_VERIFICATION.md § Closeout](PHASE4_VERIFICATION.md#closeout-2026-08-02) for the account. A subsequent review of revision 034 found one concurrency race, incomplete identity-immutability coverage, and three verification gaps, closed by revisions 035–036; see [PHASE4_VERIFICATION.md § Second closeout](PHASE4_VERIFICATION.md#second-closeout-2026-08-02). A review of revision 036 then found that character languages bypassed the world's ruleset allow-list plus three focused verification gaps, closed by revision 037 and its associated tests; see [PHASE4_VERIFICATION.md § Third closeout](PHASE4_VERIFICATION.md#third-closeout-2026-08-02). Phase 4 is complete.

### Phase 5: Locations and dungeon play

Deliver:

- locations
- dungeons
- areas
- connections
- features
- hazards
- interactables
- location and feature state
- discovery records

Exit criteria:

- A party can enter and navigate a multi-room dungeon.
- Hidden connections remain distinct from party knowledge.
- Actions can alter dungeon state.

First-time obligations (per [PLAN.md §23.1](PLAN.md#231-phase-exit-review)):

- **Close Phase 4's character-location forward references.** Add `character.characters.origin_location_id` (deferred in Phase 4 — [DATABASE_MODEL.md §7.1](architecture/DATABASE_MODEL.md#71-shared-character-definition) already names "origin" as part of the target model) and `campaign.character_location_history` (deferred in Phase 4's [PLAN.md §7.3](PLAN.md#73-timeline-state)), both with real foreign keys to `world.locations` now that it exists. Neither had anything to reference before this phase.

**Discovery records pulled the knowledge domain forward.** This phase's "discovery records" deliverable and its "hidden connections remain distinct from party knowledge" exit criterion turned out to depend on `knowledge.knowledge_items`/`knowledge.party_discoveries`, which [DATABASE_MODEL.md §23](architecture/DATABASE_MODEL.md#23-implementation-order) places after locations, interactions/events, and quests — normally Phase 7's job. Rather than invent a smaller Phase-5-only discovery table, `knowledge.knowledge_items`, `knowledge.entity_knowledge`, and `knowledge.party_discoveries` were built now using their documented Phase 7 shape; `knowledge.knowledge_versions`, `information_transfers`, `expertise_domains`/`character_expertise`, and `public_knowledge` remain deferred to Phase 7, which should treat the three pulled-forward tables as already delivered rather than re-designing them. See [DATABASE_MODEL.md §26](architecture/DATABASE_MODEL.md#26-reconciliation-notes-phase-5) for the full account.

`world.area_spawn_definitions`, named above and in [DATABASE_MODEL.md §9.2](architecture/DATABASE_MODEL.md#92-dungeon-structure) (a prior revision), was **not built** — no creature-instance or stat-block model exists in this schema yet, and Phase 9 (encounters) is its natural owner. DATABASE_MODEL.md §9.2 has been corrected to match; this line records the correction.

**First exit review corrections.** Before merge, a review of the branch found the location-history table used a partial-unique-index shortcut instead of the full ADR 0010 interval contract (no overlap prevention, no ordering check), several revision-039 structural rules validated only at insert time and could be mutated into an invalid state afterward, two knowledge-domain world-time columns went unchecked, the five dungeon-state tables' `updated_at` columns had no maintenance trigger, the `realm` location kind from DOMAIN_MODEL.md §9.1 was missing, and conditional routes (named in this phase's own deliverable list) had not been implemented even descriptively. Five forward-only revisions (043–047) closed all of these without touching revisions 038–042; see [DATABASE_MODEL.md § First exit review corrections](architecture/DATABASE_MODEL.md#first-exit-review-corrections-2026-08-03) and [PHASE5_VERIFICATION.md](PHASE5_VERIFICATION.md) for the full account.

**Second exit review corrections.** A second pre-merge review, after the first pass had already gone CI-green, found that entity-type mutation was only guarded from the subtype side (nothing stopped retyping a dungeon away from `dungeon` while its `world.dungeon_areas` children remained), the containment-cycle check had no lock and so was not safe against two genuinely concurrent writers, `location_period` was never tightened to `NOT NULL` despite the derivation trigger already guaranteeing one, and the conditional-route columns permitted contradictory states (`is_conditional = true` with no description, or `false` with one). Four more revisions (048–051) addressed the ordinary tested cases without touching revisions 038–047; see [DATABASE_MODEL.md § Second exit review corrections](architecture/DATABASE_MODEL.md#second-exit-review-corrections-2026-08-03) and [PHASE5_VERIFICATION.md](PHASE5_VERIFICATION.md) for the recorded evidence.

**Third and fourth exit review corrections (post-merge).** PR #5 merged those revisions into `main`, and a post-merge review found that parent-side type checks were still racy against concurrent subtype/dungeon-area writes, the depth-limited containment walk could silently miss deep or pre-existing cycles, revision 050 asserted rather than backfilled populated revision-043 rows, and conditional-route "nonblank" validation trimmed only ordinary spaces. Three forward revisions (053–055) plus one narrowly scoped, explicitly documented migration-history exception (revision 052 spliced immediately before revision 050, requiring revision 050's `down_revision` to change; see revision 052's docstring) addressed those findings. PR #6 merged the pass at `7ae606c`, and GitHub Actions run [`30835071145`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30835071145) passed all 1,080 tests and migration checks. A fourth review then found the child-location side of dungeon-area creation versus direct `parent_location_id` changes still lacked a shared lock, while the existing concurrency tests did not prove that their original waiting statements resume and revalidate. Revision 056 added the missing child-location advisory lock, and the affected concurrency tests were rewritten (plus two new ones) to prove genuine resumption via a background thread and a `pg_stat_activity` lock-wait poll rather than a timeout-and-retry. See [PHASE5_VERIFICATION.md § Third exit review corrections](PHASE5_VERIFICATION.md#third-exit-review-corrections-2026-08-03) and [§ Fourth exit review corrections](PHASE5_VERIFICATION.md#fourth-exit-review-corrections-2026-08-03) for the full account. [PHASE5_REMAINING_ISSUES.md](PHASE5_REMAINING_ISSUES.md) is now a closed historical record; Phase 5 is complete.
