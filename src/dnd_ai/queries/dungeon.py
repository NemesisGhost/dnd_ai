"""Audience-filtered effective dungeon-area query.

`world.dungeon_areas` and its structural children (`world.area_features`/
`.area_hazards`/`.area_interactables`/`.area_connections`) describe what
exists; `campaign.location_state`/`.area_feature_state`/`.hazard_state`/
`.area_connection_state`/`.interactable_state` describe what is currently
true on a timeline; `is_hidden` on each structural child is a fact about
the object itself, never about party knowledge (docs/architecture/
DATABASE_MODEL.md §9.3). This module is the read side that reassembles
those three concerns into one effective, audience-filtered view — the
"party/public knowledge-derived access... resolved by the query layer that
already has a character perspective" `dnd_ai.domain.access` explicitly
defers here (see that module's docstring).

Audience filtering: `include_hidden=True` (a caller holding the `canon.edit`
role capability — a GM) sees every structural child regardless of
`is_hidden`. Otherwise, a hidden child is included only when the requesting
party has discovered it — a `knowledge.knowledge_items` row whose
`subject_area_*_id` names that exact child, joined to a
`knowledge.party_discoveries` row for `(timeline_id, party_id)`. A
non-hidden child is always included. This means a hidden, undiscovered
child is dropped from the result set entirely, not merely flagged — the
same "cannot be inferred through counts... or errors" non-disclosure rule
docs/PLAN.md §25 step 15 requires of every audience-scoped read in this
codebase.

`party_id=None` (no party context — an observer, or a player query made
without one) is a safe default, not an error: `knowledge.party_discoveries.
party_id = NULL` never matches under normal SQL NULL semantics, so every
hidden child is simply excluded, identically to a party with no discoveries
yet.

This module is framework-free and does not authorize anything itself — a
caller-supplied `party_id` is trusted here only because a `campaign.
campaign_parties` association is *not*, by itself, sufficient
authorization for a party perspective (docs/architecture/DATABASE_MODEL.md
§15: fictional party knowledge is not itself human authorization). Every
caller must first resolve `party_id` through `dnd_ai.api.access.
resolve_party_perspective` — which proves the authenticated user holds
`character.view_knowledge` for a specific character *and* that character
is currently a member of exactly that party — before passing it here; this
function performs no independent check of its own and would otherwise
happily filter by any party a caller named, campaign-associated or not.
`knowledge.party_discoveries` is scoped by `timeline_id` alone, so an
unauthorized `party_id` would otherwise leak that party's discoveries to a
caller with no relationship to it at all.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class DungeonAreaNotFoundError(DomainAuthorizationError):
    """Raised by `get_dungeon_area_view()` for a nonexistent
    `dungeon_area_id`, or one whose own world does not match the caller's
    `expected_world_id` — identically, so a caller can never distinguish
    "doesn't exist" from "belongs to a different world" (docs/architecture/
    DATABASE_MODEL.md §19.7's "prefer NotFound when existence itself is a
    disclosure" rule, mirroring `dnd_ai.commands.encounters.
    EncounterNotFoundError` and `dnd_ai.commands.integration.
    ExternalSystemNotFoundError`'s identical reasoning for the world/
    campaign-scoped domains that predate this one). The supplied
    dungeon_area_id/world ids are included only in the constructor's
    `detail` argument (`str(self)`), never in `safe_message`."""


@dataclass(frozen=True)
class DungeonAreaFeatureView:
    area_feature_id: uuid.UUID
    feature_type: str | None
    description: str | None
    is_hidden: bool
    is_destroyed: bool
    condition_notes: str | None


@dataclass(frozen=True)
class DungeonAreaHazardView:
    area_hazard_id: uuid.UUID
    hazard_type: str | None
    description: str | None
    severity: int | None
    is_hidden: bool
    hazard_status_code: str | None


@dataclass(frozen=True)
class DungeonAreaInteractableView:
    area_interactable_id: uuid.UUID
    interactable_type: str | None
    description: str | None
    is_hidden: bool
    interactable_status_code: str | None


@dataclass(frozen=True)
class DungeonAreaConnectionView:
    """`direction` is "outgoing" if the queried area is this connection's
    `from_dungeon_area_id`, "incoming" otherwise — never a reflection of
    whether the connection is actually traversable from here (`is_one_way`
    names that separately)."""

    area_connection_id: uuid.UUID
    connection_type_code: str
    other_dungeon_area_id: uuid.UUID
    direction: str
    is_one_way: bool
    is_hidden: bool
    description: str | None
    connection_status_code: str | None


@dataclass(frozen=True)
class DungeonAreaView:
    dungeon_area_id: uuid.UUID
    name: str
    area_type: str | None
    dimensions: str | None
    environmental_properties: str | None
    is_searched: bool
    is_destroyed: bool
    alarm_level: int
    condition_notes: str | None
    features: tuple[DungeonAreaFeatureView, ...]
    hazards: tuple[DungeonAreaHazardView, ...]
    interactables: tuple[DungeonAreaInteractableView, ...]
    connections: tuple[DungeonAreaConnectionView, ...]


# Shared by every structural-child query below: a hidden row is included
# only for a GM (:include_hidden) or when the requesting party has
# discovered the knowledge item naming it as subject — see this module's
# own docstring. `subject_column` is always an internal literal supplied by
# the callers in this file, never user-controlled.
_DISCOVERY_EXISTS = """
    EXISTS (
        SELECT 1 FROM knowledge.knowledge_items ki
        JOIN knowledge.party_discoveries pd ON pd.knowledge_item_id = ki.knowledge_item_id
        WHERE ki.{subject_column} = {row_column}
          AND pd.timeline_id = :timeline
          AND pd.party_id = :party
    )
"""


def get_dungeon_area_view(
    connection: Connection,
    *,
    dungeon_area_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    party_id: uuid.UUID | None,
    include_hidden: bool,
) -> DungeonAreaView:
    """The effective, audience-filtered state of one dungeon area: its
    definition, current `campaign.location_state`, and every structural
    child (features, hazards, interactables, connections) visible to the
    requesting audience. Raises `DungeonAreaNotFoundError` for a
    nonexistent area or one belonging to a different world than
    `expected_world_id` (always the caller's own resolved-timeline world —
    `dnd_ai.api._shared.timeline_world_id`, never caller-supplied)."""
    area_row = (
        connection.execute(
            text("""
            SELECT da.dungeon_area_id, e.world_id, e.canonical_name, da.area_type,
                   da.dimensions, da.environmental_properties,
                   COALESCE(ls.is_searched, false) AS is_searched,
                   COALESCE(ls.is_destroyed, false) AS is_destroyed,
                   COALESCE(ls.alarm_level, 0) AS alarm_level,
                   ls.condition_notes
            FROM world.dungeon_areas da
            JOIN core.entities e ON e.entity_id = da.dungeon_area_id
            LEFT JOIN campaign.location_state ls
                   ON ls.timeline_id = :timeline AND ls.location_id = da.dungeon_area_id
            WHERE da.dungeon_area_id = :area
        """),
            {"area": dungeon_area_id, "timeline": timeline_id},
        )
        .mappings()
        .one_or_none()
    )

    if area_row is None or area_row["world_id"] != expected_world_id:
        raise DungeonAreaNotFoundError(
            f"dungeon area {dungeon_area_id} does not exist in world {expected_world_id} "
            f"(actual world: {area_row['world_id'] if area_row is not None else None})"
        )

    params = {
        "area": dungeon_area_id,
        "timeline": timeline_id,
        "party": party_id,
        "include_hidden": include_hidden,
    }

    feature_rows = connection.execute(
        text(f"""
            SELECT af.area_feature_id, af.feature_type, af.description, af.is_hidden,
                   COALESCE(afs.is_destroyed, false) AS is_destroyed, afs.condition_notes
            FROM world.area_features af
            LEFT JOIN campaign.area_feature_state afs
                   ON afs.timeline_id = :timeline AND afs.area_feature_id = af.area_feature_id
            WHERE af.dungeon_area_id = :area
              AND (
                :include_hidden
                OR NOT af.is_hidden
                OR {
            _DISCOVERY_EXISTS.format(
                subject_column="subject_area_feature_id",
                row_column="af.area_feature_id",
            )
        }
              )
            ORDER BY af.area_feature_id
        """),
        params,
    ).mappings()
    features = tuple(
        DungeonAreaFeatureView(
            area_feature_id=row["area_feature_id"],
            feature_type=row["feature_type"],
            description=row["description"],
            is_hidden=row["is_hidden"],
            is_destroyed=row["is_destroyed"],
            condition_notes=row["condition_notes"],
        )
        for row in feature_rows
    )

    hazard_rows = connection.execute(
        text(f"""
            SELECT ah.area_hazard_id, ah.hazard_type, ah.description, ah.severity, ah.is_hidden,
                   hs.code AS hazard_status_code
            FROM world.area_hazards ah
            LEFT JOIN campaign.hazard_state hst
                   ON hst.timeline_id = :timeline AND hst.area_hazard_id = ah.area_hazard_id
            LEFT JOIN campaign.hazard_statuses hs ON hs.hazard_status_id = hst.hazard_status_id
            WHERE ah.dungeon_area_id = :area
              AND (
                :include_hidden
                OR NOT ah.is_hidden
                OR {
            _DISCOVERY_EXISTS.format(
                subject_column="subject_area_hazard_id",
                row_column="ah.area_hazard_id",
            )
        }
              )
            ORDER BY ah.area_hazard_id
        """),
        params,
    ).mappings()
    hazards = tuple(
        DungeonAreaHazardView(
            area_hazard_id=row["area_hazard_id"],
            hazard_type=row["hazard_type"],
            description=row["description"],
            severity=row["severity"],
            is_hidden=row["is_hidden"],
            hazard_status_code=row["hazard_status_code"],
        )
        for row in hazard_rows
    )

    interactable_rows = connection.execute(
        text(f"""
            SELECT ai.area_interactable_id, ai.interactable_type, ai.description, ai.is_hidden,
                   ist.code AS interactable_status_code
            FROM world.area_interactables ai
            LEFT JOIN campaign.interactable_state ins
                   ON ins.timeline_id = :timeline
                  AND ins.area_interactable_id = ai.area_interactable_id
            LEFT JOIN campaign.interactable_statuses ist
                   ON ist.interactable_status_id = ins.interactable_status_id
            WHERE ai.dungeon_area_id = :area
              AND (
                :include_hidden
                OR NOT ai.is_hidden
                OR {
            _DISCOVERY_EXISTS.format(
                subject_column="subject_area_interactable_id",
                row_column="ai.area_interactable_id",
            )
        }
              )
            ORDER BY ai.area_interactable_id
        """),
        params,
    ).mappings()
    interactables = tuple(
        DungeonAreaInteractableView(
            area_interactable_id=row["area_interactable_id"],
            interactable_type=row["interactable_type"],
            description=row["description"],
            is_hidden=row["is_hidden"],
            interactable_status_code=row["interactable_status_code"],
        )
        for row in interactable_rows
    )

    connection_rows = connection.execute(
        text(f"""
            SELECT ac.area_connection_id, ct.code AS connection_type_code, ac.is_one_way,
                   ac.is_hidden, ac.description,
                   CASE WHEN ac.from_dungeon_area_id = :area THEN 'outgoing' ELSE 'incoming' END
                       AS direction,
                   CASE WHEN ac.from_dungeon_area_id = :area
                        THEN ac.to_dungeon_area_id ELSE ac.from_dungeon_area_id END
                       AS other_dungeon_area_id,
                   cs.code AS connection_status_code
            FROM world.area_connections ac
            JOIN world.connection_types ct ON ct.connection_type_id = ac.connection_type_id
            LEFT JOIN campaign.area_connection_state acs
                   ON acs.timeline_id = :timeline
                  AND acs.area_connection_id = ac.area_connection_id
            LEFT JOIN campaign.connection_statuses cs
                   ON cs.connection_status_id = acs.connection_status_id
            WHERE (ac.from_dungeon_area_id = :area OR ac.to_dungeon_area_id = :area)
              AND (
                :include_hidden
                OR NOT ac.is_hidden
                OR {
            _DISCOVERY_EXISTS.format(
                subject_column="subject_area_connection_id",
                row_column="ac.area_connection_id",
            )
        }
              )
            ORDER BY ac.area_connection_id
        """),
        params,
    ).mappings()
    connections = tuple(
        DungeonAreaConnectionView(
            area_connection_id=row["area_connection_id"],
            connection_type_code=row["connection_type_code"],
            other_dungeon_area_id=row["other_dungeon_area_id"],
            direction=row["direction"],
            is_one_way=row["is_one_way"],
            is_hidden=row["is_hidden"],
            description=row["description"],
            connection_status_code=row["connection_status_code"],
        )
        for row in connection_rows
    )

    return DungeonAreaView(
        dungeon_area_id=area_row["dungeon_area_id"],
        name=area_row["canonical_name"],
        area_type=area_row["area_type"],
        dimensions=area_row["dimensions"],
        environmental_properties=area_row["environmental_properties"],
        is_searched=area_row["is_searched"],
        is_destroyed=area_row["is_destroyed"],
        alarm_level=area_row["alarm_level"],
        condition_notes=area_row["condition_notes"],
        features=features,
        hazards=hazards,
        interactables=interactables,
        connections=connections,
    )
