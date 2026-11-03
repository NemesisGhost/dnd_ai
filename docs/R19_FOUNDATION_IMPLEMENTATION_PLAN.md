# Phase 19 foundation implementation plan (R19-P0 to R19-P4)

**Status:** Proposed. This is the R19-P0 planning deliverable, dated 2026-11-02, prepared for independent architecture review. Nothing in it is implemented, and no checkpoint is complete.

**Branch:** `planning/r19-p0-architecture`, from `main` at `defe3f7`.

**Governing documents:** [PLANv2.md](PLANv2.md) §6.1, §8 (15H) and §12 (19.0–19.8), and the ADRs below.

**Architecture decisions (Proposed):**

- [ADR 0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md): shared actor identity, campaign control and authoring responsibility. Phase 15 owns implementation through P03-A/B/C.
- [ADR 0022](adr/0022-creature-templates-combatants-and-promotion.md): creature templates, encounter combatants and promotion.
- [ADR 0023](adr/0023-rules-engine-calculation-validation-and-source-authorization.md): rules engine, calculation, validation and source authorization.

**Labels used throughout:**

- **Existing** means verified in code at `defe3f7`.
- **Planned** means named in an earlier plan, but not built.
- **New** means proposed here.

**Audience:** independent reviewers, the owner, and the Claude Sonnet implementers of each checkpoint. Each checkpoint below is written so an implementer needs no further major architectural decision. Where a product policy is still open, the checkpoint names the register entry (§9) and its recommended default.

---

## 1. Decision traceability

| Owner decision | Where it is realised | Implementing checkpoint |
|---|---|---|
| 1. Campaign-based character control | ADR 0021 §2 (assignment rows in `security.membership_character_relationships`; `character.character_controllers` retired) | P03-B (Phase 15) = R19-P1 |
| 2. World authority owns canonical characters | ADR 0021 §3 (authoring responsibility, delegated authoring) and §4 (build scope and activation authority) | P03-C (Phase 15) = R19-P1; activation guard (Phase 15) |
| 3. Hybrid creature representation | ADR 0022 | R19-P2d (templates), R19-P4a (persistent creatures), R19-P4b (combatants and promotion) |
| 4. Rules-engine-neutral architecture | ADR 0023 §2 and §13 | R19-P3a, R19-P3f |
| 5. Versioned house-rule overrides and extensions | ADR 0023 §6 | R19-P2b, R19-P2c, R19-P3c |
| 6. Drafts with unsupported mechanics flagged | ADR 0023 §7 | R19-P3d |

### 1.1 Discrepancies found during the investigation

These were found while reviewing documentation against code. None of them is fixed by this plan; each is assigned to an owner.

| # | Discrepancy | Evidence | Disposition |
|---|---|---|---|
| X1 | `character.character_controllers` is documented as a table but was never built. | `DATABASE_MODEL.md` §7.3 and `DOMAIN_MODEL.md` §8.4. No table exists in `src/dnd_ai/persistence/tables/` or the migrations. | ADR 0021 §2.1 retires it. The docs are corrected with P03-B. |
| X2 | ADR 0020 decision 6 keeps player-character identity on campaign `canon.edit`, which conflicts with owner Decision 2. | `domain/record_authoring.py`, `CAMPAIGN_ORIGINATED_TYPES` | ADR 0021 §3.4 amends ADR 0020 through a compatibility migration. Owner decision OD-5 governs new characters. |
| X3 | Two campaigns may share a timeline and pin different ruleset versions, yet share one active build and one runtime state. | `campaign.campaigns.timeline_id` comment ("Not unique"); `campaign.character_state` is keyed by `(timeline_id, character_id)` | ADR 0021 §4 adds an activation guard. The engine reports `incompatible_ruleset_version`. OD-1 is open. |
| X4 | `activate_character_build` does not check that the build's ruleset version matches the activating campaign's. | `commands/character_builds.py` (`activate_character_build`) | Phase 15 adds a small guard; see §5.2. |
| X5 | Version-blind calculation: `supports_ruleset` gates on the family code only, so 2024 formulas would apply to a 2014 version. | `domain/character_calculations.py` | R19-P3a adds a per-version registry. |
| X6 | Seeded rules content records no license or origin. | `database/seeds/rules.*.yaml`, revision 022 | R19-P2a adds a provenance audit. OD-7. |
| X7 | PLANv2 19.5 lists an "initial subset" (ability modifiers, proficiency, skills, passives, spell DC/attack) that already exists as un-traced sheet formulas. | `queries/character_sheet.py` | R19-P3a ports these into the engine with parity tests. They are not new behaviour. |
| X8 | `maximum_hit_points` is an entered state value, not a derived one. | `campaign.character_state` | It is kept as authoritative state. The engine reports `declared_value_differs` and never overwrites it. |
| X9 | The P03 planning sources (the investigation and handoff) are untracked on this PC and not on `main`. | Working tree at `defe3f7` | PLANv2 §18 item 19. This plan cites them by file name only. |

---

## 2. Subsystem inventory

For each subsystem the table records what exists today, what is reused unchanged, what is extended additively, what is eventually migrated or retired, which checkpoint owns the change, and what consumes the resulting contract.

| Subsystem | Exists (verified) | Reuse unchanged | Additive extension | Migration or retirement | Owner checkpoint | Downstream consumers |
|---|---|---|---|---|---|---|
| Actor identity | `core.entities` → `character.characters`; `npcs` (`detail_level`) and `player_characters` (`player_user_id`) markers | Entity and character rows, UUIDs, CTI | — | Markers become compatibility hints; their optional retirement comes last (ADR 0021 §7) | P03-C | Every character consumer; Phase 16; Phase 19 creatures |
| Builds | Immutable `character_builds` plus 5e children; `create_character_build` / `activate_character_build`; active build in `campaign.character_state` | The immutability model, the timeline activation model, and the event on activation | `build_scope`, `origin_campaign_id`, `created_by_user_id` (P03-C); custom-mechanics, review and template-basis children (R19-P3d, P4a) | Backfill `legacy_unscoped`; `_BUILDABLE` kind list replaced by capability eligibility | P03-C (scope, authority); R19-P3d (drafts, reviews); R19-P4a (template basis) | Phase 16 editor; R19 engine; creatures |
| Runtime state | `campaign.character_state`, `character_conditions`, `character_resources` keyed by `(timeline_id, character_id)` | All of it | — | — | — | Engine (inputs); P03-B bounded operations |
| Relationships and access | `security.membership_character_relationships` (typed, fictional period, real-time revoke and expiry); `BUILTIN_RELATIONSHIP_CAPABILITIES`; `security.resource_grants`; reserved capability codes `character.control`, `edit_mechanical_state`, `edit_narrative`, `interact` | Table, resolver freshness, deny-over-allow | `is_control_assignment`, `campaign_id`, revocation provenance, primary-uniqueness exclusion; `CONTROL_ASSIGNMENT_CAPABILITIES`; new codes `character.assign_control`, `character.propose_build`, `character.reveal` | Legacy controller rows stay read-only; manifest-confirmed promotion only | P03-A (reveal), P03-B (control), P03-C (delegation) | Phase 16; R19 projection; encounters |
| Authoring authority | `record_authoring.py` with the `CAMPAIGN_ORIGINATED_TYPES` exception; world authority (ADR 0020) | World/campaign two-key rule | `character.character_authoring_responsibilities` | `player_character` removed from the exception via manifest | P03-C | All character authoring; R19-P3d approvals |
| Discovery and projection | Role, relationship and grant discovery; summary/full tiers; B1-1 encounter member projection | Tier resolver, B1-1 projection | Revelation record, public profile, controller view (investigation D6) | Legacy background quarantine | P03-A | R19 derived-value projection (ADR 0023 §9) |
| Portrayal | `npc_portrayal_profiles` → `npcs.npc_id` `ON DELETE CASCADE` | Append-only versions | `character_id` column | FK re-key, then drop the `npc_id` dependency | P03-C | Phase 20 |
| Session participation | `PARTICIPANT_KINDS = (player_character, npc)`; stored roles | Stored historical roles | — | Kind list replaced by capability eligibility | P03-C | Session UI; Phase 16 |
| Rules definitions | `rules.*` typed per-version tables, immutable identity, `source_id`, `canon_status_id`; 5e 2024 sample seed | Every table and its identity | `content_package_id` (P2a); prerequisites and exclusions (P2a schema, P4c use); creature templates (P2d) | Mechanical immutability for new mechanical fields | R19-P2 | Engine, Phase 16, Phase 18 |
| Rulesets and campaign pin | `rulesets`, `ruleset_versions`, `world_rulesets`; `campaigns.ruleset_version_id` | All of it | Option policy and configuration version (P2b) | — | R19-P2b | Catalog, engine |
| Item definitions and inventory | `rules.item_definitions` (`owning_world_id`, `row_version`, descriptive fields); `world.item_instances`; `campaign.item_state` / `inventory_entries` / `item_attunements`; `knowledge.item_identification` | All of it | Item mechanics payload and modifier references (P3e) | — | R19-P3e | Engine (equipment) |
| Calculations | `domain/character_calculations.py` (5e formulas, family gate); used by `queries/character_sheet.py` | Kept in place during the port; parity oracle | `domain/rules_engine/` core and 5e adapter (P3a) | The shim is retired after the sheet moves to the engine, after P03-A | R19-P3a/b | Sheet, previews, analysis, AI |
| Encounters | `narrative.encounters`, `encounter_participants` (entity NOT NULL, unique per encounter), rounds, turns (by participant id), `interaction.combat_actions` and `targets`; Foundry sync by entity | Rows, commands, Foundry contract, B1-1 projection | Combatant columns, combatant state, target participant column (P4b) | `participant_entity_id` nullable | R19-P4b (with Phase 15 encounter-owner review) | Encounter analysis; Phase 21 Foundry |
| Reference corpus | `core.source_documents` (rights flags, `general` / `campaign_restricted`), `ai.reference_source_campaigns`, `rules_source.manage` | All of it | `contributor_private` visibility and owner (OD-12; Phase 18 or 20) | — | Phase 18/20 (not R19-P2) | Phase 20 retrieval |
| Proposals | `ai.proposed_changes` / `ai.change_reviews` (AI only) | Unchanged | Build drafts use their own table (ADR 0023 §7); AI later proposes drafts | — | R19-P3d | Phase 18, Phase 20 |
| Migrations and tests | Alembic `NNN_name.py` (latest `140_clock_advance_details`); `tests/unit`, `tests/database`, `tests/scenario` | Conventions | — | — | Every checkpoint | — |

