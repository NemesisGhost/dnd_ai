"""Audience-filtered character query endpoint.

Exposes
`dnd_ai.queries.character.get_character_view` over HTTP as
`GET /campaigns/{campaign_id}/characters/{character_id}`, on the same
already-delivered OIDC authentication, transaction management, and access
resolution every other router uses.

Authorization: requires the `campaign.view` role capability in the target
campaign (the same base gate `dnd_ai.api.dungeon` uses), then a second,
resource-scoped decision specific to this endpoint: how much detail about
*this* character the caller may see. `dnd_ai.api.access.
resolve_character_view_tier` returns `True` (full mechanical detail — hit
points, conditions, resources, current location, and — Phase 11 workstream
5 — the active encounter this character currently participates in, if
any) for a caller holding
`canon.edit` (a GM) or `character.view_full` for this exact `character_id`,
`False` (name/species/size only) for one holding only `character.
view_summary`, and raises a fixed, non-disclosing 404 for a caller holding
neither — identical to a nonexistent character, so a caller can never learn
whether a character they have no relationship to even exists. This mirrors
`dnd_ai.api.dungeon`'s GM/party-perspective split: a capability tier
decided from the resolved `AccessContext`, not a query parameter, and never
downgraded by a caller simply omitting one.

Cross-campaign/world character ownership: `character.characters` carries no
`campaign_id` at all (world-scoped, like the dungeon/item/quest/
relationship domains) — `get_character_view` itself asserts the
character's own `core.entities.world_id` matches the caller's
resolved-timeline world (`dnd_ai.api._shared.timeline_world_id`, never
caller-supplied) before returning anything, raising
`CharacterNotFoundError` (a fixed, non-disclosing 404) identically for a
nonexistent character or one in a different world.

This is a read: no idempotency key, no `audit.change_log` row (a routine,
already-authorized character read is not "sensitive" in that table's
documented sense — see `dnd_ai.api.dungeon`'s identical reasoning) and no
mutation of any kind.

Phase 10 workstream 16 added a sub-resource:
`GET /campaigns/{campaign_id}/characters/{character_id}/inventory`
(`dnd_ai.queries.inventory.get_inventory_view`). It requires the *full*
character-view tier for `character_id` — `resolve_character_view_tier`
returning `False` (summary-only) is treated as unauthorized here too,
since inventory contents are full-detail data with no separate summary
form; the same `CharacterViewNotAuthorizedError` fixed 404 that route
already raises for "neither capability held" now also covers "only the
summary tier applies." A caller holding `canon.edit` for this exact
`character_id` (`access.has_capability(..., character_id=character_id)` —
never checked without a target, which would skip any character-scoped
`security.resource_grants` deny and let a role-derived GM bypass an
explicit, targeted restriction; see `dnd_ai.api.access.
resolve_character_view_tier`'s own docstring for the identical reasoning
its own `canon.edit` check already follows) additionally sees every item's
hidden mechanical properties regardless of identification state — see
`dnd_ai.queries.inventory`'s own docstring for why identification is
otherwise resolved only from the holder's own perspective, never an
arbitrary caller-supplied knower.

Phase 13D added a third sub-resource:
`GET /campaigns/{campaign_id}/characters/{character_id}/sheet`
(`dnd_ai.queries.character_sheet.get_character_sheet_view`). This closes the
documented backend gap (docs/PHASE13D_BACKEND_READINESS.md) blocking the
portal's Character workspace Sheet panel (docs/UI_DESIGN.md §5.5): the
existing `GET .../characters/{character_id}` response deliberately stays
Overview/Current-State-shaped (unchanged by this addition, for backward
compatibility, and because it is also part of the bounded Foundry-facing
surface — see `_ENCOUNTER_READ_SCOPE` above) rather than growing a large
nested mechanical-build payload onto it. The sheet route requires the same
*full* character-view tier `get_character_inventory_endpoint` requires
(`resolve_character_view_tier` returning `False` is insufficient here too,
for the identical reason: a full mechanical build is not summary-shaped
data), reusing `resolve_character_view_tier` rather than any new
authorization path, and — like inventory — does not opt into Foundry
access (`allow_foundry_access` omitted): it is portal-only until a
documented requirement demands otherwise. See `dnd_ai.queries.
character_sheet`'s own docstring for the active-build resolution rule
(`campaign.character_state.character_build_id` only, never a caller
input, the newest build, or a guess) and `docs/
PHASE13D_CHARACTER_SHEET_BACKEND.md` for the full response contract, raw-
vs-derived field policy, and known data-model limitations.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.character import get_character_view
from dnd_ai.queries.character_sheet import get_character_sheet_view
from dnd_ai.queries.inventory import get_inventory_view

from ._shared import timeline_world_id
from .access import (
    CharacterViewNotAuthorizedError,
    require_campaign_capability,
    resolve_character_view_tier,
)
from .deps import get_connection

router = APIRouter(tags=["characters"])

# The base campaign-membership gate — the same capability
# dnd_ai.api.dungeon requires for its own read endpoint.
_CHARACTER_VIEW_CAPABILITY = "campaign.view"

# The Foundry scope (dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES) get_
# character_endpoint requires from a paired-device credential — the
# "current location or encounter" read this route closes the exit
# criterion for (see its own comment below), matching FOUNDRY_SCOPES'
# documented "encounter/current-state reads" bundling.
_ENCOUNTER_READ_SCOPE = "encounter_read"

# canon.edit also unlocks every item's hidden properties regardless of the
# holder's own identification state — see this module's docstring.
_CHARACTER_MANAGE_CAPABILITY = "canon.edit"


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class CharacterConditionResponse(BaseModel):
    condition_code: str
    source_description: str | None


class CharacterResourceResponse(BaseModel):
    resource_code: str
    current_amount: int
    maximum_amount: int


class CharacterResponse(BaseModel):
    character_id: uuid.UUID
    name: str
    species_code: str
    size_category: str
    # None on every field below when the caller was authorized only for
    # the summary tier (dnd_ai.api.access.resolve_character_view_tier).
    current_hit_points: int | None
    maximum_hit_points: int | None
    temporary_hit_points: int | None
    exhaustion_level: int | None
    death_save_successes: int | None
    death_save_failures: int | None
    current_location_id: uuid.UUID | None
    # Phase 11 workstream 5 — see dnd_ai.queries.character's own docstring
    # for why this is a plain id, not the encounter's own content.
    active_encounter_id: uuid.UUID | None
    conditions: list[CharacterConditionResponse] | None
    resources: list[CharacterResourceResponse] | None


class InventoryItemResponse(BaseModel):
    item_instance_id: uuid.UUID
    display_name: str
    item_category_code: str
    rarity: str
    quantity: int
    condition_percentage: int | None
    charges_current: int | None
    charges_maximum: int | None
    is_equipped: bool
    is_destroyed: bool
    owner_entity_id: uuid.UUID | None
    identification_level: str
    # None unless identification_level allows it (or the caller holds
    # canon.edit) — see dnd_ai.queries.inventory's own docstring.
    properties: dict[str, Any] | None


class CharacterSheetClassLevelResponse(BaseModel):
    class_id: uuid.UUID
    class_code: str
    class_display_name: str
    level: int
    hit_die: int
    subclass_id: uuid.UUID | None
    subclass_code: str | None
    subclass_display_name: str | None


class CharacterSheetAbilityScoreResponse(BaseModel):
    ability_id: uuid.UUID
    ability_code: str
    ability_display_name: str
    score: int
    # None only for an unsupported (non-dnd5e) ruleset — see dnd_ai.queries.
    # character_sheet's own docstring.
    modifier: int | None


class CharacterSheetSkillResponse(BaseModel):
    skill_id: uuid.UUID
    code: str
    display_name: str
    governing_ability_code: str
    # None if the build has no character_ability_scores row for the
    # governing ability, or the ruleset is unsupported.
    governing_ability_modifier: int | None
    is_proficient: bool
    is_expertise: bool
    bonus: int | None
    passive_score: int | None


class CharacterSheetSavingThrowResponse(BaseModel):
    ability_id: uuid.UUID
    ability_code: str
    ability_display_name: str
    ability_modifier: int | None
    is_proficient: bool
    bonus: int | None


class CharacterSheetProficiencyResponse(BaseModel):
    proficiency_type_code: str
    proficiency_type_display_name: str
    target_label: str
    is_expertise: bool


class CharacterSheetFeatureResponse(BaseModel):
    feature_id: uuid.UUID
    code: str
    display_name: str
    description: str | None
    granted_at_level: int | None
    # "class" | "subclass" | "species" | "other" — see dnd_ai.queries.
    # character_sheet.FeatureView's own docstring.
    source_category: str


class CharacterSheetSpellResponse(BaseModel):
    spell_id: uuid.UUID
    code: str
    display_name: str
    level: int
    school: str | None
    casting_time: str | None
    range: str | None
    duration: str | None
    description: str | None
    damage_type_code: str | None
    damage_type_display_name: str | None
    # Independent associations — never require is_prepared to imply
    # is_known (see dnd_ai.queries.character_sheet's own docstring).
    is_known: bool
    is_prepared: bool


class CharacterSheetSpellcastingProfileResponse(BaseModel):
    character_spellcasting_profile_id: uuid.UUID
    class_id: uuid.UUID | None
    class_code: str | None
    class_display_name: str | None
    spellcasting_ability_id: uuid.UUID
    spellcasting_ability_code: str
    spellcasting_ability_display_name: str
    spellcasting_ability_modifier: int | None
    spell_attack_bonus: int | None
    spell_save_dc: int | None
    spells: list[CharacterSheetSpellResponse]


class CharacterSheetLanguageResponse(BaseModel):
    language_id: uuid.UUID
    code: str
    display_name: str


class CharacterSheetSenseResponse(BaseModel):
    sense_type: str
    range_feet: int


class CharacterSheetMovementResponse(BaseModel):
    movement_type: str
    speed_feet: int


class CharacterSheetResponse(BaseModel):
    character_id: uuid.UUID
    name: str
    species_code: str
    species_display_name: str
    size_category: str
    # None/empty below when the character has no active build selected on
    # this timeline (campaign.character_state.character_build_id IS NULL)
    # — a legitimate, successful "no active build" result, not an error.
    # See dnd_ai.queries.character_sheet's own docstring.
    character_build_id: uuid.UUID | None
    build_label: str | None
    ruleset_code: str | None
    ruleset_display_name: str | None
    ruleset_version_id: uuid.UUID | None
    ruleset_version_label: str | None
    total_level: int
    proficiency_bonus: int | None
    class_levels: list[CharacterSheetClassLevelResponse]
    ability_scores: list[CharacterSheetAbilityScoreResponse]
    skills: list[CharacterSheetSkillResponse]
    saving_throws: list[CharacterSheetSavingThrowResponse]
    other_proficiencies: list[CharacterSheetProficiencyResponse]
    features: list[CharacterSheetFeatureResponse]
    spellcasting_profiles: list[CharacterSheetSpellcastingProfileResponse]
    # Character-level, not build-owned — populated regardless of whether an
    # active build exists. See dnd_ai.queries.character_sheet's own
    # docstring.
    languages: list[CharacterSheetLanguageResponse]
    senses: list[CharacterSheetSenseResponse]
    movements: list[CharacterSheetMovementResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/characters/{character_id}",
    response_model=CharacterResponse,
    status_code=200,
)
def get_character_endpoint(
    character_id: uuid.UUID,
    # campaign_id is not otherwise used in this body — require_campaign_
    # capability's own returned dependency callable declares campaign_id
    # itself and binds it from the URL path independently, the same way
    # every other capability-gated route's path parameter resolves.
    #
    # allow_foundry_access=True, foundry_scope=encounter_read (Phase 11R
    # workstream F, scope-enforced by the Workstream 11R High-severity
    # correction): this route is what closes the "current location or
    # encounter" exit criterion for a paired Foundry device
    # (active_encounter_id below). get_character_inventory_endpoint below
    # deliberately does not opt in — it is not part of the bounded
    # adapter-facing surface any Phase 11 workstream built. The legacy
    # FoundrySystem credential is retired (dnd_ai.api.auth) and can never
    # reach this route at all.
    access: Annotated[
        AccessContext,
        Depends(
            require_campaign_capability(
                _CHARACTER_VIEW_CAPABILITY,
                allow_foundry_access=True,
                foundry_scope=_ENCOUNTER_READ_SCOPE,
            )
        ),
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CharacterResponse:
    include_full = resolve_character_view_tier(access, character_id=character_id)

    view = get_character_view(
        connection,
        character_id=character_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        include_full=include_full,
    )

    return CharacterResponse(
        character_id=view.character_id,
        name=view.name,
        species_code=view.species_code,
        size_category=view.size_category,
        current_hit_points=view.current_hit_points,
        maximum_hit_points=view.maximum_hit_points,
        temporary_hit_points=view.temporary_hit_points,
        exhaustion_level=view.exhaustion_level,
        death_save_successes=view.death_save_successes,
        death_save_failures=view.death_save_failures,
        current_location_id=view.current_location_id,
        active_encounter_id=view.active_encounter_id,
        conditions=(
            None
            if view.conditions is None
            else [
                CharacterConditionResponse(
                    condition_code=c.condition_code, source_description=c.source_description
                )
                for c in view.conditions
            ]
        ),
        resources=(
            None
            if view.resources is None
            else [
                CharacterResourceResponse(
                    resource_code=r.resource_code,
                    current_amount=r.current_amount,
                    maximum_amount=r.maximum_amount,
                )
                for r in view.resources
            ]
        ),
    )


@router.get(
    "/campaigns/{campaign_id}/characters/{character_id}/inventory",
    response_model=list[InventoryItemResponse],
    status_code=200,
)
def get_character_inventory_endpoint(
    character_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_CHARACTER_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> list[InventoryItemResponse]:
    if not resolve_character_view_tier(access, character_id=character_id):
        # The summary tier alone is not enough to see inventory contents —
        # see this module's docstring. Raised identically to "neither
        # capability held," which resolve_character_view_tier itself
        # already raises for that case.
        raise CharacterViewNotAuthorizedError(
            f"user {access.user_id} holds only the summary tier for character {character_id}, "
            "insufficient for inventory"
        )

    items = get_inventory_view(
        connection,
        holder_entity_id=character_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        reveal_all_properties=access.has_capability(
            _CHARACTER_MANAGE_CAPABILITY, character_id=character_id
        ),
    )

    return [
        InventoryItemResponse(
            item_instance_id=item.item_instance_id,
            display_name=item.display_name,
            item_category_code=item.item_category_code,
            rarity=item.rarity,
            quantity=item.quantity,
            condition_percentage=item.condition_percentage,
            charges_current=item.charges_current,
            charges_maximum=item.charges_maximum,
            is_equipped=item.is_equipped,
            is_destroyed=item.is_destroyed,
            owner_entity_id=item.owner_entity_id,
            identification_level=item.identification_level,
            properties=item.properties,
        )
        for item in items
    ]


@router.get(
    "/campaigns/{campaign_id}/characters/{character_id}/sheet",
    response_model=CharacterSheetResponse,
    status_code=200,
)
def get_character_sheet_endpoint(
    character_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_CHARACTER_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CharacterSheetResponse:
    if not resolve_character_view_tier(access, character_id=character_id):
        # The summary tier alone is not enough to see the mechanical sheet
        # — see this module's docstring. Raised identically to "neither
        # capability held," which resolve_character_view_tier itself
        # already raises for that case.
        raise CharacterViewNotAuthorizedError(
            f"user {access.user_id} holds only the summary tier for character {character_id}, "
            "insufficient for the sheet"
        )

    view = get_character_sheet_view(
        connection,
        character_id=character_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
    )

    return CharacterSheetResponse(
        character_id=view.character_id,
        name=view.name,
        species_code=view.species_code,
        species_display_name=view.species_display_name,
        size_category=view.size_category,
        character_build_id=view.character_build_id,
        build_label=view.build_label,
        ruleset_code=view.ruleset_code,
        ruleset_display_name=view.ruleset_display_name,
        ruleset_version_id=view.ruleset_version_id,
        ruleset_version_label=view.ruleset_version_label,
        total_level=view.total_level,
        proficiency_bonus=view.proficiency_bonus,
        class_levels=[
            CharacterSheetClassLevelResponse(
                class_id=c.class_id,
                class_code=c.class_code,
                class_display_name=c.class_display_name,
                level=c.level,
                hit_die=c.hit_die,
                subclass_id=c.subclass_id,
                subclass_code=c.subclass_code,
                subclass_display_name=c.subclass_display_name,
            )
            for c in view.class_levels
        ],
        ability_scores=[
            CharacterSheetAbilityScoreResponse(
                ability_id=a.ability_id,
                ability_code=a.ability_code,
                ability_display_name=a.ability_display_name,
                score=a.score,
                modifier=a.modifier,
            )
            for a in view.ability_scores
        ],
        skills=[
            CharacterSheetSkillResponse(
                skill_id=s.skill_id,
                code=s.code,
                display_name=s.display_name,
                governing_ability_code=s.governing_ability_code,
                governing_ability_modifier=s.governing_ability_modifier,
                is_proficient=s.is_proficient,
                is_expertise=s.is_expertise,
                bonus=s.bonus,
                passive_score=s.passive_score,
            )
            for s in view.skills
        ],
        saving_throws=[
            CharacterSheetSavingThrowResponse(
                ability_id=st.ability_id,
                ability_code=st.ability_code,
                ability_display_name=st.ability_display_name,
                ability_modifier=st.ability_modifier,
                is_proficient=st.is_proficient,
                bonus=st.bonus,
            )
            for st in view.saving_throws
        ],
        other_proficiencies=[
            CharacterSheetProficiencyResponse(
                proficiency_type_code=p.proficiency_type_code,
                proficiency_type_display_name=p.proficiency_type_display_name,
                target_label=p.target_label,
                is_expertise=p.is_expertise,
            )
            for p in view.other_proficiencies
        ],
        features=[
            CharacterSheetFeatureResponse(
                feature_id=f.feature_id,
                code=f.code,
                display_name=f.display_name,
                description=f.description,
                granted_at_level=f.granted_at_level,
                source_category=f.source_category,
            )
            for f in view.features
        ],
        spellcasting_profiles=[
            CharacterSheetSpellcastingProfileResponse(
                character_spellcasting_profile_id=p.character_spellcasting_profile_id,
                class_id=p.class_id,
                class_code=p.class_code,
                class_display_name=p.class_display_name,
                spellcasting_ability_id=p.spellcasting_ability_id,
                spellcasting_ability_code=p.spellcasting_ability_code,
                spellcasting_ability_display_name=p.spellcasting_ability_display_name,
                spellcasting_ability_modifier=p.spellcasting_ability_modifier,
                spell_attack_bonus=p.spell_attack_bonus,
                spell_save_dc=p.spell_save_dc,
                spells=[
                    CharacterSheetSpellResponse(
                        spell_id=sp.spell_id,
                        code=sp.code,
                        display_name=sp.display_name,
                        level=sp.level,
                        school=sp.school,
                        casting_time=sp.casting_time,
                        range=sp.range,
                        duration=sp.duration,
                        description=sp.description,
                        damage_type_code=sp.damage_type_code,
                        damage_type_display_name=sp.damage_type_display_name,
                        is_known=sp.is_known,
                        is_prepared=sp.is_prepared,
                    )
                    for sp in p.spells
                ],
            )
            for p in view.spellcasting_profiles
        ],
        languages=[
            CharacterSheetLanguageResponse(
                language_id=lang.language_id, code=lang.code, display_name=lang.display_name
            )
            for lang in view.languages
        ],
        senses=[
            CharacterSheetSenseResponse(sense_type=s.sense_type, range_feet=s.range_feet)
            for s in view.senses
        ],
        movements=[
            CharacterSheetMovementResponse(movement_type=m.movement_type, speed_feet=m.speed_feet)
            for m in view.movements
        ],
    )
