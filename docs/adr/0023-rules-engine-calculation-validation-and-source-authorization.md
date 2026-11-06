# ADR 0023: Rules engine, calculation, validation, and source authorization

- **Status**: Accepted by the owner on 2026-11-06, as reviewed at `2ca4648` (the ADR file is unchanged from that revision). R19-P0 architecture deliverable, corrected after independent review (findings R19-05, R19-06, R19-08, and the source and provenance corrections). It implements owner Decisions 4 (rules-engine-neutral core), 5 (versioned house rules) and 6 (drafts with unsupported mechanics, honest validation, authorized review).
- **Owner decision applied**: OD-1 (Owner-approved, 2026-11-02). Campaigns sharing a world or timeline keep independent mechanical state ([ADR 0021 §3](0021-shared-actor-identity-control-and-authoring-responsibility.md)). Every evaluation in this ADR is therefore for **one campaign**: input loading (§1), authorization and projection (§9), the manifest, fingerprint and any future cache identity (§10) are all campaign-scoped.
- **Owner decisions applied**: OD-20 and OD-21 (Owner-approved, 2026-11-02).
  - **OD-20:** equipment inputs come from the route campaign's **possession**, item state and attunement. Fictional/legal ownership (`campaign.item_ownership`, shared narrative) is **not** a mechanical input and never changes because of a calculation (ADR 0021 §3.1.1).
  - **OD-21:** the engine's only cross-campaign truth read is inside the separately authorized, disabled seeding and copy commands (ADR 0021 §3.6).
- **Owner decisions applied (Owner-approved 2026-11-03)**: OD-7 (seed provenance, §4), OD-9 (rules exceptions and legacy builds, §7.4, §7.6), OD-10 (rules authority, §6) and OD-12 (player-registered sources, §9). These are policy approvals, not acceptance of this ADR.
- **Owner decisions applied (Owner-approved 2026-11-04)**: OD-7a (the existing public repository seed is treated as potentially distributed, §4) and OD-12a (only the contributor authorizes access to a contributor-private source, §9). These are policy approvals, not acceptance of this ADR, and OD-7a is **not** licensing clearance.
- **Date**: 2026-11-02
- **Extends**: [ADR 0005](0005-separate-rules-definitions-from-world-instances.md) and the identity-immutability policy of `DATABASE_MODEL.md` §8 (revisions 033/036). It does not replace the `rules` schema.
- **Related**: [ADR 0006](0006-ai-proposes-but-does-not-own-canon.md), [ADR 0016](0016-data-classification-and-private-data-handling.md), [ADR 0021](0021-shared-actor-identity-control-and-authoring-responsibility.md), [ADR 0022](0022-creature-templates-combatants-and-promotion.md).

## Context (verified at `10a1a4e`)

- **Rulesets.**
  - `rules.rulesets` is the edition-neutral family (`dnd5e`).
  - `rules.ruleset_versions` holds the versions.
  - `rules.world_rulesets` is each world's family allow-list.
  - `campaign.campaigns.ruleset_version_id` pins each campaign. Campaigns may share a timeline with different pins (ADR 0021 §3).
- **Definitions.**
  - Typed per-version tables: `abilities`, `skills`, `species`, `classes` (with `hit_die`, `primary_ability_id`), `subclasses`, `features`, `feats` (free-text `prerequisite_description`), `spells`, `conditions` (14 seeded), `creature_types`, `damage_types`, `languages`, `proficiency_types`, `resource_definitions`.
  - Revisions 033/036 made **identity** columns immutable. Non-identity associations (`classes.primary_ability_id`, `skills.ability_id`, `spells.damage_type_id`) and descriptive columns, including `hit_die`, remain mutable.
  - `rules.item_definitions` has `owning_world_id` and `row_version`, and is edited through a supported homebrew command. Its `requires_attunement`, rarity, weight and cost are mutable while canon.
- **Seed.** Revision 022 seeds a small 5e 2024 sample from `database/seeds/rules.*.yaml`. The seed records no origin or license.
- **Builds.** Immutable `character.character_builds` with typed 5e children. `create_character_build` checks only existence, canon status and same-version membership. There are no prerequisites, choice rules or completeness checks.
- **Calculations.** `domain/character_calculations.py` is pure 5e arithmetic, gated by the family-only `supports_ruleset`. `queries/character_sheet.py` uses it. There is no trace, no version awareness, no equipment, conditions or house rules.
- **Runtime state and tokens.** `campaign.character_state`, `character_conditions`, `character_resources`, `item_state`, `inventory_entries` and `item_attunements` carry `last_event_id`. However:
  - encounter damage (`commands/encounters.py`) updates `current_hit_points` **without** setting it;
  - the first build activation and `initialize_character_state` are administrative (`NULL`);
  - a branch with no local row inherits its value through event history (`queries/character_build_resolution.py`), so there is no local token.
  - `last_event_id` is therefore not a reliable change token.
  - These tables are keyed by **timeline**, not campaign. Under OD-1, Phase 15 checkpoint P03-S replaces them with campaign-keyed tables (ADR 0021 §3.2). Until P03-S cuts over, R19 readers see legacy timeline rows. For a timeline hosting more than one campaign, those rows are labeled `legacy_shared_state`.