---

## 3. Sequencing and parallel-work categories

The categories are those of PLANv2 §6.1:

- **Category 1:** may begin now.
- **Category 2:** may merge as isolated, compatible infrastructure.
- **Category 3:** cannot ship or be accepted until its dependencies are met.

```text
R19-P0 (this plan + ADRs 0021–0023) ── review/acceptance
   │
   ├─ R19-P2a provenance ─┐
   ├─ R19-P3a engine core ┼─ R19-P3b context/catalog ─ R19-P2b options ─ R19-P2c house rules ─ R19-P3c conditions/overrides
   │                      └─ R19-P2d creature templates ──────────────────────────────────────────────┐
   │                                                                                                   │
   │   Phase 15: P03-A ── P03-B ── P03-C (= R19-P1)                                                     │
   │                          │        │                                                               │
   │                          │        └── R19-P3d drafts/reviews (merge needs build-command owner sign-off; rebase after P03-C)
   │                          └────────── R19-P3e equipment + audience mode (audience path needs P03-A projections)
   │                                       R19-P3f contract freeze + neutrality fake adapter
   │
   Phase 16 (consumes P03-B/C, R19-P3d/P3f) ── Phase 17 gate ── R19-P4a–g
```

### 3.1 Safe to start now, while P03 is underway

These are category 1, and category 2 once merged. Each touches no file that P03 is expected to touch.

- R19-P2a: content provenance and packages. New `rules` tables and columns only.
- R19-P3a: engine core and 5e adapter port. Pure new modules; no existing file is modified.
- R19-P3b: context loader, catalog resolver, a GM-only explanation endpoint and the support endpoint. New query and API modules; `character_sheet.py` is not modified.
- R19-P2b: option policy. New tables, with one guarded change to build validation that needs build-command owner sign-off.
- R19-P2c: house rules.
- R19-P3c: conditions and override evaluation.
- R19-P2d: creature template definitions.

### 3.2 Waits for P03-A, P03-B or P03-C

- **R19-P3d (build drafts, reviews and custom mechanics).** Design and implementation may start. Merge needs build-command owner sign-off and must rebase onto P03-C's `character_builds.py` changes if those are in flight. Delegated *player* drafting is enabled only after P03-B/C (`character.propose_build`); until then drafts are GM-only.
- **R19-P3e audience mode.** It needs P03-A's projection contract. The truth-mode equipment work may merge earlier.
- **Moving the character sheet onto the engine** (shim retirement) waits for P03-A to settle the sheet projection.
- **Every R19-P4 item** that reads control, authoring responsibility or build scope.

### 3.3 Waits for Phase 17

All of R19-P4: template-basis persistent creatures, encounter combatants and promotion, advancement, expanded open-content packages, encounter analysis, Phase 19 portal workflows and end-to-end acceptance. PLANv2 §6 and 17.4 still apply.

---

## 4. Conventions every checkpoint follows

- **Layering.** Pure domain lives in `src/dnd_ai/domain/rules_engine/`. Queries go in `src/dnd_ai/queries/`, commands in `src/dnd_ai/commands/` (the only writers) and thin routers in `src/dnd_ai/api/` (`SYSTEM_ARCHITECTURE.md` §5).
- **Migrations.** Use the next free `NNN_` number at merge time; never reuse a number. If the primary PC has merged migrations meanwhile, rebase and renumber before merge. Every revision follows `DATABASE_CONVENTIONS.md` §25 (docstring with purpose, rollback, data implications, locking) and §19 (an index for every FK) and §20 (constraints), uses lookup tables over enums, and is schema-qualified with no `public`.
- **Commands.** They follow PLANv2 §3.1 and §17: actor and capability, scope binding, lock order, durable idempotency for retryable creates and transitions, audit through `audit_initial` / `audit_change` (never narrative content), and non-disclosing errors (`SafeMessageError` subclasses).
- **Tests.**
  - `tests/unit/` holds pure policy and engine tests.
  - `tests/database/` holds command and query, constraint, migration and API tests.
  - `tests/scenario/` holds cross-domain flows.
  - Every checkpoint runs `ruff format`, `ruff check`, `mypy src`, its focused tests, the full suites (or the `verify-local` skill), migration up/down/up, and final-head CI. Test the smallest production invariant (CLAUDE.md §7.9).
- **Documentation.** Each checkpoint updates `DATABASE_MODEL.md`, `DOMAIN_MODEL.md` and `ENTITY_LIFECYCLE.md` for what it builds, marking items **Built** only when merged.
- **Review.** Each checkpoint is one reviewable PR to `main` (or to an integration branch the owner names), with the exact parent and target SHAs, scope, contracts, known limits and evidence.

---

## 5. Integration contracts

Each contract below is a stable boundary that other phases consume without knowing its implementation. Its owner changes it only by an ADR amendment or a reviewed contract-version bump.

### 5.1 Character and actor contract (owner: Phase 15, P03-A/B/C)

**Dependencies:** ADR 0020 and ADR 0021.

**Boundary:** a domain function and query module, proposed as `dnd_ai.domain.actor_contract` plus `dnd_ai.queries.actor_contract`. Exact names are P03's choice; R19 code depends only on these signatures.

| Element | Contract |
|---|---|
| Stable identity | `actor_id: UUID` (= `character_id`), world id, lifecycle status. Never changes through control, kind, promotion or template. |
| Optional build | `active_build(timeline_id, character_id) -> BuildRef \| None` with `ruleset_version_id`, `build_scope`, `origin_campaign_id`. `None` is a supported state. |
| Campaign control | `control_state(campaign_id, character_id, at=effective clock) -> ControlState` with `primary`, `co_controllers[]` and `gm_operated: bool`. `may_operate(access, character_id, operation_code) -> bool`, rechecked under the caller's lock. |
| Authoring responsibility | `authoring_responsibility(character_id) -> {kind, campaign_id?}`; `record_authoring(...)` extended to consult it. |
| Eligible operations | A closed `CONTROLLER_OPERATIONS` allow-list (P03-B, OD-3); each operation names its capability and its lock. |
| Visibility and projection | `projection_tier(access, character_id) -> {none, public_profile, controller, gm}` (P03-A). It feeds ADR 0023 `mode` selection. |
| Runtime state references | State row tokens (`last_event_id`) for `character_state`, `character_conditions` and `character_resources` on the campaign timeline. |

**Compatibility:** legacy `/npcs` and `/player-characters` payloads keep working through adapters, and legacy relationship rows keep their current capabilities.

**Acceptance tests:**

- One UUID through control change, multi-campaign control, a monster with no build, co-controller revocation, independent-grant survival, whole-character deny, and mechanics not leaking for a hidden character.
- All of the above for scenarios T1–T7 in §8.
- Old-route compatibility tests.

### 5.2 Character authoring and validation contract (owners: Phase 15 for the build command family; Phase 16 for player submission; Phase 19 for drafts, validation and review)

**Dependencies:** ADR 0021 §3–4, ADR 0023 §7, the R19-P3a engine and P03-C build scope.

| Element | Contract |
|---|---|
| Build draft | `create_build_draft`, `update_build_draft(expected_row_version)`, `withdraw_build_draft` over `character.character_build_drafts`. The payload is the adapter-schema JSON (`build_payload.v1` for 5e mirrors `BuildInput`). |
| Proposed change | A draft in status `submitted`. The proposer is GM (`canon.edit`) or delegated player (`character.propose_build`, after P03-B/C). |
| Preview | `POST /campaigns/{c}/characters/{ch}/build-drafts/{d}/validate` and `POST /campaigns/{c}/characters/{ch}/mechanics/preview` (unsaved payload). Both return a `ValidationReport` plus an `EvaluationResult`, with `authority: informational`. They make no write, except storing `last_validation_jsonb` on the draft when the draft is validated. |
| Mechanical validation | ADR 0023 statuses `valid` / `invalid` / `incomplete` / `unsupported` / `conflicting`; legacy builds are `not_evaluated`. |
| Approval | `approve_build_draft(decision, adjudications[], reason?)`. It re-validates under lock, records `character.character_build_reviews`, and calls `create_character_build` in the same transaction. `reject_build_draft(reason)`. |
| Activation | `activate_character_build` only. It gains the ruleset-version guard (X4) and the build-scope rule (ADR 0021 §4). |
| Audit and history | Draft creation, submission, decision and activation are audited. Reviews are append-only. Drafts are never deleted by validation. |

**Compatibility:**

- `create_character_build`'s existing signature and behaviour stay valid. The new optional parameters are `custom_mechanics`, `adjudicated_refs` and `build_scope`, all defaulting to today's behaviour.
- The existing GM direct-create route (`POST …/builds`) stays.

**Acceptance tests:**

- T15, T16 and T20 (§8).
- A GM direct-create parity test.
- Invalid builds cannot be approved without `approved_as_rules_exception` and a reason.
- A delegated player cannot approve.

### 5.3 Creature contract (owner: Phase 19)

**Dependencies:** ADR 0022, the P2d schema, P03-C build scope, and the Phase 15 encounter commands.

| Element | Contract |
|---|---|
| Template definition | `rules.creature_templates`, with world homebrew or a content package. Commands: `create_creature_template`, `archive_creature_template`. |
| Template version | `create_template_version(draft)`, `update_template_version(draft, expected_row_version)`, `publish_template_version` (draft → canon, which makes it immutable). Adapter-validated `mechanics_jsonb` plus typed references. |
| Lightweight combatant | `add_encounter_combatants(encounter, template_version, count, label_prefix, side, overrides?)` (P4b); addressed by `encounter_participant_id`. |
| Persistent instance | A character with a template-basis build (`create_character_build(template_basis=…)`), P4a. |
| Overrides | Adapter-schema JSON recorded on the combatant or the template-basis build; trace status `declared`. |
| Promotion | `promote_encounter_combatant` (P4b), with the ADR 0022 §6 semantics. |

