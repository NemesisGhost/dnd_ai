# ADR 0023: Rules engine, calculation, validation, and source authorization

- **Status**: Proposed (R19-P0 architecture deliverable, 2026-11-02; awaiting independent architecture review and owner acceptance). It implements owner Decisions 4 (rules-engine-neutral architecture), 5 (versioned house rules) and 6 (drafts and unsupported mechanics).
- **Date**: 2026-11-02
- **Extends**: [ADR 0005](0005-separate-rules-definitions-from-world-instances.md) (rules definitions are separate from world instances) and the immutability policy of `DATABASE_MODEL.md` §8 (revisions 033/036). It does not replace the `rules` schema.
- **Related**: [ADR 0006](0006-ai-proposes-but-does-not-own-canon.md), [ADR 0016](0016-data-classification-and-private-data-handling.md), [ADR 0021](0021-shared-actor-identity-control-and-authoring-responsibility.md), [ADR 0022](0022-creature-templates-combatants-and-promotion.md).

## Context

What exists (verified in code at `defe3f7`):

- **Rulesets.**
  - `rules.rulesets` is the edition-neutral family; code `dnd5e` since revision 034.
  - `rules.ruleset_versions` has one `is_current` per family.
  - `rules.world_rulesets` is the world's family allow-list.
  - `campaign.campaigns.ruleset_version_id` pins each campaign to one exact version.
  - Seeded content (revision 022, `database/seeds/rules.*.yaml`) is a small 5e 2024 sample: two classes, two species, a few features and spells, plus full fixed vocabularies. The seed files record no license or origin.
- **Definitions.**
  - Typed tables `rules.abilities`, `skills`, `species`, `classes`, `subclasses`, `features`, `feats` (with free-text `prerequisite_description` only), `spells`, `conditions`, `creature_types`, `damage_types`, `languages`, `proficiency_types`, `resource_definitions`.
  - Each has a per-version `code`, immutable identity columns, a nullable `source_id` and a required `canon_status_id`.
  - `rules.item_definitions` additionally has `owning_world_id` (world homebrew) and `row_version`. It carries descriptive fields (rarity, attunement, weight, cost) but no mechanical modifiers.
- **Builds.** Immutable `character.character_builds` with 5e-shaped typed children. They are validated by `create_character_build` only for existence, canon status and same-version membership (`_require_in_ruleset`). There are no prerequisites, choice rules or completeness checks.
- **Calculations.** `src/dnd_ai/domain/character_calculations.py` holds pure 5e formulas: ability modifier, total level, proficiency bonus, skill and passive bonuses, saving throws, spell attack and save DC. They are gated by `supports_ruleset(ruleset_code)`, which recognises only `dnd5e`. `src/dnd_ai/queries/character_sheet.py` calls them and returns `None` for any value it cannot compute. There is no trace, no explanation, no version awareness (2014 and 2024 are treated alike), no equipment or conditions, and no house rules.
- **Runtime state.** `campaign.character_state` stores `current_hit_points` and `maximum_hit_points` as entered values. Conditions and resources are stored per `(timeline_id, character_id)`.
- **Reference corpus.** `core.source_documents` holds the classification, usage-rights status, `visibility` (`general` | `campaign_restricted`), allow-indexing, quotation, summarization, export and training flags, hash, supersession and removal. `ai.reference_source_campaigns` grants a source to a campaign. Registration and grants need campaign capability `rules_source.manage`; retrieval needs `campaign.view`. `PLAN.md` §6.1 and §18.3: a retrieved passage is reference context and never creates a rules definition.
- **Sources for world content.** `core.sources` are world-owned GM sources (D-26). They are not a licensing model.

Six owner decisions apply:
1. campaign control (ADR 0021);
2. world authority (ADR 0021);
3. hybrid creatures (ADR 0022);
4. rules-engine-neutral architecture from day one;
5. explicit, versioned house rules;
6. drafts may hold unsupported mechanics, which are flagged and never silently validated.

## Decision

### 1. Layering and ownership

The rules engine is ordinary application code in the existing layers. It is not a service with its own store:

