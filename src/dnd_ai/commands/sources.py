"""Source commands (Phase 15 checkpoint 15.3C-1, decision D-26).

`create_source` makes a world-owned source of an authorable type; `attach_source` and
`detach_source` link and unlink a world's source and one of its entities, keeping the history of
both. Attaching or detaching changes nothing about the entity definition itself, so it does not
touch the entity row version or add a revision: it is provenance, kept in
`core.entity_source_links`. The state of the link is the optimistic guard: attaching what is
attached, or detaching what is not, is a conflict.

Lock order: authority scope, the entity `FOR SHARE`, the source `FOR SHARE`, then a transaction
advisory lock on the (entity, source) pair, which serializes two attaches of the same pair before
there is a link row to lock.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import initial_fields
from dnd_ai.domain.source_authoring import (
    SourceAlreadyAttachedError,
    SourceNotAttachedError,
    SourceNotUsableError,
    normalize_reference,
    normalize_source_type,
    normalize_title,
)
from dnd_ai.domain.world_authority import WORLD_CANON_EDIT

from ._content import EntityNotFoundError, lock_authoring_scope, lock_entities
from ._shared import lookup_id


@dataclass(frozen=True)
class SourceResult:
    world_id: uuid.UUID
    source_id: uuid.UUID
    entity_id: uuid.UUID | None = None
    link_id: uuid.UUID | None = None
    table: str = "sources"
    action: str = "created"
    changed_fields: dict[str, object] = field(default_factory=dict)


def create_source(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    source_type: str,
    title: str,
    reference: str | None = None,
) -> SourceResult:
    code = normalize_source_type(source_type)
    clean_title = normalize_title(title)
    clean_reference = normalize_reference(reference)
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=WORLD_CANON_EDIT,
    )
    type_id = lookup_id(connection, "core", "source_types", "source_type_id", code)
    source_id = connection.execute(
        text("""
            INSERT INTO core.sources
                (world_id, source_type_id, title, reference, created_by_user_id)
            VALUES (:w, :t, :title, :reference, :u) RETURNING source_id
        """),
        {
            "w": scope.world_id,
            "t": type_id,
            "title": clean_title,
            "reference": clean_reference,
            "u": actor_user_id,
        },
    ).scalar()
    assert isinstance(source_id, uuid.UUID)
    return SourceResult(
        world_id=scope.world_id,
        source_id=source_id,
        changed_fields=dict(
            initial_fields(
                {"source_type": code, "title": clean_title, "reference": clean_reference}
            )
        ),
    )


def _lock_pair(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    entity_id: uuid.UUID,
    source_id: uuid.UUID,
) -> uuid.UUID:
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=WORLD_CANON_EDIT,
    )
    locked = lock_entities(connection, world_id=scope.world_id, share_ids=[entity_id])
    if entity_id not in locked:
        raise EntityNotFoundError(f"entity {entity_id} is not in this world")
    found = connection.execute(
        text("SELECT 1 FROM core.sources WHERE source_id = :s AND world_id = :w FOR SHARE"),
        {"s": source_id, "w": scope.world_id},
    ).scalar()
    if found is None:
        raise SourceNotUsableError(f"source {source_id} is not in this world")
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"core.entity_source_links:{entity_id}:{source_id}"},
    )
    return scope.world_id


def attach_source(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    entity_id: uuid.UUID,
    source_id: uuid.UUID,
) -> SourceResult:
    world_id = _lock_pair(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        entity_id=entity_id,
        source_id=source_id,
    )
    active = connection.execute(
        text("""
            SELECT 1 FROM core.entity_source_links
            WHERE entity_id = :e AND source_id = :s AND detached_at IS NULL
        """),
        {"e": entity_id, "s": source_id},
    ).scalar()
    if active is not None:
        raise SourceAlreadyAttachedError(f"source {source_id} is attached to {entity_id}")
    link_id = connection.execute(
        text("""
            INSERT INTO core.entity_source_links (entity_id, source_id, attached_by_user_id)
            VALUES (:e, :s, :u) RETURNING entity_source_link_id
        """),
        {"e": entity_id, "s": source_id, "u": actor_user_id},
    ).scalar()
    assert isinstance(link_id, uuid.UUID)
    return SourceResult(
        world_id=world_id,
        source_id=source_id,
        entity_id=entity_id,
        link_id=link_id,
        table="entity_source_links",
        action="created",
    )


def detach_source(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    entity_id: uuid.UUID,
    source_id: uuid.UUID,
) -> SourceResult:
    world_id = _lock_pair(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        entity_id=entity_id,
        source_id=source_id,
    )
    link_id = connection.execute(
        text("""
            UPDATE core.entity_source_links
            SET detached_at = now(), detached_by_user_id = :u
            WHERE entity_id = :e AND source_id = :s AND detached_at IS NULL
            RETURNING entity_source_link_id
        """),
        {"e": entity_id, "s": source_id, "u": actor_user_id},
    ).scalar()
    if link_id is None:
        raise SourceNotAttachedError(f"source {source_id} is not attached to {entity_id}")
    return SourceResult(
        world_id=world_id,
        source_id=source_id,
        entity_id=entity_id,
        link_id=link_id,
        table="entity_source_links",
        action="updated",
    )