**Compatibility:** entity-addressed encounter APIs are unchanged, and the Foundry sync refuses combatants explicitly.

**Acceptance tests:** T9–T12 (§8), plus the B1-1 member-projection negative tests extended to combatants.

### 5.4 Rules calculation contract (owner: Phase 19)

**Dependencies:** ADR 0023 §2–5 and §10.

| Element | Contract |
|---|---|
| Evaluation context | `RulesContext`, `EvaluationRequest` (ADR 0023 §5). |
| Ruleset-specific adapter | `RulesAdapter` protocol plus the closed `registry.py`; `support(ruleset_version)`. |
| Inputs and dependency resolution | `queries.rules_context.load_bundle(connection, request, access)` returns a projection-scoped `InputBundle`; `queries.rules_catalog.eligible_catalog(...)`. |
| Structured results | `EvaluationResult` / `DerivedValue` / `Finding`, serialized as `rules_result.v1` JSON. |
| Derivation trace | `TraceStep` with `DefinitionRef` (id plus version token). |
| Unsupported or incomplete | Explicit statuses; never omitted, never zero. |

**Compatibility:** the JSON schema is versioned (`rules_result.v1`). Additive fields are allowed; renames need `v2`.

**Acceptance tests:** determinism (shuffled inputs give an identical result and fingerprint), the neutrality guard (§6, R19-P3f), parity with `character_calculations.py`, T13, T14, T18, T19 and T20.

### 5.5 Source and permission contract (shared coordination: Phase 19 for option policy and catalog; Phase 18/20 for the corpus; Phase 15 for authority)

**Dependencies:** ADR 0023 §9, ADR 0020 and ADR 0021.

| Decision | API and domain boundary |
|---|---|
| Source access | The existing corpus endpoints and capability `rules_source.manage` / `campaign.view`; the future `contributor_private` visibility (OD-12) |
| Retrieval and use | Existing `allow_*` flags, and Phase 20 purpose rules |
| Campaign option eligibility | `queries.rules_catalog.option_permitted(campaign, ref)`; commands `set_campaign_option_policy` and `add_option_entry` / `remove_option_entry` (P2b) |
| Validation authority | Adapter support level plus the catalog |
| Approval | Review records plus ADR 0021 authority |

**Compatibility:** the default option mode is `all_canon`, which is today's behaviour.

**Acceptance tests:**

- T17, a player-owned source whose text is not shared.
- A permitted option exposes no source text.
- A denied option is refused at draft validation with `option_not_permitted`, and at direct create with the existing non-disclosing `build_option_not_available`.
- Each decision is tested with the other four held fixed.

---

## 6. Checkpoints

Each checkpoint lists the same 16 fields:

1. Objective and outcome
2. Prerequisites
3. Existing modules
4. New or modified modules
5. Schema changes
6. API and command contracts
7. Authorization
8. Migration strategy
9. Backward compatibility
10. Automated tests
11. Manual acceptance
12. Performance
13. Rollback
14. Branch dependencies
15. Completion criteria
16. Start / merge / ship

### R19-P0 — Architecture and contracts (this deliverable)

1. **Objective and outcome:** accepted ADRs 0021–0023 and this plan. Implementers then make no further major architectural decision.
2. **Prerequisites:** PLANv2 `defe3f7`.
3. **Existing modules:** none modified.
4. **New or modified modules:** three ADRs and this plan.
5. **Schema changes:** none.
6. **API and command contracts:** §5 of this plan.
7. **Authorization:** none.
8. **Migration strategy:** none.
9. **Backward compatibility:** not applicable.
10. **Automated tests:** none. Run the documentation link and table check.
11. **Manual acceptance:** independent architecture review, then owner decisions on OD-1 to OD-16.
12. **Performance:** not applicable.
13. **Rollback:** revert the documentation commit.
14. **Branch dependencies:** none.
15. **Completion criteria:**
    - The ADRs are accepted, or amended per review.
    - Owner decisions are recorded in each ADR's status line.
    - The planning branch is merged to `main` by the owner.
    - The primary PC acknowledges ADR 0021.
16. **Start / merge / ship:** start now; merge after review.

### R19-P1 — Shared actor foundation (Phase 15 P03-A/B/C; listed here only as Phase 19's dependency)

1. **Objective and outcome:** ADR 0021 is implemented, so Phase 19 can rely on the §5.1 contract.
2. **Prerequisites:** ADR 0021 accepted; P02 navigation; DEF-007 no-clock decision (OD-14).
3. **Existing modules:** see ADR 0021 Context.
4. **New or modified modules (owned by P03):**
   - **P03-A:** revelation record, public-profile release, the shared discovery predicate, B1-1 follow-ups.
   - **P03-B:** assignment columns, exclusion constraint, `CONTROL_ASSIGNMENT_CAPABILITIES`, `assign_character_control` / `revoke_character_control`, the bounded operations allow-list.
   - **P03-C:** authoring responsibilities table, the `record_authoring` change, build scope columns, portrayal re-key, kind-to-capability eligibility, manifest, adapters.
5. **Schema changes:** as listed in ADR 0021 §2.2–2.3, §3.3, §4 and §6.
6. **API and command contracts:** §5.1.
7. **Authorization:** ADR 0021 §2.7–2.10 and §3.5.
8. **Migration strategy:** ADR 0021 §7 (manifest, additive first, compare effective access on a restored copy).
9. **Backward compatibility:** legacy routes, payloads and relationship capabilities are preserved.
10. **Automated tests:** T1–T7 and T21 (§8), plus P03's own matrix (investigation D6.4/D6.8).
11. **Manual acceptance:** the corrected Sella/F4 scenario; a player-controlled monster; the same actor under two controllers in two campaigns.
12. **Performance:** discovery predicates must stay SQL-filtered before counting and pagination.
13. **Rollback:** additive migrations have working downgrades until marker or portrayal FK retirement, which is backup-gated.
14. **Branch dependencies:** the primary PC's Phase 14/15 stream.
15. **Completion criteria:** PLANv2 15.9's 15H criterion.
16. **Start / merge / ship:** Phase 15 owns the timing. R19 must not implement any of it.

**Small Phase 15 fix that R19 needs early (X4):** in `activate_character_build`, reject a build whose `ruleset_version_id` ≠ the activating campaign's pinned version. Use a new `SafeMessageError` such as `build_ruleset_mismatch` (400). Add a database test: create campaigns A (2024) and B (a different version) on one timeline, then show that activating A's build from B is refused. Phase 15 owns it; it may land with P03-C or earlier.

### R19-P2a — Rules content provenance and packages

1. **Objective and outcome:** every rules definition can state its origin and license, and Phase 17 gains a concept for optional content packages. Developers can answer "where did this definition come from, and may we redistribute it?" from data.
2. **Prerequisites:** ADR 0023 accepted (§4). OD-7 is answered for the baseline package's license; until then the backfill uses license `unreviewed`.
3. **Existing modules:**
   - `src/dnd_ai/persistence/tables/rules.py`
   - `database/migrations/versions/022_seed_initial_ruleset.py`, `033_*`, `036_*`
   - `src/dnd_ai/persistence/seeds.py`
   - `tests/database/test_ruleset_provenance.py`
4. **New or modified modules:**
   - New migration `NNN_rules_content_packages.py`.
   - Table metadata in `persistence/tables/rules.py`.
   - Seed lookups `database/seeds/rules.content_origins.yaml` and `rules.content_licenses.yaml`.
   - New query `queries/rules_provenance.py`.
   - Read endpoint in `api/rulesets.py`: `GET /rulesets/{rv}/content-packages`, authenticated (`campaign.view` in any campaign on that version) or system admin.
   - An audit report `docs/R19_SEED_CONTENT_PROVENANCE_AUDIT.md`, which records what the seed contains and why its origin is believed to be what it is.
5. **Schema changes:**
   - Lookups `rules.content_origins` (`open_content`, `system_baseline`, `homebrew_world`, `gm_custom`, `licensed`) and `rules.content_licenses` (`unreviewed`, `cc_by_4_0`, `ogl_1_0a`, `proprietary_licensed`, `homebrew_private`, `public_domain`), each with code, name and description.
   - `rules.content_packages`, as in ADR 0023 §4; unique `(ruleset_version_id, code)`.
   - Nullable `content_package_id UUID` FK (`ON DELETE RESTRICT`), with an index, on `rules.abilities`, `skills`, `species`, `classes`, `subclasses`, `features`, `feats`, `spells`, `conditions`, `creature_types`, `damage_types`, `languages`, `proficiency_types`, `resource_definitions` and `item_definitions`.
   - It is immutable once set, using the existing `core.enforce_immutable_columns()`.
   - A trigger enforces that the package's `ruleset_version_id` equals the row's version, or the version of its class or subclass parent for subclasses and features.
6. **API and command contracts:** read-only in this checkpoint. Package installation commands come with Phase 17 packaging (§7.3).
7. **Authorization:** reading package metadata is non-sensitive (titles, licenses), so any authenticated user with a campaign on that ruleset version may read it. No writes.
8. **Migration strategy:**
   - Create the lookups and the table.
   - Insert one package `dnd5e-2024-baseline` (origin `system_baseline`, license `unreviewed`).
   - Backfill `content_package_id` on every existing ruleset-wide row of that version.
   - World-owned homebrew item definitions stay NULL.
   - The migration is idempotent and runs in one transaction. Tables are small, so there is no batching.
9. **Backward compatibility:** columns are nullable, and no reader requires them. Build and sheet behaviour is unchanged.
10. **Automated tests:**
    - Migration up/down/up.
    - Backfill counts equal row counts per table.
    - The version-mismatch trigger refuses a cross-version package.
    - The column is immutable.
    - A homebrew item definition is allowed with NULL.
    - The seeds unit test covers the new lookups.
    - The endpoint is denied to an outsider and returns the baseline package.
