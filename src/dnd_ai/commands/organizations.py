"""Typed Organization authoring commands (Phase 15.1, ADR 0015).

`create_organization` / `update_organization` author the six organization kinds
(`dnd_ai.domain.organization_authoring.ORGANIZATION_KINDS`): the generic
`organization` and the five that have a subtype table. They write **definition**
rows only -- `core.entities`, `world.organizations`, and the kind's subtype row
-- never `campaign.organization_state` (timeline state), founding/dissolution
world times, or `world.relationships` (memberships, offices; Phase 15.2).

The server fixes the agreement between the entity type and
`world.organizations.organization_type` (the database does not check it): every
kind but the generic one stores its own type; the generic one chooses among
guild / criminal_organization / secret_society / other.

Lock order (SYSTEM_ARCHITECTURE §7.1): authority scope, then entities by
ascending id (the target `FOR UPDATE`; a changed parent organization,
headquarters, or religion `FOR SHARE`), then the world's organization hierarchy
advisory lock -- the same key `tr_organizations_enforce_no_cycle` takes.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    AuthoringValidationError,
    HeadquartersLocationInvalidError,
    OrganizationHierarchyCycleError,
    OrganizationParentInvalidError,
    ReligionInvalidError,
    normalize_description,
    normalize_name,
    normalize_reason,
)
from dnd_ai.domain.content_authoring import (
    AUTHORABLE_LOCATION_CATEGORIES,
    diff_fields,
    initial_fields,
)
from dnd_ai.domain.organization_authoring import (
    DESCRIPTION_FIELD_MAX_LENGTH,
    ORGANIZATION_ENTITY_TYPE_CODES,
    OrganizationKind,
    normalize_optional_text,
    normalize_typed_fields,
    organization_kind,
    organization_type_for,
)
from dnd_ai.domain.world_authority import WORLD_CANON_EDIT

from ._content import (
    ContentWriteResult,
    LockedContent,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
    usable_reference,
)

# kind -> (subtype table, primary-key column); the typed field names are the
# column names. Closed constants, never request data.
_SUBTYPE_TABLES: dict[str, tuple[str, str]] = {
    "business": ("world.businesses", "business_id"),
    "government": ("world.governments", "government_id"),
    "military_unit": ("world.military_units", "military_unit_id"),
    "political_faction": ("world.political_factions", "political_faction_id"),
}


def _normalize_common(
    name: str | None,
    summary: str | None,
    public_description: str | None,
    internal_description: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    return (
        normalize_name(name),
        normalize_description(summary),
        normalize_optional_text(
            public_description, field="public_description", max_length=DESCRIPTION_FIELD_MAX_LENGTH
        ),
        normalize_optional_text(
            internal_description,
            field="internal_description",
            max_length=DESCRIPTION_FIELD_MAX_LENGTH,
        ),
    )


def _require_religion_rule(kind: OrganizationKind, religion_id: uuid.UUID | None) -> None:
    if kind.needs_religion and religion_id is None:
        raise AuthoringValidationError("religion_id is required for a religious organization")
    if not kind.needs_religion and religion_id is not None:
        raise AuthoringValidationError("religion_id does not apply to this kind")


def _validate_references(
    locked: dict[uuid.UUID, LockedContent],
    *,
    parent_organization_id: uuid.UUID | None,
    headquarters_location_id: uuid.UUID | None,
    religion_id: uuid.UUID | None,
) -> None:
    usable_reference(
        locked,
        parent_organization_id,
        type_codes=ORGANIZATION_ENTITY_TYPE_CODES,
        error=OrganizationParentInvalidError,
    )
    usable_reference(
        locked,
        headquarters_location_id,
        type_codes=AUTHORABLE_LOCATION_CATEGORIES,
        error=HeadquartersLocationInvalidError,
    )
    usable_reference(
        locked, religion_id, type_codes=frozenset({"religion"}), error=ReligionInvalidError
    )


def _text_id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _insert_subtype_rows(
    connection: Connection,
    *,
    kind: OrganizationKind,
    entity_id: uuid.UUID,
    typed: Mapping[str, object],
    religion_id: uuid.UUID | None,
) -> None:
    if kind.code == "business":
        connection.execute(
            text("""
                INSERT INTO world.businesses
                    (business_id, business_type, operating_status, reputation)
                VALUES (:id, :business_type, :operating_status, :reputation)
            """),
            {
                "id": entity_id,
                "business_type": typed["business_type"],
                "operating_status": typed["operating_status"] or "operating",
                "reputation": typed["reputation"],
            },
        )
    elif kind.code in _SUBTYPE_TABLES:
        table, pk = _SUBTYPE_TABLES[kind.code]
        (field,) = [f.name for f in kind.fields]
        connection.execute(
            text(f"INSERT INTO {table} ({pk}, {field}) VALUES (:id, :value)"),
            {"id": entity_id, "value": typed[field]},
        )
    elif kind.code == "religious_organization":
        connection.execute(
            text(
                "INSERT INTO world.religious_organizations "
                "(religious_organization_id, religion_id) VALUES (:id, :religion)"
            ),
            {"id": entity_id, "religion": religion_id},
        )


def create_organization(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    kind_code: str,
    name: str | None,
    summary: str | None,
    public_description: str | None = None,
    internal_description: str | None = None,
    parent_organization_id: uuid.UUID | None = None,
    headquarters_location_id: uuid.UUID | None = None,
    religion_id: uuid.UUID | None = None,
    typed_fields: Mapping[str, object] | None = None,
) -> ContentWriteResult:
    """Create an Organization draft of one of the six kinds, with its complete
    subtype chain, in the caller's transaction."""
    kind = organization_kind(kind_code)
    clean_name, clean_summary, clean_public, clean_internal = _normalize_common(
        name, summary, public_description, internal_description
    )
    typed = normalize_typed_fields(kind, typed_fields or {})
    _require_religion_rule(kind, religion_id)
    organization_type = organization_type_for(kind, typed)

    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=WORLD_CANON_EDIT,
    )
    reference_ids = [
        r for r in (parent_organization_id, headquarters_location_id, religion_id) if r is not None
    ]
    locked = lock_entities(connection, world_id=scope.world_id, share_ids=reference_ids)
    _validate_references(
        locked,
        parent_organization_id=parent_organization_id,
        headquarters_location_id=headquarters_location_id,
        religion_id=religion_id,
    )

    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code=kind.code,
        name=clean_name,
        summary=clean_summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("""
            INSERT INTO world.organizations
                (organization_id, organization_type_id, parent_organization_id,
                 headquarters_location_id, public_description, internal_description)
            VALUES (
                :id,
                (SELECT organization_type_id FROM world.organization_types WHERE code = :type),
                :parent, :hq, :public, :internal
            )
        """),
        {
            "id": entity_id,
            "type": organization_type,
            "parent": parent_organization_id,
            "hq": headquarters_location_id,
            "public": clean_public,
            "internal": clean_internal,
        },
    )
    _insert_subtype_rows(
        connection, kind=kind, entity_id=entity_id, typed=typed, religion_id=religion_id
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code=kind.code,
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "kind": kind.code,
                "name": clean_name,
                "summary": clean_summary,
                "public_description": clean_public,
                "internal_description": clean_internal,
                "parent_organization_id": _text_id(parent_organization_id),
                "headquarters_location_id": _text_id(headquarters_location_id),
                "religion_id": _text_id(religion_id),
                **typed,
            }
        ),
        source_id=source_id,
    )