| Layer | Module (new unless stated) | Responsibility |
|---|---|---|
| Domain (pure) | `src/dnd_ai/domain/rules_engine/` (`contracts.py`, `registry.py`, `composition.py`, `validation.py`, `fingerprint.py`) | Neutral types, the adapter protocol, deterministic composition, result and validation types. No database, no HTTP, no authorization. |
| Domain (pure, per system) | `src/dnd_ai/domain/rules_engine/adapters/dnd5e.py` | The D&D 5e adapter. It absorbs `domain/character_calculations.py`, which remains as a thin compatibility shim until its callers move. |
| Queries | `src/dnd_ai/queries/rules_context.py`, `src/dnd_ai/queries/rules_catalog.py` | Load an authorized, projection-scoped input bundle and the eligible catalog for one evaluation. |
| Commands | existing build commands plus new draft, review, house-rule and option-policy commands | Persist drafts, reviews, house rules and policies. The engine itself never writes. |
| API | `src/dnd_ai/api/rules_mechanics.py`, `rules_configuration.py` | Thin routers. Authorization happens here and in the query layer, before the engine is called. |

PostgreSQL stays authoritative for every input. Every derived value is disposable and rebuildable (`CLAUDE.md` §5 rule 1). The engine needs no AI model, no Foundry, no network and no external rules provider.

### 2. Neutral core contracts (no D&D concepts)

The core vocabulary is closed and system-neutral. **No universal type names classes, levels, proficiency, armor class, spell slots, six abilities or challenge rating.** Those exist only as adapter-declared keys.

- `RulesetRef(ruleset_code, ruleset_version_id, version_label)`.
- `SupportLevel` per ruleset version, declared by the adapter registry:
  - `none`: no adapter;
  - `descriptive`: definitions can be stored and shown, nothing is computed;
  - `calculating`: values are derived but not validated as rules-legal;
  - `validating`: values are derived and choices are validated.

  The level is published to clients (`GET …/rules/support`), so a UI can never advertise validation for a ruleset that lacks it.
- `OutputDescriptor(key, value_type, label, category)`. The key is namespaced and adapter-declared (`dnd5e.armor_class`, `pct.skill.climb`).
- `value_type` is one of `integer`, `decimal`, `dice` (count, size and modifier terms), `boolean`, `enum`, `set` and `text`. This is enough for a d20 bonus, a percentile skill, a damage-bonus die or a resistance set.
- `DefinitionRef(kind, id, version_token)`. `kind` is a closed core vocabulary of persisted definition kinds (`rules_definition`, `item_definition`, `creature_template_version`, `house_rule_version`, `content_package`, `declared_override`, `runtime_state`). The concrete table is resolved by the catalog, so the core does not enumerate 5e tables.
- `Contribution(target_key, operation, amount, layer, source: DefinitionRef, condition_note?)`.
  - `operation` is one of `set`, `add`, `multiply`, `min`, `max`, `grant` (add to a set) and `revoke`.
  - `layer` is one of `baseline`, `definition`, `build_choice`, `equipment`, `persistent_effect`, `temporary_effect`, `extension`, `declared_override`.
- `DerivedValue(key, value | None, status, contributions, notes)`. `status` is one of `computed`, `missing_input`, `unsupported`, `conflicting`, `declared`, `withheld`.
- `Finding(code, status, subject_path, message_key, refs)`. `status` is one of `valid`, `invalid`, `incomplete`, `unsupported`, `conflicting`.
- `EvaluationResult`, specified in §5.

The **adapter protocol** (`RulesAdapter`) has these members:

- `adapter_id`, `adapter_version`, a semantic version that is bumped whenever any formula's output can change;
- `support(ruleset_version) -> SupportLevel`;
- `outputs(ruleset_version) -> list[OutputDescriptor]`;
- `override_points(ruleset_version) -> list[OverridePoint]`;
- `payload_schemas() -> {schema_code: {version: pydantic model}}`, for template mechanics, overrides, house-rule parameters and draft payloads;
- `contributions(bundle) -> list[Contribution]`, which turns a typed input bundle into contributions;
- `compose(key, contributions, overrides) -> DerivedValue`, the per-key formula over the composed contributions, so system-specific maths stays in the adapter;
- `validate(bundle, catalog, purpose) -> list[Finding]`;
- `advancement_options(bundle, catalog)`, added in R19-P4c (structure in §8).