11. **Manual acceptance:** an operator reads the baseline package and its license `unreviewed` from the API. The owner reviews the provenance audit document.
12. **Performance:** negligible; one indexed FK per table.
13. **Rollback:** the downgrade drops the columns, table and lookups. No data loss beyond the provenance itself.
14. **Branch dependencies:** none. It touches no P03 file.
15. **Completion criteria:** every ruleset-wide definition has a package. The audit document is reviewed. `DATABASE_MODEL.md` §8 is updated to mark these **Built**.
16. **Start / merge / ship:** start now (category 1) and merge independently (category 2). There is no user-facing feature.

### R19-P3a — Engine contracts, registry and the 5e adapter (pure)

1. **Objective and outcome:** the neutral core types and the deterministic composition exist, and a 5e adapter reproduces today's sheet formulas with a full trace and per-version support. Developers get a tested, pure API for later checkpoints.
2. **Prerequisites:** ADR 0023 accepted (§2, §3, §5, §10).
3. **Existing modules:**
   - `domain/character_calculations.py` (the parity oracle; **not modified**)
   - `queries/character_sheet.py` (read only, to understand inputs)
4. **New or modified modules:**
   - `src/dnd_ai/domain/rules_engine/__init__.py`
   - `contracts.py`: dataclasses, enums and protocols
   - `composition.py`: ordering, conflict detection, application
   - `validation.py`: `Finding` and `ValidationReport` aggregation
   - `fingerprint.py`: canonical JSON and SHA-256
   - `registry.py`: closed registry and support per version
   - `adapters/__init__.py`
   - `adapters/dnd5e.py`: keys `ability_modifier.<code>`, `total_level`, `proficiency_bonus`, `skill.<code>`, `passive.<code>`, `saving_throw.<code>`, `spell_attack_bonus.<profile>`, `spell_save_dc.<profile>`. Override points are declared but unused until P3c.
   - `adapters/schemas/dnd5e_build_payload_v1.py`, a Pydantic model mirroring `BuildInput`.
5. **Schema changes:** none.
6. **API and command contracts:** Python API only (§5.4). Serialization `rules_result.v1` lives in `contracts.py` (`to_json()`).
7. **Authorization:** none. The engine is pure, and callers authorize.
8. **Migration strategy:** none.
9. **Backward compatibility:** no existing file changes. The sheet is unchanged.
10. **Automated tests (`tests/unit/`):**
    - `test_rules_engine_composition.py`: layer order, stable sort, `set` conflicts produce `conflicting` with no value, and `declared` handling.
    - `test_rules_engine_determinism.py`: 200 random permutations of the same contributions give an identical result and fingerprint.
    - `test_rules_engine_fingerprint.py`: canonical JSON is key-order independent, and a changed token changes the fingerprint.
    - `test_rules_engine_registry.py`: `dnd5e`/2024 is `calculating`; `dnd5e`/2014 and an unknown family are `none`; an unknown version produces no values.
    - `test_dnd5e_adapter_parity.py`: table-driven against `character_calculations` across scores 1–30, levels 1–20, and proficiency/expertise combinations.
    - `test_dnd5e_adapter_missing_inputs.py`: no class levels gives `proficiency_bonus` the status `missing_input`, and a missing ability makes dependants `missing_input`.
    - `test_rules_engine_neutrality.py` (the neutrality guard): a static check that no file under `rules_engine/` outside `adapters/` contains the tokens `proficien`, `armor_class`, `class_level`, `spell_slot`, `challenge_rating`, `hit_die` or `dnd5e`; and that `contracts.py` imports nothing from `adapters`.
11. **Manual acceptance:** a reviewer reads one trace JSON for a fixture build and confirms that each value cites its build rows.
12. **Performance:** the pure functions run in microseconds. The fingerprint uses `hashlib` only.
13. **Rollback:** delete the new package. Nothing depends on it yet.
14. **Branch dependencies:** none.
15. **Completion criteria:**
    - The tests above pass and `mypy` is strict-clean for the package.
    - Parity is 100% over the table.
    - ADR 0023 is marked "P3a built" in its status line.
16. **Start / merge / ship:** start now; merge independently. There is no user-facing feature.

### R19-P3b — Context loader, catalog resolver, explanation and support endpoints

1. **Objective and outcome:** given a campaign and a character, the server loads a batched, authorized input bundle, evaluates it, and returns values with an explanation to GMs. Every member can see the campaign's rules support level, so UIs can stop guessing.
2. **Prerequisites:** P3a. P2a is optional; package refs are included when present.
3. **Existing modules:**
   - `queries/character_build_resolution.py` (active build resolution)
   - `queries/character_sheet.py` (input query patterns; **not modified**)
   - `api/access.py` (`require_campaign_capability`)
   - `api/character_builds.py` (for route style)
4. **New or modified modules:**
   - `queries/rules_context.py`: `load_bundle()`, one round trip per family, covering build children, state and condition rows with tokens, and the ruleset version.
   - `queries/rules_catalog.py`: `eligible_catalog()` (version, canon, world homebrew); the option-policy hook is a no-op until P2b.
   - `api/rules_mechanics.py`:
     - `GET /campaigns/{c}/characters/{ch}/mechanics?keys=` requires `canon.edit` and uses `mode=truth`. It returns `rules_result.v1`; 404 when the character is not visible to the caller (existing non-disclosing resolution).
     - `GET /campaigns/{c}/rules/support` requires `campaign.view` and returns `{ruleset_code, version_label, support_level, adapter_version, outputs[]}`.
   - Register the router in `api/app.py`.
5. **Schema changes:** none.
6. **API and command contracts:** as above. The responses are versioned JSON.
7. **Authorization:** mechanics require `canon.edit`. This is deliberately GM-only until P03-A's projection tiers exist; P3e adds the audience mode. Support data is campaign-level metadata.
8. **Migration strategy:** none.
9. **Backward compatibility:** these are new routes only.
10. **Automated tests (`tests/database/`):**
    - `test_rules_context_loader.py`: correct tokens; a character with no active build returns `missing_input` for build-dependent keys and is not an error; a character on a different timeline cannot be loaded through this campaign.
    - `test_api_rules_mechanics.py`:
      - a GM gets values and a trace;
      - a player gets 403/404 (non-disclosing);
      - another campaign's character gets 404;
      - an archived character follows existing lifecycle reads;
      - the result equals the sheet's derived fields for the same fixture (parity);
      - an unsupported ruleset version returns `support: none` and no values.
    - `test_api_rules_support.py`.
    - A query-count assertion that `load_bundle` issues at most N statements, with N fixed per family.
11. **Manual acceptance:** a GM opens the endpoint for a fixture fighter and confirms the explanation is readable. A player is refused.
12. **Performance:** target p95 under 50 ms for one character on local PostgreSQL 18, recorded in the PR. No list endpoint calls the engine.
13. **Rollback:** remove the router. Nothing persisted.
14. **Branch dependencies:** none. `character_sheet.py` is untouched to avoid colliding with P03-A.
15. **Completion criteria:** tests and parity pass; the endpoints are documented in `DATABASE_MODEL.md` and the API docs section; ADR 0023 status is updated.
16. **Start / merge / ship:** start after P3a; merge independently (category 2). GM-only API, with no portal UI.

### R19-P2b — Campaign option policy and rules configuration version

1. **Objective and outcome:** a GM can restrict which definitions a campaign permits. Every rules-configuration change bumps a version that fingerprints include. The default preserves today's behaviour.
2. **Prerequisites:** P3b (catalog hook); P2a recommended for package-level entries. The owner decides OD-8 (default `all_canon`) and OD-10 (`canon.edit` to configure).
3. **Existing modules:**
   - `commands/character_builds.py` (`_validate_rules` / `_require_in_ruleset`)
   - `api/character_builds.py` (`build_options_endpoint`)
   - `persistence/tables/campaign.py`
4. **New or modified modules:**
   - Migration `NNN_campaign_rule_options.py`.
   - Tables in `persistence/tables/campaign.py`.
   - `commands/rules_configuration.py`: `set_campaign_option_mode`, `add_campaign_option_entry`, `remove_campaign_option_entry`, and the internal `bump_rules_configuration`.
   - `queries/rules_catalog.py`: `option_permitted()` and `permitted_options()`.
   - `api/rules_configuration.py`.
   - **Coordinated change:** `commands/character_builds._validate_rules` refuses non-permitted options with the existing `BuildOptionNotAvailableError`, and `build_options_endpoint` filters by policy. Both are no-ops in `all_canon` mode.
5. **Schema changes:**
   - `campaign.campaign_rules_configurations` (`campaign_id` PK/FK, `configuration_version BIGINT NOT NULL DEFAULT 1`, `updated_at`).
   - `campaign.campaign_rule_option_policies` (`campaign_id` PK/FK, `mode_code` FK to lookup `campaign.rule_option_modes` with `all_canon` / `allow_list`, `updated_by_user_id`, `updated_at`).
   - `campaign.campaign_rule_option_entries`:
     - `campaign_rule_option_entry_id`, `campaign_id`;
     - `effect_code` (`allow` / `deny`, lookup);
     - typed target FKs, exactly one set: `class_id`, `subclass_id`, `species_id`, `feat_id`, `spell_id`, `feature_id`, `item_definition_id`, `content_package_id`. `creature_template_id` is added by P2d;
     - `created_by_user_id`, `created_at`, `removed_at`, `removed_by_user_id`.

     It has a CHECK for exactly one target, a trigger requiring the target's ruleset version to equal the campaign's pin, and a unique partial index of live entries per target.
   - The migration backfills one configuration and one policy (`all_canon`) row per existing campaign. Campaign creation inserts both (a `commands/campaigns.py` change, coordinated with Phase 14 ownership).
6. **API and command contracts:**
   - `GET /campaigns/{c}/rules/configuration` (members): mode, live entries, version, and the house rules once P2c lands.
   - `PUT …/rules/option-policy {mode, expected_configuration_version}`.
   - `POST` and `DELETE …/rules/option-entries`.
   - Writes are idempotent (`Idempotency-Key`) and stale-checked against `expected_configuration_version`, under a campaign-row lock.