def _current_fields(
    connection: Connection, entity_id: uuid.UUID, kind: OrganizationKind
) -> dict[str, object]:
    row = connection.execute(
        text("""
            SELECT ot.code AS organization_type, o.parent_organization_id,
                   o.headquarters_location_id, o.public_description, o.internal_description,
                   ro.religion_id
            FROM world.organizations o
            JOIN world.organization_types ot ON ot.organization_type_id = o.organization_type_id
            LEFT JOIN world.religious_organizations ro ON ro.religious_organization_id = o.organization_id
            WHERE o.organization_id = :id
        """),
        {"id": entity_id},
    ).one()
    current: dict[str, object] = {
        "public_description": row.public_description,
        "internal_description": row.internal_description,
        "parent_organization_id": _text_id(row.parent_organization_id),
        "headquarters_location_id": _text_id(row.headquarters_location_id),
    }
    if kind.needs_religion:
        current["religion_id"] = _text_id(row.religion_id)
    if kind.organization_type is None:
        current["organization_type"] = row.organization_type
    if kind.code in _SUBTYPE_TABLES:
        table, pk = _SUBTYPE_TABLES[kind.code]
        columns = ", ".join(f.name for f in kind.fields)
        sub = connection.execute(
            text(f"SELECT {columns} FROM {table} WHERE {pk} = :id"), {"id": entity_id}
        ).one_or_none()
        for descriptor in kind.fields:
            current[descriptor.name] = None if sub is None else getattr(sub, descriptor.name)
    return current


