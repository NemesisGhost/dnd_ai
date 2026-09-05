# Phase 13D character Sheet-panel backend

Backend-only workstream closing the documented gap preventing the Character
workspace's Sheet panel (`docs/UI_DESIGN.md` §5.5) from displaying a
character's active mechanical build. Scope is backend-only, per the owner's
instructions for this workstream: `portal/` was not opened or modified.
React implementation of the Sheet panel remains owner work on another
machine, tracked separately.

## 1. Endpoint and response contract

`GET /campaigns/{campaign_id}/characters/{character_id}/sheet`
(`src/dnd_ai/api/characters.py`), backed by
`dnd_ai.queries.character_sheet.get_character_sheet_view`. A new
sub-resource of the existing character router, alongside the pre-existing
`GET .../characters/{character_id}` (Overview/Current-State) and
`GET .../characters/{character_id}/inventory` routes — none of which were
enlarged or reshaped by this workstream.

The response (`CharacterSheetResponse`, explicit nested Pydantic models,
no `dict[str, Any]` anywhere in the response shape) contains:

- **Character and build identity**: `character_id`, `name`, `species_code`,
  `species_display_name`, `size_category`, `character_build_id` (nullable),
  `build_label` (nullable), `ruleset_code`/`ruleset_display_name`/
  `ruleset_version_id`/`ruleset_version_label` (all nullable together with
  the build — see §6).
- **Class levels**: `class_levels[]` — `class_id`, `class_code`,
  `class_display_name`, `level`, `hit_die`, `subclass_id`/`subclass_code`/
  `subclass_display_name` (nullable). Ordered by class code — deterministic
  regardless of insertion order or multiclassing. Also `total_level` (sum
  of every class level) and `proficiency_bonus` (nullable — see §5).
- **Ability scores**: `ability_scores[]` — `ability_id`, `ability_code`,
  `ability_display_name`, `score`, `modifier` (nullable). An ordered
  collection, not six hardcoded JSON properties — a ruleset with a
  different ability count works unchanged.
- **Skills**: `skills[]` — every skill defined for the build's ruleset
  version, not only proficient ones. `skill_id`, `code`, `display_name`,
  `governing_ability_code`, `governing_ability_modifier` (nullable if the
  build lacks that ability score), `is_proficient`, `is_expertise`,
  `bonus` (nullable), `passive_score` (nullable). Expertise is never
  conflated with plain proficiency — it doubles the proficiency-bonus
  contribution rather than being reported as an ordinary proficient skill.
- **Saving throws**: `saving_throws[]` — every ability defined for the
  ruleset version reported as a saving throw entry: `ability_id`,
  `ability_code`, `ability_display_name`, `ability_modifier` (nullable),
  `is_proficient`, `bonus` (nullable).
- **Other proficiencies**: `other_proficiencies[]` — free-text weapon/
  armor/tool proficiencies only (`proficiency_type_code`,
  `proficiency_type_display_name`, `target_label`, `is_expertise`). Skill
  and saving-throw proficiencies stay in their own structured collections
  above and are never duplicated here.
- **Features**: `features[]` — every `character_features` row for the
  active build: `feature_id`, `code`, `display_name`, `description`,
  `granted_at_level` (nullable), `source_category` (`"class"` /
  `"subclass"` / `"species"` / `"other"`, derived from which of
  `rules.features.class_id`/`.subclass_id`/`.species_id` is set — most
  specific wins when more than one is, since the schema allows overlap).
  No feature is inferred or synthesized without a `character_features` row
  — see §7 for the one related, genuine limitation.
- **Spellcasting**: `spellcasting_profiles[]` — one entry per
  `character_spellcasting_profiles` row: `character_spellcasting_profile_id`,
  `class_id`/`class_code`/`class_display_name` (nullable — species/feat-
  granted casting has no owning class), `spellcasting_ability_id`/`_code`/
  `_display_name`, `spellcasting_ability_modifier` (nullable),
  `spell_attack_bonus` (nullable), `spell_save_dc` (nullable), and
  `spells[]`. Each spell appears **once per profile** with two independent
  booleans, `is_known`/`is_prepared` — never assumed to be a subset of one
  another, matching `character_known_spells`/`character_prepared_spells`'
  own documented independence. Spell fields: `spell_id`, `code`,
  `display_name`, `level`, `school`, `casting_time`, `range`, `duration`,
  `description`, `damage_type_code`/`damage_type_display_name` (nullable).