7. **Authorization:** writes need campaign `canon.edit` (OD-10). Reads need `campaign.view`; entries name definitions that are already visible in build options.
8. **Migration strategy:** an additive backfill, so existing campaigns behave identically.
9. **Backward compatibility:** in `all_canon` mode, `_validate_rules` and build options behave exactly as before. A parity test runs the existing build tests unchanged.
10. **Automated tests:**
    - Policy CRUD with stale and idempotent replay.
    - Allow-list mode permits only listed items.
    - Deny beats allow.
    - A package-level allow combined with an item-level deny.
    - A cross-version target is refused.
    - Direct build create with a denied option is refused, non-disclosing.
    - Draft validation shows `option_not_permitted` (after P3d).
    - The configuration version bumps exactly once per change, and not on replay.
    - The existing `test_character_builds.py` and `test_api_character_builds.py` pass unchanged.
11. **Manual acceptance:** a GM restricts the campaign to one class; build options show only that class; a second campaign on the same world is unaffected (T8).
12. **Performance:** `permitted_options` is a single query using the partial index.
13. **Rollback:** the downgrade drops the tables. The guarded code paths treat a missing policy as `all_canon` during the deploy window.
14. **Branch dependencies:** the `character_builds.py` change needs **Phase 15 build-command owner sign-off**. If P03-C is editing that file, land P2b's two-line guard after P03-C or coordinate a joint rebase.
15. **Completion criteria:** tests pass, owner sign-off on the build-command touch, and documentation updated.
16. **Start / merge / ship:** start now; merge as category 2 because default behaviour is unchanged. Portal UI comes with R19-P4f.

### R19-P2c — House rules

1. **Objective and outcome:** GMs record versioned house rules (override, extension or unevaluated) and adopt them explicitly with deterministic precedence. Unresolved conflicts are visible.
2. **Prerequisites:** P3a (override-point registry and payload schemas) and P2b (configuration version). OD-10 is decided.
3. **Existing modules:** `persistence/tables/rules.py`, `persistence/tables/campaign.py`, `domain/record_authoring.py` (world authority for world-scoped house rules), `domain/world_authority.py`.
4. **New or modified modules:**
   - Migration `NNN_house_rules.py`.
   - Tables.
   - `domain/house_rules.py` (pure: kind rules, conflict detection).
   - `commands/house_rules.py`: `create_house_rule`, `create_house_rule_version` (draft), `update_house_rule_version(expected_row_version)`, `publish_house_rule_version`, `adopt_house_rule_version`, `retire_house_rule_adoption`, `reorder_house_rule_adoptions`, `acknowledge_house_rule_conflict`.
   - `queries/house_rules.py`: the active set and conflicts.
   - API routes in `api/rules_configuration.py`.
   - The 5e adapter declares override points `dnd5e.hit_points_per_level`, `dnd5e.ability_score_generation` and `dnd5e.exhaustion_model`, with Pydantic parameter schemas.
5. **Schema changes:** as ADR 0023 §6 describes.
   - Lookups `rules.house_rule_kinds` and `rules.house_rule_scopes`.
   - `rules.house_rules` with `owning_world_id NOT NULL`. A CHECK makes `campaign_id` required for campaign scope; a trigger requires the campaign to belong to the world.
   - `rules.house_rule_versions` with `row_version`. An immutability trigger applies when the canon status is canon.
   - `campaign.campaign_house_rule_adoptions` with a partial unique index `(campaign_id, precedence) WHERE retired_at IS NULL`. A trigger requires version parity with the campaign's pinned version and a canon version.
6. **API and command contracts:**
   - `GET /campaigns/{c}/rules/house-rules` (members; `gm_notes` stripped unless `canon.edit`).
   - `POST …/house-rules`.
   - `POST …/house-rules/{h}/versions`.
   - `PATCH …/versions/{v}`.
   - `POST …/versions/{v}/publish`.
   - `POST …/rules/adoptions`.
   - `DELETE …/rules/adoptions/{a}`.
   - `PUT …/rules/adoptions/order`.

   Each adoption change bumps the configuration version in the same transaction.
7. **Authorization:**
   - Campaign scope: `canon.edit` to author, publish and adopt.
   - World scope: world `world.canon.edit` to author, `world.canon.review` to publish, plus campaign `canon.edit` on the route (ADR 0020 decision 6).
   - Adoption into a campaign: that campaign's `canon.edit`.
8. **Migration strategy:** new tables only.
9. **Backward compatibility:** no adoptions means today's behaviour.
10. **Automated tests:**
    - Override parameters are validated against the adapter schema; an invalid one is refused, and an unknown override point is refused for kind `override`.
    - An `unevaluated` version accepts text only.
    - A canon version is immutable.
    - Adopting a draft is refused.
    - Precedence is unique.
    - Two overrides of the same point without acknowledgement are listed as a conflict; with acknowledgement they are not.
    - A world rule cannot be adopted by another world's campaign.
    - Retirement keeps history.
    - Each change bumps the configuration version once.
    - Writes are concurrency-safe (two concurrent adoptions at the same precedence: one wins and one gets a stale or conflict error).
    - Players see the description without GM notes.
11. **Manual acceptance:** a GM adopts "average HP" and then a conflicting "max HP at level 1". The configuration page lists the conflict until it is acknowledged.
12. **Performance:** the active set is one indexed query per campaign.
13. **Rollback:** the downgrade drops the tables.
14. **Branch dependencies:** none with P03.
15. **Completion criteria:** T13 and T14 pass at the data layer (their evaluation half lands in P3c), and documentation is updated.
16. **Start / merge / ship:** start after P3a and P2b; merge as category 2.

### R19-P3c — Runtime conditions, exhaustion and override evaluation (5e subset)

1. **Objective and outcome:** the engine applies seeded conditions, exhaustion (version-specific) and adopted override points, with explanation. Hit-point maximum becomes derivable, and it is reported against the stored value without replacing it.
2. **Prerequisites:** P3b and P2c.
3. **Existing modules:**
   - `campaign.character_state.exhaustion_level`
   - `campaign.character_conditions`
   - the seeded conditions (`blinded` … `unconscious`)
   - `rules.classes.hit_die`
4. **New or modified modules:**
   - The 5e adapter adds contributions for conditions as `enum` roll-mode keys (`dnd5e.attack_roll_mode`, `dnd5e.ability_check_mode`, `dnd5e.saving_throw_mode.<ability>`, `dnd5e.speed_zero`).
   - Exhaustion under the `exhaustion_model` override point, defaulting to `2024_d20_penalty` for 2024: d20 tests −2 × level, speed −5 ft × level.
   - `dnd5e.hit_point_maximum` from class hit dice, the CON modifier and the `hit_points_per_level` parameter.
   - `rules_context.load_bundle` adds the house-rule adoptions and conditions.
   - Unknown or unseeded conditions on a character are reported `unsupported`.
5. **Schema changes:** none.
6. **API and command contracts:** the existing mechanics endpoint gains these keys, and the result schema stays `v1`.
7. **Authorization:** unchanged (GM truth mode).
8. **Migration strategy:** none.
9. **Backward compatibility:** the sheet is unaffected.
10. **Automated tests:**
    - Each seeded condition's mapping.
    - Exhaustion levels 0–6 under 2024.
    - A 2014 version is `none`.
    - Adopted `average` versus default.
    - Unacknowledged conflicting overrides make HP `conflicting` with both candidates.
    - An `unevaluated` house rule naming `dnd5e.critical_damage` makes that key `unsupported`.
    - A `declared_value_differs` finding is raised when stored max HP differs.
    - Determinism, and T13, T14 and T19.
11. **Manual acceptance:** the ADR 0023 §12 worked example is reproduced on a fixture, apart from the equipment part, which is P3e.
12. **Performance:** unchanged.
13. **Rollback:** revert the adapter code.
14. **Branch dependencies:** none.
15. **Completion criteria:** the tests pass, and the adapter version is bumped.
16. **Start / merge / ship:** category 2.

### R19-P2d — Creature template definitions

1. **Objective and outcome:** a GM can author world-homebrew creature templates with immutable published versions. The engine can evaluate a template version for informational GM use. There are no instances or encounter integration yet.
2. **Prerequisites:** ADR 0022 accepted, P3a, and P2a (packages).
3. **Existing modules:** `rules.creature_types`, the `rules.item_definitions` homebrew precedent (`commands/item_definitions.py`, `domain/item_definition_authoring.py`), and `domain/record_authoring.py`.
4. **New or modified modules:**
   - Migration `NNN_creature_templates.py`.
   - Tables.
   - `domain/creature_template_authoring.py`.
   - `commands/creature_templates.py`.
   - `queries/creature_templates.py`.
   - `api/creature_template_authoring.py`.
   - The 5e adapter adds the schema `dnd5e_creature_mechanics.v1`: ability scores, armor value with its source note, hit-point formula and average, speed, saves, skills, damage resistances, immunities and vulnerabilities, condition immunities, senses, languages, challenge/XP as adapter keys, traits and actions as **text plus optional structured attack entries** (bonus, damage dice, damage type). Its outputs are `dnd5e.creature.*`.
   - The option-entry target `creature_template_id` is added to P2b's table.
5. **Schema changes:** as ADR 0022 §2 describes.
   - `rules.creature_templates` with world homebrew (`owning_world_id NOT NULL` in this checkpoint, because ruleset-wide templates arrive only through packages in P4d) and `row_version`.
   - `rules.creature_template_versions` with a draft-mutable, canon-immutable trigger.
   - `rules.creature_template_version_references` with typed FKs, an at-most-one check and a same-version trigger.
6. **API and command contracts:**
   - `POST /campaigns/{c}/creature-templates`.
   - `POST …/{t}/versions`.
   - `PATCH …/versions/{v}` (draft, `expected_row_version`).
   - `POST …/versions/{v}/publish`.
   - `POST …/{t}/archive`.
   - `GET …/creature-templates` (GM).
   - `GET …/versions/{v}/mechanics` (an engine result, `informational`).

   Validation uses the shared `ValidationReport`. An unknown schema can be saved as a draft but cannot be published as validated; a publish with non-`valid` overall requires `approved_with_adjudication` and a reason (ADR 0023 §7 semantics).