- **Sources.** These are two distinct things:
  - **`core.sources`** records citations: an optional `world_id` (NULL = not world-specific), a closed type list, title, `reference` locator and description. `rules.*.source_id` points here, and GMs author world sources (D-26).
  - **`core.source_documents`** is the rights-bearing reference corpus: classification, `usage_rights_status`, `visibility` (`general` | `campaign_restricted`), `allow_indexing`, `allow_quotation`, `allow_summarization`, `allow_export`, `allow_training`, hash, supersession and removal. Its campaign grants live in `ai.reference_source_campaigns`. Management needs `rules_source.manage`; retrieval needs `campaign.view`.
  - No link exists between the two. `PLAN.md` §6.1 and §18.3: a retrieved passage never creates a rules definition.

## Decision

### 1. Layering

| Layer | Modules (new unless stated) | Responsibility |
|---|---|---|
| Domain, pure and neutral | `domain/rules_engine/{contracts,composition,validation,manifest,fingerprint}.py` | Types, ordering, dependency evaluation, results, validation and manifest. No database, HTTP, authorization or system terms. |
| Domain, registration | `domain/rules_engine/registry.py` | An explicit, closed registration of adapters by id (the codebase's closed-vocabulary style). It may import adapters. |
| Domain, per system | `domain/rules_engine/adapters/dnd5e.py`; test-only fixture adapters | System formulas, schemas, override points. `domain/character_calculations.py` is untouched until the sheet moves (after P03-A). |
| Queries | `queries/rules_context.py` (the neutral envelope), `queries/rules_context_dnd5e.py` (the 5e loader), `queries/rules_catalog.py` | Load the **authorized** input bundle and the eligible catalog. **All mechanical facts come from the route campaign's state only**: its active build, HP, conditions, resources, item state, possession and attunement (ADR 0021 §3.4), through `ActorContractPort`. Facts are never read from another campaign, and never from a parent timeline's current row. |
| Commands | Draft, review, house-rule and option-policy commands; existing build commands extended | The only writers. The engine never writes. |
| API | `api/rules_mechanics.py`, `api/rules_configuration.py` | Authorize, then call. |

PostgreSQL is authoritative for every input. Derived values are disposable. No AI model, Foundry, network or external rules provider is needed.

### 2. Neutral contracts

These are core types. **None of them names classes, levels, proficiency, armor class, spell slots, a fixed ability list or challenge rating.**

- `RulesetRef(ruleset_code, ruleset_version_id, version_label)`.
- `SupportLevel`, declared per ruleset **version** by the registry:
  - `none`: no adapter for this version;
  - `calculating`: values are derived but not validated;
  - `validating`: values are derived and choices validated.

  Undeclared versions are `none`. Stored definitions remain readable through existing reads. `GET …/rules/support` publishes the level.
- `OutputDescriptor(key, value_type, label, category, depends_on: tuple[key], optional_dependencies: tuple[key], reduction)`.
  - Keys are adapter-namespaced.
  - `value_type` is one of `integer`, `decimal`, `dice`, `boolean`, `enum`, `set` or `text`.
  - `reduction` is a core reducer (`sum`, `max`, `min`, `set_union`, `single_set`) or `custom` (a pure adapter function).
- `DefinitionRef(kind, id, content_hash)`. `kind` is one of:
  - `rules_definition`, with the table carried in `DefinitionFact`;
  - `item_definition`, `creature_template_version`, `house_rule_version`, `content_package`;
  - `build_component`: `id = (character_build_id, component_kind, component_key)`, where `component_kind` is adapter-declared (`dnd5e.ability_score`, `pct.skill_allocation`);
  - `declared_override`, `runtime_fact`, `equipment_fact`, `draft_payload`.
- **`InputBundle`**, a frozen in-memory envelope. It is never persisted, so it is not an EAV store:

  ```text
  InputBundle
    context:            RulesContext  (ruleset, campaign_id, timeline_id, as_of, mode, purpose,
                                       configuration_version, house_rules[], option_policy)
    subject:            SubjectRef    (build | template_version | combatant | build_draft | unsaved_preview)
    definitions:        {DefinitionRef: DefinitionFact(kind_key, content: frozen mapping, content_hash)}
    build_components:   [ComponentFact(component_kind, ref, values: frozen mapping)]
    runtime_facts:      [RuntimeFact(fact_kind, ref, values, advisory_token)]
    equipment_facts:    [EquipmentFact(fact_kind, ref, values, advisory_token)]
    declared_overrides: [DeclaredOverride(target_key, value, ref, note)]
    manifest:           EffectiveInputManifest   (§10)
  ```

  `kind_key`, `component_kind` and `fact_kind` are adapter-declared strings. The core treats them as opaque. Each adapter's query-layer loader produces facts from its own typed tables. For 5e that is `rules_context_dnd5e.py`, reading `character_ability_scores`, `class_levels`, and so on.
- **The adapter protocol** has these members:
  - `adapter_id`, `adapter_version`, bumped whenever any output can change;
  - `support(ruleset_version)`;
  - `outputs(ruleset_version)`;
  - `override_points(ruleset_version)`;
  - `payload_schemas()`: Pydantic models by schema code and version;
  - `contributions(bundle) -> [Contribution]`;
  - `reduce(key, ordered_contributions, dependency_values)`, used only for `custom` reductions;
  - `validate(bundle, catalog, purpose) -> [Finding]`;
  - `advancement_options(bundle, catalog)`, added in R19-P4c.
- **Persistence neutrality.**
  - The build header is already neutral.
  - Each ruleset adds its **own typed child tables** with its adapter. Generic EAV build or rules tables are forbidden (`DATABASE_CONVENTIONS.md` §34).
  - Creature mechanics, overrides and house-rule parameters are adapter-schema JSONB, versioned per §18.4, with typed FK rows for every reference.

### 3. Deterministic composition

1. **Contribution identity.** `Contribution(source: DefinitionRef, ordinal, target_key, operation, amount, layer, note)`, where `contribution_id = (source.kind, source.id, ordinal, target_key)`.
   - The adapter assigns `ordinal` deterministically within one source: for example, the index of the effect in the definition's mechanics payload, or a declared sub-key.
   - `operation` is one of `set`, `add`, `multiply`, `min`, `max`, `grant`, `revoke`.
   - `layer` is one of `baseline`, `definition`, `build_choice`, `equipment`, `persistent_effect`, `temporary_effect`, `extension`, `declared_override`.
2. **Total order.** Contributions are sorted by `(layer rank, house-rule precedence (0 for non-house-rule sources), source.kind, str(source.id), ordinal, target_key)`. No two distinct contributions can tie, because the tuple contains the contribution id.
3. **Duplicates.**
   - The same `contribution_id` with identical payload collapses to one, with a `duplicate_contribution_collapsed` warning.
   - The same id with a different payload is an adapter contract violation. The affected key becomes `unsupported` with an `adapter_contract_violation` finding. The request does not fail.
4. **Dependencies.**
   - The core computes the transitive closure of `depends_on` for the requested keys and evaluates in topological order.
   - Each key's reduction receives its resolved dependency values.
   - Cycles are rejected when the registry is validated (a unit test), never at request time.
5. **Missing-input propagation.**
   - If any required dependency is `withheld`, `conflicting`, `unsupported` or `missing_input`, the dependent has no value. Its status is the most severe of these, in that order, and `blocked_by` lists the dependency keys.
   - `optional_dependencies` may fall back to an adapter-declared default, traced as `default_applied`.
6. **Conflicts.** These produce `conflicting` with every candidate value and its sources, and no single value:
   - two `set` contributions to one key in one layer with different values;
   - two house-rule overrides of one point without acknowledgement (§6).

   A `declared_override` that disagrees with a derivation the adapter can perform keeps the declared value, with status `declared` and a `declared_value_differs` finding.
7. **Purity.** No randomness (dice results are recorded inputs), no wall-clock reads and no I/O inside evaluation.
8. **Permanent versus temporary.**
   - Build components are `build_choice`.
   - Template mechanics and overrides are `definition` and `declared_override`.
   - Runtime facts (conditions, exhaustion, resources) are `persistent_effect`.
   - Time-limited effects are `temporary_effect`. Until an effect model exists they are reported `unsupported` when named.
   - Equipment contributes only while its facts say it is equipped or attuned.
9. **Build-choice traces** cite `build_component` refs, so every value points at the build row that produced it.

### 4. Rules content and provenance (R19-P2a)

- **Content packages.** New table `rules.content_packages`:
  - `content_package_id`, `ruleset_version_id`, `code`, `title`, `publisher_or_author`, `version_label`;
  - `origin_code` (lookup: `open_content`, `system_baseline`, `homebrew_world`, `gm_custom`, `licensed`);
  - `license_code` (lookup), `attribution_text`, `provenance_evidence_text`;
  - `review_status` (lookup: `unreviewed`, `reviewed`), `reviewed_by_user_id`, `reviewed_at`;
  - `checksum`, `installed_at`, `status`.

  Ruleset-wide definition tables gain a nullable, immutable `content_package_id`. World homebrew uses `owning_world_id` and an optional `source_id`. No definition must cite a commercial sourcebook.
- **The seed stays unreviewed.** The revision-022 content is backfilled into one package with `license_code = 'unknown'` and `review_status = 'unreviewed'`. This ADR makes **no legal determination** and claims no license. **OD-7 (Owner-approved 2026-11-03):**
  - The seed's provenance stays `unknown` / `unreviewed` until an evidence inventory is complete.
  - Before distribution, documented rights clearance, or replacement of uncleared content, is required.
  - The approval is **not** licensing clearance.

  The requirement applies before the next distributed artifact that contains the seed: any release image, packaged installer or public repository publication, and at the latest the Phase 17 packaging gate.

  **OD-7a (Owner-approved 2026-11-04).** The repository is publicly visible and already contains the seed. That existing publication is treated as **potentially distributed**:
  - the requirement for documented rights clearance, or replacement of uncleared material, therefore already applies to the seed as published, not only to the next artifact;
  - the R19-P2a rights and provenance inventory is prioritized ahead of other R19-P2 work;
  - the seed's package stays `license_code = 'unknown'` and `review_status = 'unreviewed'` until documented evidence supports a change. A recorded clearance changes only the items it documents.

  OD-7a is **not** licensing clearance and makes no determination that distribution has or has not occurred. This ADR still makes no legal determination.
- **Stable lineage.** `(family, definition table, code)` across ruleset versions.
- **Mutable existing fields.** Mechanically relevant columns that are mutable today stay mutable, because changing their editability is a behavior change. They are covered by content hashing in the manifest (§10). New mechanical payload columns introduced by R19 (template, item and house-rule mechanics, structured prerequisites) are mutable only while `draft` and immutable once `canon`.
- **Structured prerequisites and exclusions** (schema later, used in R19-P4c) are typed rows. A prerequisite the adapter cannot evaluate is `unsupported`, never treated as satisfied.

### 5. Evaluation contract

**Request:**
- `context`: the ruleset, campaign, timeline, `as_of` (`current` or a world time), `mode` (`truth` | `audience`), `purpose` (`display` | `validation` | `preview` | `analysis`), configuration version, house-rule versions with precedence, and option policy;
- `subject`;
- `requested_keys`.

**Result.** There are three separate axes. No single field merges them.

- **Calculation:** `support_level`, plus `completeness` (`complete` | `partial` | `none`) over the requested keys. Each value is a `DerivedValue(key, value | None, status, contributions, blocked_by, notes)`, where `status` is one of `computed`, `declared`, `default_applied`, `missing_input`, `unsupported`, `conflicting`, `withheld`.
- **Legality:** `validation`, which is `null` unless the purpose is `validation`, or the subject is a build with a stored review.
- **Approval:** `review`, one of:
  - `not_evaluated`: a legacy build created before review records existed;
  - `unreviewed`;
  - or the stored review decision.
- **Everything else:**
  - `trace`, the ordered contributions per key;
  - `contributing_definitions`;
  - `findings`, `missing_inputs`, `unsupported`, `conflicts`, `warnings`;
  - `manifest_fingerprint`, `adapter_id`, `adapter_version`.

**Label rules** for every client, with no exceptions:

| Condition | Label |
|---|---|
| Support `validating`, validation `valid`, review present, and no `declared`, `unsupported` or `conflicting` value among the displayed keys | **Rules-validated** |
| Validation `invalid` | "Invalid: …", even if every value computed, together with the review decision if any (for example "Rules exception approved by GM") |
| Any displayed value `unsupported` or `declared` | "Includes unsupported or GM-declared mechanics" |
| Support `calculating`, or no validation run | "Calculated, not rules-validated" |
| `audience` mode, a draft or a preview | "Preview, not rules-validated" |

There is no `authoritative` result field. "Rules-validated" can never coexist with an invalid, incomplete or unsupported finding.

### 6. House rules (owner Decision 5)

Storage is the same as in the first draft:
- `rules.house_rules`: identity, owning world, scope `world` | `campaign`;
- `rules.house_rule_versions`: append-only; kind `override` | `extension` | `unevaluated`; pinned ruleset version; parameters validated by the adapter's override-point schema; description; GM notes; source; canon status; supersedes. Editable while draft, immutable once canon;
- `campaign.campaign_house_rule_adoptions`: precedence unique among live adoptions; `acknowledges_adoption_ids`; adopted, retired, by and reason;
- `campaign.campaign_rules_configurations`: a monotonically increasing `configuration_version`, bumped in the same transaction as any adoption or option-policy change.

Semantics:
- Adoption is explicit; world rules never apply implicitly.
- Precedence is the integer, highest first.
- Overlapping overrides of one point are deterministic only when the higher adoption acknowledges the lower. Otherwise the affected keys are `conflicting`, and the configuration read lists the conflict.
- Extensions never replace the baseline.
- Override points are code-declared with parameter schemas. No user code or expression language is evaluated, ever.
- `unevaluated` rules are recorded and shown, and any key they name is at most "Calculated, not rules-validated".
- Changes never rewrite builds, reviews, events or combat outcomes.

**Authority to author, publish and adopt (OD-10, Owner-approved 2026-11-03):**
- **Campaign rules.** Campaign canon editors (campaign `canon.edit` on the route campaign) manage campaign-specific rules, house-rule adoption and allowed options.
- **Shared-world rules.** These need the matching world authority (`world.canon.edit` to author, `world.canon.review` to publish) plus route-campaign `canon.edit`.
- **Versioning.** Rules and overrides stay versioned: house-rule versions are append-only, and option policy changes advance the configuration version.

Read paths and schema may merge first. Commands that write house rules or option policy enforce this authority. They enable through their checkpoint's tests and review; no owner-decision gate remains.

### 7. Validation, drafts, review and effective use (owner Decision 6)

#### 7.1 Three separate axes

These are separate fields everywhere and are never merged:

| Axis | Values | Source |
|---|---|---|
| Calculation confidence | `support_level` and `completeness` | The adapter |
| Mechanical legality | The validation outcome `valid` / `invalid` / `incomplete` / `unsupported` / `conflicting` (the worst finding wins, in that order); `not_evaluated` when no validation has ever run | The adapter `validate()` with the eligible catalog |
| Human approval | The review decision `approved` / `approved_with_adjudication` / `approved_as_rules_exception`, or none | An authorized human |

#### 7.2 One policy for every producer

| Producer | Path | Result |
|---|---|---|
| GM direct create (`POST …/builds`, preserved) | Validates, then materializes (§7.5) | If valid: a review `approved` by the creator (`basis = direct_create`). Otherwise the build is created **unreviewed**, with its stored validation |
| GM via draft | Draft, validate, approve | A review with the decision taken |
| Delegated player (`character.propose_build`, after P03-B/C) | Draft, submit | Cannot approve or direct-create |
| Import (Phase 18), AI (Phase 20) | Draft only | Same review path |
| Creature template and house-rule publication | Validate, publish | The same three axes. Publishing a non-valid version needs adjudication or exception with a reason |

#### 7.3 Drafts (P3d-1)

`character.character_build_drafts` holds:
- character, origin campaign, ruleset version;
- `payload_schema_version`, `payload_jsonb`, which may hold custom or unsupported entries;
- status `editing` | `submitted` | `approved` | `rejected` | `withdrawn`;
- author, `row_version`;
- last validation snapshot and fingerprint.

Failed validation never deletes or rewrites draft content.

#### 7.4 Activation gate (P3d-2, a behavior change)

`activate_character_build` additionally requires one of:
1. the build has a review (any approval decision); or
2. the build is a legacy build (`not_evaluated`, created before P3d-2). **OD-9 (Owner-approved 2026-11-03):** legacy builds stay usable, with a visible "not evaluated" label, until they are explicitly reviewed under this activation policy. Once a review is recorded, item 1 governs.

An **unreviewed** build cannot be activated until an authorized reviewer records a review through `review_character_build`. That reviewer holds the same authority as approval.

#### 7.5 Immutable materialization

Approval and direct create copy everything into immutable rows in one transaction:
- typed build children;
- `character.character_build_custom_mechanics` (label, description, optional adapter-schema payload, `support_status`, adjudication note, by and at);
- and `character.character_build_reviews`: validation outcome and report snapshot, the **full effective-input manifest** (§10), decision, reviewer, reason, `build_draft_id` and payload hash.

The build has **no FK dependency on the draft**. Every referenced definition must be canon at materialization. A reference to a draft or otherwise mutable homebrew definition must either be published first or converted by the reviewer into a custom mechanic, which copies its content. The manifest's content hashes record the loaded content of every mutable existing definition used.

#### 7.6 Rules exceptions

**OD-9 (Owner-approved 2026-11-03):** campaign canon editors may approve supported rules exceptions with a recorded reason. Exceptions never override integrity or authorization constraints. `approved_as_rules_exception`:
- waives only **mechanical legality findings**: prerequisites, choice limits, rule-defined bounds;
- **never** waives:
  - authorization;
  - world, campaign or ruleset-version scope;
  - referential integrity (every FK, same-version and same-world trigger and canon requirement still applies);
  - payload safety (schema validation, size bounds);
  - provenance: the effective-input manifest, the content-package and source records, and the review record itself;
- requires a reason, which is recorded with the review;
- is available only to holders of campaign `canon.edit` on the route campaign, never to a delegated proposer or a controller.

Approval never changes a finding's outcome.

### 8. Advancement (R19-P4c)

`advancement_options(bundle, catalog) -> AdvancementOffer([AdvancementStep(kind_key, choices, constraints, explanation_refs)])`:
- `kind_key` is adapter-declared;
- proposals become drafts (§7);
- level-based and point- or skill-based systems use the same types (§13).

### 9. Authorization: five independent decisions, plus projection

| Decision | Question | Data and check | Never implies |
|---|---|---|---|
| 1. Source access | May this user read this `core.source_documents` document or passage? | `visibility`, `ai.reference_source_campaigns`, corpus capabilities. `contributor_private` visibility (OD-12, Owner-approved 2026-11-03) | Any of 2–5 |
| 2. Source retrieval and use | May this purpose use it (player read, GM prep, AI context, export)? | The `allow_*` flags plus purpose audience rules | 1, 3–5 |
| 3. Permitted campaign option | May characters in this campaign choose this definition? | `campaign.campaign_rule_option_policies` / `campaign_rule_option_entries` (deny wins) via `rules_catalog.py` | 1, 2, 4, 5 |
| 4. Mechanical validation | Is it rules-legal under the effective configuration? | The adapter plus the eligible catalog | 5 |
| 5. GM approval | Does an authorized human accept it? | Review records plus ADR 0021 authority | 4 (approval never upgrades a finding) |

**Citations.**
- Rules definitions cite **`core.sources`** only (the existing `source_id`).
- A citation to a rights-bearing `core.source_documents` document requires a typed link that does not yet exist. The proposed `rules.definition_document_citations` would hold a typed definition target, `source_document_id`, a locator, `cited_by_user_id` and `created_at`. It must be designed, with its **metadata authorization**, before any definition may cite a private or campaign-restricted document. The document's title and locator are shown only to viewers who pass decision 1 for that document. Everyone else sees nothing about the citation, not even its existence.
- The engine reads structured definitions only, never passages.

**Copied text.**
- The platform does **not** promise to detect copied licensed text.
- The bounded workflow is:
  1. authoring forms for definitions with descriptive text require an author attestation that the text is the author's own or permitted;
  2. when the author has access to quotation-forbidden documents, an optional server-side check compares the text against those passages (normalized exact and near-duplicate shingles above a fixed threshold) and flags matches for the reviewer, without refusing automatically;
  3. reviewers see flags in the review queue.
- **Limitations:** paraphrase, sources outside the corpus and short phrases are not detected. The check is an aid, not a guarantee, and makes no legal determination.

**A player's contributed material (OD-12, Owner-approved 2026-11-03):**
- Players may register reference sources they are entitled to use.
- A registered source starts `contributor_private`.
- GM access requires an explicit grant. **OD-12a (Owner-approved 2026-11-04):**
  - Only the **contributor** authorizes access to their contributor-private source, including a GM's access.
  - A GM cannot grant themselves access. Neither can any other campaign role, `access.manage` holder or access group.
  - World ownership, world roles and system administration (including the ADR 0020 recovery commands) grant no access automatically.
  - Consequently, the general `create_resource_grant` command and campaign retrieval grants (`ai.reference_source_campaigns`) refuse a contributor-private source unless the caller is its contributor. Each grant is explicit, scoped to named grantees, revocable by the contributor, and audited.
- Citations (decision 1, and the typed citation link) and AI retrieval (decision 2) are governed by those explicit sharing permissions. A reader who fails them sees nothing about the source or the citation.
- Deriving a homebrew definition from the material never widens access to its text.

**Catalog eligibility:**
1. the same version as the campaign pin;
2. canon, or a draft visible to its own authors for preview only;
3. ruleset-wide, or the campaign world's homebrew;
4. option-permitted, for choosing only. An approved build's definitions stay evaluable, with an `option_no_longer_permitted` warning.

**Projection.**
- **Truth mode** uses all authorized inputs and is returned only to callers who may read every input: initially `canon.edit`, later the ADR 0021 GM projection.
- **Audience mode** builds its bundle only from inputs visible to the viewer. Unidentified item properties and GM-hidden effects are excluded before evaluation, without any marker.
- Audience mode requires the P03-A projection tier, and for controllers the P03-B assignment.
- **Campaign scope (OD-1).** Authorization is resolved in the route campaign, and the evaluated state is that campaign's. A controller or GM of campaign A can never receive campaign B's mechanical values, even for the same character on the same timeline. A truth read of another campaign happens only inside lineage seeding or cross-campaign copy (ADR 0021 §3.6, OD-21 Owner-approved). That read requires `mechanics.transfer_read` in the source **and** the target capability, is limited to mechanical components (never player-private, Knowledge, briefing or GM-note material), and is available only after the commands are enabled.
- **Ownership is not an input (OD-20).** Equipment facts are built from the route campaign's possession, item state and attunement. If a future adapter needs legal ownership (for example a rule about "items you own"), it reads it as a **narrative fact**, read-only, recorded in the manifest like any other input. A calculation never changes ownership or possession.

### 10. Effective-input manifest, fingerprint, reproducibility (R19-05)

**The manifest.** `EffectiveInputManifest`, schema `rules_manifest.v1`, is canonical JSON with sorted keys and normalized numbers:

| Section | Contents |
|---|---|
| `engine` | `adapter_id`, `adapter_version`, `ruleset_version_id` |
| `context` | `campaign_id` (always required), `timeline_id`; `state_scope`: `campaign`, `lineage_seeded`, `migrated_from_timeline`, `cross_campaign_copy`, or `legacy_shared_state` (from each row's origin); `as_of` (`current`, or `world_time_id` + `sort_key`); the request clock `sort_key` used; `mode`, `purpose`, `requested_keys` |
| `configuration` | `configuration_version`; the ordered `(house_rule_version_id, precedence, acknowledges[])`; option-policy mode and live entry ids |
| `subject` | The subject kind and ids. For drafts and previews, a SHA-256 of the **normalized payload** (so two different unsaved payloads never share a fingerprint). For overrides, a SHA-256 of the normalized overrides |
| `definitions` | Every definition loaded: `{kind, table, id, canon_status, row_version?, content_hash}`. `content_hash` covers every column the adapter reads, **as loaded**, including mutable ones such as `hit_die` and `requires_attunement` |
| `build_components` | `{component_kind, key, values_hash}` |
| `runtime_facts` / `equipment_facts` | `{fact_kind, campaign_id, key, values_hash, advisory_token, initialized}`, loaded from the **route campaign's** tables. `initialized` distinguishes an explicitly empty family from a never-initialized one (ADR 0021 §3.8). An equipped item whose definition belongs to a different ruleset version is recorded as `incompatible_ruleset_version` and contributes nothing (ADR 0021 §3.7, ED-12). Rows with `compatibility_status = 'quarantined_incompatible_version'` (migrated state, ADR 0021 §3.7) are recorded as `quarantined` facts. They contribute nothing and raise a GM-only warning. Only effects classified `campaign_mechanical` in the registry (ADR 0021 §3.3) are ever loaded as runtime facts. The **loaded values are hashed**: HP, max HP, temporary HP, exhaustion, active build id, condition rows, resource amounts, item state (equipped, charges, quantity), inventory holder, attunement start and break. `last_event_id` is recorded as an advisory token only |
| `authorization` | The projection tier and mode, and the sorted list of included input refs. In audience mode it covers only audience-visible inputs, so hidden changes never alter an audience fingerprint |

- **Fingerprint.** SHA-256 of the manifest. Truth-mode manifests are stored only in GM-visible records (reviews, analyses). An audience-mode response carries only its own fingerprint.
- **Token ownership.** The engine **does not depend on `last_event_id`**. Phase 15 owns the state writers, and fixing the encounter-damage token omission is assigned to **Phase 15 P03-S** (cutover group G1, ADR 0021 §3.8). No R19 checkpoint changes state writers. Item state uses **split revision checks**: shared ownership versus campaign mechanical state (ADR 0021 §3.1.1). The engine reads the campaign mechanical values only.
- **Reconstruction.**
  - A stored review or analysis keeps its manifest and result. That is the exact historical record of what was computed.
  - A recomputation reproduces it only if the adapter version and every content and values hash still match. Otherwise the result reports `inputs_changed`, listing the differing refs, or `adapter_version_changed`. Old adapter code and old definition content are not retained.
  - **As-of requests:** the active build is reconstructable from the **campaign's** mechanical events (`campaign_id` = route campaign) within the timeline's bounded effective history. Before P03-S, the existing timeline resolution applies, labeled `legacy_shared_state` on multi-campaign timelines. Campaign state tables are current snapshots, so any other state fact for a past `as_of` is `missing_input` (`historical_state_unavailable`). Definitions are always current loaded content.
  - **Branch requests:** a campaign never reads a parent timeline's state. Branch inheritance is the explicit lineage seeding of ADR 0021 §3.4, which is materialized as local rows. Components that were not seeded are `missing_input`.
- **Caching.** No persistent cache in R19-P3. A future cache needs its own plan: storage, eviction, the leak analysis of cached truth values, and invalidation tests. A fingerprint alone is not that plan. Per-request memoization only.
- **Cache and memo identity (OD-1).** Every memo key, and any future cache key, includes `campaign_id`, `state_scope`, `mode` and the viewer's projection tier, as well as the fingerprint. Two campaigns with byte-identical state still have different fingerprints, because `campaign_id` is in the manifest. A value computed for campaign A can never be served for campaign B.
- **Performance.** Batched loaders (one round trip per family). List endpoints never evaluate. Encounter analysis evaluates each template version once.

### 11. Phase integration

- **Phase 16:** drafts through `character.propose_build`, the frozen preview contract (P3f), labels per §5. No client-side rules.
- **Phase 18:** imports produce drafts with provenance and use the same validation and approval. They never write builds or canon rules directly.
- **Phase 20:** AI explains from traces and cites manifest fingerprints. It never asserts uncomputed numbers. Player-purpose contexts use audience-mode results only.

### 12. Worked example: D&D 5e (2024)

Inputs:
- **Build B7:** `dnd5e`/2024; STR 16, DEX 12, CON 14; Fighter 3; Athletics and STR/CON save proficiencies; feature `fighting_style_defense`.
- **Custom mechanic:** "Ancestral grudge", `declared`, adjudicated in B7's review.
- **Equipment:** chain mail (armor 16, no DEX) and a shield (+2), both equipped.
- **State:** `poisoned`; `exhaustion_level` 1.
- **Configuration v4:** HR1 v2 overrides `dnd5e.hit_points_per_level` = `average` (precedence 10); HR2 v1 is `unevaluated` ("critical hits maximise dice").

Results (truth mode, display):
- `dnd5e.ability_modifier.str` = 3. Ref: the `build_component` (B7, `dnd5e.ability_score`, str).
- `dnd5e.proficiency_bonus` = 2. Refs: the class-level component; formula `dnd5e.pb_by_level`.
- `dnd5e.skill.athletics` = 3 + 2 − 2 = 3. The trace runs: STR modifier, then proficiency, then exhaustion. Exhaustion is a `persistent_effect` −2 × 1 under the 2024 model; its ref is the `runtime_fact` `character_state.exhaustion_level`, with a values hash.
- `dnd5e.armor_class` = 16 + 2 + 1 = 19. Refs: the two item definitions (content hashes), the feature, the equipment facts.
- `dnd5e.attack_roll_mode` = `disadvantage` (poisoned).
- `dnd5e.hit_point_maximum` uses HR1 v2. It differs from the stored `maximum_hit_points`, which yields `declared_value_differs`. The stored state stays authoritative.
- `dnd5e.critical_damage` is `unsupported` (HR2 `unevaluated`).

Axes:
- calculation `partial`;
- validation `unsupported`, from the stored review: the custom mechanic is an `unsupported` finding;
- review `approved_with_adjudication`.

Label: **"Includes unsupported or GM-declared mechanics"**, never "Rules-validated". If B7 had violated a prerequisite and been approved as a rules exception, AC would still compute 19, while the build's labels read "Invalid: prerequisite …" and "Rules exception approved by GM". That is the invalid-but-computable case.

A campaign pinned to an undeclared 2014 version gets `support: none`.

### 13. Contrasting archetype: a classless percentile system

This archetype is proven in **R19-P3a** by a test-only fixture adapter. No second ruleset is shipped.

- **Components:** `pct.characteristic` (STR, CON, SIZ, …, values 3–18) and `pct.skill_allocation` (points). There are no classes and no levels.
- **Outputs:**
  - `pct.skill.climb` (integer %, depending on `pct.characteristic.dex` and the allocation);
  - `pct.hit_points` = ⌈(CON + SIZ) / 2⌉;
  - `pct.damage_bonus` (`dice`, for example +1d4);
  - `pct.armor_points.location.chest` (damage absorbed, not a to-hit target).
- **Effects:** `poisoned` contributes `add −20` to skills. The override point is `pct.skill_cap`.
- **Advancement:** `pct.experience_check` steps with recorded rolls.

The same `InputBundle`, `Contribution`, `DerivedValue` and `Finding` types are used throughout.

## Consequences

- **Easier.** One engine serves sheets, previews, validation, templates, analysis and AI explanation. Unsupported rulesets and mechanics are honest by construction. Every value is traceable to the rows and content it used.
- **Harder.** Batched loaders per adapter. Hash-based manifests. The activation gate is a behavior change that needs acceptance. The citation link and the copied-text aid need their own work before private sources can be cited.
- **Foreclosed.**
  - User scripting.
  - Generic EAV rules or build storage.
  - Client-side rules.
  - Approval upgrading legality.
  - Exceptions waiving integrity.
  - The engine reading passages.
  - Implicit house rules.
  - D&D-shaped core types.
  - Persistent caching without its own plan.
- **Limitations.** Historical reproduction is by snapshot. Recomputation is exact only while inputs and adapter version are unchanged. Past runtime state is not reconstructable.

## References

- [PLANv2.md](../PLANv2.md) §6.1, 19.0–19.8; [PLAN.md](../PLAN.md) §6.1–6.3, §18.3
- Code: `src/dnd_ai/domain/character_calculations.py`, `src/dnd_ai/queries/{character_sheet,character_build_resolution}.py`, `src/dnd_ai/commands/{character_builds,character_state,encounters,item_operations,event_corrections}.py`, `src/dnd_ai/persistence/tables/{rules,characters,campaign,items,core,ai}.py`, `src/dnd_ai/api/reference_corpus.py`, `database/migrations/versions/{022,033,036}_*.py`
- [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §5.7, §18, §34
- [R19_FOUNDATION_IMPLEMENTATION_PLAN.md](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md)