- **Languages, senses, movement**: `languages[]`, `senses[]`,
  `movements[]` — character-level records (`character.
  character_languages`/`.character_senses`/`.character_movements`), not
  build-owned. Populated regardless of whether an active build exists.

## 2. Active-build selection

Resolved exclusively through `campaign.character_state.character_build_id`
for the caller's resolved timeline and the requested character — the
documented, sole active-build rule (a `character_builds.is_current` column
was removed by revision 028 for exactly this reason: a character may use a
different build on different timelines after a branch). The query:

- never selects the newest build;
- never picks an arbitrary build among several;
- never accepts or trusts a caller-supplied build id;
- never infers a build from the campaign's ruleset.

The resolved `character_build_id` is defensively re-validated as belonging
to the requested `character_id` (`character.character_builds.character_id
= :character` in the same query) — the DB trigger from revision 028
already enforces this invariant at write time, so a mismatch here is
treated as a data-integrity assertion failure, not a caller-facing error
(unreachable in practice, per that trigger).

A character queried through two campaigns pinned to two different
timelines correctly returns each timeline's own selected build — proven at
`tests/database/test_query_character_sheet.py::
test_different_timelines_select_different_builds_for_the_same_character`.

## 3. Authorization behavior

Reuses the existing unified boundary with no new authorization path:

1. `require_campaign_capability("campaign.view")` — the same base gate
   every other character route uses.
2. `dnd_ai.api.access.resolve_character_view_tier(access,
   character_id=character_id)` — the same resource-scoped resolver
   `GET .../characters/{character_id}` and `.../inventory` already use.
   Returns `True` (full tier: `canon.edit` or `character.view_full` for
   this exact character) or `False` (summary tier only), or raises the
   fixed non-disclosing 404 if neither applies.
3. The summary tier alone is **insufficient** for the sheet — identical to
   the existing inventory route's own reasoning (a mechanical build has no
   meaningful "summary" shape). `resolve_character_view_tier` returning
   `False` raises the same `CharacterViewNotAuthorizedError` (fixed 404)
   the "neither capability held" case already raises.
4. Every check passes `character_id=character_id` through to
   `AccessContext.has_capability`, so a targeted `security.resource_grants`
   deny or allow on this exact character overrides a role-derived baseline
   exactly as it does for the existing character/inventory routes —
   including a targeted `canon.edit` denial overriding a role-derived GM
   (proven at `tests/database/test_api_character_sheet.py::
   test_a_character_targeted_canon_edit_deny_overrides_a_role_derived_gm`).
5. Nonexistent characters, cross-world characters, characters the caller
   cannot discover/view, and callers holding only the summary tier all
   raise the identical fixed 404 — a caller can never distinguish which
   case applied.
6. `require_campaign_capability` resolves a fresh `AccessContext` on every
   request (no caching) — a revoked role, relationship, or grant takes
   effect on the very next call, the same as every other route built on it.
7. The route takes no `character_id`/`party_id` perspective parameter at
   all (unlike the knowledge/quest routes) — there is nothing for a caller
   to supply that could be mistaken for a grant.
8. `allow_foundry_access` is intentionally omitted: this route is
   portal-only for now, matching the task's instruction not to enable
   Foundry-device access without an existing documented requirement (none
   names the Sheet panel).

No second, portal-specific authorization implementation was created —
every check above is a call into `dnd_ai.api.access`/`dnd_ai.domain.access`
that other routes already use and already have dedicated regression tests
for; this workstream added only the one new regression proving the sheet
route wires `resolve_character_view_tier` through correctly (§11), not a
re-derivation of the whole deny/allow-precedence matrix
`tests/database/test_api_characters.py` already covers exhaustively.

## 4. Raw versus derived fields

