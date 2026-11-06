# Phase 19 foundation implementation plan (R19-P0 to R19-P4)

**Status:** Proposed. This is the R19-P0 planning deliverable, first drafted at `10a1a4e` and corrected after independent reviews (findings R19-01 to R19-13; see §13). **This revision (R19-10 to R19-13) is proposed design only. Nothing in it is implemented, enabled, tested or accepted.** Nothing here is implemented or accepted. **Owner decisions recorded (all 2026-11-02, all Owner-approved):**

- **OD-1:** campaigns sharing a world or timeline maintain independent mechanical character state (ADR 0021 §3).
- **OD-20:** character location and fictional/legal item ownership are shared narrative; mechanical possession, inventory, equipment, attunement, charges and quantities are per campaign (ADR 0021 §3.1.1).
- **OD-21:** lineage seeding and cross-campaign copy are separately authorized and stay disabled until enablement acceptance (ADR 0021 §3.6).

- **2026-11-03:** OD-2, OD-3, OD-4, OD-5, OD-7, OD-9, OD-10, OD-11, OD-12, OD-14, OD-17, OD-18, OD-19 and OD-22 are Owner-approved (§9, §13.4). These are policy approvals; the ADRs stay Proposed.

- **2026-11-04:** OD-4a (assistant-GM delegation of control assignment), OD-7a (the existing public seed treated as potentially distributed) and OD-12a (only the contributor authorizes access to a contributor-private source) are Owner-approved, and OD-18 is clarified (controllers edit the campaign-scoped player profile; this is not `character.edit_narrative`) (§9, §13.5). These are policy approvals; the ADRs stay Proposed, and OD-7a is not licensing clearance.

As instructed, OD-6 is reconciled to permit campaign-scoped builds. **No owner question remains open for R19-P0.**

**Branch:** `planning/r19-p0-architecture`, from `main` at `defe3f7`.

**Governing documents:** [PLANv2.md](PLANv2.md) §6.1, §8 (15H), §12 (19.0–19.8) and three Proposed ADRs:

- [ADR 0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md): actor identity, control, authoring responsibility. Phase 15 owns it.
- [ADR 0022](adr/0022-creature-templates-combatants-and-promotion.md): creature templates, combatants, promotion.
- [ADR 0023](adr/0023-rules-engine-calculation-validation-and-source-authorization.md): rules engine, validation, sources.

**Evidence.** Claims about the repository were verified in code at `10a1a4e`; application code is unchanged since `defe3f7`. Several Phase 14/15 documents served as **supplementary evidence only**: the app-interaction investigation (§D6, P03-A/B/C), the DEF-007 effective-time plan, the P02 navigation plan and audit, the Batch 1 repair plan, and the 2026-11-02 handoff. They are **untracked on this branch and not committed**. Where this plan relies on one of them, the claim was checked against source. For example, B1-1 `67f80de` and DEF7 `bcc0e16`/`cb26462`/`4ce9187` are ancestors of this branch, and `queries/party_membership_period.py` implements DEF-007's no-clock rule.

**Labels used throughout:**

- **Existing:** verified in code at the stated commit.
- **Planned:** named in an earlier plan but not built.
- **New:** proposed here.

**Audience:** independent reviewers, the owner, and the Sonnet implementers. Implementers must not encode any UNRESOLVED owner default. A checkpoint blocked by an owner decision says so in its gates.

---

## 1. Decision traceability and verified discrepancies

| Owner decision | Realised in | Implementing checkpoint |
|---|---|---|
| 1. Campaign primary and co-control | ADR 0021 §2–3 | P03-B (= R19-P1) |
| 2. World-authoritative canon with delegated authoring | ADR 0021 §4–5 | P03-C (= R19-P1); Phase 15 version guard |
| 3. Hybrid creatures | ADR 0022 | R19-P2d, R19-P4a, R19-P4b |
| 4. Neutral engine core | ADR 0023 §2–3, §13 | R19-P3a (including the percentile fixture), R19-P3f |
| 5. Versioned house rules | ADR 0023 §6 | R19-P2b, R19-P2c, R19-P3c |
| 6. Unsupported drafts, honest validation, authorized review | ADR 0023 §5, §7 | R19-P3d-1, R19-P3d-2 |

**Discrepancies found during verification:**

| # | Discrepancy | Evidence | Disposition |
|---|---|---|---|
| X1 | `character.character_controllers` is documented, never built. | DATABASE_MODEL §7.3, DOMAIN_MODEL §8.4; no table exists | ADR 0021 §2.1 retires it. |
| X2 | Player-character identity and lifecycle bypass world authority; any campaign `canon.edit` holder on the world qualifies. | `npcs._identity_world_capability`, `record_authoring.CAMPAIGN_ORIGINATED_TYPES` | ADR 0021 §4 (OD-5, OD-19). The ADR 0020 note points to the proposal. |
| X3 | Shared-timeline campaigns share the active build and runtime state across different pins. | `campaign.character_state` key; `campaigns.timeline_id` is not unique; `campaigns.timeline_id` is immutable (revision 030) | **OD-1 (Owner-approved):** mechanical state becomes campaign-scoped. Phase 15 P03-S adds campaign-keyed tables, lineage seeding and a manifest migration (ADR 0021 §3). |
| X4 | `activate_character_build` has no ruleset-version check. | `commands/character_builds.py` | Phase 15 guard (§6, R19-P1). |
| X5 | Calculation support is gated by family, not version. | `character_calculations.supports_ruleset` | R19-P3a registry. |
| X6 | The seed records no origin or license. | `database/seeds/rules.*.yaml`, revision 022 | R19-P2a records it as unreviewed (OD-7). |
| X7 | The PLANv2 19.5 "initial subset" already exists as untraced sheet formulas. | `queries/character_sheet.py` | R19-P3a ports it with parity tests. |
| X8 | `maximum_hit_points` is an entered value. | `campaign.character_state` | Reported with `declared_value_differs`; never overwritten. |
| X9 | The P03 sources are untracked. | Working tree | PLANv2 §18 item 19. |
| X10 | Live uniqueness is per `(membership, character, type)`, so a legacy row and an assignment of the same type would collide. Nothing enforces one primary per campaign. | `ux_membership_character_relationships_active_type` | ADR 0021 §2.3 index replacement. |
| X11 | `effective_period` is NULL when no start endpoint is supplied. | Revision 080 trigger | ADR 0021 §2.3 (`ongoing` and `dated` kinds). |
| X12 | Relationship effectiveness ignores the campaign clock, and its docstring says no clock exists. | `domain/access.py` | ADR 0021 §2.4 (OD-14); docstring follow-up. |
| X13 | `last_event_id` is not reliable: encounter damage omits it, the baseline is administrative, branch rows are inherited. | `commands/encounters.py`, `commands/character_builds.py`, `queries/character_build_resolution.py` | ADR 0023 §10 hashes loaded values; **P03-S (group G1) fixes the damage token**. |
| X14 | Mechanically relevant rules columns stay mutable (`hit_die`, associations; homebrew item fields). | Revisions 033/036; `commands/item_definitions.py` | ADR 0023 §4 and §10 content hashes. |
| X15 | Encounter readers inner-join participant entities; interaction actors require entities. | `queries/encounter_preparation.py` lines 93 and 111; `interaction.actions`, `check_requests` | ADR 0022 E1–E14 (R19-P4b). |
| X17 | Event explanations and corrections admit any event on the caller's timeline, so under OD-1 a campaign could see or correct another campaign's mechanical effects. | `queries/event_explanations.py` docstring; `api/event_corrections.py` ("Only events of the campaign's own timeline") | ADR 0021 §3.3 (P03-S, G4) |
| X18 | Item operations use a single token, `item_state.last_event_id`, for every item table, ownership included. | `commands/item_operations.py` docstring; `assess_event` | ADR 0021 §3.1.1 split checks (P03-S, G3) |
| X19 | `AwardRequest.set_owner` defaults to `True`, and the portal `AwardItemSection.tsx` omits it, so it changes ownership implicitly. | `api/item_authoring.py`; `portal/src/components/AwardItemSection.tsx` | ADR 0021 §3.1.1 R19-12 |
| X20 | `lock_operation_scope` refuses any capability other than `canon.edit`. | `commands/_operations.py` | ADR 0021 §2.8 `lock_controller_operation_scope` |
| X21 | The party-inventory route lives in `api/item_authoring.py`, not `api/parties.py`. | `GET /campaigns/{id}/parties/{party_id}/inventory` | Inventory corrected (ADR 0021 §3.8, §3.9) |
| X22 | Item operations do not check the item definition's ruleset version; only instance creation does. | `commands/item_instances._require_usable_definition` | ADR 0021 §3.7 (ED-12) |
| X16 | `core.sources` (citations) and `core.source_documents` (rights-bearing corpus) are unrelated. | `persistence/tables/core.py` | ADR 0023 §9 citation link (ED-8). |

---

## 2. Subsystem inventory

| Subsystem | Existing | Reused unchanged | Additive extension | Migration or retirement | Owner | Consumers |
|---|---|---|---|---|---|---|
| Actor identity | `core.entities` → `character.characters`; NPC and PC markers | UUIDs, entity and character rows | — | Markers become hints; optional retirement last | P03-C | All |
| Relationships and control | `membership_character_relationships`; `BUILTIN_RELATIONSHIP_CAPABILITIES`; reserved capability codes | Legacy rows and their capabilities, resolver freshness, lock chain | `is_control_assignment`, `campaign_id`, `is_primary`, `assignment_period_kind`, revocation columns; replaced and new unique indexes; `CONTROL_ASSIGNMENT_CAPABILITIES`; `character.assign_control` | Manifest-confirmed assignment creation only | P03-B | Phase 16, R19 projection, encounters |
| Authoring responsibility | `record_authoring` with the PC exception | World two-key rule | Delegations table; legacy-exception table | Per-character disposition (OD-5, OD-19) | P03-C | All character authoring |
| Discovery and projection | Role, relationship and grant discovery; summary and full tiers; B1-1 | Tier resolver, B1-1 | Revelation, public profile, controller view (OD-17) | Legacy background quarantine | P03-A | R19 audience mode |
| Portrayal | `npc_portrayal_profiles` → `npcs`, cascade; writes need `canon.edit` | Append-only versions | `character_id`; a separate player-guidance profile (OD-18) | FK re-key | P03-C (Phase 16 for player guidance) | Phase 20 |
| Builds | Immutable builds; `create_character_build` / `activate_character_build`; branch-effective resolution | Immutability, timeline activation, branch resolution | Scope columns (P03-C); version guard (Phase 15); drafts, reviews, custom mechanics, activation gate (R19-P3d); template basis (R19-P4a) | `legacy_unscoped` backfill; kind list replaced | Phase 15 owns the command contract; R19 extends under sign-off | Phase 16, R19 |
| Mechanical runtime state | Character, condition, resource, item, inventory and attunement state, keyed by **timeline** | Legacy rows (read-only after cutover; never dropped in Phase 15) | **OD-1:** campaign-keyed tables, `campaign_mechanical_lineages`, migration records, `campaign.effect_component_classes` (ADR 0021 §3.2) | Reviewed manifest; dual-read; writer cutover per consumer family (ADR 0021 §3.8) | **Phase 15 P03-S** (schema, commands, resolvers, APIs). No R19 writer changes; the encounter character-damage token fix is **P03-S (G1)** | Engine (route-campaign facts, hashed values) |
| Rules definitions | `rules.*` with identity immutability; mutable associations and descriptions | All | `content_package_id` (P2a); prerequisites and exclusions schema (later); creature templates (P2d) | None to existing columns | R19-P2 | Engine, Phase 16/18 |
| Campaign rules configuration | Campaign version pin | Pin | Option policy, configuration version (P2b-1); house rules (P2c) | — | R19-P2b/c | Catalog, engine |
| Items | Item definitions (homebrew editable), instances, state, inventory, attunements, identification | All | Mechanics payload columns (P3e-T) | — | R19-P3e under item-owner sign-off | Engine |
| Calculations | `character_calculations.py` (5e, family gate), sheet | Kept as the parity oracle | `domain/rules_engine/` (P3a) | Shim retired after P03-A | R19-P3 | Sheet, previews, AI |
| Encounters | Encounters, participants (entity NOT NULL), turns, interactions, events, Foundry | All existing contracts | E1–E14 (ADR 0022) | Participant entity becomes nullable | R19-P4b with the Phase 15 encounter owner | Analysis, Phase 21 |
| Reference corpus | `core.source_documents`, campaign grants | All | `contributor_private` (OD-12); typed citation link (ED-8) | — | Phase 18/20; ED-8 before private citation | Phase 20 |
| Proposals | `ai.proposed_changes` (AI only) | Unchanged | Build drafts are separate | — | R19-P3d | Phase 18/20 |

---

## 3. Gates

The four gates are applied in the sense of PLANv2 §6.1:

- **Begin:** work may start (category 1).
- **Merge:** the change may merge to `main` (category 2 when isolated).
- **Enable:** exposure as a usable feature through the portal, a non-GM API, or a behavior change to an existing command (category 3).
- **Accept:** counted as delivered.

A hook that changes an existing command's behavior is category 3 even if its default preserves behavior.