7. **Authorization:** authoring a template is world canon. It needs world `world.canon.edit` (draft) and `world.canon.review` (publish), plus campaign `canon.edit` on the route, through `record_authoring` exactly like other world definitions. Players: no access (a GM projection only).
8. **Migration strategy:** new tables.
9. **Backward compatibility:** none affected.
10. **Automated tests:**
    - Lifecycle and immutability.
    - A version pinned to the campaign's ruleset version.
    - The reference table enforces FKs, and JSON references missing from it are refused.
    - Another world's template is invisible and non-disclosing.
    - Every payload field is checked against the adapter schema.
    - A player is denied.
    - Engine evaluation of a goblin-like fixture yields the expected values with a trace.
    - Publishing v2 leaves v1 unchanged (the T9 data half).
11. **Manual acceptance:** a GM creates "Goblin", publishes v1, edits a draft v2 and publishes it, and v1 remains readable.
12. **Performance:** small.
13. **Rollback:** the downgrade drops the tables while no P4 consumer exists.
14. **Branch dependencies:** none with P03.
15. **Completion criteria:** the tests pass, and ADR 0022 status records "P2d built".
16. **Start / merge / ship:** category 2, an API without portal UI. Do not advertise creature authoring before R19-P4.

### R19-P3d — Validation report, build drafts, review and custom mechanics

1. **Objective and outcome:** one draft, validate, submit and review workflow for character builds. It is usable now by GMs, and later by delegated players (Phase 16), imports (Phase 18) and AI (Phase 20). Unsupported content is stored and adjudicated without being misreported as validated.
2. **Prerequisites:**
   - P3b and P2b.
   - ADR 0021 accepted, for build authority and scope.
   - **Build-command owner (Phase 15) sign-off on the `create_character_build` extension.**
   - OD-9 is decided.
3. **Existing modules:**
   - `commands/character_builds.py`, `domain/character_builds.py` (`BuildInput`, `normalize_build`), `api/character_builds.py`
   - `domain/data_classification.py` (audit)
   - the idempotency machinery
4. **New or modified modules:**
   - Migration `NNN_character_build_drafts_and_reviews.py`.
   - `domain/build_drafts.py`: status transitions, adjudication rules, the effective-state policy table.
   - `commands/build_drafts.py`: `create_build_draft`, `update_build_draft`, `submit_build_draft`, `withdraw_build_draft`, `approve_build_draft`, `reject_build_draft`.
   - `queries/build_drafts.py`.
   - `api/build_drafts.py`.
   - **Coordinated extension:** `create_character_build(…, custom_mechanics=(), adjudicated_refs=frozenset())`. Both are optional and preserve existing behaviour. `adjudicated_refs` lets an approved reference that is not canon in the catalog pass only when the review names it; otherwise `_require_in_ruleset` is unchanged.
   - P03-C later adds `build_scope` to the same function, so this checkpoint does **not** add scope columns.
5. **Schema changes:** as ADR 0023 §7 describes.
   - `character.character_build_drafts`: status lookup `character.build_draft_statuses`, `payload_jsonb` with `payload_schema_version`, `row_version`, `last_validation_jsonb`, `last_validation_fingerprint`. The campaign must be on the character's world (trigger).
   - `character.character_build_reviews`: append-only trigger, decision lookup `character.build_review_decisions`, validation outcome lookup `character.validation_outcomes` (`valid`, `invalid`, `incomplete`, `unsupported`, `conflicting`).
   - `character.character_build_custom_mechanics`: immutable with the build; support status lookup.
6. **API and command contracts** (all under `/campaigns/{c}/characters/{ch}/`):
   - `POST …/build-drafts`
   - `PATCH …/build-drafts/{d}`
   - `POST …/build-drafts/{d}/validate`
   - `POST …/build-drafts/{d}/submit`
   - `POST …/build-drafts/{d}/withdraw`
   - `POST …/build-drafts/{d}/approve {decision, adjudications[{finding_code, subject_path, note}], reason}`
   - `POST …/build-drafts/{d}/reject`
   - `GET …/build-drafts`
   - `GET …/builds/{b}/review`

   Creates and transitions are idempotent and stale-checked.