Every raw value (scores, levels, proficiency/expertise booleans, known/
prepared flags, feature/spell text fields) comes directly from the
database and is always populated once its owning row exists. Every
*derived* value (ability modifier, proficiency bonus, skill/saving-throw
bonus, passive score, spell attack bonus, spell save DC) is computed by
the new `dnd_ai.domain.character_calculations` module and is `None`
whenever:

- the build's ruleset is not recognized (§5), or
- one of the value's own raw inputs is missing — most commonly a skill or
  saving throw whose governing ability has no `character_ability_scores`
  row in this build, or any proficiency-gated bonus when the build has no
  class levels at all (no total level, so no proficiency bonus to derive).

No derived field is ever a guessed or "plausible-looking" placeholder — a
missing input always propagates to `None`, never a fabricated number.

## 5. Supported ruleset calculations

`dnd_ai.domain.character_calculations.supports_ruleset(ruleset_code)` is
the single, explicit gate every derived value passes through — currently
recognizing only `dnd5e` (the seeded ruleset family; the D&D 5e ability-
modifier/proficiency-bonus formulas are unchanged across the 2014/2024
editions this codebase's own seed data spans, so gating on the ruleset
*code* rather than also requiring a specific `version_label` is
deliberate, not an oversight — see that module's own docstring). For any
other (homebrew or future) ruleset, every derived field in the response is
`None` and only raw, authoritative values are returned — proven at
`tests/database/test_query_character_sheet.py::
test_an_unsupported_ruleset_returns_raw_values_with_every_derived_field_none`.

Implemented formulas (all D&D 5e, `docs/PLAN.md` §6.3):

- ability modifier: `floor((score - 10) / 2)`, correct for odd scores
  below 10 (Python's floor-division `//` already floors toward negative
  infinity, matching the rule exactly);
- total level: sum of a build's class levels;
- proficiency bonus: `2 + floor((level - 1) / 4)`, for `level >= 1`;
- skill/saving-throw bonus: ability modifier, plus the proficiency bonus
  once if proficient or twice if expertise applies;
- passive score: `10 + skill bonus`;
- spell attack bonus: ability modifier + proficiency bonus;
- spell save DC: `8 + ability modifier + proficiency bonus`.

This is deliberately not a general rules engine or plugin framework — one
closed ruleset-code vocabulary and one set of formulas, matching the one
ruleset this platform seeds today. Initiative was considered and
deliberately **not** added to this response: it is not derivable from
anything the sheet response contract asks for, and duplicating it here
would collide with Current State's own authoritative `campaign.
character_state.initiative` column (set only while a character is in an
encounter) — see §7.

Armor class, carrying capacity, maximum hit points, and attack rolls are
**not** calculated by this endpoint or module — the repository does not
yet contain all the authoritative inputs and semantics those calculations
require (e.g. no modeled worn-armor/shield state, no encumbrance rules, no
per-class hit-point-progression policy), and `docs/PLAN.md` §6.3 lists them
as future derived-calculation work. Guessing at undocumented assumptions
for any of these was explicitly out of scope.

## 6. Empty-build behavior

A character with no active build selected on the caller's timeline
(`campaign.character_state.character_build_id IS NULL`, or no `campaign.
character_state` row at all) is a **legitimate, successful** result, never
a 404 or 500: the response still identifies the character (name, species,
size) and represents every build-owned field/collection at one documented,
consistent "no build" value —
`character_build_id`/`build_label`/`ruleset_code`/`ruleset_display_name`/
`ruleset_version_id`/`ruleset_version_label` all `null`, `total_level` 0,
`proficiency_bonus` `null`, and `class_levels`/`ability_scores`/`skills`/
`saving_throws`/`other_proficiencies`/`features`/`spellcasting_profiles`
all empty arrays. The character-level `languages`/`senses`/`movements`
arrays are still populated in this state, since they never depended on a
build. The portal can render this state as "No active build."

## 7. Fields deliberately left in Current State or Inventory

Not duplicated onto this endpoint, per the task's explicit boundary:

- **Current State** (`GET .../characters/{character_id}`) keeps current/
  maximum/temporary hit points, exhaustion, death saves, conditions,
  resources, current location, and the active encounter. None of this is
  build-owned (it is `campaign.character_state`/`.character_conditions`/
  `.character_resources` timeline state), and duplicating it here would
  create exactly the second copy of domain state this codebase's own
  `dnd_ai.queries.integration` docstring already explains it avoids.
  Initiative in particular stays exclusively `campaign.character_state.
  initiative`, set only in an encounter — not recomputed or echoed here.
- **Inventory** (`GET .../characters/{character_id}/inventory`) keeps
  every item/equipment concern. The sheet response says nothing about
  what a character is carrying or wearing.

## 8. Genuine remaining data-model limitations

- **No confirmed active-build feat association.** `rules.feats` exists
  (Alert, Tough seeded), but there is no `character_*` table associating a
  feat with a build the way `character_features`/`character_proficiencies`
  do for features/proficiencies. This response does not invent one — feats
  are simply not represented in the Sheet response today. Adding a
  `character_feats` (or similar) association table is a schema change that
  belongs to its own convention-change/migration/test process, not this
  read-only workstream.
- **Armor class, carrying capacity, maximum hit points, and attack rolls**
  are not calculated here — see §5's closing paragraph for the exact
  missing inputs.
- **Homebrew/non-`dnd5e` rulesets get raw values only.** Extending
  `dnd_ai.domain.character_calculations` to a second ruleset is future
  work, gated behind that ruleset actually existing and needing it.

## 9. Fixture data added

`scripts/setup_phase13c_dev_data.py` (already the source of the Phase 13C/
13D live-verification dataset) was extended, not replaced — same
idempotent create-or-reconcile discipline as its existing Current-State
extension:

- **Character A** ("Fighter 2 / Wizard 1", champion subclass) — a fully
  populated build: all six ability scores; a multiclass build with a
  subclass; a proficient skill (Athletics) and an expertise skill
  (Perception — a fixture liberty, since nothing in this schema restricts
  expertise by class); a proficient saving throw (Strength); two free-text
  proficiencies (Martial Weapons, Heavy Armor); two granted features
  (Second Wind, Spellcasting — one per class); one spellcasting profile
  with independent known-only (Mage Hand), known-and-prepared (Magic
  Missile), and prepared-only (Cure Wounds) spells; one language
  (Common); one sense (Darkvision, 60 ft); one movement mode (Walk, 30
  ft).
- **Character B** ("Fighter 1") — a legitimate *minimal* build: one class
  level, only three of six ability scores (so a skill/saving throw
  governed by an absent ability renders its documented null-modifier
  state), one movement mode, and no proficiencies/features/spellcasting/
  languages/senses at all.

Both builds are selected as each character's *active* build on Phase13C
Timeline A via `campaign.character_state.character_build_id`
(`_ensure_active_build_selection`) — never a "current" flag on the build
itself. Every `rules.*` id the fixture references is looked up by code
against the already-seeded dnd5e/2024 content (migration 022); the fixture
creates no `rules.*` rows of its own.

## 10. Files changed

- `src/dnd_ai/domain/character_calculations.py` (new) — the derived-
  calculation service (§5).
- `src/dnd_ai/queries/character_sheet.py` (new) — `get_character_sheet_view`
  and its view dataclasses.
- `src/dnd_ai/api/characters.py` — the new `/sheet` route, its Pydantic
  response models, and an updated module docstring.
- `scripts/setup_phase13c_dev_data.py` — Character A/B sheet fixture data
  (§9) and updated module docstring.
- `tests/factories.py` — new factories for `character.character_builds`/
  `.character_ability_scores`/`.character_class_levels`/
  `.character_proficiencies`/`.character_features`/
  `.character_spellcasting_profiles`/`.character_known_spells`/
  `.character_prepared_spells`/`.character_languages`/`.character_senses`/
  `.character_movements` and for `rules.classes`/`.subclasses`/`.features`/
  `.spells`/`.damage_types`/`.proficiency_types`/`.languages`; extended
  `make_character_state` with an optional `character_build_id`; added
  `ruleset_content_id` and `use_dnd5e_ruleset` test helpers for reusing
  already-seeded rules content without colliding with it.
- `tests/database/test_query_character_sheet.py` (new).
- `tests/database/test_api_character_sheet.py` (new).
- `tests/database/test_setup_phase13c_dev_data.py` — one new regression
  reading Character A/B's sheets back through the real query.
- `docs/PHASE13D_CHARACTER_SHEET_BACKEND.md` (this file).
- `docs/PLAN.md` — one added clause to the Phase 13 status paragraph.

No migration was required — every table and column this endpoint reads
(`character.character_builds` and its children, `campaign.character_state.
character_build_id`, `rules.*`) already existed. Confirmed by `alembic
check` reporting no schema diff.

`portal/` was not opened or modified.

## 11. Focused tests added

**`tests/database/test_query_character_sheet.py`** (query-layer, no HTTP —
mirrors `tests/database/test_query_bootstrap.py`'s direct-query
discipline): no-character-state and no-build-selected empty-sheet states;
character-level languages/senses/movements returned even with no active
build; active build resolved from `campaign.character_state`, not the
newest or an arbitrary build (proven against three builds, only one
selected); different timelines selecting different builds for the same
character; nonexistent/cross-world character rejection; multiclass total
level and deterministic class ordering (inserted out of alphabetical
order); ability-modifier floor-division across six scores including two
below 10; the complete skill list (proficient, expertise, and non-
proficient with a missing governing ability, in one build); saving-throw
proficiency and bonus across every ruleset ability; free-text
proficiencies kept separate from skills/saving throws; feature source-
category derivation (class vs. species) and deterministic ordering;
independent known/prepared spell associations (known-only, both, and
prepared-only in one profile, each spell appearing exactly once);
legitimate empty collections for a build with only one class level; and
the unsupported-ruleset raw-values-only contract.

**`tests/database/test_api_character_sheet.py`** (HTTP/authorization —
mirrors `tests/database/test_api_characters.py`'s access-control shape):
non-member 404, capless-member 403, campaign-view-but-no-character-
capability 404, summary-tier-alone 404, full-tier success with build/
class/ability/skill data, a GM without any character-specific
relationship, a valid character with no active build returning the
documented empty response, a character-targeted `canon.edit` denial
overriding a role-derived GM, cross-world/nonexistent character
rejection, and that the two are indistinguishable (identical error code
and message; `correlation_id` is intentionally excluded from that
comparison, since it legitimately differs per request).

**`tests/database/test_setup_phase13c_dev_data.py`** (+1 test) —
`test_character_a_and_b_sheets_match_the_documented_fixture`: runs the
real fixture script twice (idempotency), then reads both characters' full
sheets back through the real `get_character_sheet_view` query and asserts
every documented populated/minimal value from §9.

Deliberately not duplicated: the full authorization deny/allow-precedence
matrix (already exhaustive in `test_api_characters.py`), database
constraint tests already covered by migration tests, and broad coverage of
every possible D&D 5e rule.

## 12. Verification

Run against a local PostgreSQL 18 server (`DATABASE_URL` set per
`docs/DEVELOPMENT.md` §3):

```
uv run ruff format --check   # PASS
uv run ruff check            # PASS
uv run mypy src              # PASS
uv run pytest tests/unit           # PASS (500 passed)
uv run pytest tests/database        # PASS (3315 passed)
uv run pytest tests/scenario        # PASS
uv run alembic -c database/alembic.ini upgrade head && \
  uv run alembic check        # PASS — no schema diff (no migration needed)
```

Full battery via `scripts/verify.sh full`:

```
PASS: ruff format --check (0s)
PASS: ruff check (0s)
PASS: mypy src (1s)
PASS: node --test foundry-module (0s)
PASS: pytest tests/unit (36s)
PASS: pytest tests/database (398s)
PASS: pytest tests/scenario (14s)
PASS: alembic check (schema diff) (3s)
All requested stages passed.
```

`git status --porcelain -- portal/` confirmed empty before and after this
workstream.