| Checkpoint | Begin | Merge | Enable | Accept |
|---|---|---|---|---|
| R19-P0 | Now | After independent review | n/a | After a separate ADR acceptance decision. Every owner decision the ADRs depend on is recorded (OD-1, 20, 21 on 2026-11-02; OD-2, 3, 4, 5, 7, 9, 10, 11, 12, 14, 17, 18, 19, 22 on 2026-11-03; OD-4a, 7a, 12a and the OD-18 clarification on 2026-11-04) |
| R19-P1 (P03-A/B/C/S) | Phase 15 | Phase 15 | Phase 15. P03-S writer cutover per group (G1–G4) in stopped-writer windows | PLANv2 15.9, including the P03-S criterion |
| P2a provenance | ADR 0023 §4 reviewed | Isolated (cat. 2) | Package metadata read API: merge = enable (non-sensitive) | With R19-P4g. **Prioritized (OD-7a).** Documented rights clearance or replacement of uncleared material is already required for the seed as published (OD-7, OD-7a); rights status stays `unknown` / `unreviewed` until evidence |
| P3a engine and fixtures | ADR 0023 §2–3 reviewed | Cat. 2 | n/a (pure) | With P3f |
| P3b loader and GM endpoints | P3a | Cat. 2 (GM `canon.edit` only, no portal) | Non-GM exposure only via P3e-A | With P3f |
| P2b-1 policy tables and reads | P3b | Cat. 2 (read paths); commands enforce OD-10 (Owner-approved) | After the checkpoint's tests and review; GM API only | With R19-P4f |
| P2b-2 build-command enforcement | P2b-1 | **Cat. 3:** merge needs build-command owner sign-off; after P03-C if `character_builds.py` is in flight | Allow-list mode exposed only after owner acceptance of the behavior change (OD-10 is approved) | With R19-P4f |
| P2c house rules | P3a, P2b-1 | Schema and reads cat. 2; commands enforce OD-10 (Owner-approved) | After the checkpoint's tests and review | With R19-P4f |
| P3c conditions and overrides | P3b, P2c (reads) | Cat. 2 | GM endpoint only | With P3f |
| P2d creature templates | P3a, P2a | Cat. 2 (GM API); **independent of P2b** | No portal before R19-P4 | R19-P4g |
| P2d-x option target for templates | P2b-1 and P2d merged | Cat. 2 | With P2b-2 | R19-P4g |
| P3d-1 drafts (create, validate, submit, withdraw, reject) | P3b; ADR 0021 accepted | Cat. 2 (GM drafts, no materialization) | Player drafting after P03-B/C and Phase 16 | Phase 16 / P3f |
| P3d-2 approval, materialization, direct-create review, activation gate | P3d-1; **P03-C build scope merged**; **P03-S G1 writer cutover** (approval activates into campaign state); OD-9 (Owner-approved) | **Cat. 3:** build-command owner sign-off | Activation-gate behavior change enabled only after owner acceptance of the behavior change (OD-9's policy is approved) | Phase 16 / P3f |
| P3e-T equipment (truth) | P3c | Cat. 2 with item-domain owner sign-off | GM endpoint | P3f |
| P3e-A audience mode | P3e-T; **P03-A projection tier accepted**; for controllers, **P03-B accepted** | Cat. 3 | Non-GM mechanics reads | P3f |
| P3f contract freeze | P3d-2, P3e-A | Cat. 2 | Phase 16 consumption | Phase 16 consumer review |
| R19-P4a–g | Design any time | After Phase 17 (PLANv2 §6, 17.4) | After Phase 17 | R19-P4g (PLANv2 19.8) |

**Safe to implement immediately (while P03 runs):** P2a and P3a. **P2a is prioritized under OD-7a.** P3b follows P3a. P2d may follow. None of them touches a file P03 is expected to change.

**Owner decisions:** OD-1, OD-20 and OD-21 (2026-11-02), OD-2, 3, 4, 5, 7, 9, 10, 11, 12, 14, 17, 18, 19 and 22 (2026-11-03), and OD-4a, 7a, 12a and the OD-18 clarification (2026-11-04) are Owner-approved and block no contract. No owner question is open. The remaining gates are not owner-decision gates: ADR acceptance, build-command owner sign-off, owner acceptance of the P2b-2 and P3d-2 behavior changes, checkpoint tests and reviews, **enablement** acceptance of lineage seeding and cross-campaign copy (ADR 0021 §3.6), and the OD-7 rights clearance or replacement of uncleared seed material, which OD-7a makes already due for the published seed.

**Waits for P03:** P2b-2 (sign-off, sequencing), P3d-2 (P03-C), P3e-A (P03-A/B), R19-P4a/b.

**Waits for Phase 17:** all of R19-P4.

---

## 4. Conventions, migration ownership and shared commands

- **Layering, migrations, commands, tests, docs and review** follow the first draft:
  - `NNN_` migration numbers are claimed at merge and renumbered on rebase.
  - Commands follow PLANv2 §3.1 and §17.
  - Each checkpoint runs `ruff`, `mypy`, its focused tests, the full suites and final-head CI.
  - Each PR names its parent and target SHAs.
- **No unresolved owner default may be encoded.** Where an OD is open, the command or path ships disabled (it refuses with `feature_policy_unresolved`, a 404-equivalent for clients) or is not merged.

### Migration ownership

| Schema change | Owner | Sign-off |
|---|---|---|
| Relationship assignment columns, indexes, capability matrix | P03-B | — |
| Authoring delegations, legacy exceptions, build scope columns, portrayal re-key | P03-C | — |
| **Campaign mechanical-state isolation (OD-1):** campaign-keyed character state, condition, resource, item-state, inventory and attunement tables; `campaign_mechanical_lineages`; `mechanical_state_migration_records`; `effect_component_classes`; the mechanical-event campaign trigger; extending the ruleset-dependency guard; legacy read-only triggers | **Phase 15 P03-S** | — (no campaign-creation restriction: the earlier refusal proposal is withdrawn) |
| `rules.content_packages` and its columns | R19-P2a | — |
| Option policy and configuration tables (rows created lazily: a missing row means `all_canon`, version 0, so **campaign creation is not touched**) | R19-P2b-1 | — |
| House-rule tables | R19-P2c | — |
| Creature template tables | R19-P2d | — |
| Drafts, reviews, custom mechanics | R19-P3d-1/2 | Build-command owner |
| Item-definition mechanics columns | R19-P3e-T | Item-domain owner (Phase 15, 15F) |
| Encounter, participant and interaction actor/target columns; combatant state | R19-P4b | Encounter owner (Phase 15) |
| **State-writer token changes** (setting `last_event_id` anywhere; the split item tokens) | Phase 15 writers; the encounter-damage fix and the item-token split in **P03-S** | Phase 15 owner. **No early R19 checkpoint changes state writers.** |

### Shared commands

| Command | Owner | R19 extension |
|---|---|---|
| `create_character_build` | Phase 15 (P03-C adds `build_scope`) | P3d-2: `custom_mechanics`, review linkage. **No reference-check waivers.** P4a: `template_basis` |
| `activate_character_build`, `initialize_character_state`; `character_state`, `encounters` damage, `event_corrections`, `item_operations`, `items`, Foundry sync writers | Phase 15 (X4 guard; **P03-S moves every mechanical writer to the route campaign's tables**) | P3d-2: activation gate (ADR 0023 §7.4). R19 never writes mechanical state |
| `_validate_rules` / `build_options_endpoint` | Phase 15 | P2b-2 option enforcement |
| Item definition commands | Phase 15 (15F) | P3e-T mechanics payload |
| Encounter preparation and operation commands; Foundry sync | Phase 15 / Phase 11. **P03-S moves damage writes to campaign state and repairs `last_event_id`** | P4b (E1–E14, combatants only) |
| Event recording, explanations, correction preview and correction (`commands/events.py`, `commands/event_corrections.py`, `queries/event_explanations.py`, `queries/event_authoring.py`) | Phase 15 (**P03-S, G4**) | R19 consumes them; never changes them |
| Item award and transfer APIs and commands (`api/item_authoring.py`, `api/items.py`, `commands/item_operations.py`, `commands/items.py`); portal item contracts | Phase 15 (**P03-S, G3**: required ownership intent, split tokens) | — |
| Controller path (`lock_controller_operation_scope`, named intents) | Phase 15 (**P03-B**) | — |

---

## 5. Integration contracts

### 5.1 Actor contract (owner: Phase 15)

| Element | Contract |
|---|---|
| Identity | `actor_id` (= `character_id`), world id, lifecycle. Stable through control, kind, promotion and template. |
| Campaign-aware build | `resolve_campaign_active_build(campaign_id, character_id) -> {usable \| incompatible_ruleset_version \| out_of_scope \| none, build_ref?}` (ADR 0021 §3.4) |
| Campaign mechanical state | `resolve_campaign_mechanical_state(campaign_id, character_id, component)` gives the local campaign row, or none. Lineage is materialized by seeding, and there is no live cross-campaign read (ADR 0021 §3.4). Each row carries its `origin`, or `legacy_shared_state` during dual-read |
| Control | `control_state(campaign_id, character_id, clock) -> {primary?, co_controllers[], gm_operated, undetermined}`; `may_operate(access, character_id, operation_code)`, rechecked after the anchor lock (ADR 0021 §2.8) |
| Authoring | `authoring_rights(access, character_id) -> {stewardship, delegated_operations[], legacy_exception}` |
| Operations | The closed `CONTROLLER_OPERATIONS` (OD-3, Owner-approved: ADR 0021 §2.5a) |
| Projection | `projection_tier(access, character_id) -> {none, public_profile, controller, gm}` |
| Runtime facts | Loaded state values (hashed by R19), plus advisory tokens |

**Compatibility boundary for early R19 work.** `queries/rules_context.py` depends on a narrow port, `ActorContractPort`, with two implementations:

- **(a) current schema (pre-P03):**
  - identity is the character row;
  - the active build comes from `character_build_resolution`. It is classified `usable` when its version equals the route campaign's pin and `incompatible_ruleset_version` otherwise. There is no `out_of_scope` until build scope exists;
  - mechanical state is read from the legacy **timeline** tables. When the route campaign's timeline hosts more than one campaign (including archived ones), every fact and result is labeled `legacy_shared_state` and is never shown as rules-validated. The manifest records `state_scope = legacy_shared_state`. After P03-S, implementation (b) reads only the route campaign's tables;
  - the projection tier is `gm` for `canon.edit` callers and `none` otherwise;
  - control is not consulted.
- **(a+C) P03-C merged, P03-S not yet cut over:** build scope is known, and state still comes from the legacy timeline rows, as in (a). P03-C must refuse activating `campaign`-scoped builds until P03-S G1 cuts over (`campaign_build_activation_requires_isolation`). This is a transitional guard, not a policy. So no campaign-private build becomes timeline-wide. Any such legacy row would resolve `out_of_scope`.
- **(a+S) P03-S cut over (per group), P03-C not merged:** state comes from campaign tables for cut-over groups and from GM-only dual-read (ADR 0021 §3.8) for the rest. Every build is treated as `legacy_unscoped`.
- **(b) both accepted:** the full contract. The port switches per phase without changing the R19 interfaces. Tests run against each implementation that exists at merge time.

R19 code and tests target the port, never subtype tables or campaign-owned characters.

### 5.2 Authoring and validation contract (Phase 15 command family; Phase 16 player submission; Phase 19 drafts, validation, review)

| Element | Contract |
|---|---|
| Draft | `create_build_draft`, `update_build_draft(expected_row_version)`, `withdraw_build_draft`, `reject_build_draft` (P3d-1) |
| Validate | `POST …/build-drafts/{d}/validate` and `POST …/mechanics/preview` return the three axes (ADR 0023 §5). No write except the draft's validation snapshot. |
| Approve | `approve_build_draft(decision, adjudications[], reason?)` (P3d-2) re-validates under lock and materializes immutably (ADR 0023 §7.5) |
| Direct create | `POST …/builds` is preserved. After P3d-2 it records a review only when valid; otherwise the build is created unreviewed (ADR 0023 §7.2) |
| Review an existing build | `review_character_build(build, decision, adjudications, reason)` (P3d-2) |
| Activate | `activate_character_build` only: writes the route campaign's state (OD-1), plus the per-campaign version guard, plus the activation gate |
| Audit | Every transition is audited without payload content. Reviews are append-only. |

### 5.3 Creature contract (owner: Phase 19)

As described in ADR 0022:

- template and versions (P2d);
- template-basis builds (P4a);
- combatants, spawning, participant-addressed actors and targets, promotion (P4b).

Entity-addressed encounter APIs are unchanged. The Foundry sync refuses combatants explicitly.

### 5.4 Calculation contract (owner: Phase 19)

ADR 0023 §2, §3, §5 and §10:

- `InputBundle`, adapter protocol, registry, composition, three-axis result, `rules_result.v1`, `rules_manifest.v1`;
- versioned JSON schemas. Additive changes stay within `v1`; renames require `v2`.

### 5.5 Source and permission contract (shared)

ADR 0023 §9: five independent decisions; citations to `core.sources` only until ED-8 is built; the bounded copied-text aid. Option eligibility goes through `rules_catalog.option_permitted`.

**Acceptance tests for every contract:** §8.

---

## 6. Checkpoints

Every checkpoint covers the same 16 fields:

1. Objective
2. Prerequisites
3. Existing modules
4. New or modified modules
5. Schema
6. API and commands
7. Authorization
8. Migration
9. Compatibility
10. Automated tests
11. Manual acceptance
12. Performance
13. Rollback
14. Branch dependencies
15. Completion criteria
16. Gates (§3)

Fields that are unchanged from the first draft are stated briefly.

### R19-P0 — Architecture and contracts

1. **Objective:** accepted ADRs 0021–0023 and this plan.
2. **Prerequisites:** none.
3. **Existing modules:** none.
4. **New or modified modules:** three ADRs, this plan, an ADR 0020 pointer note, a PLANv2 cross-reference.
5. **Schema:** none.
6. **API and commands:** §5.
7. **Authorization:** none.
8. **Migration:** none.
9. **Compatibility:** not applicable.
10. **Automated tests:** documentation link and table checks.
11. **Manual acceptance:** independent review; a separate ADR acceptance decision. The owner decisions are recorded in the ADR status lines (OD-1, 20, 21 on 2026-11-02; OD-2, 3, 4, 5, 7, 9, 10, 11, 12, 14, 17, 18, 19, 22 on 2026-11-03; OD-4a, 7a, 12a and the OD-18 clarification on 2026-11-04).
12. **Performance:** not applicable.
13. **Rollback:** revert the documentation.
14. **Branch dependencies:** none.
15. **Completion criteria:** the ADRs are Accepted (or amended), and the primary PC acknowledges ADR 0021.
16. **Gates:** §3.

### R19-P1 — Shared actor foundation (Phase 15 P03-A/B/C/S)

The obligations are those of ADR 0021:

- **P03-A:** revelation (OD-17), public profile, projection tiers, discovery predicate, and the campaign-scoped player-profile storage and read (OD-18).
- **P03-B:** assignment columns, index replacement, `CONTROL_ASSIGNMENT_CAPABILITIES` (including `character.view_player_profile` and `character.edit_player_profile`, never `character.edit_narrative`; OD-18 clarification), the locking protocol, clock rules (OD-14), operations (OD-3) that write the route campaign's state (P03-S), assignment authority (OD-4), the assistant-GM delegation of `character.assign_control` with no redelegation (OD-4a), co-controller rules (OD-2).
- **P03-C:** delegations, legacy exceptions and campaign-scoped pending player characters (OD-5, OD-19), build scope (OD-6, reconciled: campaign-scoped builds permitted), portrayal re-key, capability eligibility, manifest, adapters.
- **P03-S (OD-1, Owner-approved):** campaign-keyed mechanical-state tables, lineage seeding, the mechanical-event campaign trigger, the reviewed migration manifest, dual-read, per-family writer cutover, and every table, command, resolver and API in ADR 0021 §3.9. P03-S must precede any P03-B operation that writes state. **OD-20:**
  - `item_ownership` and `character_location_history` stay shared and are not migrated;
  - `award_item`'s implicit owner default is removed, and explicit ownership is written as a separately authorized narrative effect;
  - a new `change_item_ownership` command.

  **OD-21:** request and approve commands for lineage seeding and copy, `campaign.mechanical_transfer_requests`, and capabilities `mechanics.transfer_read`, `mechanics.seed`, `mechanics.copy_in`. All of it stays **disabled until enablement acceptance**. **Neither is required to complete P03-S isolation**, because existing branch-inherited rows go through the reviewed offline migration.

  **R19-10 to R19-13 obligations (P03-S and P03-B):**
  - event visibility, authoring and correction rules (ADR 0021 §3.3, group G4);
  - split item revision checks and atomic mixed operations (§3.1.1, G3);
  - required ownership intent at every boundary, including the portal (§3.1.1, G3);
  - the encounter-damage `last_event_id` repair (G1);
  - `lock_controller_operation_scope` and named controller intents, with canonical commands unchanged (§2.8, P03-B);
  - the item version rule (§3.7, ED-12);
  - the full migration protocol: **family-atomic** manifest, validation and apply (membership hashes, dependencies, `pending_drift`, `reviewed_replacement`, `empty_confirmed`, idempotent retry); initialization markers written only with complete families; cutover groups in stopped-writer windows; the authorization-safe fallback; qualified rollback (§3.8);
  - the fail-closed effect registry `campaign.effect_component_classes`, with a foreign key and coverage tests. the universal disclosure rule: a `campaign_mechanical` effect is disclosed only after its classification and origin attribution are both reviewed and recorded (`authorized_at_write` for new events, `migration_reviewed` for legacy ones, in `campaign.event_effect_attributions`), whenever its code was classified; `unclassified` effects are always withheld; raw review happens only in migration review (§3.3, §3.8 step 2a);
  - quarantine and resolution of incompatible migrated item state (§3.7);
  - `data_classification` registration.

**Also Phase 15, early:** the X4 activation version guard (`build_ruleset_mismatch`, 400), with a database test. Campaigns A and B pin different versions on one timeline; activating A's build from B is refused.

**Tests (Phase 15 acceptance):** T1–T7, T21–T26, T31, T33–T39, T46–T56, T63–T68, T70–T82, T85, T86. **Ordinary P03-S completion does not depend on any runtime transfer command.** Enablement of the OD-21 commands additionally needs T24, T32, T40–T45, T57–T61. Phase 17: T62, T69.

R19 implements none of this.

### R19-P2a — Rules content provenance and packages

1. **Objective:** each ruleset-wide definition names its content package, origin, license status and review status. The seed is recorded as **unreviewed** with license `unknown`.
2. **Prerequisites:** ADR 0023 §4 reviewed.
3. **Existing modules:** `persistence/tables/rules.py`, revisions 022/033/036, `persistence/seeds.py`, `tests/database/test_ruleset_provenance.py`.
4. **New or modified modules:**
   - migration `NNN_rules_content_packages.py`;
   - lookups `rules.content_origins`, `rules.content_licenses` (includes `unknown`), `rules.content_review_statuses`;
   - `queries/rules_provenance.py`;
   - `GET /rulesets/{rv}/content-packages`;
   - `docs/R19_SEED_CONTENT_PROVENANCE_AUDIT.md`, a factual inventory of what the seed contains and what evidence exists. It makes **no legal conclusion**.
5. **Schema:** ADR 0023 §4. Nullable, immutable `content_package_id` on the 15 ruleset-wide tables, with a version-agreement trigger.
6. **API and commands:** read-only.
7. **Authorization:** any authenticated member of a campaign on that version, or a system admin.
8. **Migration:** create one package for revision 022's version (`system_baseline`, `unknown`, `unreviewed`) and backfill. Homebrew items stay NULL.
9. **Compatibility:** nullable columns; no reader changes.
10. **Automated tests:** migration up/down/up, backfill counts, the trigger, immutability, seeds, endpoint authorization.
11. **Manual acceptance:** the owner reads the audit document (the OD-7 evidence inventory), which lists each seed item's evidence and disposition: cleared with documentation, replaced, or outstanding (T88).
12. **Performance:** negligible.
13. **Rollback:** drop the objects.
14. **Branch dependencies:** none.
15. **Completion criteria:** tests pass; documentation is updated; the OD-7 evidence inventory is complete. **OD-7a (Owner-approved 2026-11-04):** the published seed is treated as potentially distributed, so P2a is prioritized and documented rights clearance or replacement of uncleared material is already required, not deferred to the next distributed artifact. The seed stays `unknown` / `unreviewed` until evidence supports a change. Neither P2a nor OD-7a is licensing clearance.
16. **Gates:** §3.

### R19-P3a — Engine core, the 5e adapter port, and the neutrality fixture (pure)

1. **Objective:**
   - the neutral types (ADR 0023 §2), deterministic composition (§3), the manifest and fingerprint (§10) and the three-axis result;
   - a 5e adapter reproducing today's sheet formulas with traces and per-version support;
   - **a small percentile fixture adapter (test-only)** proving the core needs no 5e concepts.
2. **Prerequisites:** ADR 0023 §2, §3, §5 and §10 reviewed.
3. **Existing modules:** `character_calculations.py` (parity oracle, **unmodified**).
4. **New or modified modules:**
   - `domain/rules_engine/{__init__,contracts,composition,validation,manifest,fingerprint,registry}.py`;
   - `adapters/dnd5e.py`, `adapters/schemas/dnd5e_build_payload_v1.py`;
   - `tests/unit/rules_engine_fixtures/percentile_adapter.py`, registered only through a test registry fixture.
5. **Schema:** none.
6. **API and commands:** the Python API only.
7. **Authorization:** none (pure).
8. **Migration:** none.
9. **Compatibility:** no existing file changes.
10. **Automated tests (`tests/unit/`):**
    - Ordering:
      - two contributions from one source with different ordinals sort deterministically;
      - 200 random permutations give an identical result and fingerprint.
    - Duplicates:
      - an identical duplicate collapses with a warning;
      - a conflicting duplicate yields `adapter_contract_violation` and an `unsupported` key.
    - Dependencies:
      - topological evaluation;
      - a registry cycle fails the registry validation test;
      - missing ability gives `missing_input` on dependants, with `blocked_by`;
      - an optional dependency with a default is traced `default_applied`.
    - Conflicts: `set`/`set` conflicts produce `conflicting` and no value.
    - Manifest:
      - unequal preview payloads produce unequal fingerprints;
      - equal payloads produce equal fingerprints;
      - changing a definition `content_hash` changes the fingerprint;
      - an audience-mode manifest excludes non-included refs.
    - 5e parity table against `character_calculations` (scores 1–30, levels 1–20, proficiency and expertise).
    - Support per version: 2024 is `calculating`; 2014 and unknown are `none`.
    - Build-choice traces cite `build_component` refs.
    - **Percentile fixture:**
      - evaluates `pct.skill.*`, `pct.hit_points`, a dice-valued `pct.damage_bonus` and an advancement offer with no level;
      - core modules accept it unchanged.
    - **Neutrality guard (scoped):**
      - `contracts.py`, `composition.py`, `validation.py`, `manifest.py` and `fingerprint.py` contain none of the tokens `proficien`, `armor_class`, `class_level`, `spell_slot`, `challenge_rating`, `hit_die`, `dnd5e`, and import nothing from `adapters`;
      - `registry.py` is **explicitly allowed** to import and register adapters by id.
11. **Manual acceptance:** a reviewer reads one 5e trace and one percentile trace.
12. **Performance:** microseconds.
13. **Rollback:** delete the package.
14. **Branch dependencies:** none.
15. **Completion criteria:** all tests pass; `mypy` strict-clean; 100% parity.
16. **Gates:** §3.

### R19-P3b — Context loader, catalog, GM explanation and support endpoints

1. **Objective:** load an authorized, batched `InputBundle` through `ActorContractPort` implementation (a), the current schema (§5.1), then evaluate. GMs get explanations; members get the support level.
2. **Prerequisites:** P3a.
3. **Existing modules:** `character_build_resolution.py`, the sheet query patterns (**the sheet itself is unmodified**), `api/access.py`.
4. **New or modified modules:**
   - `queries/rules_context.py` (envelope, port);
   - `queries/rules_context_dnd5e.py` (loader);
   - `queries/rules_catalog.py`;
   - `api/rules_mechanics.py`:
     - `GET /campaigns/{c}/characters/{ch}/mechanics` requires `canon.edit` and uses truth mode;
     - `GET /campaigns/{c}/rules/support` requires `campaign.view`.
5. **Schema:** none.
6. **API and commands:** as above. `rules_result.v1`.
7. **Authorization:** mechanics require `canon.edit`, otherwise a non-disclosing refusal. Characters resolve through the route campaign's **world** and lifecycle rules, never through any notion of campaign ownership.
8. **Migration:** none.
9. **Compatibility:** new routes only.
10. **Automated tests:**
    - **Loader:**
      - tokens are advisory, and values are hashed;
      - a character with no build gives `missing_input` statuses;
      - a branch-inherited build resolves through existing resolution;
      - a past `as_of` gives `historical_state_unavailable` for runtime facts;
      - a branch component without branch resolution gives `branch_state_unresolved`;
      - encounter damage (which does not set `last_event_id`) still changes the fingerprint;
      - an attunement change changes it;
      - a SQL-fixture edit of `rules.classes.hit_die` changes the content hash.
    - **API:**
      - the GM gets values;
      - a player is refused, non-disclosing;
      - a character of **another world** gets 404;
      - same-world draft, archived and denied characters follow existing lifecycle and deny rules;
      - parity with the sheet's derived fields for one fixture;
      - an unsupported version returns `support: none`;
      - a campaign whose pin differs from the active build's version returns `incompatible_ruleset_version`;
      - **OD-1 regressions before P03-S:** two campaigns on one timeline both get the `legacy_shared_state` warning; identical state gives different fingerprints per campaign (T35); a campaign alone on its timeline gets no warning;
      - **the same tests re-run after P03-S** with implementation (b): T22, T23.
    - **Query count** is bounded per family.
11. **Manual acceptance:** a GM reads one explanation; a player is refused.
12. **Performance:** p95 under 50 ms per character locally, recorded in the PR.
13. **Rollback:** remove the router.
14. **Branch dependencies:** none (port implementation (a)).
15. **Completion criteria:** tests pass; documentation updated.
16. **Gates:** §3.

### R19-P2b-1 — Option policy and configuration version (tables, commands, reads)

1. **Objective:** store per-campaign option policy and a configuration version. Commands enforce the OD-10 authority (Owner-approved 2026-11-03).
2. **Prerequisites:** P3b; P2a for package-level entries.
3. **Existing modules:** `persistence/tables/campaign.py`.
4. **New or modified modules:**
   - migration;
   - `commands/rules_configuration.py`;
   - `queries/rules_catalog.option_permitted` / `permitted_options`;
   - `api/rules_configuration.py`.
5. **Schema:**
   - `campaign.campaign_rules_configurations`;
   - `campaign.campaign_rule_option_policies` (mode lookup `all_canon` / `allow_list`);
   - `campaign.campaign_rule_option_entries`: allow or deny; at-most-one typed target (class, subclass, species, feat, spell, feature, item definition, content package); same-version trigger; live-entry unique index.

   Rows are created lazily. Missing rows read as `all_canon`, version 0.
6. **API and commands:**
   - `GET /campaigns/{c}/rules/configuration` (members);
   - `PUT …/rules/option-policy`, `POST` / `DELETE …/rules/option-entries`. They are idempotent and stale-checked on the configuration version.
7. **Authorization:** reads need `campaign.view`. Writes need campaign `canon.edit` on the route campaign (OD-10, Owner-approved). Every change advances the configuration version.
8. **Migration:** new tables only; no backfill.
9. **Compatibility:** `_validate_rules` and build options are **not touched** (that is P2b-2).
10. **Automated tests:**
    - lazy defaults;
    - entry validation, cross-version refusal, deny over allow;
    - the configuration version bumps exactly once per change and not on replay;
    - writes without campaign `canon.edit` are refused (non-disclosing).
11. **Manual acceptance:** a GM writes option policy through the API; a non-editor is refused.
12. **Performance:** indexed.
13. **Rollback:** drop the tables.
14. **Branch dependencies:** none.
15. **Completion criteria:** tests pass.
16. **Gates:** §3.

### R19-P2b-2 — Option enforcement in build creation (behavior change)

1. **Objective:** `allow_list` campaigns refuse non-permitted options at direct build creation, using the existing non-disclosing `build_option_not_available`, and filter build options.
2. **Prerequisites:**
   - P2b-1;
   - OD-10 (Owner-approved);
   - build-command owner sign-off;
   - P03-C merged, if it changes `character_builds.py`.
3. **Existing modules:** `commands/character_builds._validate_rules`, `api/character_builds.build_options_endpoint`.
4. **New or modified modules:** a two-line guarded hook in each.
5. **Schema:** none.
6. **API and commands:** unchanged shapes.
7. **Authorization:** unchanged.
8. **Migration:** none.
9. **Compatibility:** `all_canon` campaigns are unaffected (the existing build tests run unchanged). This is still category 3, because enabling `allow_list` changes command behavior.
10. **Automated tests:**
    - a denied option is refused, non-disclosing;
    - build options are filtered;
    - T8.
11. **Manual acceptance:** T8 in the portal (R19-P4f) or by the API.
12. **Performance:** one indexed query.
13. **Rollback:** revert the hooks.
14. **Branch dependencies:** P03-C sequencing.
15. **Completion criteria:** owner sign-off; tests pass.
16. **Gates:** §3.

### R19-P2c — House rules

As in ADR 0023 §6:

- tables, `domain/house_rules.py`, `commands/house_rules.py`, `queries/house_rules.py`;
- 5e override points `hit_points_per_level`, `ability_score_generation`, `exhaustion_model`.

**Authority (OD-10, Owner-approved 2026-11-03):** campaign house rules need campaign `canon.edit`. World house rules need `world.canon.edit` to author and `world.canon.review` to publish, plus route-campaign `canon.edit`. House-rule versions are append-only. Read paths and schema may merge first; commands enable with the checkpoint's tests and review.

**Tests:**

- schema validation of parameters;
- unknown override point refused;
- `unevaluated` is text-only;
- canon versions are immutable;
- adopting a draft is refused;
- unique precedence;
- unacknowledged overlap is listed as a conflict, and acknowledgement resolves it;
- a cross-world adoption is refused;
- retirement keeps history;
- the configuration version bumps once;
- a concurrent same-precedence adoption has exactly one winner;
- members see descriptions without GM notes.

**Rollback:** drop the tables. **Gates:** §3.

### R19-P3c — Conditions, exhaustion and override evaluation (5e)

- **Additions:**
  - the 14 seeded conditions as enum roll-mode keys;
  - exhaustion as a `runtime_fact` under the `exhaustion_model` point (2024: −2 × level to d20 tests, −5 ft × level speed);
  - `dnd5e.hit_point_maximum` from `hit_die` and the CON modifier under `hit_points_per_level`;
  - house-rule adoptions loaded into the bundle;
  - an unknown condition reported `unsupported`.
- **Tests:**
  - each condition;
  - exhaustion levels 0–6;
  - 2014 gives `none`;
  - adopted vs default;
  - unacknowledged conflict gives `conflicting` with both candidates;
  - `unevaluated` gives `unsupported`;
  - `declared_value_differs`;
  - T13, T14.
- **Gates:** §3.

### R19-P2d — Creature template definitions

- **Content:** ADR 0022 §2 tables, `commands/creature_templates.py`, `queries/creature_templates.py`, `api/creature_template_authoring.py`, the 5e `dnd5e_creature_mechanics.v1` schema.
- **No dependency on P2b.** The option-entry target `creature_template_id` is the separate follow-up **P2d-x**, which merges only after P2b-1 and P2d.
- **Authorization:** world `world.canon.edit` / `world.canon.review` plus route `canon.edit`. Players are denied.
- **Publication:** follows ADR 0023 §7 (a non-valid version needs adjudication or exception with a reason).
- **Tests:**
  - lifecycle and immutability;
  - version pin;
  - reference integrity;
  - another world's template is invisible;
  - schema validation;
  - player denied;
  - informational evaluation;
  - publishing v2 leaves v1 unchanged.
- **Gates:** §3.

### R19-P3d-1 — Build drafts (no materialization)

1. **Objective:** drafts with custom and unsupported content, validation snapshots, submit, withdraw and reject. **No approval.**
2. **Prerequisites:** P3b; ADR 0021 accepted.
3. **Existing modules:** `domain/character_builds.py` (`BuildInput` bounds), the idempotency machinery.
4. **New or modified modules:**
   - migration (`character.character_build_drafts`, status lookup);
   - `domain/build_drafts.py`;
   - `commands/build_drafts.py` (create, update, validate, submit, withdraw, reject);
   - `queries/build_drafts.py`;
   - `api/build_drafts.py`.
5. **Schema:** ADR 0023 §7.3. A trigger requires the campaign to be on the character's world.
6. **API and commands:** §5.2, excluding approve.
7. **Authorization:**
   - GM `canon.edit` now;
   - `character.propose_build` holders only after P03-B/C. The path is coded behind the port and refuses until the P03 contract is present;
   - draft reads are limited to the author and `canon.edit` holders.
8. **Migration:** new table.
9. **Compatibility:** no existing command touched.
10. **Automated tests:**
    - status machine;
    - failed validation preserves content;
    - stale `row_version` is refused;
    - idempotency;
    - a non-author player cannot read;
    - audit carries no payload;
    - unequal previews have unequal fingerprints;
    - T15 (draft half), T20.
11. **Manual acceptance:** a GM drafts a build with a custom feature and sees `unsupported`.
12. **Performance:** bounded payloads.
13. **Rollback:** drop the table.
14. **Branch dependencies:** none.
15. **Completion criteria:** tests pass.
16. **Gates:** §3.

### R19-P3d-2 — Approval, immutable materialization, direct-create review, activation gate

1. **Objective:** ADR 0023 §7.2–7.6 in full.
2. **Prerequisites:**
   - P3d-1;
   - **P03-C build scope merged**, so approval passes `build_scope`;
   - OD-9 recorded (Owner-approved 2026-11-03);
   - P03-S cutover for build activation, because approval activates into the route campaign's state;
   - build-command owner sign-off.
3. **Existing modules:** `commands/character_builds.py` (create, activate), `api/character_builds.py`.
4. **New or modified modules:**
   - migration (`character_build_reviews`, `character_build_custom_mechanics`, decision and outcome lookups);
   - `approve_build_draft`, `review_character_build`;
   - `create_character_build(custom_mechanics=…, review=…)`: **no reference-waiver parameter**;
   - the direct-create path records a review only when valid;
   - the `activate_character_build` gate.
5. **Schema:** ADR 0023 §7.5.
6. **API and commands:** §5.2.
7. **Authorization:**
   - approval follows ADR 0021 §5 for the resulting scope;
   - `approved_as_rules_exception` is limited to `canon.edit` holders and never available to delegated proposers;
   - an exception never waives authorization, scope, references or payload safety.
8. **Migration:** new tables. Existing builds read `not_evaluated`.
9. **Compatibility:**
   - the direct-create endpoint and its request shape are preserved;
   - **behavior change:** non-valid new builds are created unreviewed and cannot be activated until reviewed. Legacy builds stay usable as `not_evaluated` until explicitly reviewed under this policy (OD-9).
10. **Automated tests:**
    - approval re-validates under lock;
    - a draft changed after validation re-validates;
    - incomplete or unsupported needs adjudication;
    - invalid needs an exception plus a reason;
    - an exception cannot reference another world's homebrew, a draft definition or a cross-version definition (integrity holds);
    - a draft-definition reference must be published or converted to a custom mechanic;
    - the build has no FK to the draft;
    - the review stores the manifest;
    - findings unchanged after approval (T16);
    - **direct-create bypass (T27):**
      - a GM direct-creates an incomplete build and it is unreviewed;
      - activation is refused, then succeeds after `review_character_build` with adjudication;
      - a delegated player cannot direct-create;
    - **invalid-but-computable (T28):**
      - values compute;
      - the label is "Invalid" plus "Rules exception approved", never "Rules-validated";
    - legacy builds are activatable and labeled `not_evaluated`;
    - concurrent approve and withdraw have one winner;
    - existing build tests pass with the direct-create path unchanged for valid builds.
11. **Manual acceptance:** T15 and T16 with the GM review queue (API).
12. **Performance:** one bundle load per approval.
13. **Rollback:** downgrade only while no review exists; afterwards restore from backup.
14. **Branch dependencies:** P03-C.
15. **Completion criteria:** owner sign-off of the behavior change; tests pass, including T83 (OD-9 is recorded).
16. **Gates:** §3.

### R19-P3e-T — Equipment modifiers (truth mode)

- **Item mechanics:** `mechanics_schema_code`, `mechanics_schema_version` and `mechanics_jsonb` on `rules.item_definitions`, plus `rules.item_definition_mechanic_references`. Mechanics are draft-mutable and canon-immutable. Existing columns are unchanged and covered by content hashes.
- **5e schema:** `dnd5e_item_mechanics.v1`.
- **Loading:** equipped and attuned items.
- **Missing mechanics:** an item without mechanics contributes nothing and raises an `item_without_mechanics` warning. Nothing is inferred from names.
- **Sign-off:** item-domain owner.
- **Tests:**
  - armor plus shield plus feature;
  - unequipped items don't contribute;
  - attunement-required items contribute only when attuned;
  - canon mechanics are immutable;
  - editing a homebrew item's existing `requires_attunement` changes the content hash, and a stored review reports `inputs_changed` on recomputation.
- **Gates:** §3.

### R19-P3e-A — Audience mode

- **Gate:** requires **P03-A projection tiers accepted**. The controller audience additionally requires **P03-B accepted** (`may_operate` and the controller projection).
- **Behavior:** the bundle contains only viewer-visible inputs. Unidentified item properties (`knowledge.item_identification`) and GM-hidden effects are excluded before evaluation, with no marker. The fingerprint covers the audience bundle only.
- **Tests:**
  - **T7:** a hidden cursed item changes truth AC, while audience AC, trace, counts and fingerprint are unchanged and reveal nothing;
  - an undiscoverable character gives a non-disclosing refusal;
  - a controller after revocation is refused on the next request.
- **Gates:** §3.

### R19-P3f — Contract freeze and Phase 16 guide

- **Contents:**
  - JSON Schemas `docs/schemas/rules_result.v1.json`, `rules_manifest.v1.json`, `validation_report.v1.json`, with drift tests;
  - `POST …/mechanics/preview`;
  - `docs/R19_PHASE16_CONSUMER_GUIDE.md`.
- **Neutrality:** already proven in P3a. P3f re-runs the percentile fixture against the frozen schemas.
- **Gates:** §3.

### R19-P4 — Full delivery (after Phase 17)

| Item | Scope | Dependencies |
|---|---|---|
| P4a | Template-basis builds; persistent creatures; player-controlled creatures | P03-B/C, P2d, P3d-2 |
| P4b | ADR 0022 E1–E14; combatant state; spawning (pending and active); participant actors and targets; promotion in the corrected order; discovery-gated promotion links. The character-damage `last_event_id` repair is **P03-S**, not P4b | Phase 15 encounter owner, P4a, ED-3; OD-11 (Owner-approved: no promotion during an active encounter; T84) |
| P4c | Advancement; structured prerequisites and exclusions | Phase 16, P3d-2, P3f |
| P4d | Content packages; operator install | P2a, OD-7 rights clearance or replacement, Phase 17 |
| P4e | Encounter analysis (GM-only, manifest-stamped) | P4a/b, P3e |
| P4f | Portal workflows | All of the above |
| P4g | PLANv2 19.8 acceptance; `PHASE19_VERIFICATION.md` | All of the above |

---

## 7. Cross-phase analysis

- **Phase 15:**
  - P03-A supplies projection tiers (P3e-A) and revelation (OD-17);
  - P03-S supplies campaign-scoped mechanical state (OD-1, Owner-approved), lineage seeding and the migration;
  - P03-B supplies control, operations and clock rules (OD-2/3/4/14);
  - P03-C supplies authoring (OD-5/19), build scope (OD-6), portrayal and eligibility.
  - Builds stay immutable. Item and encounter commands are extended only under owner sign-off. R19 never rewrites history, and no early R19 checkpoint changes state writers.
- **Phase 16:**
  - Manual player authoring uses **P3d-1 drafts**, which may be entirely custom (support `none`) and are labeled "not rules-validated", plus **P3d-2 review** by the GM with adjudication.
  - If Phase 16 is ready before P3d-2, P3d-2 is prioritized. No disposable builder is built.
  - Delegation comes from P03-B/C (`character.propose_build`).
  - **Player portrayal guidance** is a campaign-scoped, controller-owned profile (OD-18). Live primary and co-controllers edit it through `character.edit_player_profile`, conferred by control (OD-18 clarification, 2026-11-04). It is never `npc_portrayal_profiles`, it grants no GM portrayal access, and it is not `character.edit_narrative` or any canonical narrative editing.
  - Option policy filters choices (P2b-2). Source text is never exposed through the builder.
- **Phase 17:**
  - R19 migrations are additive and are covered by Phase 17's upgrade, backup and restore verification.
  - **P03-S state** must be included in backup and restore: campaign mechanical tables, initialization markers, migration records, lineage and transfer-request tables, and the read-only legacy tables.
  - The P03-S migration runs in **stopped-writer windows**, with a verified backup taken in each window immediately before cutover. After divergence, rollback is restoring that backup (T55).
  - An upgrade from a pre-P03-S release must stop at manifest review. Unreviewed rows stay in GM-only dual-read, and no `multi_campaign` mapping is applied automatically (T62).
  - Backup and restore must preserve complete versus pending families, quarantined state and its resolutions, the effect registry and event attributions, and per-campaign divergence (T69).
  - The seed stays `unknown` / `unreviewed` until the OD-7 evidence inventory is complete. Documented rights clearance or replacement is required before the **next distributed artifact containing it**: a release image, installer or public repository publication, and no later than the Phase 17 packaging gate. OD-7's approval is not licensing clearance. Under OD-7a (Owner-approved 2026-11-04) the seed already in the public repository is treated as potentially distributed: the requirement already applies to it, and R19-P2a is prioritized.
  - There is no startup dependency on packages, AI or external providers.
- **Phase 18:** imports produce drafts (builds, templates, house rules, homebrew), validated and reviewed through the same path. No direct canon or build writes.
- **Phase 20:**
  - AI explains traces and cites manifest fingerprints.
  - Player-purpose contexts use audience-mode results only.
  - AI never originates numbers.

---

## 8. Acceptance and compatibility scenarios

Layer key: **db** (database test), **scen** (scenario test), **man** (manual), **unit** (unit test).

| # | Scenario | Checkpoint | Layer | Key assertions |
|---|---|---|---|---|
| T1 | One world character, controlled by different players in two campaigns, on different timelines **and on the same timeline** (OD-1) | P03-B, P03-S | db, scen | One UUID; independent assignments and mechanical state; no `canon.edit` |
| T2 | NPC assigned to a player | P03-B | db | UUID, build and portrayal unchanged; no perspective or private reads from the assignment |
| T3 | Player-controlled monster with no class or level | P03-B, P4a | db, man | Assignment works with no build or a template basis |
| T4 | Character without an active build | P3b | db | `missing_input`, not an error |
| T5 | Co-controller loses access | P03-B | db | Next operation refused; in-flight operation serialized by the anchor |
| T6 | Controller removed while another grant remains | P03-A/B | db | Legacy viewer, private and perspective grants survive; play gone |
| T7 | Hidden character or hidden item mechanics do not leak | P03-A, P3b, P3e-A | db | Refusals non-disclosing; audience values and fingerprints unchanged by hidden inputs |
| T8 | World character with campaign-specific option restrictions | P2b-2 | db | A's allow-list does not affect B |
| T9 | Template updated after instances exist | P2d, P4a/b | db | Pinned versions unchanged |
| T10 | Four unnamed goblins | P4b | db, man | Four participants, no entities, labels only for members |
| T11 | One goblin promoted | P4b | db, man | Order: character, publish, build, state (event), activation, link. Idempotent replay. Link only for discoverers |
| T12 | Historical encounter after a template update | P4b | db | Actions and pins unchanged |
| T13 | House rule overrides a baseline | P2c, P3c | db, unit | Trace cites the rule version; fingerprint includes the configuration |
| T14 | Conflicting second house rule | P2c, P3c | db | `conflicting` until acknowledged |
| T15 | Player submits an unsupported advancement option | P3d-1/2, Phase 16, P4c | db, man | Draft saved; `unsupported`; player cannot approve |
| T16 | GM approves unsupported content | P3d-2 | db | Findings preserved; never labeled rules-validated |
| T17 | Player-owned source not shared | OD-12, OD-12a, ED-8 (Phase 18/20) | db | A player-registered source is `contributor_private`. Its text, citation metadata and AI retrieval are invisible to every other user, GMs included, until the contributor's explicit grant (see T87) |
| T18 | Two campaigns, different versions | P3b, X4, P03-S | db | Each campaign activates and evaluates its own version's build. A build of the wrong version is refused by the per-campaign guard. Before P03-S: `legacy_shared_state` label |
| T19 | Non-D&D archetype | P3a | unit | Percentile fixture passes with core types only |
| T20 | Invalid or stale preview | P3d-1/2 | db | Stale `row_version` refused; approval re-validates |
| T21 | Migration preserves portrayal, builds, history, UUIDs | P03-C | db, man | Counts, chains and access compared |
| T22 | **Regression: shared timeline, same ruleset** (ADR 0021 §3.10) | P03-S, P03-B | db, scen | A and B activate different builds; HP, condition, resource, equip and attunement changes in A leave B unchanged; both campaigns' controllers act concurrently on separate rows; encounter damage in A affects A only; travel stays shared (OD-20) |
| T23 | **Regression: shared timeline, different ruleset versions** | P03-S, P3b | db, scen | Each campaign's build, adapter and support level apply independently; a cross-campaign build copy is refused for version mismatch and listed; no `incompatible_ruleset_version` in normal use |
| T24 | Branch campaign lineage | P03-S (enablement per ADR 0021 §3.6) | db | Without a lineage, the campaign starts empty. With an enabled, authorized seed, see T40. Later source changes never propagate |
| T31 | Mechanical-state migration manifest | P03-S | db, man (restored copy) | `single_campaign` proposed, `multi_campaign` stays legacy (`legacy_shared_state`, read-only), `no_campaign` legacy, `branch_inherited` needs lineage; no ownership inferred; migration records written; rollback before cutover leaves legacy byte-identical |
| T32 | Explicit cross-campaign copy | P03-S (enablement per ADR 0021 §3.6) | db | Writes the target only, with an event citing the source; per-component preview and approval; invalid components skipped and listed; see T42–T45 |
| T33 | Mechanical events need a campaign | P03-S | db | A new mechanical effect on an event without a campaign is refused; a campaign-less encounter cannot apply damage; correction restores only the event's campaign |
| T34 | Per-campaign item mechanics | P03-S | db | One active possession and attunement per (campaign, item); the three-attunement limit per (campaign, character); B unaffected by A |
| T35 | Campaign-scoped evaluation identity | P3b, P3e-A | unit, db | Identical state in A and B gives different fingerprints; a memo for A is never served to B; a controller of A gets refused or non-disclosing for B's values |
| T36 | Two campaigns share character K, each with independent inventory (OD-20) | P03-S | db, scen | Awards, transfers, equips and attunements in A never appear in B; one active possession per (campaign, item) |
| T37 | Fictional ownership changes with no mechanical transfer | P03-S | db | `change_item_ownership` updates the shared owner, with a narrative event at a world time; possession, item state and attunement are unchanged in every campaign; `award_item` without an explicit owner leaves ownership unchanged |
| T38 | Mechanical item use without an ownership change | P03-S | db | Consume, charge use, equip, attune and damage in A change only A's rows; `item_ownership` and B are unchanged |
| T39 | A player controller attempts an unauthorized shared-world change | P03-B, P03-S | db | Changing ownership or location with only a control assignment is refused, non-disclosing; no event; the assignment cannot reach `change_item_ownership`, movement or travel |
| T40 | Authorized lineage seeding at a branch point (after enablement) | P03-S (OD-21) | db | Request, then preview with per-component outcomes, then a separate approval; rows `lineage_seeded`; lineage row records source, branch point and approver; source fingerprint unchanged; `history_unavailable` components reported, not filled |
| T41 | Unauthorized source-campaign access during seeding | P03-S (OD-21) | db | No `mechanics.transfer_read` in the source gives a non-disclosing refusal, with no preview and no hint of the source's state; a world Owner with no campaign role and a target-only GM are both refused |
| T42 | Cross-campaign copy between different ruleset versions | P03-S (OD-21), P3b | db | Build and definitions outside the target version are reported `incompatible_version` and skipped; compatible components are copied after approval; the target evaluates under its own version |
| T43 | Duplicate requests and concurrent target updates | P03-S (OD-21) | db | A replay with the same key returns the original result; a target change after preview makes the apply fail with `stale_preview` and a new conflict report; no overwrite; concurrent approvals give one winner |
| T44 | Hidden or player-private information stays protected | P03-S (OD-21), P3e-A | db | Previews and copies contain mechanical components only, never player-private notes, briefings, GM notes, Knowledge or identification; target members see results only through target projections; provenance is GM-only |
| T45 | Disabled commands refuse until enablement acceptance | P03-S | db | Seed and copy requests return `feature_not_enabled` (non-disclosing) for every caller, including fully authorized ones, until the enablement review is recorded |
| T46 | Cross-campaign event visibility (R19-10) | P03-S (G4) | db | A mechanical-only event of A is absent from B's lists, counts, cause and correction links, detail (404), preview and correction (404); no value, name, reference, placeholder or status leaks |
| T47 | Mixed event (narrative and mechanical) | P03-S | db | B sees the narrative part only; B's GM cannot preview or correct it (404); A's GM corrects atomically; one irreversible part means nothing is reversed |
| T48 | Legacy mechanical events (universal disclosure rule) | P03-S | db | Before the G4 cutover, behavior is unchanged. After it, a legacy effect with a seeded `campaign_mechanical` code, on an event with or without a `campaign_id`, is withheld from every audience (including that campaign's GM, world roles, controllers and the recorder). It is absent if purely withheld, and preview, void and correct return 404, until a `migration_reviewed` origin attribution is recorded. It is never shown as `legacy_shared_state`. Afterwards only the attributed campaign reads and corrects it. The GM-only `legacy_shared_state` character-state dual-read is unchanged |
| T49 | Sequential A/E1 → B/E2 → correct E1 (R19-11) | P03-S (G3) | db | E1 (A, award with ownership) and E2 (B possession) → correcting E1 reverts A's possession and the shared owner, and leaves B untouched. Variant: E2 changes ownership → the whole E1 correction is refused, with side `ownership` and no B data |
| T50 | Mixed operation tokens | P03-S (G3) | db | A stale ownership token, or a stale campaign token, refuses the whole operation and names the stale side; an idempotent replay returns the original result; one audit row per state family; fingerprints include both tokens and the intent |
| T51 | Ownership intent required (R19-12) | P03-S (G3) | db, unit, portal | An API award or transfer without `ownership` gives 422; the command needs the keyword (mypy and tests); the portal `AwardItemSection` sends an explicit choice; `unchanged` keeps the owner; `assign_to_holder` needs both authorizations; controllers cannot request it |
| T52 | Bounded controller path (residual R19-02) | P03-B, P03-S | db | An allow-listed controller intent succeeds without `canon.edit`; the canonical command still refuses the controller; an assignment revoked before the scope lock gives a refusal; a non-allow-listed parameter or another actor is refused |
| T53 | Manifest-to-live validation (family level) | P03-S | db, man (restored copy) | The membership and member hashes are recomputed live; any drift makes the whole family pending (see T66); deleted members are never resurrected |
| T54 | Explicitly empty versus uninitialized state | P03-S | db | An initialized family (including `empty_confirmed`) never falls back to legacy rows; an uninitialized or `pending_drift` family falls back to the GM-only labeled legacy value; players, controllers and audience mode get no state |
| T55 | Cutover groups, stopped writers, rollback | P03-S | man, db | G4 switches no later than the first of G1–G3; write-block triggers apply per group; the in-window backup restores cleanly; post-divergence rollback restores that backup and discards later writes |
| T56 | Item definition from another ruleset version (R19-8) | P03-S, P3e-T | db | Possession, equip and ownership are allowed; attune is refused (`item_definition_version_mismatch`); the engine marks the facts `incompatible_ruleset_version` and maps nothing |
| T57 | OD-21 indirect paths | P03-S, P3d-2, P4b, Phase 18 | db | Build approval and activation, item award and transfer, encounter damage and promotion, Foundry sync, quest rewards, import promotion and AI proposals never read or write another campaign's mechanical state |
| T58 | OD-21 revoked-access replay | P03-S (after enablement) | db | Replays return id-only receipts; reading a preview after revocation is refused, non-disclosing; approval and apply after revocation fail |
| T59 | OD-21 safe conflict and provenance (ED-17) | P03-S (after enablement) | db | Target events carry only applied values and an opaque request id; the protected transfer record (source id, snapshot, conflicts) is readable only with current source read and target capability; approval responses are id-only receipts; audit holds no values |
| T60 | OD-21 source snapshot | P03-S (after enablement) | db | Apply writes the previewed snapshot; a source or target change after the preview gives `stale_preview` |
| T61 | OD-21 runtime seeding uses only proven branch-time history (after enablement) | P03-S (OD-21) | db | Untimed administrative baselines give `history_unavailable` in the preview and are never seeded; event-linked history bounded at the branch point is seeded. Offline migration acceptance is **T63**, not this test |
| T62 | Phase 17 backup, restore and upgrade of P03-S state | Phase 17 | man | Restore preserves campaign tables, initialization markers, migration records, transfer requests and read-only legacy tables; an upgrade from a pre-P03-S release requires manifest review and leaves unreviewed rows in GM-only dual-read |
| T63 | Reviewed offline migration acceptance (separate from runtime seeding) | P03-S | db, man (restored copy) | Families apply only under a reviewed manifest, in stopped-writer windows, through operator tooling; no runtime `mechanics.*` capability is used or granted; `branch_inherited` families apply only with the explicit `materialize_inherited` disposition; ordinary P03-S completion needs no transfer command |
| T64 | Effect-registry coverage and fail-closed classification (R19-14) | P03-S (G4) | unit, db | A source scan proves every emitted code is registered; the foreign key refuses an unregistered code; readers resolve classes only through the registry, and a code missing from a reader's local mapping is withheld; an `unclassified` effect reaches **no** application audience, including the origin campaign's GM and every `canon.edit` holder on the timeline, on any surface (T70–T73) |
| T65 | Cross-campaign end-attunement | P03-S (G3, G4) | db | A ends K's attunement to X (`item_attunement_ended`). B's attunement row, limit count and events are unchanged; A's event is absent from B's lists, counts and links; B cannot preview or correct it |
| T66 | Family drift (R19-15) | P03-S | db, man | A member added, changed or deleted after S0 makes the **whole** family `pending_drift`: nothing written, no initialization marker, the GM-only legacy fallback remains, returned for review |
| T67 | Partial review, replacement, empty and retry | P03-S | db | A partial member review is not applied; `reviewed_replacement` writes exactly the reviewed set; `empty_confirmed` writes only a marker; an unconfirmed empty family stays uninitialized; a retry with the same membership hash is skipped; a different hash is refused |
| T68 | Incompatible migrated attunement cleanup (R19-16) | P03-S (G3) | db | A migrated attunement whose item definition is another version is quarantined: no contribution, counted toward the limit. `end_item_attunement` in that campaign succeeds; a later transfer there changes only its rows; legal ownership and other campaigns are unchanged; attune and charge interpretation stay refused |
| T69 | Phase 17 backup and restore of divergent and partially migrated state | Phase 17 | man | Restore reproduces complete and pending families, initialization markers, quarantined rows and their resolutions, the effect registry, event attributions, campaign divergence between A and B on one timeline, and read-only legacy tables. Restoring the pre-cutover backup discards later divergence as documented |
| T70 | Unclassified effect on an event with a `campaign_id` (residual R19-14) | P03-S (G4) | db | Campaign A's event carries an `unclassified` effect. A's GM (`canon.edit`), A's players and controllers, and B's GM receive no value, component name, reference, placeholder, count or status for it in lists, counts, cause and correction links, explanations, the authoring view or calculations. If every effect of the event is unclassified, the event is absent from all lists and counts, and a direct read returns 404. Preview, void and correct return 404 to A's GM too |
| T71 | Classified mechanical effect, no `campaign_id` (universal rule) | P03-S (G4) | db | A campaign-less event carries an effect whose code the **seeded** registry classifies as `campaign_mechanical` (for example `current_hit_points`). Second case: an `unclassified` effect. No GM of any campaign on the timeline, no world Owner, Editor or Reviewer, no controller and no recorder receives anything from either, in any list, count, link, explanation, authoring view, preview, void or correct. Neither is labeled `legacy_shared_state`. After a `migration_reviewed` origin attribution to A is recorded, the classified effect becomes visible and correctable in A only; B still receives nothing. Raw rows and the event's `campaign_id` are unchanged |
| T72 | Mixed events with unclassified effects (residual R19-14) | P03-S (G4) | db | Narrative + unclassified: each audience receives exactly what it receives for the same event without the unclassified effect, including the effect count. Narrative + known mechanical (origin A) + unclassified: A's GM sees the narrative and mechanical parts, B's GM sees the narrative part, and neither sees the withheld part. Preview, void and correct return the single 404 to every caller, and nothing is reversed |
| T73 | GM of another campaign sharing the timeline (residual R19-14) | P03-S (G4) | db | Campaigns A and B are on one timeline. For A's events and campaign-less events with unclassified effects, B's GM receives nothing derived from those effects in lists, counts, links, explanations, the authoring view, previews or corrections. B's effect counts equal the counts of the classified effects B may see. B's correction attempts return the single 404 with no reason |
| T74 | Migration review, classification and attribution (residual R19-14, stricter rule) | P03-S | db, man (restored copy) | Raw withheld rows are readable only in the §3.8 step 2a workflow on the restored copy, and no application route returns them. A reviewed classification migration alone releases nothing. A `campaign_mechanical` effect, whether its code was seeded or classified in review, with or without an event `campaign_id`, stays withheld from every audience and never appears as `legacy_shared_state` until a reviewed origin campaign is recorded; afterwards it follows that origin campaign's mechanical-effect rules (lists, detail, counts, links, explanations, preview, void, correct) and no other campaign receives it. A `shared_knowledge` effect stays withheld until its knower or audience is recorded. No origin is derived from timeline membership, character control, campaign relationships, the event's creator, session, encounter or request route. An event's `campaign_id` may only **propose** a mapping. A bulk approval of evidence-supported proposals lists its exceptions and records one attribution per effect. Genuinely ambiguous effects stay withheld. Raw effect rows, the event's `campaign_id`, references, provenance and audit history are byte-identical before and after release; the attribution is a separate record |
| T75 | Unattributed mechanical effect on a shared timeline (residual R19-14, regression) | P03-S (G4) | db | Campaigns A and B share a timeline. An effect classified `campaign_mechanical` (run once with a seeded code and once with a code classified in review) has no recorded origin; one case has a campaign-less event, the other an event carrying A's `campaign_id`. Neither A's GM nor B's GM receives its value, name, existence or count from event lists, detail, counts, links, explanations, the authoring view, preview, void or correct, nor through any `legacy_shared_state` explanation or dual-read value. A controller of the character in A and the event's recorder in A also receive nothing |
| T76 | G4 attribution readiness gate (confirmed policy) | P03-S (G4) | man (restored copy), db | The report counts and identifies reviewed, withheld, ambiguous and failed historical effects and lists the bulk-approval exceptions. Without a recorded operator approval, G4 does not run. With unresolved effects, the approval must state that they stay withheld. After cutover those effects are withheld (T48, T75), and failed records are never released |
| T77 | Attribution immutability and new-effect release (confirmed policy) | P03-S (G4) | db | A new mechanical effect written by an authorized command in A is released on commit, with one `authorized_at_write` attribution to A and no review step. Correcting or voiding it, editing the event, and an idempotent replay leave its attribution unchanged. A replay writes no new attribution. The correcting event's mechanical effects are attributed to A in the same transaction. A mixed correction from B returns 404 and writes nothing. Only a new reviewed migration record can supersede a `migration_reviewed` attribution, and the old one stays in history |
| T78 | Co-controllers survive primary revocation (OD-2) | P03-B | db | A has primary P1 and co-controllers C1, C2. Revoking P1 leaves C1 and C2 live with the same operations, promotes nobody, and leaves no primary; a new primary appears only by an explicit assignment. Neither P1 nor C1 can assign or revoke control |
| T79 | Assignment authority (OD-4) | P03-B | db | `campaign_owner` and `gm` assign and revoke. An `assistant_gm` without a delegation is refused (non-disclosing); with a live OD-4a delegation it succeeds (T86). A controller is refused |
| T80 | Controller operation allow-list (OD-3) | P03-B, P03-S | db | A controller adjusts HP within bounds, sets temporary HP, expends and recovers a named resource, applies a designated self-manageable condition, and equips, unequips, attunes and ends attunement for an item K possesses in A. Each refused: maxima, a non-designated condition, an encounter command, location or ownership change, possession transfer, canon or build authoring, another actor. Attuning an item of another version is refused (ED-12) |
| T81 | New player character as a campaign-scoped pending record (OD-5) | P03-C | db | A's GM without a world role creates PC Q: Q is `draft`, with origin A. B's GM cannot see or edit Q. A's GM cannot publish Q or grant any delegation. A world reviewer with route `canon.edit` publishes Q after submission; afterwards A's GM edits only under a delegation granted with `world.canon.review` |
| T82 | Revelation and player profile disclose nothing private or unreleased (OD-17, OD-18) | P03-A, Phase 16 | db | A member revelation, a group revelation, and campaign-wide current-only and current-and-future revelations each reach exactly their audience; a member who joins later is included only by the second kind. Audiences see only deliberately released versions, never drafts, GM-private fields, the GM view or derived mechanics. The player profile is readable by A's GMs and K's controllers in A only; a field reaches other audiences only through a revelation or OD-5 review. Editing is T85 |
| T83 | Rules exceptions never bypass integrity (OD-9) | P3d-2 | db | A campaign canon editor approves a prerequisite violation as a rules exception with a reason; the validation outcome stays `invalid` and the label shows the exception. A delegated proposer and a controller cannot. An exception cannot admit a cross-world, wrong-version or non-canon reference, an oversized payload, or a missing manifest. A legacy build activates as `not_evaluated` until it is reviewed |
| T84 | No promotion during an active encounter (OD-11) | P4b | db | Promotion is refused while the encounter is `pending` or `active` and succeeds once it is `completed` or `aborted`; no delegation substitutes for world authority |
| T85 | Controllers edit the player profile, not canon (OD-18 clarification) | P03-A, P03-B, Phase 16 | db | K's primary P1 and co-controller C1 in A each edit K's player profile in A; each version is attributed to its editor. Neither edit changes `character.character_descriptions`, any world-canon field, `npc_portrayal_profiles`, mechanical state, or K's profile in B. Both are refused `character.edit_narrative`, canonical identity edits, GM-private portrayal and GM-private fields. A member who is not a live controller is refused. After P1's assignment is revoked, P1's next edit is refused, and an edit holding the anchor lock completes first. No field reaches another audience without an OD-17 revelation or OD-5 review |
| T86 | Assistant-GM delegation of control assignment (OD-4a) | P03-B | db | A's Owner delegates `character.assign_control` to assistant GM G, who then assigns, replaces and revokes control in A but not in B. G's attempt to delegate to another assistant GM is refused, including through a custom role or resource grant. A delegation to a membership without `assistant_gm` is refused. A's GM revokes it; G's next assignment is refused and G's earlier assignments stay in force. A separate delegation granted by GM H stays in force after H loses the `gm` role. Grant and revoke are audited with their reason |
| T87 | Contributor-only authorization of private sources (OD-12a) | Phase 18/20 | db | A GM, an `access.manage` holder, the world Owner and a system Admin each fail to grant themselves or anyone access to a `contributor_private` source, through `create_resource_grant` and through a campaign retrieval grant, and each sees nothing about it. The contributor grants GM X access; X then sees exactly what the grant permits in citations and AI retrieval, and nobody else gains access. The contributor's revocation removes it on the next request |
| T88 | Seed rights inventory and status (OD-7, OD-7a) | R19-P2a | man, db | The inventory lists every seed file and definition with its evidence and disposition (cleared with documentation, replaced, or outstanding). The seed package stays `unknown` / `unreviewed` with no license claimed; only documented clearance changes an item's status, and only for that item |
| T25 | Control migration and concurrency (ADR 0021 acceptance list) | P03-B | db | Index replacement; one-primary race; revoke vs operation; empty-set anchor; clock boundaries; branch has no inheritance |
| T26 | PC used by A and B, unrelated C on the world | P03-C, OD-19 | db, man | `pending` exception keeps A, B and C; `replace` removes only unnamed campaigns, recorded |
| T27 | Direct-create bypass | P3d-2 | db | Unreviewed build cannot activate until reviewed; delegated player cannot direct-create |
| T28 | Invalid but computable build | P3d-2 | db, unit | Values compute; labels "Invalid" and "Rules exception", never "Rules-validated" |
| T29 | Combatant integration inventory | P4b | db | Every E1–E14 path: start, turn by participant, targets, check refusal, outcomes, readers include combatants, member projection, Foundry refusal |
| T30 | Fingerprint inputs | P3a/b, P3e-T | unit, db | Unequal previews; truth vs audience; encounter damage without a token; attunement; mutable definition field; branch and as-of requests |

---

## 9. Decision register

**Owner decisions** are product policy, and each is **UNRESOLVED** unless the status says otherwise. A recommendation is advice only; it is **never encoded before it is recorded**. The deadline is the gate the decision blocks.

| ID | Decision | Alternatives | Recommendation | Consequences | Implementation owner | Deadline (blocked gate) | Status |
|---|---|---|---|---|---|---|---|
| OD-1 | Shared-timeline mechanical-state semantics | — | **Decided by the owner:** campaigns sharing a world or timeline maintain independent mechanical character state (active build, HP, conditions, resources, mechanical equipment and inventory, temporary effects); rulesets and versions may differ; no cross-campaign mechanical effect without an explicit authorized operation. The earlier single-campaign-timeline proposal is withdrawn | Campaign-keyed tables, lineage seeding, a manifest migration (ADR 0021 §3) | Phase 15 P03-S (schema, commands); Phase 19 (campaign-scoped calculation) | — | **Owner-approved 2026-11-02** |
| OD-2 | Co-controller authority; behavior when the primary is revoked | — | **Decided by the owner:** primary and co-controllers receive the same bounded gameplay operations. Neither manages assignments. Revoking a primary does not revoke co-controllers or automatically promote one | `CONTROL_ASSIGNMENT_CAPABILITIES` is identical for both roles and excludes `character.assign_control` (ADR 0021 §2.5) | P03-B | — | **Owner-approved 2026-11-03** |
| OD-3 | Initial controller operation allow-list | — | **Decided by the owner:** HP and temporary HP; named resource expenditure and recovery; explicitly self-manageable conditions; the controller's eligible equipment and attunement operations. No encounter commands, shared narrative changes, ownership transfers or canon authoring through control | Closed `CONTROLLER_OPERATIONS` (ADR 0021 §2.5a). Self-manageable conditions need an explicit campaign designation under OD-10 | P03-B | — | **Owner-approved 2026-11-03** |
| OD-4 | Who holds `character.assign_control` | — | **Decided by the owner:** Campaign Owners and GMs may assign or revoke control. Assistant GMs require explicit delegation | `campaign_owner` and `gm` hold it; `assistant_gm` only through an explicit delegation (ADR 0021 §2.7). The delegator is settled by OD-4a | P03-B | — | **Owner-approved 2026-11-03** |
| OD-5 | Delegation granter and revoker authority; new player-character creation without a world role | — | **Decided by the owner:** canonical character authoring delegation is governed by world-authorized review and appropriate campaign authority. Campaign GMs cannot grant themselves world-canon rights. New player characters may begin as campaign-scoped pending records without a world role; publication into world canon follows authorized review | Grant and revoke need `world.canon.review` plus route `canon.edit`; campaign-scoped pending records via `character.character_authoring_origins`; no delegation path for promotion (ADR 0021 §4.3, §4.4; ADR 0022 §6) | P03-C | — | **Owner-approved 2026-11-03** |
| OD-6 | Whether campaign-scoped builds exist (build scope) | — | **Reconciled with owner-approved OD-1, per the owner's 2026-11-02 instruction:** campaign-scoped builds are permitted on any timeline and selectable only by their origin campaign; `world_shared` builds are selectable by any campaign with a matching version | Delegated campaign builds need no world authority | P03-C | — | Reconciled (owner instruction 2026-11-02) |
| OD-20 | Shared narrative ownership and campaign-specific mechanical possession | — | **Decided by the owner:**<br>• Character location and fictional/legal item ownership stay world/timeline narrative.<br>• Possession, inventory, equipment, attunement, charges, quantities and other mechanical item state are per campaign.<br>• Inventory changes never change ownership automatically.<br>• Ownership and location changes need canonical authorization and a temporal workflow.<br>• Control never suffices. | `award_item` default removed; `change_item_ownership` added; ownership effects decoupled from possession; ownership and location tables stay shared (ADR 0021 §3.1.1) | P03-S (Phase 15 owner sign-off for the `award_item` behavior change) | — | **Owner-approved 2026-11-02** |
| OD-21 | Separate authorization for lineage seeding and cross-campaign copy | — | **Decided by the owner:**<br>• Two distinct operations.<br>• Each needs explicit source-read **and** target authorization, plus explicit target approval.<br>• Each has a preview, provenance, audit and idempotency.<br>• Neither mutates the source; there is no inferred lineage and no synchronization.<br>• Control grants neither, and world ownership does not open player-private information.<br>• **Both stay disabled until security, compatibility and acceptance tests pass. Approval does not enable them.** | ADR 0021 §3.6: request and approve commands; `mechanics.transfer_read`, `mechanics.seed`, `mechanics.copy_in` (ED-11); transfer-request table; T40–T45 | P03-S, with enablement in a later reviewed step | Enablement review (not an owner decision already taken) | **Owner-approved 2026-11-02** (commands remain disabled) |
| OD-22 | Whether a shared narrative record of an unheld item's whereabouts is wanted at all | — | **Decided by the owner:** no world-shared record of an unheld item's whereabouts at this stage. Item whereabouts stay campaign-specific under OD-20. A future canonical-placement feature needs a separate proposal and approval | Campaigns may disagree about where an unheld item lies (ADR 0021 §3.1.1) | Not assigned | — | **Owner-approved 2026-11-03** |
| OD-7 | Seed origin and distribution review | — | **Decided by the owner:** seed provenance stays `unknown` / `unreviewed` until an evidence inventory is complete. Before distribution, documented rights clearance or replacement of uncleared content is required. **This approval is not licensing clearance** | No license claim; clearance or replacement before the next distributed artifact (ADR 0023 §4). The current public repository is settled by OD-7a | Owner; R19-P2a supplies the inventory | — (the clearance itself gates the next distributed artifact; Phase 17 packaging at the latest) | **Owner-approved 2026-11-03** |
| OD-9 | Rules-exception approval, and whether legacy builds are exempt from the activation gate | — | **Decided by the owner:** campaign canon editors may approve supported rules exceptions with a recorded reason. Exceptions never override integrity or authorization constraints. Existing builds stay usable as `not_evaluated` until explicitly reviewed under the new activation policy | ADR 0023 §7.4, §7.6. The behavior change still needs owner acceptance at P3d-2 | R19-P3d-2 | — | **Owner-approved 2026-11-03** |
| OD-10 | Authority for house rules and option policy | — | **Decided by the owner:** campaign canon editors manage campaign-specific rules and allowed options. Shared-world rules need the matching world authority plus campaign authorization. Rules and overrides stay versioned | ADR 0023 §6. Commands enforce it and enable with their checkpoint's tests and review | R19-P2b-1, P2c | — | **Owner-approved 2026-11-03** |
| OD-11 | Promotion during an active encounter | — | **Decided by the owner:** no promotion of a lightweight combatant to a persistent character during an active encounter. Promotion may occur after the encounter ends | ADR 0022 §6 (`completed` or `aborted` only) | R19-P4b | — | **Owner-approved 2026-11-03** |
| OD-12 | Player-contributed reference sources | — | **Decided by the owner:** players may register reference sources they are entitled to use. Sources start contributor-private. GM access must be explicitly granted. Citations and AI retrieval enforce source permissions | ADR 0023 §9. The grantor of GM access is settled by OD-12a | Phase 18/20 | — | **Owner-approved 2026-11-03** |
| OD-14 | Control without a clock; dated vs ongoing kinds; the default kind | — | **Decided by the owner:** support explicit ongoing and dated control assignments. Ongoing works without a world clock. Dated assignments stay undetermined without a usable clock; ongoing status is never inferred | No default kind; the kind is explicit on every assignment (ADR 0021 §2.4) | P03-B | — | **Owner-approved 2026-11-03** |
| OD-17 | Revelation audiences and public-profile release semantics | — | **Decided by the owner:** specific-member, group and campaign-wide audiences. Current members are distinguished from future members. Released information follows deliberately published versions, never unpublished edits | ADR 0021 §6. The current-only or current-and-future choice is explicit, with no default | P03-A | — | **Owner-approved 2026-11-03** |
| OD-18 | Player-authored portrayal and profile scope | — | **Decided by the owner:** a campaign-scoped, player-authored portrayal/profile, distinct from world canon and GM-private portrayal. Authorized GMs and controllers can see it. Explicitly selected fields can be published through the appropriate workflow.<br>**Clarified by the owner (2026-11-04):** primary and co-controllers may edit their own campaign-scoped player portrayal/profile. This does not grant `character.edit_narrative`, world-canon editing or GM-private portrayal access. Publication stays governed by OD-17 and OD-5 | ADR 0021 §2.5, §2.8, §4.7, §7: controllers read through `character.view_player_profile` and edit through `character.edit_player_profile`, both conferred by control; `character.edit_narrative` is canonical narrative editing, never conferred by control or a player-authoring grant; the earlier `edit_narrative` profile grant is withdrawn; publication through OD-17 revelation or OD-5 review; T82, T85 | P03-A, P03-B / Phase 16 | — | **Owner-approved 2026-11-03; clarification Owner-approved 2026-11-04** |
| OD-19 | Intentional legacy-access reductions (for example other campaigns' GMs losing PC edit rights) | — | **Decided by the owner:** preserve existing authoring access until an explicit, per-character reviewed disposition authorizes replacement or reduction. Record reasons and affected principals | Legacy exceptions stay `pending` until disposed; no per-world or bulk reduction (ADR 0021 §4.5; T26) | P03-C | — | **Owner-approved 2026-11-03** |
| OD-4a | Who may delegate `character.assign_control` to an assistant GM (residual of OD-4) | — | **Decided by the owner:** Campaign Owners and GMs may explicitly grant and revoke `character.assign_control` for assistant GMs. Delegation is campaign-scoped, auditable and revocable. Recipients cannot redelegate authority | ADR 0021 §2.7, §2.8: grantors hold the built-in `campaign_owner` or `gm` role; recipient is an active `assistant_gm` membership; history-preserving record with reason; no redelegation, and `character.assign_control` is never carried by a custom role or resource grant; revocation leaves earlier assignments in force; T79, T86 | P03-B | — | **Owner-approved 2026-11-04** |
| OD-7a | Whether the repository's current public visibility is already distribution of the seed under OD-7 (residual of OD-7) | — | **Decided by the owner:** treat the existing public repository seed as potentially distributed. Prioritize the R19-P2a rights/provenance inventory. Require documented clearance or replacement of uncleared material. **This decision is not licensing clearance** | ADR 0023 §4: the OD-7 requirement already applies to the published seed; R19-P2a prioritized (§3, §12); the seed stays `unknown` / `unreviewed` until evidence supports a change; T88 | Owner; R19-P2a supplies the inventory | — (clearance or replacement is already due; no later than the next distributed artifact and the Phase 17 packaging gate) | **Owner-approved 2026-11-04** |
| OD-12a | Who may grant a GM access to a contributor-private source (residual of OD-12) | — | **Decided by the owner:** the contributor authorizes access to their private source. GMs cannot grant themselves access. World ownership and system administration do not automatically grant access. Explicit sharing permissions govern citations and AI retrieval | ADR 0023 §9: contributor-only grants; `create_resource_grant` and campaign retrieval grants refuse other callers; no access from campaign roles, `access.manage`, world roles, Admin or recovery commands; T17, T87 | Phase 18/20 | — | **Owner-approved 2026-11-04** |

**Engineering decisions** are resolved here, subject to independent review.

| ID | Decision | Resolution |
|---|---|---|
| ED-1 (formerly OD-8) | Missing option-policy rows | `all_canon`, version 0 (lazy rows) |
| ED-2 (formerly OD-13) | Hidden inputs in audience mode | Excluded before evaluation, no marker |
| ED-3 (formerly OD-15) | Spawn limits | 50 per call, 200 participants per encounter |
| ED-4 | Fingerprint basis | Hash loaded values and content; tokens advisory (ADR 0023 §10) |
| ED-5 | Contribution identity and order | ADR 0023 §3 |
| ED-6 | Rules-exception limits | Never waive integrity (ADR 0023 §7.6) |
| ED-7 | Neutrality guard scope | Core modules only; registry may name adapters |
| ED-8 | Typed citation link to `core.source_documents` | Design and build before any private-document citation (ADR 0023 §9) |
| ED-9 | Control locking protocol and index replacement | ADR 0021 §2.3 and §2.8 |
| ED-10 | No persistent calculation cache in R19-P3 | ADR 0023 §10 |
| ED-12 | Shared item instances across ruleset versions | Possession, ownership, equip, quantity, damage, destroy and **end attunement** are allowed; attuning and creating or interpreting definition mechanics are refused (`item_definition_version_mismatch`); migrated incompatible rows are quarantined, with supported resolutions; the engine marks the facts incompatible or quarantined and maps nothing (ADR 0021 §3.7) |
| ED-13 | Item revision checks | Split shared-ownership and campaign-mechanical tokens; atomic mixed operations and corrections (ADR 0021 §3.1.1) |
| ED-14 | Controller authorization path | `lock_controller_operation_scope` plus named intents; canonical commands unchanged (ADR 0021 §2.8) |
| ED-15 | Migration protocol | Stopped-writer windows; **family-atomic** review, validation and apply (membership hashes, dependencies, `pending_drift`, `reviewed_replacement`, `empty_confirmed`, idempotent retry); markers only with complete families; cutover groups G1–G4; GM-only legacy fallback; restore-only rollback after divergence (ADR 0021 §3.8) |
| ED-16 | Event effect classification and visibility | A **closed, fail-closed** registry `campaign.effect_component_classes` (`campaign_mechanical`, `shared_narrative`, `shared_knowledge`, `unclassified`), seeded from the verified emitted codes; a foreign key on new effects; unknown or `unclassified` codes **withheld** from every application audience, including every `canon.edit` holder of the origin campaign or the timeline, until classified; **one universal rule** for every `campaign_mechanical` effect, seeded, later classified or legacy: disclosed only after classification **and** a recorded origin attribution (`authorized_at_write` or `migration_reviewed`; an event's `campaign_id` is evidence only; never inferred; never shown through `legacy_shared_state`, which is limited to character-state dual-read); `shared_knowledge` needs its knower or audience; events with withheld effects are uncorrectable (404); raw inspection only in migration review (§3.8 step 2a); new effects need no routine per-event human review; attribution records are immutable to correction, editing and replay, and corrections keep the same origin; bulk review is allowed with explicit exceptions; ambiguous effects stay withheld; G4 needs an approved attribution readiness report; one classification for writes, reads, counts, links, explanations, authoring views, previews and corrections (ADR 0021 §3.3) |
| ED-17 | Transfer provenance contract | Target events carry applied values and an opaque request id only. The protected transfer record (source id, snapshot, outcomes, conflicts) is readable only with current source read **and** target capability. Audit holds no values (ADR 0021 §3.6) |
| ED-11 | Capability codes and role mapping for OD-21 commands | `mechanics.transfer_read` (source), `mechanics.seed` and `mechanics.copy_in` (target), all campaign-scoped. They are never in the control or relationship matrices and never implied by world roles or `canon.edit`. The role mapping, and whether a requester may self-approve, are fixed at enablement review (ADR 0021 §3.6) |

**Coordination item:**

| ID | Item | Resolution |
|---|---|---|
| C-1 (formerly OD-16) | ADR numbering | ADRs 0021–0023 are held by this branch. Primary-PC ADRs start at 0024. P03 work reviews ADR 0021 rather than writing a competing ADR. |

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Assignment rows inheriting legacy capabilities, or legacy rows promoted automatically | Exclusive routing (ADR 0021 §2.5); manifest-only creation; T2, T6, T25 |
| One campaign's mechanical writes leaking into another campaign | P03-S campaign-keyed tables; route campaign = state campaign; mechanical-event campaign trigger; T22, T33, T34 |
| Legacy timeline rows misattributed to a campaign | Manifest classification; no inference; dual-read `legacy_shared_state`; T31 |
| Another campaign's mechanical event values, names or diagnostics leaking through explanations or corrections | Origin-campaign gating before serialization; G4 switches first; T46–T48 |
| A cross-campaign correction or stale item token corrupting another campaign | Split tokens; atomic mixed corrections; T49, T50 |
| An implicit ownership change through an omitted field | Required intent at every boundary; T51 |
| Controllers gaining canonical power | Separate scope and intents; canonical commands unchanged; T52 |
| A live database diverging from the reviewed manifest | Live validation in stopped-writer windows; T53, T55 |
| A value computed for one campaign served to another | `campaign_id` in the manifest and memo identity; T35 |
| Campaign-private builds leaking through branches | Lineage seeding refuses another campaign's private build (`out_of_scope`); T24 |
| Access silently reduced or expanded at PC cutover | Legacy exceptions; OD-19 per-character records; T26 |
| Derived values disclosing hidden inputs | Audience mode after P03-A/B; T7 |
| Stale or wrong fingerprints from unreliable tokens | Hashing loaded values; T30 |
| Approval laundering invalid or mutable content | Separate axes; immutable materialization; exception limits; T16, T27, T28 |
| Combatants dropped by inner joins or refused silently | E1–E14 inventory; T29 |
| Merge collisions with P03 on build or encounter commands | Ownership tables (§4); P2b-2 and P3d-2 sequenced after P03-C |
| Licensed text in definitions | Attestation plus bounded similarity aid; limitations stated; no legal claims |
| Migration-number collisions | Claim at merge |

---

## 11. Instructions for the primary PC before P03-B/C

1. **Owner decisions are recorded.** OD-1 (mechanical state per campaign), OD-20, OD-21, OD-2, 3, 4, 5, 14, 17, 18, 19 and 22, and on 2026-11-04 OD-4a and the OD-18 clarification are Owner-approved (ADR 0021 status). No owner question is open. Freeze the P03-B/C/S contracts only after ADR 0021 is accepted.
2. **Storage.** Control goes in `security.membership_character_relationships`:
   - add `is_control_assignment`, `campaign_id`, `is_primary`, `assignment_period_kind`, and revocation provenance;
   - replace `ux_membership_character_relationships_active_type` with the legacy-only predicate;
   - add the one-live-primary-per-campaign and one-live-assignment-per-membership indexes;
   - forbid `expires_at` and `timeline_id` on assignments.
   - **Do not build `character.character_controllers`.**
3. **Capability routing.**
   - Exclude assignment rows from `BUILTIN_RELATIONSHIP_CAPABILITIES`.
   - Resolve them **only** through `CONTROL_ASSIGNMENT_CAPABILITIES`.
   - Keep legacy `primary_controller` / `co_controller` capabilities (`view_private`, `view_knowledge`) exactly as they are.
   - Never promote legacy rows automatically.
   - Primary and co-controllers get identical entries; neither gets `character.assign_control` (OD-2). Grant `character.assign_control` to `campaign_owner` and `gm`, and to an `assistant_gm` only through the OD-4a delegation that an Owner or GM grants and revokes (ADR 0021 §2.7). The delegation cannot be redelegated, and `character.assign_control` must never be assignable through a custom role or a resource grant (OD-4, OD-4a).
   - Both controller roles get `character.view_player_profile` and `character.edit_player_profile`, and never `character.edit_narrative` (OD-18 clarification). Profile editing is not a `CONTROLLER_OPERATIONS` entry; it uses the §2.8 player-profile path.
   - Implement exactly the OD-3 allow-list (ADR 0021 §2.5a).
4. **Locking.**
   - Assign, replace and revoke lock: membership (+ the row being revoked), then campaign, then user, then the character `core.entities` row `FOR UPDATE` (the anchor), then the assignment rows.
   - Controller operations do **not** use `lock_operation_scope`, which is canon-only. They use a new `lock_controller_operation_scope`: the same prefix (world, membership and role rows, account, campaign `FOR SHARE`) without `canon.edit`, then the character entity `FOR SHARE`, then the in-effect assignment `FOR SHARE`, then the operation allow-list check, then the campaign state rows `FOR UPDATE`.
   - Expose only named controller intents that call internal implementations. Never widen or parameterize the canonical commands.
5. **Clock.**
   - Resolve one request clock through `resolve_effective_clock`.
   - Dated assignments are half-open `[start, end)`.
   - With no clock, a dated assignment is undetermined.
   - `ongoing` must be an explicit kind.
   - Don't apply DEF-007's party rule to control. Under OD-14 there is no default kind, a dated assignment is undetermined without a clock, and ongoing status is never inferred.
   - Update the stale "no fictional clock" docstring in `domain/access.py`.
6. **Authoring.**
   - Implement stewardship, delegations and legacy exceptions separately.
   - Write a `pending` legacy exception for every PC that exists at cutover, preserving current world-wide campaign authoring until a per-character disposition (OD-19).
   - Create new PCs from callers without a world capability as campaign-scoped pending records (`character.character_authoring_origins`, ADR 0021 §4.4, OD-5); write no legacy exception for them.
   - Never infer from creator, kind, first campaign, hosting permission or audit.
7. **Builds.**
   - Add `build_scope`, `origin_campaign_id` and `created_by_user_id`, backfilling `legacy_unscoped`.
   - Add the X4 version guard early.
   - Activation writes only the route campaign's state (P03-S), with the per-campaign version guard. There is no campaign-creation restriction.
8. **Mechanical isolation (P03-S, OD-1).**
   - Add the campaign-keyed tables of ADR 0021 §3.2; do not add `campaign_id` to the existing primary keys.
   - Move every writer and reader in ADR 0021 §3.9, one consumer family at a time.
   - Require `campaign_id` on new mechanical events.
   - Build the §3.8 manifest on a restored copy and never infer ownership of `multi_campaign` rows.
   - Keep the legacy tables read-only and never drop them in Phase 15.
   - **OD-20:** keep `item_ownership` and `character_location_history` shared and unmigrated. Remove `award_item`'s implicit `set_owner=True` and route explicit ownership through a separately authorized narrative effect or `change_item_ownership`. Give controllers no ownership or location operation.
   - **OD-21:** if you build the seeding and copy commands, build them as separate request and approve commands with `mechanics.transfer_read`, `mechanics.seed` and `mechanics.copy_in`, preview, conflict reports, idempotency and source-immutability tests. Ship them **disabled**. P03-S completion must not depend on them.
   - P03-S must precede any P03-B operation that writes state.
9. **Portrayal and eligibility.**
   - Re-key portrayal before touching markers.
   - Keep player portrayal guidance out of `npc_portrayal_profiles` and `character.character_descriptions` (OD-18).
   - Replace kind lists with capability and lifecycle eligibility.
10. **Contract.** Expose the §5.1 functions. R19 binds to them through `ActorContractPort`.
11. **Boundaries.**
    - Don't modify `rules.*`, `domain/character_calculations.py` or `domain/rules_engine/`.
    - Sequence `character_builds.py` changes with R19-P2b-2 and R19-P3d-2.
    - The encounter-damage `last_event_id` repair and the item-token split are **P03-S** work (groups G1 and G3).

---

## 12. Recommended first checkpoints

- **R19-P3a (revised scope):**
  - neutral core with contribution identity, dependency evaluation and missing-input propagation;
  - three-axis result types;
  - `rules_manifest.v1` and fingerprint;
  - the registry with per-version support;
  - the 5e adapter port with parity tests;
  - **the percentile fixture adapter (test-only)**;
  - the scoped neutrality guard.

  No schema. No existing file changed.
- **R19-P2a (in parallel, prioritized under OD-7a):**
  - content packages and lookups;
  - backfilling the seed as license `unknown`, `unreviewed`;
  - the read endpoint;
  - the factual seed inventory document.

  No legal conclusion.

---

## 13. Review correction record (2026-11-02, against `10a1a4e`)

| Finding | Correction | Where |
|---|---|---|
| R19-01 Campaign/timeline isolation | Campaign-aware resolution; examples (same version, different versions, inherited build, controller writes); alternatives; OD-1 moved before acceptance and contract freeze | ADR 0021 §3; §8 T22–T24; §9 OD-1 |
| R19-02 Control persistence and concurrency | NULL-period and unique-index facts; assignment invariants; coexistence; index replacement; primary-only rules; expiry forbidden; entity anchor; locking protocol; exclusive capability routing; legacy grants preserved; migration and concurrency scenarios | ADR 0021 §2.2–2.10, acceptance list; §8 T25 |
| R19-03 No-clock semantics | Open-end fallback removed; dated vs ongoing; one request clock; half-open intervals; branch fallback; OD-14; DEF-007 cited only as precedent | ADR 0021 §2.4; OD-14 |
| R19-04 Authoring migration | Current author sets shown; stewardship, delegations and legacy exceptions separated; granter and revoker; pending disposition; no inference; hosting is not delegation; ADR 0020 amendment timing | ADR 0021 §4; ADR 0020 note; OD-5, OD-19; T26 |
| R19-05 Fingerprints and reproducibility | Canonical manifest; value hashing (tokens unreliable); token ownership; mutable fields; draft dependencies removed; reconstruction limits; no cache | ADR 0023 §4, §7.5, §10; T30 |
| R19-06 Validation, approval, use | Three axes; every producer including direct create; unreviewed builds plus activation gate; label rules; immutable materialization; exception limits | ADR 0023 §5, §7; P3d split; T27, T28 |
| R19-07 Combatant integration | E1–E14 inventory; participant-addressed actors and targets with integrity; causal damage; check refusal; corrected promotion order; idempotency; discovery-gated links; pending/active spawning; P4b gate | ADR 0022; T29 |
| R19-08 Deterministic, neutral composition | Contribution identity and order; duplicates; dependencies; propagation; build-component refs; `InputBundle`; percentile fixture moved to P3a; scoped guard | ADR 0023 §2–3, §13; P3a |
| R19-09 Sequencing and ownership | Four-gate table; P2d independent of P2b (P2d-x); P2b and P3d split into isolated and behavior-changing halves; P3d-2 after P03-C; P3e split by projection and controller gates; P3b port and test fix; Phase 16 manual path and player portrayal; migration and command ownership | §3, §4, §5.1, §6, §7 |
| Source and provenance | `core.sources` vs `core.source_documents`; typed citation link (ED-8); bounded copied-text aid with limitations; seed unreviewed, review at the next distributed artifact or Phase 17; no legal claims | ADR 0023 §4, §9; OD-7 |
| Register | Owner and engineering decisions separated; alternatives, consequences, owners, deadlines; no encoded defaults; OD-17/18/19 added; OD-1 expanded | §9 |
| **OD-1 addendum** (owner decision 2026-11-02) | OD-1 Owner-approved: independent per-campaign mechanical state. The single-campaign-timeline proposal and the one-controlling-campaign rule are withdrawn. Phase 15 P03-S gets campaign-keyed tables, lineage seeding, the mechanical-event campaign rule, the manifest migration, and the full table, command, resolver and API inventory. Phase 19 gets campaign-scoped loading, authorization, manifest and memo identity. OD-6 reconciled; OD-20 and OD-21 added; regression scenarios T22–T24 and T31–T35 | ADR 0021 §3; ADR 0022 §4.4, §6; ADR 0023 status, §1, §9, §10; this plan §1–§11 |
| **OD-20 / OD-21 record** (owner decisions 2026-11-02) | OD-20 and OD-21 Owner-approved. Ownership versus possession verified in the schema; implicit ownership writes (`award_item` default, `transfer_ownership`) are scheduled for decoupling; `change_item_ownership` added; the item-whereabouts observation logged as OD-22. Seeding and copy split into separately authorized, previewed, approved, idempotent, disabled commands (ED-11). P03-S independent of both; branch-inherited rows go through the reviewed migration. Scenarios T36–T45 | ADR 0021 status, §3.1, §3.1.1, §3.3, §3.4, §3.6, §3.8–§3.10; ADR 0023 status, §9; this plan §3, §6, §8, §9, §11; PLANv2 15H |

### 13.1 Second review (R19-10 to R19-13, residual R19-02, R19-09), against `74a10cb`

| Finding | Correction (proposed design) | Where |
|---|---|---|
| R19-10 Event paths | Narrative and mechanical classification; origin-campaign gating in every event reader before serialization; atomic mixed corrections; legacy campaign-less mechanical events | ADR 0021 §3.3; §4 ownership; T46–T48 |
| R19-11 Item tokens | Split ownership and campaign tokens; lock order; atomic mixed operations, corrections, audit and idempotency; A/E1 → B/E2 → correct-E1 regression | ADR 0021 §3.1.1; T49, T50 |
| R19-12 Ownership intent | Required `ownership` at the API, command, internal callers and portal; omission gives 422 or `TypeError` | ADR 0021 §3.1.1; T51 |
| Residual R19-02 | `lock_controller_operation_scope` and named intents; canonical commands unchanged | ADR 0021 §2.8; §11; T52 |
| R19-09 / R19-13 | P03-S in Phase 15 acceptance (PLANv2 15.9) and in the §3, §4 and PLANv2 §6.1 tables; P3d-2 needs P03-S G1; the encounter-token repair moved to P03-S everywhere; port phases a, a+C, a+S and b; rollback qualified identically | §3, §4, §5.1, §6; ADR 0021 §3.8; ADR 0022 §4.4, §9; ADR 0023 §10; PLANv2 |
| Migration protocol | Stopped-writer windows; manifest-to-live validation; initialization markers; groups G1–G4; GM-only fallback; restore after divergence | ADR 0021 §3.8; T53–T55 |
| Inventory | Event APIs and queries; `api/item_authoring.py`; portal item contracts; `data_classification`; party-inventory route corrected | ADR 0021 §3.9; X17–X22 |
| Item version rule | ED-12 | ADR 0021 §3.7; T56 |
| OD-21 extensions | Indirect paths; revoked replays; safe conflict and provenance; source snapshot; proven baselines; the offline migration separated from runtime capabilities. Commands still disabled | ADR 0021 §3.4, §3.6; T57–T61 |
| OD-22 wording | No shared placement record exists or is designed; the question only | ADR 0021 §3.1.1; §9 |
| Phase 15 and 17 acceptance | P03-S criteria; backup, restore and upgrade (T62) | PLANv2 15.9, 17.3, 17.4; §7 |

P2a and P3a keep their independent begin and merge eligibility (§3). Their later acceptance gates are unchanged.

### 13.2 Third review (R19-14 to R19-16 and residual items), against `6ea0e73`

| Finding | Correction (proposed design only) | Where |
|---|---|---|
| R19-14 / residual R19-10 | A fail-closed registry seeded from the verified emitted codes (including `item_attunement_ended`, `item_attuned`, `condition_id`, `current_amount`, item state, possession, build, HP); a foreign key on new effects; `unclassified` handled as hidden mechanical (superseded by §13.3: withheld from every application audience); one classification for every surface | ADR 0021 §3.3, §3.9; ED-16; T64, T65 |
| R19-15 | Family-atomic manifest, validation and apply with membership and dependencies; `pending_drift`; per-family dispositions; idempotent retry; explicit empty | ADR 0021 §3.8; ED-15; T53, T54, T66, T67 |
| R19-16 | Version checks stay on creation and interpretation; `end_item_attunement` allowed; quarantine with audited resolutions; target-only effects; ownership preserved | ADR 0021 §3.7; ED-12; T68 |
| Residual R19-09/R19-13 | The last P4b damage-token attribution removed (§2 inventory); P03-S references and rollback wording reconciled | §2, §4; ADR 0022 §4.4, §9 |
| Lineage baselines | Untimed administrative baselines give `history_unavailable` in both §3.4 and §3.6; `materialize_inherited` is a distinct offline disposition | ADR 0021 §3.4, §3.6, §3.8 |
| Provenance | One contract: target event, protected transfer record, audit | ADR 0021 §3.6; ED-17 |
| T61 split | T61 (runtime seeding) separated from T63 (offline migration); P03-S completion independent of transfer commands | §6 R19-P1; §8 |
| Phase 15 and 17 acceptance | Phase 15 test list extended (T63–T68); Phase 17 adds T69 | §6, §7; PLANv2 15.9, 17.3 |

### 13.3 Residual R19-14 (withheld unclassified effects), against `e812dcf`

| Item | Correction (proposed design only) | Where |
|---|---|---|
| Contradictory `canon.edit` exposure | Removed. Unclassified effects were visible to `canon.edit` holders of the origin campaign, or of every campaign on the timeline. They are now **withheld** from every application audience | ADR 0021 §3.3 items 1, 4 |
| Classification and attribution first | Values, names, existence and metadata are released only after a reviewed classification migration and any attribution the class needs | ADR 0021 §3.3 item 3 |
| Every surface, including mixed events | Lists, counts, links, explanations, authoring views, previews, voids, corrections and calculations; withheld-only events are absent (404); mixed events show only admitted classified parts; any withheld effect makes the event uncorrectable (404); event shape computed over classified effects | ADR 0021 §3.3 item 2, event shape |
| Raw inspection | Only in the migration-review workflow on the restored copy (step 2a), as a restricted operator artifact | ADR 0021 §3.8 step 2a |
| Unknown versus known legacy | Corrections item 5 applies only to known `campaign_mechanical` codes (superseded by the universal disclosure rule row below: no distinction by when a code was classified) | ADR 0021 §3.3 item 4, corrections item 5 |
| Stricter attribution rule (Owner-approved 2026-11-03) | Classification alone discloses nothing. A `campaign_mechanical` effect stays withheld until its origin campaign is reviewed and recorded, even if the event has a `campaign_id`, and is never projected as `legacy_shared_state`. Origin is never inferred from timeline membership, control, creator or an associated campaign. `shared_knowledge` needs its knower or audience. Raw rows, provenance and audit are preserved | ADR 0021 §3.3 items 1–6, event shape; §3.8 step 2a |
| Universal disclosure rule (Owner-approved 2026-11-03) | The rule covers every `campaign_mechanical` effect, including seeded codes and legacy effects with or without a `campaign_id`. The known-legacy compatibility projection (GM-only `legacy_shared_state` explanations, 409 refusal) is removed; such effects are withheld and correction returns 404 until a `migration_reviewed` attribution. New events record `authorized_at_write` attributions. `legacy_shared_state` is limited to character-state dual-read | ADR 0021 §3.3 disclosure rule items 1–7, authoring rule, visibility, corrections items 1 and 5; §3.8 steps 1, 2, 2a, 6; §3.9 |
| Confirmed attribution policy (Owner-approved 2026-11-03) | `authorized_at_write` releases new effects with no routine per-event review. Historical effects need `migration_reviewed` attribution even with a `campaign_id`, which may only propose a mapping. Evidence-backed bulk approval with explicit exceptions is allowed. Ambiguous effects stay withheld. G4 needs a readiness report (reviewed, withheld, ambiguous, failed) and explicit operator approval to proceed with unresolved effects withheld. Attribution records are immutable to correction, editing and replay. Corrections and mixed transactions keep the origin and the authorization boundary | ADR 0021 §3.3 disclosure rule items 1 and 7, corrections item 3; §3.8 step 2a, G4 readiness gate; T76, T77 |
| Acceptance (owner decisions) | T17 revised; T78–T84 added (T78–T82 in Phase 15 acceptance; T83 at P3d-2; T84 at P4b) | §8 |
| Acceptance | T64 revised; T70–T75 added to Phase 15 acceptance (T74 revised and T75 added for the stricter rule; T48 and T71 revised and T75 extended for the universal rule; T74 extended and T76, T77 added for the confirmed policy) | §6 R19-P1; §8; ED-16 |

### 13.4 Owner policy decisions (Owner-approved 2026-11-03), against `611c6c7`

| OD | Approved policy (summary) | Contracts changed | Owner gate removed | Remaining gate |
|---|---|---|---|---|
| OD-2 | Same bounded operations for primary and co-controllers; neither manages assignments; no revocation cascade or auto-promotion | ADR 0021 §2.5 item 4, §2.7; T78 | P03-B contract freeze (OD-2 part) | ADR 0021 acceptance; P03-B tests |
| OD-3 | HP and temporary HP, named resources, explicitly self-manageable conditions, eligible equipment and attunement; no encounter, narrative, ownership or canon operations | ADR 0021 §2.5, §2.5a, §3.7 end-attunement row; plan §5.1; T80 | P03-B operations implementation | P03-S precedence for state writes; P03-B tests |
| OD-4 | Campaign Owners and GMs assign and revoke; assistant GMs only by explicit delegation | ADR 0021 §2.7; §11; T79 | P03-B contract freeze (OD-4 part) | OD-4a (the delegator) for the assistant-GM path only |
| OD-5 | World-authorized review plus campaign authority governs delegation; no GM self-grant of world-canon rights; new PCs as campaign-scoped pending records; publication by authorized review | ADR 0021 §4.3, §4.4; ADR 0022 §6; §11; T81 | ADR 0021 acceptance (OD-5 part); P03-C cutover | ADR 0021 acceptance (amends ADR 0020 decision 6); P03-C tests |
| OD-7 | Provenance `unknown` / `unreviewed` until the evidence inventory; clearance or replacement before distribution; not licensing clearance | ADR 0023 §4; plan §3, R19-P2a, §6 P4d, §7 | The policy decision | The evidence inventory and clearance or replacement before distribution; OD-7a |
| OD-9 | Campaign canon editors approve supported exceptions with a reason; never over integrity or authorization; legacy builds `not_evaluated` until reviewed | ADR 0023 §7.4, §7.6; plan P3d-2; T83 | The P3d-2 OD-9 prerequisite | Owner acceptance of the activation-gate behavior change; build-command sign-off; tests |
| OD-10 | Campaign canon editors manage campaign rules and options; shared-world rules need world authority plus campaign authorization; versioned | ADR 0023 §6; plan §3, P2b-1, P2b-2, P2c | "Commands disabled until OD-10" | Checkpoint tests and review; P2b-2 behavior-change acceptance |
| OD-11 | No promotion during an active encounter; after it ends | ADR 0022 §6; plan P4b; T84 | P4b design (OD-11 part) | P4b dependencies (Phase 15 encounter owner, P4a, ED-3) |
| OD-12 | Players register entitled sources; contributor-private; explicit GM grant; citations and retrieval enforce permissions | ADR 0023 §9; T17 | Phase 18 intake design (policy) | OD-12a (the grantor); ED-8 citation link |
| OD-14 | Explicit ongoing and dated kinds; ongoing works without a clock; dated undetermined without a clock; no inference | ADR 0021 §2.4; §11 | P03-B contract freeze (OD-14 part) | P03-B tests |
| OD-17 | Member, group and campaign-wide audiences; current versus future members; only deliberately published versions | ADR 0021 §6; T82 | P03-A schema | P03-A tests |
| OD-18 | Campaign-scoped player profile, distinct from canon and GM portrayal; GMs and controllers read; selected fields published through workflows | ADR 0021 §2.5, §4.7, §7; T82 | P03-A field list; Phase 16 16A scope | P03-A and Phase 16 tests |
| OD-19 | Existing access preserved until per-character reviewed disposition, with reasons and affected principals | ADR 0021 §4.1, §4.5, §8; T26 | P03-C cutover (OD-19 part) | P03-C manifest review per character |
| OD-22 | No world-shared whereabouts record now; campaign-specific under OD-20; a future feature needs its own proposal | ADR 0021 §3.1.1 | None (it was non-blocking) | None |

The ADRs stay Proposed. OD-1, OD-20 and OD-21 are unchanged, and the OD-21 commands stay disabled pending their enablement review.

### 13.5 Final owner decision reconciliation (Owner-approved 2026-11-04), against `1cfb943`

| OD | Approved policy (summary) | Contracts changed | Owner gate removed | Remaining gate |
|---|---|---|---|---|
| OD-4a | Owners and GMs grant and revoke `character.assign_control` for assistant GMs; campaign-scoped, audited, revocable; no redelegation | ADR 0021 §2.7, §2.8 (delegation lock row), acceptance list; plan §6 R19-P1, §9, §11; T79, T86 | The assistant-GM delegation path | ADR 0021 acceptance; P03-B contract freeze (choice of the delegation table); T86 |
| OD-7a | The published seed is treated as potentially distributed; R19-P2a inventory prioritized; documented clearance or replacement of uncleared material required; not licensing clearance | ADR 0023 §4; plan §3, R19-P2a, §7, §12; T88 | The question of whether the requirement applies now | The evidence inventory, then clearance or replacement of uncleared material (owner). Rights status stays `unknown` / `unreviewed` |
| OD-12a | Only the contributor authorizes access; no GM self-grant; world ownership and system administration grant nothing automatically; explicit sharing governs citations and AI retrieval | ADR 0023 §9; T17, T87 | The Phase 18 intake grantor question | Phase 18 intake design; ED-8 citation link |
| OD-18 (clarification) | Primary and co-controllers edit their own campaign-scoped player profile; no `character.edit_narrative`, world-canon edit or GM-private portrayal access; publication under OD-17 and OD-5 | ADR 0021 §2.5 (capability table), §2.8 (profile lock row), §4.7 (`edit_narrative` profile grant withdrawn; `edit_narrative` is canonical narrative editing), §7, acceptance list; plan §6 R19-P1, §7, §9, §11; PLANv2 16A; T82, T85 | None (OD-18 was approved) | P03-A, P03-B and Phase 16 tests |

Unchanged by this reconciliation: OD-1, OD-2, OD-3 (the closed `CONTROLLER_OPERATIONS` list; profile editing is not added to it), OD-5 and the existing authoring permissions of ADR 0021 §4.1–§4.5, the OD-19 per-character review requirement, OD-17, the R19-14 attribution architecture (ADR 0021 §3.3, ED-16, T70–T77), OD-21 (seeding and cross-campaign copy stay disabled) and the seed's `unknown` / `unreviewed` rights status. The ADRs stay Proposed.

## 14. Self-review

- **Terminology** is consistent across all three ADRs and this plan: assignment, `ongoing` / `dated`, stewardship, delegation, legacy exception, campaign-aware resolution, build scope, the three axes (calculation, legality, approval), manifest and fingerprint, combatant, template basis.
- **Ownership:** Phase 15 owns actor, control and authoring, plus state writers and the P03-S campaign mechanical-state schema, commands, resolvers and APIs. Phase 19 owns rules, engine, drafts and reviews, templates and the combatant extension, each under the sign-offs in §4.
- **All six owner decisions** are preserved (§1).
- **Phase 16** can proceed before full Phase 19, using P3d-1/2, P03-B/C and, optionally, P3f.
- **No core type uses 5e terms**, and the percentile fixture runs in P3a.
- **Unsupported mechanics cannot become validated:** the label rules and separate axes prevent it.
- **No new source access:** citations stay on `core.sources` until ED-8.
- **Reproduction limits** are stated.
- **IDs and history** are preserved.
- **No owner approval is claimed** beyond the recorded policy decisions, and every ADR remains Proposed.
- **No owner question is open** for R19-P0 after the 2026-11-04 decisions (§9, §13.5).