7. **Authorization:**
   - **This checkpoint:** create, edit and submit need `canon.edit`. Approval needs `canon.edit`, plus world `world.canon.edit` when the resulting build is world-shared (after P03-C; before P03-C every approved build is created exactly as today's direct create, `legacy_unscoped`).
   - **After P03-B/C (Phase 16 enables it):** a delegated `character.propose_build` holder may create, edit, submit and withdraw only their own drafts for that character in that campaign. They may never approve. `approved_as_rules_exception` is never available to a delegated proposer.
   - Draft reads are limited to the author and `canon.edit` holders.
8. **Migration strategy:** new tables only. Existing builds have no review and read as `not_evaluated`.
9. **Backward compatibility:** the GM direct-create route is unchanged. The `create_character_build` defaults reproduce today's behaviour, and the existing build tests run unchanged.
10. **Automated tests:**
    - Status machine.
    - Failed validation never deletes or rewrites draft content.
    - Approval re-validates under lock; a stale draft (changed since validation) re-validates and uses the new report.
    - `incomplete` or `unsupported` drafts cannot be approved as plain `approved`.
    - `invalid` needs `approved_as_rules_exception` and a reason.
    - Custom mechanics persist on the build with their support status.
    - The review record keeps findings after approval: approval does not upgrade them (T16).
    - Activating an approved build works through `activate_character_build`.
    - Idempotent replays.
    - Concurrent approve and withdraw: one wins.
    - A non-author player cannot read a draft.
    - Audit rows contain no payload content.
    - The legacy build reads as `not_evaluated`.
11. **Manual acceptance:** a GM drafts a build with one custom feature, sees `unsupported`, approves it with adjudication, activates it, and the explanation shows the feature as `declared` or `unsupported` (T15 and T16, GM half).
12. **Performance:** validation is one bundle load; the draft payload is bounded (`MAX_*` from `domain/character_builds.py`).
13. **Rollback:** the downgrade drops the tables while no review exists. After that, restore from backup, because reviews are history.
14. **Branch dependencies:** **coordinate with P03-C** on `commands/character_builds.py`. If P03-C is in flight, rebase after its build-scope change and pass `build_scope` through.
15. **Completion criteria:** tests pass, owner sign-off, and §5.2 is documented as the Phase 16 contract.
16. **Start / merge / ship:** start now. Merge after sign-off as category 2 (a GM API). Player use is Phase 16 (category 3 until P03-B/C and Phase 16 acceptance).

### R19-P3e — Equipment modifiers and audience-mode evaluation

1. **Objective and outcome:** armor, shields and simple item modifiers contribute to derived values. Controllers can receive derived values computed only from what they may see.
2. **Prerequisites:**
   - P3c.
   - P03-A projection tiers, for the audience half only.
   - `knowledge.item_identification` semantics are confirmed with the item-domain owner.
3. **Existing modules:**
   - `rules.item_definitions`, `campaign.item_state` (`equipped`), `campaign.inventory_entries`, `campaign.item_attunements`
   - `knowledge.item_identification`
   - `queries/inventory.py` (restricted projection)
4. **New or modified modules:**
   - Migration `NNN_item_definition_mechanics.py`.
   - 5e adapter schema `dnd5e_item_mechanics.v1` (armor category, base value, dexterity cap, shield bonus, flat bonuses to declared keys, attunement requirement).
   - `commands/item_definitions.py` validates mechanics on homebrew create and update, with draft-only mutability of mechanics.
   - `rules_context` loads equipped and attuned items with tokens.
   - Audience-mode bundle building in `queries/rules_context.py`.
   - `api/rules_mechanics.py` adds `mode=audience` for a controller (P03-B) or a `character.view_full` holder.
5. **Schema changes:** `rules.item_definitions` gains `mechanics_schema_code`, `mechanics_schema_version` and `mechanics_jsonb` (nullable), plus `rules.item_definition_mechanic_references` (typed). A trigger makes the mechanics columns immutable once the canon status is canon. Descriptive columns stay editable (ADR 0023 §4).
6. **API and command contracts:** item-definition authoring accepts optional `mechanics`. Mechanics `mode=audience` is available to non-GMs.
7. **Authorization:** truth mode stays GM-only. Audience mode builds its bundle only from the viewer's visible inputs. Unidentified properties and GM-hidden effects are excluded before evaluation, without any marker of exclusion.
8. **Migration strategy:** additive columns. Existing items have no mechanics and contribute nothing. An equipped item without mechanics raises an `item_without_mechanics` warning finding, in truth mode only. The engine never infers mechanics from an item's name.
9. **Backward compatibility:** existing item authoring is unchanged when mechanics are omitted.
10. **Automated tests:**
    - AC from armor plus shield plus a feature (the ADR 0023 §12 example).
    - Unequipped items do not contribute.
    - Attunement-required items contribute only when attuned.
    - Canon mechanics are immutable.
    - **T7 leak test:** a hidden cursed item lowers truth AC, while audience-mode AC excludes it and the response contains no trace ref, count or flag revealing it.
    - A hidden character's mechanics are not returned to a player at all.
    - Fingerprint changes on equip and unequip.
11. **Manual acceptance:** the full worked example, and a controller view (after P03-B).
12. **Performance:** one inventory query per bundle.
13. **Rollback:** the downgrade drops the columns while they are unused.
14. **Branch dependencies:** the audience half waits for P03-A/B merges; the truth half can merge before.
15. **Completion criteria:** tests pass, and the leak tests are reviewed by an independent reviewer.
16. **Start / merge / ship:** the truth half is category 2; the audience half is category 3 until P03-A is accepted.

### R19-P3f — Contract freeze, neutrality proof, and the Phase 16 consumer guide

1. **Objective and outcome:** the validation-preview and evaluation contracts are frozen as versioned schemas that Phase 16 can build on. Neutrality is demonstrated by a test-only adapter.
2. **Prerequisites:** P3d. P3e is recommended.
3. **Existing modules:** the engine, the drafts.
4. **New or modified modules:**
   - `tests/unit/rules_engine_fixtures/percentile_adapter.py`, a **test-only** fake adapter implementing the ADR 0023 §13 archetype keys: `pct.skill.*`, `pct.hit_points`, `pct.damage_bonus` (dice) and a `pct.experience_check` advancement offer.
   - `tests/unit/test_rules_engine_second_archetype.py`.
   - JSON Schema exports `docs/schemas/rules_result.v1.json` and `validation_report.v1.json`, generated from the Pydantic models, with a test that fails on drift.
   - `POST /campaigns/{c}/characters/{ch}/mechanics/preview` (unsaved payload, informational) if P3d did not already add it.
   - `docs/R19_PHASE16_CONSUMER_GUIDE.md`, a short guide: which endpoints, statuses and capabilities to call, and what the UI must label.
5. **Schema changes:** none.
6. **API and command contracts:** frozen `v1`.
7. **Authorization:** as in P3d/P3e.
8. **Migration strategy:** none.
9. **Backward compatibility:** a contract test pins `v1`.
10. **Automated tests:**
    - The fake adapter registers *only in tests* and composes with the same core.
    - A build bundle with no class levels, no armor class and no proficiency evaluates.
    - The advancement offer has no level concept.
    - Dice-valued outputs serialize.
    - The JSON Schema drift test.
11. **Manual acceptance:** the Phase 16 lead reviews the consumer guide.
12. **Performance:** not applicable.
13. **Rollback:** not applicable.
14. **Branch dependencies:** none.
15. **Completion criteria:** contract tests pass, and the guide is accepted.
16. **Start / merge / ship:** category 2. This closes the early R19-P3 foundation.

### R19-P4 — Full Phase 19 delivery (after the Phase 17 gate)

Each item below is planned in detail when Phase 17 closes, re-using this plan's template. The contracts are fixed by ADRs 0021–0023.

| Item | Scope | Key dependencies | Notes |
|---|---|---|---|
| **P4a** Persistent creatures | Template-basis builds (`character.character_build_template_bases`), creating creatures from templates, player-controlled creatures through P03-B assignments | P03-B/C, P2d, P3d | Extends `create_character_build` (`template_basis=`); T3 and T9 (persistent half) |
| **P4b** Encounter combatants | ADR 0022 §4–6: participant columns, combatant state and conditions, `target_encounter_participant_id`, spawning, promotion, member projection, the Foundry refusal path | Phase 15 encounter-owner review, P2d, P4a | T10, T11, T12; spawn limits of 50 per call and 200 participants per encounter (OD-15 may tune them) |
| **P4c** Advancement | `advancement_options` for 5e, structured prerequisites and exclusions (`rules.definition_prerequisites` / `rules.definition_exclusions`), the Phase 16 draft path, history and explanations | Phase 16 accepted, P3d/P3f | T15 (player half) |
| **P4d** Content packages | Installable open-content packages (SRD-licensed only after OD-7 review), the operator install command, Phase 17 packaging hooks | P2a, Phase 17 | No commercial ingestion without legal review |
| **P4e** Encounter analysis | Party-specific analysis (PLANv2 19.4) using engine results; GM-only; assumptions and uncertainty shown | P4a/P4b, P3e | Analysis snapshots store their fingerprint |
| **P4f** Portal | Rules configuration, house rules, option policy, template authoring, draft review queue, mechanics explanations, combatant tools | All of the above | Accessibility and responsiveness per PLANv2 §17.5 |
| **P4g** Acceptance | PLANv2 19.8 end-to-end scenarios; `docs/PHASE19_VERIFICATION.md` | All of the above | Phase 19 is complete only here |

---

## 7. Cross-phase analysis

### 7.1 Phase 15

- **P03-A.** It provides projection tiers, which R19-P3e's audience mode consumes, and the revelation predicates, which mechanics endpoints must respect: a player never receives derived values for a character they cannot discover. R19 adds no projection or discovery code of its own.
- **P03-B.** It provides control assignments and bounded operations. R19 consumes `may_operate` for controller audience views (P3e) and for player-controlled creatures (P4a). R19 must not add control rows or capabilities.
- **P03-C.** It provides authoring responsibility, build scope, kind-to-capability eligibility and the portrayal re-key. R19-P3d's approval passes `build_scope`. R19-P4a needs non-NPC/PC characters to be buildable.
- **Existing builds.** They stay immutable and unchanged. R19 adds reviews and custom mechanics alongside, and they read as `not_evaluated`.
- **Item and inventory authoring.** R19-P3e adds optional mechanics to item definitions. Instance commands are unchanged.
- **Encounter runtime.** Phase 15's encounter commands stay authoritative. R19-P4b extends them additively under owner review, and keeps entity addressing and the Foundry sync.
- **Historical migration safety.** R19 never rewrites builds, events, encounter rows or participation roles. Every R19 table is additive.

### 7.2 Phase 16

- **Player-owned build drafts.** These are P3d drafts created by a `character.propose_build` holder (ADR 0021 §3.5), with no separate builder.
- **Delegated authoring.** The capability and grant come from P03-C. The draft commands accept it once P03-C ships.
- **Validation previews.** The P3f-frozen endpoints. Phase 16 shows `support_level`, `overall` and findings verbatim.
- **GM approvals.** P3d `approve_build_draft` is the review queue. Phase 16 adds the portal queue view (or P4f if it comes later).
- **Unsupported manual mechanics.** Players may add custom entries to drafts. They stay `unsupported` until adjudicated, and are labeled.
- **Source access and permitted options.** The option policy (P2b) filters the choices the player sees. Source text is never shown through the builder.
- **Campaign-specific character state.** Players change only P03-B's bounded operations. Builds and state remain separate.
- **Phase 16 can proceed before Phase 19 completes.** It needs only P03-B/C plus P3d/P3f. Without P3f, Phase 16 labels submissions "not validated" (PLANv2 16A).

### 7.3 Phase 17

- **Packaging.** No new service. The engine is in the API image.
- **Migrations.** Every R19 migration is additive and covered by Phase 17's upgrade, backup and restore verification (PLANv2 17.4).
- **Rules data initialization.** The baseline package from revision 022 plus P2a. Startup requires no other package.
- **Version compatibility.** The adapter version is reported by `/rules/support`. Upgrade notes list adapter version bumps.
- **Backup and restore.** House rules, policies, drafts, reviews and templates are ordinary tables and are included.
- **Optional rules content packages.** Installed by an operator command (P4d).
- **No startup dependency** on paid sourcebooks, AI services or external rules providers.

### 7.4 Phase 18

Imported rules content becomes **drafts**: creature-template drafts, house-rule drafts, build drafts and homebrew definition drafts, each with source provenance and import-batch metadata. It is validated by the same `ValidationReport` and promoted by the same approve and publish commands. Import never writes `rules.*` canon or builds directly. A reference passage never creates a definition (`PLAN.md` §6.1).

### 7.5 Phase 20

AI explanations use `EvaluationResult.trace` and cite its fingerprint and definition refs. AI retrieval goes through source decisions 1 and 2. AI may propose drafts, and the proposals carry the same validation. AI never computes or asserts a number that the engine did not produce. Audience-mode results are the only ones placed in a player-purpose context.

---

## 8. Acceptance and compatibility scenarios

The scenario labels used below are:

- **db:** a `tests/database` test
- **scen:** a `tests/scenario` test
- **man:** manual acceptance
- **unit:** a `tests/unit` test

| # | Scenario | Checkpoint | Layer | Key assertions (privilege escalation, disclosure, staleness, reproducibility, contamination) |
|---|---|---|---|---|
| T1 | One world character controlled by player P1 in campaign A and P2 in campaign B | P03-B | db + scen | One UUID. P1 cannot operate in B. Assignments are independent. Neither gains `canon.edit` |
| T2 | An NPC assigned to a player | P03-B | db | UUID, build, portrayal and history unchanged. The NPC marker remains. No perspective or secrets are gained without a separate grant |
| T3 | A player-controlled monster with no class or level | P03-B, P4a | db + man | Assignment works with no build, or with a template-basis build. The engine reports `missing_input` or computes from the template. There is no rejection by kind |
| T4 | A character without an active build | P3b | db | Mechanics endpoint returns `missing_input` statuses, not errors. The sheet is unchanged |
| T5 | A co-controller loses access | P03-B | db | The next read and write is refused, including an in-flight write that locks after revocation. The primary is unaffected |
| T6 | A controller is removed while another grant remains | P03-A/B | db | Viewer or revelation grants survive. Play operations are gone. The effective-access explanation shows the surviving source |
| T7 | A hidden character's mechanics must not leak | P03-A, P3b, P3e | db | A player gets 404 with no count or ID from the mechanics, sheet, roster and encounter reads. Audience mode excludes unidentified item effects without a marker |
| T8 | A world character with campaign-specific rules restrictions | P2b | db | Campaign A's allow-list blocks an option that campaign B permits. The world character is unchanged. B's builds are unaffected |
| T9 | A creature template is updated after instances exist | P2d, P4a/b | db | v1-pinned combatants and builds are unchanged. A "newer version" flag is shown. Re-pinning is explicit |
| T10 | Four unnamed goblins as lightweight combatants | P4b | db + man | Four participant rows, no `core.entities` rows, labels "Goblin 1–4", one spawn group. Members see only labels |
| T11 | One goblin promoted to a persistent character | P4b | db + man | A new character with a template-basis build and state copied by an event. `promoted_character_id` is set. Historical turns are unchanged. Promotion reveals nothing |
| T12 | A historical encounter stays reproducible after a template update | P4b | db | The encounter read shows the pinned v1 mechanics. Recorded combat actions are unchanged. Recomputation uses v1 |
| T13 | A house rule overrides a baseline calculation | P2c, P3c | db + unit | HP uses `average`. The trace cites the HR version. The fingerprint includes the configuration version |
| T14 | A second house rule conflicts with the first | P2c, P3c | db | The key is `conflicting` with both candidates. The configuration read lists the conflict. Acknowledgement resolves it deterministically |
| T15 | A player submits an unsupported advancement option | P3d, Phase 16, P4c | db + man | The draft is saved. Validation is `unsupported` with exact refs. The player cannot approve |
| T16 | A GM approves unsupported content without claiming automated validation | P3d | db | The review records `approved_with_adjudication`. Findings remain `unsupported`. Explanations show it as `declared` or `unsupported`. The build is never labeled validated |
| T17 | A player-owned reference source whose text is not shared | Phase 18/20 (OD-12), P2b | db | The source is visible only to its owner. A GM homebrew definition citing it shows mechanics only. Members cannot retrieve the passages |
| T18 | Two campaigns use different ruleset versions | P3b, Phase 15 X4 | db | Each evaluates under its own version. Activating an incompatible build is refused. On a shared timeline, the other campaign gets `incompatible_ruleset_version` |
| T19 | A non-D&D ruleset without classes or levels | P3a, P3f | unit | The fake adapter evaluates with core types only. A real unsupported ruleset reports `support: none` and no validated claims |
| T20 | An invalid or stale mechanical preview | P3d | db | Approving a draft changed after validation re-validates. A stale `row_version` is refused. A preview is never persisted as authoritative |
| T21 | A migration preserves legacy NPC portrayal, builds, history and UUIDs | P03-C | db + man (restored copy) | Entity counts and UUIDs are equal. Portrayal versions are re-keyed with chains intact. Builds and events are unchanged. Effective access before and after is compared, and differences are documented |

---

## 9. Outstanding decisions register

Owner decisions are product policy. Technical decisions are resolved here unless a reviewer objects. Each entry gives a recommended default, which implementation uses until the decision is recorded.

| ID | Decision | Type | Recommended default | Blocks |
|---|---|---|---|---|
| OD-1 | Campaigns sharing one timeline with different ruleset versions share one active build | Owner | Keep timeline-scoped activation, add the version guard (X4), and report `incompatible_ruleset_version`. Consider a campaign-scoped build selection only on demand | Nothing early; affects R19-P4 for shared timelines |
| OD-2 | Co-controller authority, and behaviour when the primary is revoked | Owner | Same bounded play operations as the primary; no assignment management; no perspective or build proposals unless separately granted; no auto-promotion | P03-B |
| OD-3 | The P03-B shipped controller operation allow-list | Owner (already open in the investigation, H) | HP and temporary HP, named resources, self-manageable conditions, equip/unequip and attune own items; no encounter actions initially | P03-B |
| OD-4 | Who holds `character.assign_control` | Owner | `campaign_owner` and `gm`; `assistant_gm` opt-in | P03-B |
| OD-5 | Retiring the PC authoring exception: who may create and edit new player characters without a world role | Owner | Existing PCs: preserve access via `campaign_delegated` responsibility in the manifest. New characters: a world Owner may enable per-campaign character-authoring delegation (default on for campaigns hosted at migration time, to preserve behaviour) | P03-C cutover |
| OD-6 | Build scope semantics (world-shared versus campaign-scoped; `legacy_unscoped` backfill) | Technical, product-visible | As ADR 0021 §4 | P03-C |
| OD-7 | License and origin of the seeded 5e content (revision 022) | Owner, legal | Record `unreviewed` until confirmed; do not distribute as a package until confirmed | R19-P4d; the P2a backfill label only |
| OD-8 | Default campaign option mode | Technical | `all_canon` (preserves behaviour) | R19-P2b |
| OD-9 | May `invalid` builds be approved as rules exceptions? | Owner | Yes, by `canon.edit` holders only, with a mandatory reason; never by delegated players | R19-P3d |
| OD-10 | Authority for house rules and option policy | Technical | Campaign: `canon.edit`. World house rules: `world.canon.edit` / `world.canon.review` + route `canon.edit` | R19-P2b/c |
| OD-11 | Promotion during an active encounter | Owner | Deferred; promotion only for completed or aborted encounters | R19-P4b |
| OD-12 | Player-contributed reference sources (`contributor_private` visibility; who may register) | Owner | Phase 18/20; the contributor owns visibility; GMs may cite by id only | Phase 18/20 |
| OD-13 | Audience-mode handling of hidden inputs | Technical | Exclude before evaluation with no exclusion marker (ADR 0023 §9) | R19-P3e |
| OD-14 | Control effectiveness when a campaign has no clock | Owner (DEF-007) | Follow the DEF-007 no-clock decision; until then, open-ended periods count as effective | P03-B |
| OD-15 | Spawn limits per call and per encounter | Technical | 50 / 200 | R19-P4b |
| OD-16 | ADR numbering coordination with the primary PC | Process | ADRs 0021–0023 are reserved by this branch. The primary PC's P03 work uses ADR 0021 rather than writing a competing actor ADR; new primary-PC ADRs start at 0024 | Now |

---

## 10. Risks

| Risk | Category | Mitigation |
|---|---|---|
| Legacy `primary_controller` rows silently become control and expand player rights | Privilege escalation | The `is_control_assignment` flag; only manifest-confirmed promotion; T2 and T6 |
| A derived value reveals a hidden item, effect or character | Disclosure | Truth mode GM-only; audience mode excludes before evaluation; T7; independent leak review in P3e |
| Licensed text copied into definitions or explanations | Source disclosure | The engine never reads passages; authoring refuses quotation-forbidden text; the five-decision separation |
| A stale preview approved as current | Stale results | Re-validation under lock at approval; `row_version`; fingerprints |
| Recomputation after an adapter change differs from history | Reproducibility | Snapshots on reviews and analysis; `adapter_version_changed` finding; no recomputation of combat outcomes |
| Shared-timeline campaigns contaminate each other's mechanics | Cross-campaign contamination | The X4 guard; `incompatible_ruleset_version`; OD-1 |
| Campaign-scoped build visible to another campaign | Cross-campaign contamination | P03-C `build_scope` listing rule; tests in P03-C |
| P2b/P3d edits to `character_builds.py` collide with P03-C | Merge conflict | Owner sign-off; rebase after P03-C; minimal guarded hooks |
| Migration-number collisions between PCs | Process | Claim at merge; renumber on rebase; linear Alembic history check in CI |
| JSONB mechanics drift from the adapter schema | Integrity | Schema version on every row; adapter validation on write; reject unknown versions as validated |
| Large encounters slow reads | Performance | Bounded spawns; indexed participant reads; evaluate a template once per encounter |
| Neutrality erodes (5e terms leak into the core) | Architecture | `test_rules_engine_neutrality.py`; review checklist |
| Portrayal cascade deletes history during the subtype cutover | Data loss | Re-key before any marker change; backup-gated irreversible steps (ADR 0021 §6–7) |

---

## 11. Instructions for the primary PC before starting P03-B and P03-C

1. Read ADR 0021 before any P03-B or P03-C schema work. Implement it rather than writing a competing actor ADR. Raise disagreements as review comments on ADR 0021, so the decision stays single (OD-16).
2. Store control in `security.membership_character_relationships` with `is_control_assignment`, a denormalized `campaign_id`, revocation provenance, and the one-live-primary exclusion constraint. Do **not** build `character.character_controllers`.
3. Never convert legacy `primary_controller` or `co_controller` rows to control automatically. Offer manifest-confirmed promotion per row.
4. Keep `CONTROL_ASSIGNMENT_CAPABILITIES` separate from `BUILTIN_RELATIONSHIP_CAPABILITIES`. Control excludes `canon.edit`, `view_private`, `view_knowledge` (perspective is a separate grant), build creation, portrayal and revelation.
5. Add `character.character_authoring_responsibilities` and route `record_authoring` through it. Remove `player_character` from `CAMPAIGN_ORIGINATED_TYPES` only through the manifest, preserving existing access. OD-5 decides the default for new characters.
6. Add `build_scope`, `origin_campaign_id` and `created_by_user_id` to `character.character_builds`, backfilling `legacy_unscoped`. Add the activation ruleset-version guard (X4) as early as convenient.
7. Expose the §5.1 contract functions (identity, active build, control state, `may_operate`, authoring responsibility, projection tier, state tokens) as named, documented functions. R19 code will import only those.
8. Re-key portrayal to `character_id` before touching NPC markers, and back up before any irreversible step.
9. Replace `_BUILDABLE` and `PARTICIPANT_KINDS` kind checks with capability and lifecycle eligibility. Keep the stored historical participation roles.
10. Coordinate with R19-P2b and R19-P3d. Both make small optional-parameter extensions to `commands/character_builds.py`. Sequence them after, or together with, P03-C's change to that file.
11. Leave `rules.*`, `domain/character_calculations.py` and the new `domain/rules_engine/` package alone. Phase 19 owns them.

---

## 12. Recommended first Sonnet checkpoint

Start with **R19-P3a (engine contracts, registry and the 5e adapter, pure)**. It needs no schema and modifies no existing file, so it cannot conflict with P03. It establishes the types every later checkpoint uses, and its parity and neutrality tests give an objective review standard. R19-P2a can run in parallel as a second, equally isolated checkpoint.

---

## 13. Self-review record (R19-P0)

- **Terminology across the ADRs.** The ADRs use the same terms throughout: "control assignment", "authoring responsibility", "build scope", "template-basis build", "combatant", "support level", "authority" (`authoritative` / `partial` / `informational`; never canon) and the validation outcomes. Ownership is identical in ADR 0021 (Phase 15), ADR 0022 and ADR 0023 (Phase 19), §5 and the PLANv2 §6.1 table.
- **All six owner decisions** are traced in §1.
- **P03 remains with Phase 15.** R19-P1 lists only obligations, and §11 restates the boundaries.
- **Phase 16 can proceed before full Phase 19** (§7.2): it needs P03-B/C and P3d/P3f only.
- **Neutrality.** The core types (ADR 0023 §2) contain no 5e terms, which `test_rules_engine_neutrality.py` enforces, and the fake second archetype is tested in P3f.
- **Unsupported mechanics never become validated.** Reviews and findings are separate fields, approval never upgrades them, and legacy builds read `not_evaluated`.
- **No new source access.** The engine reads no passages, and the five decisions are separated (ADR 0023 §9). `contributor_private` is deferred to Phase 18/20.
- **Reproducibility** holds through immutable ids and the fingerprint. The limitation across adapter versions is stated (ADR 0023 §10).
- **IDs and history** are preserved: every migration is additive and the manifest is reviewed (ADR 0021 §7; T21).
- **Sequencing** matches PLANv2 §6 and §6.1. R19-P4 follows Phase 17.
- **Checkpoint size.** Each P2 and P3 checkpoint is one reviewable PR with its own tests.
- **Labels.** Existing, planned and new components are labeled in §2 and in the ADR Context tables.
- **Scope of the change.** The R19-P0 commit adds documentation files only: three ADRs, this plan, and a one-line PLANv2 cross-reference.
