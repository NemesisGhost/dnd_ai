"""Source lists and the provenance of an entity (Phase 15 checkpoint 15.3C-1, D-26).

`canon.edit` only. The provenance view says who created an entity and from which source, which
further sources are or were attached (with who attached or detached them and when), the
lifecycle transitions it went through and who made them, and its supersession links. The
reference text of a source is GM-only and is shown here only because the caller can edit canon.
Transition history comes from the audit rows of the lifecycle commands (action, statuses, actor
and time only; never the free-text reason or the changed fields).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.source_authoring import LIFECYCLE_COMMANDS


@dataclass(frozen=True)
class SourceRow:
    source_id: uuid.UUID
    source_type: str
    source_type_label: str
    title: str
    reference: str | None
    created_by_name: str | None
    attached_count: int


@dataclass(frozen=True)
class LinkRow:
    source_id: uuid.UUID
    source_type_label: str
    title: str
    reference: str | None
    attached_at: datetime
    attached_by_name: str | None
    detached_at: datetime | None
    detached_by_name: str | None


@dataclass(frozen=True)
class TransitionRow:
    label: str
    previous_status: str | None
    new_status: str | None
    actor_name: str | None
    recorded_at: datetime


@dataclass(frozen=True)
class EntityRef:
    entity_id: uuid.UUID
    name: str


@dataclass(frozen=True)
class ProvenanceView:
    entity_id: uuid.UUID
    name: str
    entity_type_code: str
    canon_status: str
    lifecycle_status: str
    created_at: datetime
    created_by_name: str | None
    origin: SourceRow | None
    links: list[LinkRow] = field(default_factory=list)
    transitions: list[TransitionRow] = field(default_factory=list)
    superseded_by: EntityRef | None = None
    supersedes: list[EntityRef] = field(default_factory=list)


def list_world_sources(connection: Connection, *, world_id: uuid.UUID) -> list[SourceRow]:
    """The world's authored sources. The creation source of each entity is shown on that entity's
    provenance, not here, so the list stays the sources a GM chose to write down."""
    rows = connection.execute(
        text("""
            SELECT s.source_id, st.code AS type_code, st.display_name AS type_label, s.title,
                   s.reference, u.display_name AS created_by,
                   (SELECT count(*) FROM core.entity_source_links l
                    WHERE l.source_id = s.source_id AND l.detached_at IS NULL) AS attached
            FROM core.sources s
            JOIN core.source_types st ON st.source_type_id = s.source_type_id
            LEFT JOIN security.users u ON u.user_id = s.created_by_user_id
            WHERE s.world_id = :w
              AND NOT EXISTS (SELECT 1 FROM core.entities e WHERE e.source_id = s.source_id)
            ORDER BY s.created_at DESC, s.source_id
        """),
        {"w": world_id},
    ).all()
    return [_source(r) for r in rows]


def _source(r: object) -> SourceRow:
    return SourceRow(
        source_id=r.source_id,  # type: ignore[attr-defined]
        source_type=str(r.type_code),  # type: ignore[attr-defined]
        source_type_label=str(r.type_label),  # type: ignore[attr-defined]
        title=str(r.title),  # type: ignore[attr-defined]
        reference=r.reference,  # type: ignore[attr-defined]
        created_by_name=None if r.created_by is None else str(r.created_by),  # type: ignore[attr-defined]
        attached_count=int(r.attached),  # type: ignore[attr-defined]
    )


def get_provenance(
    connection: Connection, *, world_id: uuid.UUID, entity_id: uuid.UUID
) -> ProvenanceView | None:
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.created_at, et.code AS type_code,
                   cs.code AS canon, ls.code AS lifecycle, cu.display_name AS created_by,
                   e.superseded_by_entity_id, rep.canonical_name AS replacement_name,
                   e.source_id,
                   s.title, s.reference, st.code AS source_type_code,
                   st.display_name AS source_type_label,
                   su.display_name AS source_created_by
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            LEFT JOIN security.users cu ON cu.user_id = e.created_by_user_id
            LEFT JOIN core.entities rep ON rep.entity_id = e.superseded_by_entity_id
            LEFT JOIN core.sources s ON s.source_id = e.source_id
            LEFT JOIN core.source_types st ON st.source_type_id = s.source_type_id
            LEFT JOIN security.users su ON su.user_id = s.created_by_user_id
            WHERE e.entity_id = :e AND e.world_id = :w
        """),
        {"e": entity_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    origin = None
    if row.source_id is not None:
        origin = SourceRow(
            source_id=row.source_id,
            source_type=str(row.source_type_code),
            source_type_label=str(row.source_type_label),
            title=str(row.title),
            reference=row.reference,
            created_by_name=None if row.source_created_by is None else str(row.source_created_by),
            attached_count=0,
        )
    links = connection.execute(
        text("""
            SELECT l.source_id, st.display_name AS type_label, s.title, s.reference,
                   l.attached_at, au.display_name AS attached_by,
                   l.detached_at, du.display_name AS detached_by
            FROM core.entity_source_links l
            JOIN core.sources s ON s.source_id = l.source_id
            JOIN core.source_types st ON st.source_type_id = s.source_type_id
            LEFT JOIN security.users au ON au.user_id = l.attached_by_user_id
            LEFT JOIN security.users du ON du.user_id = l.detached_by_user_id
            WHERE l.entity_id = :e
            ORDER BY (l.detached_at IS NULL) DESC, l.attached_at DESC, l.entity_source_link_id
        """),
        {"e": entity_id},
    ).all()
    transitions = connection.execute(
        text("""
            SELECT cl.command_name, cl.previous_status, cl.new_status, cl.recorded_at,
                   u.display_name AS actor
            FROM audit.change_log cl
            LEFT JOIN security.users u ON u.user_id = cl.actor_user_id
            WHERE cl.entity_id = :e AND cl.world_id = :w AND cl.command_name = ANY(:commands)
            ORDER BY cl.recorded_at, cl.change_log_id
        """),
        {"e": entity_id, "w": world_id, "commands": list(LIFECYCLE_COMMANDS)},
    ).all()
    replaced = connection.execute(
        text("""
            SELECT entity_id, canonical_name FROM core.entities
            WHERE superseded_by_entity_id = :e AND world_id = :w
            ORDER BY lower(canonical_name), entity_id
        """),
        {"e": entity_id, "w": world_id},
    ).all()
    return ProvenanceView(
        entity_id=entity_id,
        name=str(row.canonical_name),
        entity_type_code=str(row.type_code),
        canon_status=str(row.canon),
        lifecycle_status=str(row.lifecycle),
        created_at=row.created_at,
        created_by_name=None if row.created_by is None else str(row.created_by),
        origin=origin,
        links=[
            LinkRow(
                source_id=link.source_id,
                source_type_label=str(link.type_label),
                title=str(link.title),
                reference=link.reference,
                attached_at=link.attached_at,
                attached_by_name=None if link.attached_by is None else str(link.attached_by),
                detached_at=link.detached_at,
                detached_by_name=None if link.detached_by is None else str(link.detached_by),
            )
            for link in links
        ],
        transitions=[
            TransitionRow(
                label=LIFECYCLE_COMMANDS[str(t.command_name)],
                previous_status=t.previous_status,
                new_status=t.new_status,
                actor_name=None if t.actor is None else str(t.actor),
                recorded_at=t.recorded_at,
            )
            for t in transitions
        ],
        superseded_by=(
            None
            if row.superseded_by_entity_id is None
            else EntityRef(row.superseded_by_entity_id, str(row.replacement_name))
        ),
        supersedes=[EntityRef(r.entity_id, str(r.canonical_name)) for r in replaced],
    )