Registration is a closed, explicit table in `registry.py` (the codebase's "explicit `if`/closed vocabulary, no string-dispatched plugin" style; see `commands/ai_proposals.py`). It is not entry-point discovery. An unregistered ruleset is `none`. Support is declared **per ruleset version**; a version the adapter does not explicitly declare is `none`. Definitions of a `none` version can still be stored and shown through the existing reads, but no derived value or validation is offered. For example, the 5e adapter declares `2024` as `calculating`, rising to `validating` as checkpoints land; a `2014` version stays `none` until its version-specific rules exist. This replaces today's family-only `supports_ruleset`, which would wrongly apply 2024 rules to a 2014 version.

**Persistence neutrality.**
- `character.character_builds` (character, ruleset version, label, scope) is already system-neutral. Its 5e typed children (ability scores, class levels, proficiencies, features, spellcasting) are the 5e build shape.
- A future ruleset adds **its own typed child tables** in the migration that introduces its adapter. Generic entity-attribute-value build tables are forbidden (`DATABASE_CONVENTIONS.md` §34).
- A build with no class levels is already valid. A system without classes simply never writes that child.
- Creature mechanics and house-rule parameters are adapter-schema JSONB (`DATABASE_CONVENTIONS.md` §5.7: ruleset-specific, schema-versioned per §18.4). Every reference to another definition keeps a typed FK row (ADR 0022 §2).

### 3. Composition, precedence and determinism

1. The query layer loads a bundle: ruleset version, subject definitions, active build or template basis and overrides, equipped items, runtime conditions and effects, adopted house-rule versions, and the option policy.
2. The adapter emits contributions. The core sorts them by `(layer order, adoption precedence, DefinitionRef kind, id)`, a total and stable order.
3. For each requested key, the adapter's `compose` applies the contributions in that order.
4. Conflicts are detected by the core:
   - two `set` contributions to one key in one layer with different values;
   - two live house-rule overrides of the same override point without an acknowledged precedence (§6);
   - a `declared_override` of a key that a validating adapter can also derive and that disagrees with the derivation. The override is kept and the value is marked `declared`; the disagreement is recorded as a finding.

   A conflicting key gets status `conflicting`, carries every candidate value with its sources, and has **no** single value.
5. No randomness, no wall-clock reads and no database access inside evaluation. Dice results are inputs (recorded rolls), never generated.
6. **Permanent versus temporary.**
   - Build choices (immutable builds) are `build_choice`.
   - Template mechanics and their overrides are `definition` and `declared_override`.
   - Runtime timeline state (conditions, resources, exhaustion, current hit points) is `persistent_effect` or `runtime_state` inputs.
   - Time-limited effects (spell effects, rage) are `temporary_effect`. Until an effect model exists they are reported `unsupported` when named, never assumed.
   - Equipment contributes only while the inventory and state rows say it is equipped or attuned.

### 4. Rules content, provenance and versioning (R19-P2)

- **Content packages.** New table `rules.content_packages`:
  - `content_package_id`, `ruleset_version_id`, `code`, `title`, `publisher_or_author`, `version_label`;
  - `origin_code`, a lookup value: `open_content`, `system_baseline`, `homebrew_world`, `gm_custom` or `licensed`;
  - `license_code`, a lookup value, plus `attribution_text`;
  - `checksum`, `installed_at`, `installed_by_user_id`, `status`.

  Every rules-definition table gains a nullable `content_package_id` (additive, FK, immutable). Ruleset-wide definitions belong to a package. World homebrew definitions have `owning_world_id` (existing for items; added for creature templates and house rules) and an optional `source_id`. No definition is required to cite a commercial sourcebook. Seeded content is backfilled to one baseline package whose `license_code` is recorded only after the owner confirms the seed's origin (OD-7). Until then it is `unreviewed`.
- **Package installation** (Phase 17): optional packages are installed by an operator command or migration-style loader. Startup never requires a package beyond the baseline.
- **Stable identity across versions.** `(ruleset family, definition table, code)` is the lineage key. A successor ruleset version reuses a code for "the same" definition. Advancement history and template re-pinning use it.
- **Mechanical immutability.** Mechanical content of a definition (its adapter mechanics payload, structured prerequisites and modifiers) is mutable only while the definition is `draft`. Once it is `canon`, it is immutable (trigger, as revisions 033/036 do for identity). A correction is a new definition, or a new template or house-rule version, with a supersession link. Descriptive text stays editable. This makes historical calculations reproducible from recorded ids. Existing item-definition `row_version` edits remain allowed for the existing descriptive columns.
- **Structured prerequisites and exclusions** (R19-P4c, schema in R19-P2): `rules.definition_prerequisites` and `rules.definition_exclusions`. These are typed rows referencing definitions with at-most-one-typed-target columns. A prerequisite the adapter cannot evaluate is stored as text and reported `unsupported`; it is never treated as satisfied.

### 5. Evaluation contract

**Request** (`EvaluationRequest`):
- `context: RulesContext`:
  - `RulesetRef` and adapter id and version;
  - the campaign id and its rules configuration version;
  - ordered adopted `house_rule_version_ids` with precedence;
  - the option-policy version.
- `subject`, one of `build` (character build id), `template_version` (+ overrides), `combatant` (participant id), `build_draft` (draft id + payload) or `unsaved_preview` (payload only).
- `state` (optional): the timeline id and the state row versions used (`last_event_id` per row), inventory and item-state event tokens, and the as-of world time.
- `requested_keys` (optional; default is all outputs).
- `mode`: `truth` (server or GM) or `audience` (controller or other viewer, §9).
- `purpose`: `display`, `validation`, `preview` or `analysis`.

**Result** (`EvaluationResult`):
- `values: {key: DerivedValue}`;
- `trace: list[TraceStep]`. A step is a key, an ordered list of contributions with operation, amount and source `DefinitionRef` (id + version token), and the formula label the adapter used;
- `contributing_definitions: list[DefinitionRef]` (deduplicated);
- `findings: list[Finding]`;
- `missing_inputs`, `unsupported`, `conflicts`, `warnings` (lists of typed items with refs);
- `authority`, one of:
  - `authoritative`: the adapter is `validating` for this version, all requested keys are `computed` or `declared` with no unsupported or conflicting inputs affecting them, and no `unevaluated` house rule targets them. It means "may be presented as rules-validated". It never means canon;
  - `partial`: some requested keys could not be derived;
  - `informational`: the adapter is only `calculating`, or the mode is `audience`, or the subject is a draft or unsaved preview;
- `fingerprint` (§10), `adapter_id`, `adapter_version`, `ruleset_version_id`, `evaluated_at` (metadata only, not an input).

An unrecognized mechanic, such as a feature with no adapter mechanics or an unknown payload schema, appears in `unsupported` with its ref and makes affected keys `unsupported` or `partial`. It is **never** silently ignored, guessed or treated as zero.

### 6. House rules (owner Decision 5)

Storage (R19-P2c):
- **`rules.house_rules`** is the identity:
  - `house_rule_id`, `owning_world_id` (required);
  - `scope_kind` (`world` | `campaign`), plus `campaign_id` when the scope is campaign;
  - `code` (unique within scope), `title`, `created_by_user_id`.
- **`rules.house_rule_versions`** is append-only:
  - `version_number`, `ruleset_version_id` (pinned);
  - `kind`:
    - `override`: replaces the baseline behaviour at one adapter-declared **override point**, with `override_point_key` + `parameters_jsonb` validated by the point's schema;
    - `extension`: adds definitions, permitted options or contributions in the adapter's declarative contribution vocabulary. It never removes or replaces the baseline;
    - `unevaluated`: text only, recorded and shown, never computed;
  - `description` (for players and GMs), `gm_notes`;
  - `source_id`, `canon_status_id`, `supersedes_version_id`, `created_by_user_id`, `created_at`.

  It is mutable while `draft` and immutable once `canon`.
- **`campaign.campaign_house_rule_adoptions`** is the history:
  - `campaign_id`, `house_rule_version_id`, `precedence` (unique among live adoptions of the campaign);
  - `acknowledges_adoption_ids` (explicit conflict resolution);
  - `adopted_at`, `adopted_by_user_id`, `retired_at`, `retired_by_user_id`, `reason`.
- **`campaign.campaign_rules_configurations`** holds `campaign_id` and a monotonically increasing `configuration_version`. It is bumped in the same transaction as any adoption, retirement, re-ordering or option-policy change.

Semantics:
- **Adoption is explicit.** A world-scoped house rule affects only campaigns that adopt it. Nothing applies implicitly.
- **Precedence** is the adoption's integer, higher first. When two live overrides target one override point, the result is deterministic **only if** the higher-precedence adoption lists the other in `acknowledges_adoption_ids`. Otherwise the affected keys are `conflicting` and the campaign's active-rules read model lists the conflict. Extensions compose by §3. Two extensions that `set` one key conflict the same way.
- **Override points are code-declared** by the adapter, with a parameter schema and a default. Examples for 5e: `dnd5e.hit_points_per_level` (`average`, `rolled`, `maximum`); `dnd5e.ability_score_generation` (`standard_array`, `point_buy`, `rolled`, `manual`); `dnd5e.exhaustion_model` (`2014_levels`, `2024_d20_penalty`). A house rule cannot introduce executable logic. No user-provided Python, JavaScript or expression language is evaluated. A rule the adapter cannot express is stored as `unevaluated`, and any output it names is at most `informational`.
- **Visibility.** The campaign's active-rules read model (`GET …/rules/configuration`) shows the ruleset version, support level, live adoptions in precedence order, their descriptions and unresolved conflicts. It is available to campaign members; `gm_notes` go to GMs only.
- **No retroactive rewrite.** Adopting, retiring or re-versioning a house rule never edits an existing build, review record, event or combat outcome. Stored review snapshots keep the configuration version and the house-rule version ids they used.

Authority (OD-10):
- campaign-scoped house rules: campaign `canon.edit` to author, `canon.edit` to adopt;
- world-scoped house rules: world `world.canon.edit` to author and `world.canon.review` to publish;
- adoption into a campaign: campaign `canon.edit`.

### 7. Validation, drafts and human review (owner Decision 6)

**One contract for every producer.** GM authoring, player proposals (Phase 16), imports (Phase 18), AI proposals (Phase 20), creature templates and house rules all use `ValidationReport`:
- `overall`: the worst of the finding statuses, in the order `invalid` > `conflicting` > `unsupported` > `incomplete` > `valid`;
- `findings`, each with an exact code, a subject path and contributing refs;
- `fingerprint`, `adapter_version`, `evaluated_at`.

There is no separate player, GM, import or creature validator.

**Build drafts** (R19-P3d). New table `character.character_build_drafts`:
- `build_draft_id`, `character_id`, `campaign_id` (the origin), `ruleset_version_id`;
- `payload_schema_version`, `payload_jsonb`: the proposed build, which may hold unknown or custom entries and references not yet in the catalog;
- `status`: `editing`, `submitted`, `approved`, `rejected` or `withdrawn`;
- `created_by_user_id`, `submitted_at`, `row_version`;
- `last_validation_jsonb` + `last_validation_fingerprint` (a snapshot, informational).

Draft content is never deleted by failed validation. A payload is a proposal snapshot (`DATABASE_CONVENTIONS.md` §5.7). It is re-validated at approval, never trusted.

**Custom and unsupported mechanics on an approved build.** New table `character.character_build_custom_mechanics`:
- `character_build_id`, `label`, `description`;
- `declared_payload_jsonb` (optional, adapter schema when one exists);
- `support_status` (`unsupported` | `incomplete` | `declared`);
- `adjudication_note`, `adjudicated_by_user_id`, `adjudicated_at`.

These rows are immutable with the build. Approval never converts them into validated mechanics. Calculation traces show them as `declared` or `unsupported`.

**Review record.** New table `character.character_build_reviews`:
- `character_build_id`, `build_draft_id`;
- `validation_overall`, `validation_report_jsonb` (a snapshot);
- `rules_fingerprint`, `adapter_version`;
- `decision`: `approved`, `approved_with_adjudication` or `approved_as_rules_exception`;
- `reviewer_user_id`, `reason`, `created_at`.

It is append-only. **Human approval and automated validation are separate fields that are never merged.** A build approved with adjudication keeps its `unsupported`, `incomplete` or `invalid` findings forever.

**Approval path.** `approve_build_draft` re-validates under lock, records the review, and materializes the build through the **existing `create_character_build`** in the same transaction. That function stays the only writer of build rows. Its contract is extended to accept custom-mechanics rows and the build scope, and to skip the strict "every reference canon" check only for items the reviewer explicitly adjudicated. `activate_character_build` stays the only activation path.

**Effective-state policy** (defaults, OD-9):

| Validation overall | Create (approve) | Activate | Character publication |
|---|---|---|---|
| `valid` | Reviewer with build authority | Campaign `canon.edit` | Independent of build validation |
| `incomplete` / `unsupported` | Only as `approved_with_adjudication`, naming each finding | Allowed; the active build shows its status | Independent |
| `conflicting` | Only with adjudication that resolves or accepts each conflict | Allowed after that | Independent |
| `invalid` | Only as `approved_as_rules_exception` with a mandatory reason, by campaign `canon.edit` (never a delegated player) | Allowed; shown as a rules exception | Independent |

Legacy builds created before R19-P3d have no review record. Their status is `not_evaluated`, which is distinct from every validation outcome. They are never shown as validated.

### 8. Advancement (structure only; implemented in R19-P4c)

Advancement is adapter-specific, behind one neutral interface:
- `advancement_options(bundle, catalog) -> AdvancementOffer`;
- the offer lists eligible steps (`AdvancementStep(kind_key, choices, constraints, explanation_refs)`). `kind_key` is adapter-declared: `dnd5e.class_level` or `pct.experience_check`;
- every proposal becomes a build draft (§7);
- a level-based system offers class levels; a point-buy or skill-improvement system offers point allocations or skill increments with recorded dice inputs. The core never assumes levels.

### 9. Authorization: five separate decisions

| Decision | Question | Data and check | Never implies |
|---|---|---|---|
| **1. Source access** | May this user read this source document or its passages? | `core.source_documents.visibility`, `ai.reference_source_campaigns` grants and corpus capabilities. Future `contributor_private` visibility with an owning user (OD-12). | Retrieval for other purposes, option permission, validation, approval |
| **2. Source retrieval and use** | May this purpose (player read, GM prep, AI context, export) use the passage? | `allow_indexing`, `allow_quotation`, `allow_summarization`, `allow_export`, `allow_training`, plus the purpose's audience rules (Phase 12/20) | Access for another purpose. Use by an option or calculation |
| **3. Permitted campaign option** | May characters in this campaign choose this definition? | `campaign.campaign_rule_option_policies` (`mode`: `all_canon` default or `allow_list`) and `campaign.campaign_rule_option_entries` (allow or deny, at-most-one typed target: class, subclass, species, feat, spell, feature, item definition, creature template or whole content package; deny wins), evaluated by `queries/rules_catalog.py` | Access to any source text. Validity. Approval |
| **4. Mechanical validation** | Is this choice or value rules-legal under the effective configuration? | The adapter (`validating` support) and the eligible catalog | Approval. Permission to commit |
| **5. GM approval** | Does an authorized human accept this into canon or effective state? | Review records (§7) and existing authoring authority (ADR 0021) | Validation (approval never upgrades a finding) |

The engine computes from **structured definitions only**. It never reads source passages. An explanation contains `DefinitionRef`s and source ids. Rendering a source's title, citation or text goes through decisions 1 and 2 for the viewer.

A player who contributes legitimately owned material does not widen its audience. Their source stays at the visibility they chose. A GM may author homebrew definitions (mechanics and a summary in their own words) and cite that source by id. Authoring commands refuse definition text that copies a passage whose source forbids quotation. The structured mechanics of a permitted option are visible to the members who may use the option; the licensed text is not.

**Catalog eligibility** (`rules_catalog.py`):
1. same ruleset version;
2. canon, except a draft read by its own authors for a preview;
3. ruleset-wide, or homebrew owned by the campaign's world;
4. permitted by the option policy (only for choosing; an already-approved build's definitions remain evaluable and produce an `option_no_longer_permitted` warning).

**Projection.** In `truth` mode values are computed from all authoritative inputs and returned only to callers who may read every input (GM/`canon.edit`, or the projection rules of ADR 0021 §5). In `audience` mode the bundle is built only from inputs visible to the viewer. Unidentified item properties (`knowledge.item_identification`) and GM-hidden effects are excluded *before* evaluation, and the result does not disclose that anything was excluded. A truth-mode value is never returned to a viewer who cannot see its inputs.

### 10. Reproducibility, caching and performance

- **Fingerprint.** SHA-256 over canonical JSON of the request's effective inputs:
  - adapter id and version, `ruleset_version_id`, campaign `configuration_version`;
  - ordered house-rule version ids, option-policy version;
  - subject ids and version tokens (build id; template version id; draft `row_version`);
  - state tokens (`last_event_id` of each `campaign.character_state`, `character_conditions` and `character_resources` row used; item-state event tokens; inventory-entry ids);
  - mode, purpose and requested keys.
- **Reproducibility.** A historical calculation is reproduced exactly while the adapter version is unchanged, because every other input is immutable or event-versioned. After an adapter formula change, the stored review or analysis snapshot is the record of what was computed then. Recomputing reports `adapter_version_changed`. Old adapter code is not retained (an explicit limitation). Historical combat outcomes are recorded facts (events, combat actions) and are **never** recomputed.
- **Invalidation by construction.** Nothing is persisted as a cache in R19-P3. Values are computed per request with a per-request memo. Each invalidation trigger changes a fingerprint input, so a future content-addressed cache can never serve stale data:

| Change | Fingerprint input |
|---|---|
| Active character build | State row `last_event_id` (activation records an event) |
| Equipment | Item-state and inventory tokens |
| Runtime effects | Condition and resource row tokens |
| Rule version | `ruleset_version_id` / template or definition version ids |
| House-rule version | Configuration version + version ids |
| Campaign rule eligibility | Configuration version (option-policy changes bump it) |
| Relevant authorization | Not cached. Projection is applied per request after evaluation (`audience` mode re-derives the bundle) |

- **Performance.** Evaluation is pure and small. The cost is loading the bundle, so the context loader batches every family in one round trip per family (no N+1). List endpoints (World Explorer, rosters) never evaluate mechanics. Encounter analysis evaluates each template version once and applies per-combatant overrides. Targets are recorded in the plan (§6 performance notes).

### 11. Phase integration

- **Phase 16.** The player build editor writes build drafts (§7) through `character.propose_build` (ADR 0021 §3.5), calls the validation preview, and submits for review. It shows the support level and validation status exactly as returned. It never computes rules client-side.
- **Phase 18.** An import creates build drafts, template drafts or house-rule drafts through the same commands, and runs the same validation. Promotion is approval. There is no import-only write or validation path.
- **Phase 20.** AI may explain results using the trace and contributing refs, and may propose drafts. It never produces a mechanical number that the engine did not compute, and it cites the engine result's fingerprint.

### 12. Worked example: D&D 5e (2024)

Inputs:
- **Subject:** Build B7, ruleset `dnd5e` / `2024`, owned by world W.
  - STR 16, DEX 12, CON 14.
  - Fighter level 3.
  - Proficiencies: Athletics; STR and CON saving throws.
  - Feature `fighting_style_defense`, which the adapter maps to +1 armor class while armor is worn.
  - A custom mechanic, "Ancestral grudge (vs goblins)", status `declared`, adjudicated.
- **Equipment:** chain mail (item-definition mechanics: armor base 16, no DEX), shield (+2), both equipped.
- **State:** condition `poisoned`; exhaustion 1.
- **Configuration:** campaign version 4. House rule HR1 v2 is an `override` of `dnd5e.hit_points_per_level` = `average` (precedence 10). House rule HR2 v1 is an `unevaluated` rule: "critical hits maximise damage dice".

Result (truth mode):
- `dnd5e.ability_modifier.str` = 3 (baseline formula; ref: ability score row on B7).
- `dnd5e.proficiency_bonus` = 2 (from total class level 3; refs: class-level row, formula label `dnd5e.pb_by_level`).
- `dnd5e.skill.athletics` = 3 + 2 − 2 = **3**. The trace has: STR modifier; proficiency; exhaustion as a `persistent_effect`, −2 × 1 under the 2024 model. Its ref is the `runtime_state` input `campaign.character_state.exhaustion_level` with that row's `last_event_id` token; exhaustion is a state column, not a seeded `rules.conditions` row.
- `dnd5e.armor_class` = 16 + 2 + 1 = **19**. Refs: chain mail and shield item definitions, the feature, item-state tokens.
- `dnd5e.attack_roll_mode` = `disadvantage` (enum; ref: poisoned condition).
- `dnd5e.hit_point_maximum` = computed with the `average` parameter (ref: HR1 v2). The stored `campaign.character_state.maximum_hit_points` differs, so a `declared_value_differs` finding is reported and the stored value stays authoritative state.
- `dnd5e.critical_damage`: status `unsupported`; its note cites HR2 v1 `unevaluated`.
- The custom mechanic is listed as `declared`, and no key consumes it.
- `authority` = `partial`, because one requested key is unsupported. The fingerprint covers B7, the state tokens, configuration 4 and adapter `dnd5e@0.3.0`.

On a campaign pinned to an un-seeded `dnd5e` / `2014` version, the same request returns `support: none` and no values, because the 2024 exhaustion and other rules may not be applied to it.

### 13. Contrasting archetype: a classless percentile skill system

This is a paper exercise. No second ruleset is implemented. It shows that the interface needs no classes, levels, armor class or proficiency. A test-only fake adapter (R19-P3f) implements a few keys to prove the core types compile and compose without 5e assumptions.

- **Build shape** (hypothetical typed tables added only if this system is ever supported): characteristics (STR, CON, SIZ, INT, POW, DEX, APP, each 3–18), skill percentages and no classes. The build header is the existing neutral `character.character_builds`.
- **Outputs:** `pct.skill.climb` (integer %, base from characteristics plus allocated points); `pct.hit_points` = ⌈(CON + SIZ) / 2⌉; `pct.damage_bonus` (dice value, for example +1d4, from STR + SIZ); `pct.armor_points.location.chest` (integer: damage absorbed, not a to-hit target).
- **Effects:** a `poisoned` condition contributes `add −20` to skill outputs; the house-rule override point `pct.skill_cap` = 95.
- **Advancement:** `advancement_options` returns `pct.experience_check` steps for skills used successfully. The roll results are recorded inputs, and the draft proposes the increments. No level exists anywhere.

Every type used (`OutputDescriptor`, `Contribution`, `DerivedValue`, `Finding`, `AdvancementStep`) is the same as in the 5e example.

## Consequences

- **Easier.** One engine serves the sheet, previews, validation, creature templates, encounter analysis and AI explanations. Unsupported rulesets are honest by construction. House rules are auditable data. Every number can be explained and reproduced from ids.
- **Harder.** Every mechanic needs an adapter contribution and tests before it can be shown as computed. Mechanical definitions become immutable once canon, so corrections need new versions. Context loading must stay batched. Projection discipline (truth versus audience) must be tested on every endpoint that returns derived values.
- **Foreclosed.**
  - A user scripting engine.
  - Generic EAV rules or build tables.
  - Client-side rules calculation.
  - Approval upgrading validation.
  - The engine reading source passages.
  - Implicit house rules.
  - Universal 5e-shaped engine types.
- **Limitation.** Exact recomputation across adapter versions is not supported. Snapshots are the historical record.
- **Follow-ups:**
  - `DATABASE_MODEL.md` §8 (content packages, house rules, option policy, drafts, reviews);
  - `DOMAIN_MODEL.md` §7 (house rule, content package, validation report vocabulary);
  - `ENTITY_LIFECYCLE.md` (draft, review and adoption commands);
  - `PLAN.md` §6.3 and §18.3 cross-references;
  - ADR 0005 stub completion (PLANv2 §18 item 17).

## References

- [PLANv2.md](../PLANv2.md) §6.1, 19.0–19.8; [PLAN.md](../PLAN.md) §6.1–6.3, §18.3
- Code: `src/dnd_ai/domain/character_calculations.py`, `src/dnd_ai/queries/character_sheet.py`, `src/dnd_ai/commands/character_builds.py`, `src/dnd_ai/domain/character_builds.py`, `src/dnd_ai/persistence/tables/{rules,characters,campaign,core,ai}.py`, `src/dnd_ai/api/reference_corpus.py`, `database/migrations/versions/022_seed_initial_ruleset.py`
- [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §5.7, §18, §34
- [R19_FOUNDATION_IMPLEMENTATION_PLAN.md](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md)
