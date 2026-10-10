"""Character build authoring endpoints (Phase 15 checkpoint 15.2B-2).

    GET  /campaigns/{id}/authoring/character-build-options
    GET  /campaigns/{id}/authoring/characters/{character_id}/builds
    POST /campaigns/{id}/authoring/characters/{character_id}/builds
    POST /campaigns/{id}/authoring/characters/{character_id}/builds/{build_id}/activate
    POST /campaigns/{id}/authoring/characters/{character_id}/state/initialize

All `canon.edit`. Builds are immutable (decision D-9): there is no edit route. The
character must be an NPC or player character of the campaign's world; anything
else is a 404. Writes use the campaign idempotency store, re-check authority under
lock, answer with id-only receipts, and write one audit row (redacted values).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.character_builds import (
    BuildResult,
    activate_character_build,
    create_character_build,
    initialize_character_state,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.character_builds import (
    ABILITY_SCORE_MAX,
    ABILITY_SCORE_MIN,
    CLASS_LEVEL_MAX,
    CLASS_LEVEL_MIN,
    LABEL_MAX_LENGTH,
    MAX_HIT_POINTS,
    TARGET_LABEL_MAX_LENGTH,
    BuildInput,
    ClassLevelInput,
    ProficiencyInput,
    SpellcastingInput,
)
from dnd_ai.queries.character_builds import (
    campaign_ruleset_version,
    get_build_options,
    get_character_builds,
)

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError

router = APIRouter(tags=["character-builds"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]

_BASE = "/campaigns/{campaign_id}/authoring/characters/{character_id}"


class AbilityScoreBody(BaseAuthoringRequest):
    ability_id: uuid.UUID
    score: int = Field(ge=ABILITY_SCORE_MIN, le=ABILITY_SCORE_MAX)


class ClassLevelBody(BaseAuthoringRequest):
    class_id: uuid.UUID
    subclass_id: uuid.UUID | None = None
    level: int = Field(ge=CLASS_LEVEL_MIN, le=CLASS_LEVEL_MAX)


class ProficiencyBody(BaseAuthoringRequest):
    proficiency_type_id: uuid.UUID
    skill_id: uuid.UUID | None = None
    saving_throw_ability_id: uuid.UUID | None = None
    target_label: str | None = Field(default=None, max_length=TARGET_LABEL_MAX_LENGTH)
    is_expertise: bool = False


class SpellcastingBody(BaseAuthoringRequest):
    class_id: uuid.UUID | None = None
    spellcasting_ability_id: uuid.UUID
    known_spell_ids: list[uuid.UUID] = Field(default_factory=list)
    prepared_spell_ids: list[uuid.UUID] = Field(default_factory=list)


class CreateBuildRequest(BaseAuthoringRequest):
    label: str | None = Field(default=None, max_length=LABEL_MAX_LENGTH)
    ability_scores: list[AbilityScoreBody] = Field(default_factory=list)
    class_levels: list[ClassLevelBody] = Field(default_factory=list)
    proficiencies: list[ProficiencyBody] = Field(default_factory=list)
    feature_ids: list[uuid.UUID] = Field(default_factory=list)
    spellcasting: list[SpellcastingBody] = Field(default_factory=list)


class ActivateBuildRequest(BaseAuthoringRequest):
    # The build the caller saw as active (null for none); a mismatch is a stale write.
    expected_active_build_id: uuid.UUID | None = None


class InitializeStateRequest(BaseAuthoringRequest):
    maximum_hit_points: int = Field(ge=1, le=MAX_HIT_POINTS)
    current_hit_points: int | None = Field(default=None, ge=0, le=MAX_HIT_POINTS)


@router.get("/campaigns/{campaign_id}/authoring/character-build-options")
def build_options_endpoint(access: _Edit, connection: _Conn) -> dict[str, Any]:
    options = get_build_options(
        connection,
        ruleset_version_id=campaign_ruleset_version(connection, campaign_id=access.campaign_id),
    )
    return {
        "limits": {
            "label_max_length": LABEL_MAX_LENGTH,
            "ability_score_min": ABILITY_SCORE_MIN,
            "ability_score_max": ABILITY_SCORE_MAX,
            "class_level_min": CLASS_LEVEL_MIN,
            "class_level_max": CLASS_LEVEL_MAX,
            "target_label_max_length": TARGET_LABEL_MAX_LENGTH,
            "max_hit_points": MAX_HIT_POINTS,
        },
        # Rules content a build cannot hold yet (none: languages, senses, and movement
        # belong to the character, not the build).
        "unsupported": [],
        **{
            family: [
                {"id": str(o.id), "name": o.name, "code": o.code, **_json(o.extra)} for o in items
            ]
            for family, items in options.items()
        },
    }


def _json(extra: dict[str, object]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in extra.items()}


@router.get(_BASE + "/builds")
def list_builds_endpoint(
    character_id: uuid.UUID, access: _Edit, connection: _Conn
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_character_builds(
        connection,
        world_id=world_id,
        timeline_id=access.timeline_id,
        character_id=character_id,
    )
    if view is None:
        raise NotFoundError()
    return {
        "character": {
            "character_id": str(view.character_id),
            "name": view.name,
            "kind": view.entity_type_code,
        },
        "state": {
            "initialized": view.state_initialized,
            "current_hit_points": view.current_hit_points,
            "maximum_hit_points": view.maximum_hit_points,
        },
        "active_build_id": None if view.active_build_id is None else str(view.active_build_id),
        "builds": [
            {
                "character_build_id": str(b.character_build_id),
                "label": b.label,
                "ruleset_version_id": str(b.ruleset_version_id),
                "created_at": b.created_at,
                "is_active": b.is_active,
                "counts": b.counts,
            }
            for b in view.builds
        ],
    }


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Any,
    status_code: int,
    created: bool,
    schema_table: tuple[str, str],
    record_id: Any,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=payload,
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result: BuildResult = command()
    record_change_log(
        connection,
        change_action_code="created" if created else "updated",
        schema_name=schema_table[0],
        table_name=schema_table[1],
        record_id=record_id(result),
        entity_id=result.character_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=result.event_id,
        changed_fields=dict(result.changed_fields),
    )
    receipt: dict[str, Any] = {
        "character_id": str(result.character_id),
        "created": created,
        "changed": True,
    }
    if command_name != "initialize_character_state":
        receipt["character_build_id"] = str(result.character_build_id)
    if result.event_id is not None:
        receipt["event_id"] = str(result.event_id)
    finish_campaign_idempotency(connection, idem, status_code=status_code, body=receipt)
    return JSONResponse(status_code=status_code, content=receipt)


@router.post(_BASE + "/builds", status_code=201)
def create_build_endpoint(
    character_id: uuid.UUID,
    body: CreateBuildRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    build = BuildInput(
        label=body.label,
        ability_scores=tuple((a.ability_id, a.score) for a in body.ability_scores),
        class_levels=tuple(
            ClassLevelInput(c.class_id, c.subclass_id, c.level) for c in body.class_levels
        ),
        proficiencies=tuple(
            ProficiencyInput(
                p.proficiency_type_id,
                p.skill_id,
                p.saving_throw_ability_id,
                p.target_label,
                p.is_expertise,
            )
            for p in body.proficiencies
        ),
        feature_ids=tuple(body.feature_ids),
        spellcasting=tuple(
            SpellcastingInput(
                s.class_id,
                s.spellcasting_ability_id,
                tuple(s.known_spell_ids),
                tuple(s.prepared_spell_ids),
            )
            for s in body.spellcasting
        ),
    )
    return _run(
        command_name="create_character_build",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"character_id": str(character_id), **body.model_dump(mode="json")},
        command=lambda: create_character_build(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            character_id=character_id,
            build=build,
        ),
        status_code=201,
        created=True,
        schema_table=("character", "character_builds"),
        record_id=lambda r: r.character_build_id,
    )


@router.post(_BASE + "/builds/{build_id}/activate")
def activate_build_endpoint(
    character_id: uuid.UUID,
    build_id: uuid.UUID,
    body: ActivateBuildRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="activate_character_build",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={
            "character_id": str(character_id),
            "build_id": str(build_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: activate_character_build(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            character_id=character_id,
            character_build_id=build_id,
            expected_active_build_id=body.expected_active_build_id,
        ),
        status_code=200,
        created=False,
        schema_table=("campaign", "character_state"),
        record_id=lambda r: r.character_id,
    )


@router.post(_BASE + "/state/initialize", status_code=201)
def initialize_state_endpoint(
    character_id: uuid.UUID,
    body: InitializeStateRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="initialize_character_state",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"character_id": str(character_id), **body.model_dump(mode="json")},
        command=lambda: initialize_character_state(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            character_id=character_id,
            maximum_hit_points=body.maximum_hit_points,
            current_hit_points=body.current_hit_points,
        ),
        status_code=201,
        created=True,
        schema_table=("campaign", "character_state"),
        record_id=lambda r: r.character_id,
    )
