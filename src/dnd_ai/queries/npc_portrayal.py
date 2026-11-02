"""Editor read models for NPC portrayal and runtime controls (Phase 15 checkpoint 15.3A-3, D-21).

`canon.edit` only. The portrayal view carries the NPC detail level, the version of the profile
being shown (the latest unless one is asked for), and the history of versions. Runtime options
are the rules conditions and resources of the campaign ruleset, which the GM runtime panel picks
from; the state itself is read through the character read model.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import content_edit_blocked_reason
from dnd_ai.domain.npc_portrayal import PROFILE_FIELD_NAMES, PortrayalVersionNotFoundError


@dataclass(frozen=True)
class ProfileVersion:
    version_number: int
    created_at: datetime
    change_note: str | None


@dataclass(frozen=True)
class NpcPortrayalView:
    npc_id: uuid.UUID
    name: str
    detail_level: str
    row_version: int
    canon_status: str
    lifecycle_status: str
    current_version: int
    shown_version: int
    fields: dict[str, str | None]
    versions: list[ProfileVersion] = field(default_factory=list)
    can_edit: bool = False


def get_npc_portrayal(
    connection: Connection, *, world_id: uuid.UUID, npc_id: uuid.UUID, version: int | None = None
) -> NpcPortrayalView | None:
    """`None` when the entity is not an NPC of this world."""
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.row_version, n.detail_level,
                   cs.code AS canon, ls.code AS lifecycle
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN character.npcs n ON n.npc_id = e.entity_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.entity_id = :n AND e.world_id = :w AND et.code = 'npc'
        """),
        {"n": npc_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    versions = [
        ProfileVersion(int(v.version_number), v.created_at, v.change_note)
        for v in connection.execute(
            text(
                "SELECT version_number, created_at, change_note "
                "FROM character.npc_portrayal_profiles WHERE npc_id = :n "
                "ORDER BY version_number DESC"
            ),
            {"n": npc_id},
        )
    ]
    current = versions[0].version_number if versions else 0
    shown = current if version is None else version
    values: dict[str, str | None] = dict.fromkeys(PROFILE_FIELD_NAMES)
    if shown != 0:
        profile = (
            connection.execute(
                text(  # noqa: S608 - fixed column names
                    "SELECT "
                    + ", ".join(PROFILE_FIELD_NAMES)
                    + " FROM character.npc_portrayal_profiles "
                    "WHERE npc_id = :n AND version_number = :v"
                ),
                {"n": npc_id, "v": shown},
            )
            .mappings()
            .one_or_none()
        )
        if profile is None:
            raise PortrayalVersionNotFoundError(f"npc {npc_id} has no version {shown}")
        values = {name: profile[name] for name in PROFILE_FIELD_NAMES}
    return NpcPortrayalView(
        npc_id=npc_id,
        name=str(row.canonical_name),
        detail_level=str(row.detail_level),
        row_version=int(row.row_version),
        canon_status=str(row.canon),
        lifecycle_status=str(row.lifecycle),
        current_version=current,
        shown_version=shown,
        fields=values,
        versions=versions,
        can_edit=content_edit_blocked_reason(str(row.canon), str(row.lifecycle)) is None,
    )


@dataclass(frozen=True)
class RuntimeOptions:
    conditions: list[tuple[uuid.UUID, str, str]]
    resources: list[tuple[uuid.UUID, str, str]]


def get_runtime_options(connection: Connection, *, campaign_id: uuid.UUID) -> RuntimeOptions:
    version = connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    conditions = [
        (r.condition_id, str(r.display_name), str(r.code))
        for r in connection.execute(
            text(
                "SELECT condition_id, display_name, code FROM rules.conditions "
                "WHERE ruleset_version_id = :v ORDER BY display_name, code"
            ),
            {"v": version},
        )
    ]
    resources = [
        (r.resource_definition_id, str(r.display_name), str(r.code))
        for r in connection.execute(
            text(
                "SELECT resource_definition_id, display_name, code FROM rules.resource_definitions "
                "WHERE ruleset_version_id = :v ORDER BY display_name, code"
            ),
            {"v": version},
        )
    ]
    return RuntimeOptions(conditions=conditions, resources=resources)
