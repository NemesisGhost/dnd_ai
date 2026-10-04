"""Organization and Religion authoring read models (Phase 15.1).

For `canon.edit` holders only -- the route dependency enforces it before any of
this runs. The views are **definitions** (never `campaign.organization_state`),
and include the GM-only `internal_description`. Player-facing organization and
religion reads are the separate audience-safe World Explorer details.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import evaluate_content_actions
from dnd_ai.domain.entity_lifecycle import BlockedAction
from dnd_ai.domain.organization_authoring import (
    ORGANIZATION_ENTITY_TYPE_CODES,
    ORGANIZATION_KINDS,
    OrganizationKind,
    organization_kind,
)
from dnd_ai.queries.content_preconditions import publish_blocked_reason

_SUBTYPE_TABLES: dict[str, tuple[str, str]] = {
    "business": ("world.businesses", "business_id"),
    "government": ("world.governments", "government_id"),
    "military_unit": ("world.military_units", "military_unit_id"),
    "political_faction": ("world.political_factions", "political_faction_id"),
}


def list_organization_kinds() -> tuple[OrganizationKind, ...]:
    return ORGANIZATION_KINDS


@dataclass(frozen=True)
class ReferenceSummary:
    entity_id: uuid.UUID
    name: str
    canon_status: str
    lifecycle_status: str


@dataclass(frozen=True)
class OrganizationAuthoringView:
    organization_id: uuid.UUID
    name: str
    summary: str | None
    kind: OrganizationKind
    organization_type: str
    public_description: str | None
    internal_description: str | None
    parent: ReferenceSummary | None
    headquarters: ReferenceSummary | None
    religion: ReferenceSummary | None
    typed: dict[str, object]
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    field_locks: list[str] = field(default_factory=list)


def _reference(connection: Connection, entity_id: uuid.UUID | None) -> ReferenceSummary | None:
    if entity_id is None:
        return None
    row = connection.execute(
        text("""
            SELECT e.canonical_name, cs.code AS canon_status, ls.code AS lifecycle_status
            FROM core.entities e
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.entity_id = :e
        """),
        {"e": entity_id},
    ).one_or_none()
    if row is None:
        return None
    return ReferenceSummary(
        entity_id=entity_id,
        name=str(row.canonical_name),
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
    )


def get_organization_authoring(
    connection: Connection, *, world_id: uuid.UUID, organization_id: uuid.UUID
) -> OrganizationAuthoringView | None:
    """The authoring view of an organization in `world_id`, or `None` if it does
    not exist there or is not an organization (target binding)."""
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.summary, e.row_version, et.code AS type_code,
                   cs.code AS canon_status, ls.code AS lifecycle_status,
                   ot.code AS organization_type, o.public_description, o.internal_description,
                   o.parent_organization_id, o.headquarters_location_id, ro.religion_id
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN world.organizations o ON o.organization_id = e.entity_id
            JOIN world.organization_types ot ON ot.organization_type_id = o.organization_type_id
            LEFT JOIN world.religious_organizations ro
              ON ro.religious_organization_id = e.entity_id
            WHERE e.entity_id = :o AND e.world_id = :w
        """),
        {"o": organization_id, "w": world_id},
    ).one_or_none()
    if row is None or row.type_code not in ORGANIZATION_ENTITY_TYPE_CODES:
        return None
    kind = organization_kind(str(row.type_code))
    typed: dict[str, object] = {}
    if kind.code in _SUBTYPE_TABLES:
        table, pk = _SUBTYPE_TABLES[kind.code]
        columns = ", ".join(f.name for f in kind.fields)
        sub = connection.execute(
            text(f"SELECT {columns} FROM {table} WHERE {pk} = :id"), {"id": organization_id}
        ).one_or_none()
        for descriptor in kind.fields:
            typed[descriptor.name] = None if sub is None else getattr(sub, descriptor.name)
    if kind.organization_type is None:
        typed["organization_type"] = str(row.organization_type)
    publish_reason = publish_blocked_reason(
        connection, entity_id=organization_id, entity_type_code=kind.code
    )
    available, blocked = evaluate_content_actions(
        entity_type_code=kind.code,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        extra_blocked={"publish": publish_reason} if publish_reason else None,
    )
    return OrganizationAuthoringView(
        organization_id=organization_id,
        name=str(row.canonical_name),
        summary=row.summary,
        kind=kind,
        organization_type=str(row.organization_type),
        public_description=row.public_description,
        internal_description=row.internal_description,
        parent=_reference(connection, row.parent_organization_id),
        headquarters=_reference(connection, row.headquarters_location_id),
        religion=_reference(connection, row.religion_id),
        typed=typed,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
    )


@dataclass(frozen=True)
class ReligionAuthoringView:
    religion_id: uuid.UUID
    name: str
    summary: str | None
    pantheon_structure: str | None
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    field_locks: list[str] = field(default_factory=list)


def get_religion_authoring(
    connection: Connection, *, world_id: uuid.UUID, religion_id: uuid.UUID
) -> ReligionAuthoringView | None:
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.summary, e.row_version, r.pantheon_structure,
                   cs.code AS canon_status, ls.code AS lifecycle_status
            FROM core.entities e
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN world.religions r ON r.religion_id = e.entity_id
            WHERE e.entity_id = :r AND e.world_id = :w
        """),
        {"r": religion_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    available, blocked = evaluate_content_actions(
        entity_type_code="religion",
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
    )
    return ReligionAuthoringView(
        religion_id=religion_id,
        name=str(row.canonical_name),
        summary=row.summary,
        pantheon_structure=row.pantheon_structure,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
    )
