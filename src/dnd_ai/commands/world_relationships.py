"""World relationship authoring commands (Phase 15 checkpoint 15.3A-2a, decision D-18, ADR 0017).

`create_relationship` writes a relationship, its participants and its kind's typed row
(family, employment, ownership, political, or a plain connection) atomically.
`update_relationship` edits what may change (the description, the start, and the typed fields);
the kind, the type and the participants are fixed for the life of the relationship (to change
them, end or archive it and create another). `end_relationship` closes it at a world time,
`archive_relationship` / `restore_relationship` move it in and out of view, and
`set_relationship_perspective` authors a participant's baseline view of it.

All of this is **definition**. The relationship's current, event-driven status is timeline
state (`commands.relationships.evolve_relationship_reaction`), which now refuses an archived
relationship. Every command takes the relationship's `expected_row_version`.

Lock order: authority scope, the participants' entities `FOR SHARE` in id order, then the
relationship row `FOR UPDATE`.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import StaleWriteError, normalize_reason
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.relationship_authoring import (
    KIND_EMPLOYMENT,
    KIND_FAMILY,
    KIND_OWNERSHIP,
    KIND_POLITICAL,
    PARTICIPANT_TYPE_CODES,
    SHORT_TEXT_MAX_LENGTH,
    PerspectiveHolderInvalidError,
    RelationshipAlreadyEndedError,
    RelationshipArchivedError,
    RelationshipInvalidError,
    RelationshipNotArchivedError,
    RelationshipParticipantInvalidError,
    RelationshipStartRequiredError,
    RelationshipTimeInvalidError,
    normalize_share,
    normalize_stance,
    normalize_text,
    relationship_kind,
    validate_shape,
)

from ._content import (
    EntityNotFoundError,
    LockedContent,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    usable_reference,
)
from ._shared import lifecycle_code, lookup_id


@dataclass(frozen=True)
class ParticipantInput:
    entity_id: uuid.UUID
    role: str


@dataclass(frozen=True)
class RelationshipResult:
    relationship_id: uuid.UUID
    world_id: uuid.UUID
    row_version: int
    created: bool
    changed: bool
    action: str = "updated"
    record_table: str = "relationships"
    record_id: uuid.UUID | None = None
    changed_fields: dict[str, object] = field(default_factory=dict)


# Typed fields each kind carries, by the name the commands and the API use.
_TYPED_FIELDS: dict[str, tuple[str, ...]] = {
    KIND_FAMILY: ("family_unit_name",),
    KIND_EMPLOYMENT: ("job_title",),
    KIND_OWNERSHIP: ("ownership_share", "is_public"),
    KIND_POLITICAL: ("is_active", "treaty_terms"),
    "general": (),
}


def _text_id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _clean_typed(kind_code: str, typed: dict[str, Any]) -> dict[str, Any]:
    allowed = _TYPED_FIELDS[kind_code]
    unknown = set(typed) - set(allowed)
    if unknown:
        raise RelationshipInvalidError(f"{kind_code} has no field(s) {sorted(unknown)}")
    clean: dict[str, Any] = {}
    for name, value in typed.items():
        if name == "family_unit_name" or name == "job_title":
            clean[name] = normalize_text(value, field=name, limit=SHORT_TEXT_MAX_LENGTH)
        elif name == "treaty_terms":
            clean[name] = normalize_text(value, field=name)
        elif name == "ownership_share":
            clean[name] = normalize_share(value)
        else:  # is_public, is_active
            if not isinstance(value, bool):
                raise RelationshipInvalidError(f"{name} must be true or false")
            clean[name] = value
    return clean


def _world_time_sort_key(
    connection: Connection, world_id: uuid.UUID, world_time_id: uuid.UUID | None
) -> int | None:
    if world_time_id is None:
        return None
    key = connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t AND world_id = :w"),
        {"t": world_time_id, "w": world_id},
    ).scalar()
    if key is None:
        raise RelationshipTimeInvalidError(f"time {world_time_id} is not in the world")
    assert isinstance(key, int)
    return key


def _touch(connection: Connection, relationship_id: uuid.UUID) -> int:
    version = connection.execute(
        text(
            "UPDATE world.relationships SET updated_at = now() "
            "WHERE relationship_id = :r RETURNING row_version"
        ),
        {"r": relationship_id},
    ).scalar()
    assert isinstance(version, int)
    return version


@dataclass(frozen=True)
class _Locked:
    world_id: uuid.UUID
    kind: str
    type_code: str
    row: Any
    participants: list[Any]
    locked: dict[uuid.UUID, LockedContent]


def _kind_of(connection: Connection, relationship_id: uuid.UUID, type_code: str) -> str:
    """The kind a stored relationship was authored as, read from which typed row it has."""
    for kind_code, table in (
        (KIND_FAMILY, "family_relationships"),
        (KIND_EMPLOYMENT, "employment_relationships"),
        (KIND_OWNERSHIP, "ownership_relationships"),
        (KIND_POLITICAL, "political_relationships"),
    ):
        found = connection.execute(
            text(f"SELECT 1 FROM world.{table} WHERE relationship_id = :r"),  # noqa: S608
            {"r": relationship_id},
        ).scalar()
        if found is not None:
            return kind_code
    del type_code
    return "general"


def _lock_relationship(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    relationship_id: uuid.UUID,
    expected_row_version: int,
    allow_archived: bool = False,
) -> _Locked:
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    participants = connection.execute(
        text(
            "SELECT p.entity_id, r.code AS role FROM world.relationship_participants p "
            "JOIN world.relationship_participant_roles r "
            "ON r.relationship_participant_role_id = p.participant_role_id "
            "JOIN world.relationships rel ON rel.relationship_id = p.relationship_id "
            "WHERE p.relationship_id = :r AND rel.world_id = :w"
        ),
        {"r": relationship_id, "w": scope.world_id},
    ).all()
    locked = lock_entities(
        connection,
        world_id=scope.world_id,
        share_ids=[p.entity_id for p in participants],
    )
    row = connection.execute(
        text("""
            SELECT r.relationship_id, r.row_version, r.lifecycle_status_id, r.description,
                   r.started_world_time_id, r.ended_world_time_id, rt.code AS type_code
            FROM world.relationships r
            JOIN world.relationship_types rt ON rt.relationship_type_id = r.relationship_type_id
            WHERE r.relationship_id = :r AND r.world_id = :w FOR UPDATE OF r
        """),
        {"r": relationship_id, "w": scope.world_id},
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError(f"relationship {relationship_id} is not in this world")
    if row.row_version != expected_row_version:
        raise StaleWriteError(f"relationship {relationship_id} is at {row.row_version}")
    if not allow_archived and lifecycle_code(connection, row.lifecycle_status_id) != "active":
        raise RelationshipArchivedError(f"relationship {relationship_id} is archived")
    return _Locked(
        world_id=scope.world_id,
        kind=_kind_of(connection, relationship_id, row.type_code),
        type_code=str(row.type_code),
        row=row,
        participants=list(participants),
        locked=locked,
    )


def create_relationship(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    kind: str,
    relationship_type: str,
    participants: list[ParticipantInput],
    description: str | None = None,
    started_world_time_id: uuid.UUID | None = None,
    typed: dict[str, Any] | None = None,
) -> RelationshipResult:
    shape = relationship_kind(kind)
    validate_shape(shape, relationship_type, [p.role for p in participants])
    clean_description = normalize_text(description, field="description")
    clean_typed = _clean_typed(shape.code, typed or {})
    entity_ids = [p.entity_id for p in participants]
    if shape.fixed_roles is not None and len(set(entity_ids)) != len(entity_ids):
        raise RelationshipInvalidError("the two sides of this kind must differ")
    if len({(p.entity_id, p.role) for p in participants}) != len(participants):
        raise RelationshipInvalidError("a participant appears twice in the same role")

    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(connection, world_id=scope.world_id, share_ids=entity_ids)
    for entity_id in set(entity_ids):
        usable_reference(
            locked,
            entity_id,
            type_codes=PARTICIPANT_TYPE_CODES,
            error=RelationshipParticipantInvalidError,
        )
    _world_time_sort_key(connection, scope.world_id, started_world_time_id)
    type_id = lookup_id(
        connection, "world", "relationship_types", "relationship_type_id", relationship_type
    )
    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    relationship_id = connection.execute(
        text("""
            INSERT INTO world.relationships
                (world_id, relationship_type_id, description, started_world_time_id, source_id,
                 created_by_user_id)
            VALUES (:w, :type, :d, :start, :source, :user) RETURNING relationship_id
        """),
        {
            "w": scope.world_id,
            "type": type_id,
            "d": clean_description,
            "start": started_world_time_id,
            "source": source_id,
            "user": actor_user_id,
        },
    ).scalar()
    assert isinstance(relationship_id, uuid.UUID)
    for participant in participants:
        connection.execute(
            text("""
                INSERT INTO world.relationship_participants
                    (relationship_id, entity_id, participant_role_id)
                VALUES (:r, :e, (SELECT relationship_participant_role_id
                                 FROM world.relationship_participant_roles WHERE code = :role))
            """),
            {"r": relationship_id, "e": participant.entity_id, "role": participant.role},
        )
    _insert_typed(
        connection,
        relationship_id=relationship_id,
        kind=shape.code,
        participants=participants,
        typed=clean_typed,
        started_world_time_id=started_world_time_id,
    )
    version = connection.execute(
        text("SELECT row_version FROM world.relationships WHERE relationship_id = :r"),
        {"r": relationship_id},
    ).scalar()
    assert isinstance(version, int)
    return RelationshipResult(
        relationship_id=relationship_id,
        world_id=scope.world_id,
        row_version=version,
        created=True,
        changed=True,
        action="created",
        record_id=relationship_id,
        changed_fields=initial_fields(
            {
                "kind": shape.code,
                "relationship_type": relationship_type,
                "description": clean_description,
                "started_world_time_id": _text_id(started_world_time_id),
                **clean_typed,
            }
        ),
    )


def _insert_typed(
    connection: Connection,
    *,
    relationship_id: uuid.UUID,
    kind: str,
    participants: list[ParticipantInput],
    typed: dict[str, Any],
    started_world_time_id: uuid.UUID | None,
) -> None:
    by_role = {p.role: p.entity_id for p in participants}
    if kind == KIND_FAMILY:
        connection.execute(
            text(
                "INSERT INTO world.family_relationships (relationship_id, family_unit_name) "
                "VALUES (:r, :n)"
            ),
            {"r": relationship_id, "n": typed.get("family_unit_name")},
        )
    elif kind == KIND_EMPLOYMENT:
        connection.execute(
            text("""
                INSERT INTO world.employment_relationships
                    (relationship_id, employer_entity_id, employee_entity_id, job_title,
                     effective_from_world_time_id)
                VALUES (:r, :employer, :employee, :title, :start)
            """),
            {
                "r": relationship_id,
                "employer": by_role["employer"],
                "employee": by_role["employee"],
                "title": typed.get("job_title"),
                "start": started_world_time_id,
            },
        )
    elif kind == KIND_OWNERSHIP:
        connection.execute(
            text("""
                INSERT INTO world.ownership_relationships
                    (relationship_id, owner_entity_id, owned_entity_id, ownership_share, is_public)
                VALUES (:r, :owner, :owned, :share, :public)
            """),
            {
                "r": relationship_id,
                "owner": by_role["owner"],
                "owned": by_role["property"],
                "share": typed.get("ownership_share"),
                "public": typed.get("is_public", True),
            },
        )
    elif kind == KIND_POLITICAL:
        connection.execute(
            text(
                "INSERT INTO world.political_relationships "
                "(relationship_id, is_active, treaty_terms) VALUES (:r, :active, :terms)"
            ),
            {
                "r": relationship_id,
                "active": typed.get("is_active", True),
                "terms": typed.get("treaty_terms"),
            },
        )


def _current_typed(connection: Connection, relationship_id: uuid.UUID, kind: str) -> dict[str, Any]:
    queries = {
        KIND_FAMILY: "SELECT family_unit_name FROM world.family_relationships",
        KIND_EMPLOYMENT: "SELECT job_title FROM world.employment_relationships",
        KIND_OWNERSHIP: "SELECT ownership_share, is_public FROM world.ownership_relationships",
        KIND_POLITICAL: "SELECT is_active, treaty_terms FROM world.political_relationships",
    }
    if kind not in queries:
        return {}
    row = (
        connection.execute(
            text(f"{queries[kind]} WHERE relationship_id = :r"),  # noqa: S608 - fixed text
            {"r": relationship_id},
        )
        .mappings()
        .one()
    )
    return dict(row)


def update_relationship(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    relationship_id: uuid.UUID,
    expected_row_version: int,
    description: str | None,
    started_world_time_id: uuid.UUID | None,
    typed: dict[str, Any] | None = None,
    change_note: str | None = None,
) -> RelationshipResult:
    normalize_reason(change_note)
    clean_description = normalize_text(description, field="description")
    locked = _lock_relationship(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        relationship_id=relationship_id,
        expected_row_version=expected_row_version,
    )
    clean_typed = _clean_typed(locked.kind, typed or {})
    start_key = _world_time_sort_key(connection, locked.world_id, started_world_time_id)
    if locked.row.ended_world_time_id is not None:
        end_key = _world_time_sort_key(connection, locked.world_id, locked.row.ended_world_time_id)
        if start_key is None or (end_key is not None and end_key <= start_key):
            raise RelationshipTimeInvalidError("the start must stay before the end")
    before: dict[str, object] = {
        "description": locked.row.description,
        "started_world_time_id": _text_id(locked.row.started_world_time_id),
        **{
            k: v
            for k, v in _current_typed(connection, relationship_id, locked.kind).items()
            if k in clean_typed
        },
    }
    after: dict[str, object] = {
        "description": clean_description,
        "started_world_time_id": _text_id(started_world_time_id),
        **clean_typed,
    }
    changed = diff_fields(before, after)
    if not changed:
        return RelationshipResult(
            relationship_id=relationship_id,
            world_id=locked.world_id,
            row_version=locked.row.row_version,
            created=False,
            changed=False,
        )
    _update_typed(connection, relationship_id, locked.kind, clean_typed, started_world_time_id)
    new_version = connection.execute(
        text(
            "UPDATE world.relationships SET description = :d, started_world_time_id = :s "
            "WHERE relationship_id = :r RETURNING row_version"
        ),
        {"d": clean_description, "s": started_world_time_id, "r": relationship_id},
    ).scalar()
    assert isinstance(new_version, int)
    return RelationshipResult(
        relationship_id=relationship_id,
        world_id=locked.world_id,
        row_version=new_version,
        created=False,
        changed=True,
        record_id=relationship_id,
        changed_fields=dict(changed),
    )


def _update_typed(
    connection: Connection,
    relationship_id: uuid.UUID,
    kind: str,
    typed: dict[str, Any],
    started_world_time_id: uuid.UUID | None,
) -> None:
    tables = {
        KIND_FAMILY: "family_relationships",
        KIND_EMPLOYMENT: "employment_relationships",
        KIND_OWNERSHIP: "ownership_relationships",
        KIND_POLITICAL: "political_relationships",
    }
    if kind not in tables:
        return
    assignments = dict(typed)
    if kind == KIND_EMPLOYMENT:
        assignments["effective_from_world_time_id"] = started_world_time_id
    if not assignments:
        return
    sets = ", ".join(f"{column} = :{column}" for column in assignments)
    connection.execute(
        text(  # noqa: S608 - fixed table names and field names
            f"UPDATE world.{tables[kind]} SET {sets}, updated_at = now() WHERE relationship_id = :r"
        ),
        {**assignments, "r": relationship_id},
    )


def end_relationship(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    relationship_id: uuid.UUID,
    expected_row_version: int,
    ended_world_time_id: uuid.UUID,
) -> RelationshipResult:
    locked = _lock_relationship(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        relationship_id=relationship_id,
        expected_row_version=expected_row_version,
    )
    if locked.row.ended_world_time_id is not None:
        raise RelationshipAlreadyEndedError(f"relationship {relationship_id} already ended")
    if locked.row.started_world_time_id is None:
        raise RelationshipStartRequiredError(f"relationship {relationship_id} has no start")
    end_key = _world_time_sort_key(connection, locked.world_id, ended_world_time_id)
    start_key = _world_time_sort_key(connection, locked.world_id, locked.row.started_world_time_id)
    assert end_key is not None and start_key is not None
    if end_key <= start_key:
        raise RelationshipTimeInvalidError("the end must be after the start")
    if locked.kind == KIND_EMPLOYMENT:
        connection.execute(
            text(
                "UPDATE world.employment_relationships SET effective_to_world_time_id = :e, "
                "updated_at = now() WHERE relationship_id = :r"
            ),
            {"e": ended_world_time_id, "r": relationship_id},
        )
    if locked.kind == KIND_POLITICAL:
        connection.execute(
            text(
                "UPDATE world.political_relationships SET is_active = false, updated_at = now() "
                "WHERE relationship_id = :r"
            ),
            {"r": relationship_id},
        )
    ended_version = connection.execute(
        text(
            "UPDATE world.relationships SET ended_world_time_id = :e "
            "WHERE relationship_id = :r RETURNING row_version"
        ),
        {"e": ended_world_time_id, "r": relationship_id},
    ).scalar()
    assert isinstance(ended_version, int)
    return RelationshipResult(
        relationship_id=relationship_id,
        world_id=locked.world_id,
        row_version=ended_version,
        created=False,
        changed=True,
        record_id=relationship_id,
        changed_fields=dict(
            diff_fields(
                {"ended_world_time_id": None}, {"ended_world_time_id": str(ended_world_time_id)}
            )
        ),
    )


def archive_relationship(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    relationship_id: uuid.UUID,
    expected_row_version: int,
) -> RelationshipResult:
    locked = _lock_relationship(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        relationship_id=relationship_id,
        expected_row_version=expected_row_version,
    )
    connection.execute(
        text(
            "UPDATE world.relationships SET archived_at = now(), lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
            "WHERE relationship_id = :r"
        ),
        {"r": relationship_id},
    )
    return RelationshipResult(
        relationship_id=relationship_id,
        world_id=locked.world_id,
        row_version=int(
            connection.execute(
                text("SELECT row_version FROM world.relationships WHERE relationship_id = :r"),
                {"r": relationship_id},
            ).scalar()
            or 0
        ),
        created=False,
        changed=True,
        record_id=relationship_id,
        changed_fields={"lifecycle": {"from": "active", "to": "archived"}},
    )


def restore_relationship(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    relationship_id: uuid.UUID,
    expected_row_version: int,
) -> RelationshipResult:
    locked = _lock_relationship(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        relationship_id=relationship_id,
        expected_row_version=expected_row_version,
        allow_archived=True,
    )
    if lifecycle_code(connection, locked.row.lifecycle_status_id) != "archived":
        raise RelationshipNotArchivedError(f"relationship {relationship_id} is not archived")
    for participant in locked.participants:
        entity = locked.locked.get(participant.entity_id)
        if entity is None or entity.lifecycle_status != "active":
            raise RelationshipParticipantInvalidError(f"{participant.entity_id} is not active")
    connection.execute(
        text(
            "UPDATE world.relationships SET archived_at = NULL, lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active') "
            "WHERE relationship_id = :r"
        ),
        {"r": relationship_id},
    )
    version = connection.execute(
        text("SELECT row_version FROM world.relationships WHERE relationship_id = :r"),
        {"r": relationship_id},
    ).scalar()
    assert isinstance(version, int)
    return RelationshipResult(
        relationship_id=relationship_id,
        world_id=locked.world_id,
        row_version=version,
        created=False,
        changed=True,
        record_id=relationship_id,
        changed_fields={"lifecycle": {"from": "archived", "to": "active"}},
    )


def set_relationship_perspective(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    relationship_id: uuid.UUID,
    expected_row_version: int,
    holder_entity_id: uuid.UUID,
    affinity: int | None = None,
    trust: int | None = None,
    respect: int | None = None,
    fear: int | None = None,
    obligation: int | None = None,
    emotional_tone: str | None = None,
    private_interpretation: str | None = None,
) -> RelationshipResult:
    values: dict[str, object] = {
        "affinity": normalize_stance(affinity, field="affinity"),
        "trust": normalize_stance(trust, field="trust"),
        "respect": normalize_stance(respect, field="respect"),
        "fear": normalize_stance(fear, field="fear"),
        "obligation": normalize_stance(obligation, field="obligation"),
        "emotional_tone": normalize_text(
            emotional_tone, field="emotional_tone", limit=SHORT_TEXT_MAX_LENGTH
        ),
        "private_interpretation": normalize_text(
            private_interpretation, field="private_interpretation"
        ),
    }
    locked = _lock_relationship(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        relationship_id=relationship_id,
        expected_row_version=expected_row_version,
    )
    if holder_entity_id not in {p.entity_id for p in locked.participants}:
        raise PerspectiveHolderInvalidError(f"{holder_entity_id} is not a participant")
    existing = (
        connection.execute(
            text(
                "SELECT relationship_perspective_id, affinity, trust, respect, fear, obligation, "
                "emotional_tone, private_interpretation FROM world.relationship_perspectives "
                "WHERE relationship_id = :r AND perspective_holder_entity_id = :h FOR UPDATE"
            ),
            {"r": relationship_id, "h": holder_entity_id},
        )
        .mappings()
        .one_or_none()
    )
    if existing is None:
        record_id = connection.execute(
            text("""
                INSERT INTO world.relationship_perspectives
                    (relationship_id, perspective_holder_entity_id, affinity, trust, respect,
                     fear, obligation, emotional_tone, private_interpretation)
                VALUES (:r, :h, :affinity, :trust, :respect, :fear, :obligation, :tone, :private)
                RETURNING relationship_perspective_id
            """),
            {
                "r": relationship_id,
                "h": holder_entity_id,
                "affinity": values["affinity"],
                "trust": values["trust"],
                "respect": values["respect"],
                "fear": values["fear"],
                "obligation": values["obligation"],
                "tone": values["emotional_tone"],
                "private": values["private_interpretation"],
            },
        ).scalar()
        assert isinstance(record_id, uuid.UUID)
        return RelationshipResult(
            relationship_id=relationship_id,
            world_id=locked.world_id,
            row_version=_touch(connection, relationship_id),
            created=True,
            changed=True,
            action="created",
            record_table="relationship_perspectives",
            record_id=record_id,
            changed_fields=initial_fields({"holder": str(holder_entity_id), **values}),
        )
    before = {k: existing[k] for k in values}
    changed = diff_fields(before, values)
    if not changed:
        return RelationshipResult(
            relationship_id=relationship_id,
            world_id=locked.world_id,
            row_version=locked.row.row_version,
            created=False,
            changed=False,
        )
    connection.execute(
        text("""
            UPDATE world.relationship_perspectives
            SET affinity = :affinity, trust = :trust, respect = :respect, fear = :fear,
                obligation = :obligation, emotional_tone = :tone,
                private_interpretation = :private, updated_at = now()
            WHERE relationship_perspective_id = :id
        """),
        {
            "affinity": values["affinity"],
            "trust": values["trust"],
            "respect": values["respect"],
            "fear": values["fear"],
            "obligation": values["obligation"],
            "tone": values["emotional_tone"],
            "private": values["private_interpretation"],
            "id": existing["relationship_perspective_id"],
        },
    )
    return RelationshipResult(
        relationship_id=relationship_id,
        world_id=locked.world_id,
        row_version=_touch(connection, relationship_id),
        created=False,
        changed=True,
        record_table="relationship_perspectives",
        record_id=existing["relationship_perspective_id"],
        changed_fields=dict(changed),
    )