def _would_create_cycle(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    organization_id: uuid.UUID,
    new_parent_id: uuid.UUID,
) -> bool:
    """Whether `organization_id` is `new_parent_id` or one of its ancestors,
    under the world's hierarchy advisory lock (the trigger's own key)."""
    connection.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('world.organizations.hierarchy:' || :w, 0))"
        ),
        {"w": str(world_id)},
    )
    found = connection.execute(
        text("""
            WITH RECURSIVE ancestry AS (
                SELECT o.organization_id, o.parent_organization_id
                FROM world.organizations o WHERE o.organization_id = :start
                UNION ALL
                SELECT o.organization_id, o.parent_organization_id
                FROM world.organizations o
                JOIN ancestry a ON o.organization_id = a.parent_organization_id
            )
            CYCLE organization_id SET is_cycle USING path
            SELECT bool_or(organization_id = :target) FROM ancestry
        """),
        {"start": new_parent_id, "target": organization_id},
    ).scalar()
    return bool(found)


def update_organization(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    public_description: str | None = None,
    internal_description: str | None = None,
    parent_organization_id: uuid.UUID | None = None,
    headquarters_location_id: uuid.UUID | None = None,
    religion_id: uuid.UUID | None = None,
    typed_fields: Mapping[str, object] | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    """Replace an Organization's editable fields. The kind (entity type) is
    immutable; an identical resubmission is a no-op."""
    normalize_reason(change_note)
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=WORLD_CANON_EDIT,
    )

    hint = connection.execute(
        text(
            "SELECT o.parent_organization_id, o.headquarters_location_id, ro.religion_id "
            "FROM world.organizations o "
            "LEFT JOIN world.religious_organizations ro ON ro.religious_organization_id = o.organization_id "
            "WHERE o.organization_id = :id"
        ),
        {"id": organization_id},
    ).one_or_none()
    current_refs = set() if hint is None else {hint[0], hint[1], hint[2]}
    share_ids = [
        r
        for r in (parent_organization_id, headquarters_location_id, religion_id)
        if r is not None and r not in current_refs and r != organization_id
    ]
    locked = lock_entities(
        connection, world_id=scope.world_id, update_ids=[organization_id], share_ids=share_ids
    )
    target = editable_target(
        locked,
        entity_id=organization_id,
        type_codes=ORGANIZATION_ENTITY_TYPE_CODES,
        expected_row_version=expected_row_version,
    )
    kind = organization_kind(target.entity_type_code)
    clean_name, clean_summary, clean_public, clean_internal = _normalize_common(
        name, summary, public_description, internal_description
    )
    typed = normalize_typed_fields(kind, typed_fields or {})
    if kind.code == "business" and typed["operating_status"] is None:
        typed["operating_status"] = "operating"
    _require_religion_rule(kind, religion_id)
    organization_type = organization_type_for(kind, typed)

    current = _current_fields(connection, organization_id, kind)
    before: dict[str, object] = {
        "name": target.canonical_name,
        "summary": target.summary,
        **current,
    }
    after: dict[str, object] = {
        "name": clean_name,
        "summary": clean_summary,
        "public_description": clean_public,
        "internal_description": clean_internal,
        "parent_organization_id": _text_id(parent_organization_id),
        "headquarters_location_id": _text_id(headquarters_location_id),
    }
    if kind.needs_religion:
        after["religion_id"] = _text_id(religion_id)
    if kind.organization_type is None:
        after["organization_type"] = organization_type
    for descriptor in kind.fields:
        if descriptor.name != "organization_type":
            after[descriptor.name] = typed[descriptor.name]
    changed_fields = diff_fields(before, after)
    if not changed_fields:
        return ContentWriteResult(
            entity_id=organization_id,
            world_id=scope.world_id,
            entity_type_code=kind.code,
            row_version=target.row_version,
            created=False,
            changed=False,
        )

    # Newly referenced records: lock any the unlocked hint missed (the target is
    # locked now, so its references are stable), then validate those that changed.
    changed_refs = {
        key: value
        for key, value in (
            ("parent_organization_id", parent_organization_id),
            ("headquarters_location_id", headquarters_location_id),
            ("religion_id", religion_id),
        )
        if key in changed_fields and value is not None
    }
    missing = [r for r in changed_refs.values() if r not in locked]
    if missing:
        locked.update(lock_entities(connection, world_id=scope.world_id, share_ids=missing))
    _validate_references(
        locked,
        parent_organization_id=changed_refs.get("parent_organization_id"),
        headquarters_location_id=changed_refs.get("headquarters_location_id"),
        religion_id=changed_refs.get("religion_id"),
    )
    if (
        parent_organization_id is not None
        and "parent_organization_id" in changed_fields
        and (
            parent_organization_id == organization_id
            or _would_create_cycle(
                connection,
                world_id=scope.world_id,
                organization_id=organization_id,
                new_parent_id=parent_organization_id,
            )
        )
    ):
        raise OrganizationHierarchyCycleError(
            f"organization {organization_id} cannot be its own ancestor"
        )

    new_version = touch_entity(
        connection, entity_id=organization_id, name=clean_name, summary=clean_summary
    )
    columns = {
        "public_description": "public_description",
        "internal_description": "internal_description",
        "parent_organization_id": "parent_organization_id",
        "headquarters_location_id": "headquarters_location_id",
    }
    org_updates = {c: after[k] for k, c in columns.items() if k in changed_fields}
    if "organization_type" in changed_fields:
        connection.execute(
            text(
                "UPDATE world.organizations SET organization_type_id = "
                "(SELECT organization_type_id FROM world.organization_types WHERE code = :t) "
                "WHERE organization_id = :id"
            ),
            {"t": organization_type, "id": organization_id},
        )
    if org_updates:
        assignments = ", ".join(f"{column} = :{column}" for column in org_updates)
        params: dict[str, object] = {"id": organization_id}
        for column, value in org_updates.items():
            params[column] = (
                uuid.UUID(value) if column.endswith("_id") and isinstance(value, str) else value
            )
        connection.execute(
            text(f"UPDATE world.organizations SET {assignments} WHERE organization_id = :id"),
            params,
        )
    if kind.code in _SUBTYPE_TABLES:
        table, pk = _SUBTYPE_TABLES[kind.code]
        sub_updates = {d.name: typed[d.name] for d in kind.fields if d.name in changed_fields}
        if sub_updates:
            assignments = ", ".join(f"{column} = :{column}" for column in sub_updates)
            connection.execute(
                text(f"UPDATE {table} SET {assignments} WHERE {pk} = :id"),
                {"id": organization_id, **sub_updates},
            )
    if "religion_id" in changed_fields:
        connection.execute(
            text(
                "UPDATE world.religious_organizations SET religion_id = :r "
                "WHERE religious_organization_id = :id"
            ),
            {"r": religion_id, "id": organization_id},
        )
    return ContentWriteResult(
        entity_id=organization_id,
        world_id=scope.world_id,
        entity_type_code=kind.code,
        row_version=new_version,
        created=False,
        changed=True,
        changed_fields=dict(changed_fields),
    )
