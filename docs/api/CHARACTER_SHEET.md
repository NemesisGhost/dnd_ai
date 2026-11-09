# Character sheet read contract

Current reference for the implemented sheet endpoint and active-build resolver, extracted
from the Phase 13D delivery record. ADRs 0021–0023 define accepted future changes; they
do not silently change this implementation. Reconcile a limitation against the current
command/query before treating it as outstanding work. Historical verification and fixture
details remain in [delivery history](../DELIVERY_HISTORY.md).

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

- **Character and build identity**: `character_id`, `name`, `character_kind` (`npc`, `player_character`, or
  `character` for a bare character row; also on `GET .../characters/{character_id}`, both tiers: not new
  disclosure, the World search card already returns the entity type to anyone who may discover the
  character), `species_code`,
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

Resolved through `campaign.character_state.character_build_id` — the
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

A character queried through two campaigns pinned to two unrelated
timelines correctly returns each timeline's own selected build — proven at
`tests/database/test_query_character_sheet.py::
test_unrelated_timelines_select_independent_builds_for_the_same_character`.

### 2.1 Branch-effective resolution

`campaign.character_state` is a current-value snapshot — one row per
`(timeline_id, character_id)`, no interval history (`docs/architecture/
DATABASE_MODEL.md` §17). Per `docs/ENTITY_LIFECYCLE.md` §9 rule 6, "the
branch creates new typed state only when it diverges": a freshly branched
child timeline has **no local row at all** until something changes on that
timeline. Reading `campaign.character_state` for the exact requested
timeline alone (the query's original, first-pass behavior) therefore
returned a false "no active build" empty sheet for any unchanged branch —
wrong, since the character's build did not stop being selected just
because a new timeline was created off its parent.

`dnd_ai.queries.character_build_resolution.
resolve_effective_character_build_id()` (used by `get_character_sheet_view`
whenever the requested timeline has no local row) resolves this correctly
and without leaking a post-branch parent change (CLAUDE.md rule 7), in
order:

1. **Local state wins.** A `character_state` row on `timeline_id` itself
   is always authoritative — even `NULL` ("explicitly no build") — and
   stops the walk. A timeline that has diverged never looks at its parent
   again for this component.
2. **Event-linked ancestry**, when it exists. `campaign.effective_events()`
   (revision 059) is the existing branch-aware effective-history function:
   it already walks `parent_timeline_id` and bounds each ancestor's own
   history at the point the next timeline down actually branched off it.
   Joining `narrative.event_effects` rows with `target_component =
   'character_build_id'` against that function's result, and taking the
   latest by world-time, recovers the value that was true on this timeline
   *as of its own effective history* — including recovering a value from
   an ancestor whose row has since changed again, which reading the row
   directly can never do.
3. **Baseline fallback.** Walk ancestors when no local state or branch-effective build event exists. A row with `last_event_id IS NULL` supplies the administrative baseline. If an ancestor later activated a build by event, recover the baseline from the `previous_value` of its earliest build effect. Checkpoint 15.2B-2 implemented `activate_character_build`: the first activation on untouched state is administrative; subsequent activations atomically record `character_build_activated`, previous/new values, and state. The fallback does not make arbitrary later event-less rewrites branch-safe.

Proven at `tests/database/test_query_character_sheet.py`:
`test_branch_child_with_no_local_state_inherits_the_parents_administrative_build`,
`test_branch_child_does_not_see_a_parent_build_change_made_after_the_branch`,
`test_branch_child_selecting_its_own_build_stays_independent_of_the_parent`,
`test_multi_level_ancestry_applies_each_timelines_own_branch_cutoff`, and
`test_a_stateless_branch_ancestry_still_returns_the_empty_sheet`.

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
- **Arbitrary later administrative build rewrites are not branch-safe.** The supported `activate_character_build` command already records later activations through causal events; its first activation initializes the administrative baseline. Do not bypass it with a second event-less write to an ancestor after branching. Such a write has no historical time to bound and cannot be reconstructed safely by the fallback. The old claim that no activation command exists was superseded by checkpoint 15.2B-2.
