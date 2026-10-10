"""Party read models (Phase 15 checkpoint 15.2C-1).

A party is listed under a campaign only through `campaign.campaign_parties`. Name
and description are campaign-visible. Archived parties are hidden unless the
caller asks and the route allows it (editors only).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.party_authoring import PARTY_ACTIVE


@dataclass(frozen=True)
class PartyView:
    party_id: uuid.UUID
    name: str
    description: str | None
    lifecycle_status: str
    row_version: int


_SELECT = """
    SELECT p.party_id, p.name, p.description, p.row_version, ls.code AS lifecycle_status
    FROM campaign.parties p
    JOIN campaign.campaign_parties cp ON cp.party_id = p.party_id
    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = p.lifecycle_status_id
    WHERE cp.campaign_id = :c
"""


def _view(row: object) -> PartyView:
    return PartyView(
        party_id=row.party_id,  # type: ignore[attr-defined]
        name=str(row.name),  # type: ignore[attr-defined]
        description=row.description,  # type: ignore[attr-defined]
        lifecycle_status=str(row.lifecycle_status),  # type: ignore[attr-defined]
        row_version=int(row.row_version),  # type: ignore[attr-defined]
    )


def list_campaign_parties(
    connection: Connection, *, campaign_id: uuid.UUID, include_archived: bool
) -> list[PartyView]:
    rows = connection.execute(
        text(
            _SELECT
            + " AND (CAST(:inc AS boolean) OR ls.code = :active)"
            + " ORDER BY lower(p.name), p.party_id"
        ),
        {"c": campaign_id, "inc": include_archived, "active": PARTY_ACTIVE},
    ).all()
    return [_view(row) for row in rows]


def get_campaign_party(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    party_id: uuid.UUID,
    include_archived: bool,
) -> PartyView | None:
    row = connection.execute(
        text(_SELECT + " AND p.party_id = :p AND (CAST(:inc AS boolean) OR ls.code = :active)"),
        {"c": campaign_id, "p": party_id, "inc": include_archived, "active": PARTY_ACTIVE},
    ).one_or_none()
    return None if row is None else _view(row)


def list_character_parties(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    include_archived: bool,
) -> list[PartyView]:
    """The parties `character_id` currently belongs to on `timeline_id`, among those attached to
    `campaign_id` — every one, in a stable name order, never paged.

    "Currently" is the table's own "still a member" representation
    (`effective_to_world_time_id IS NULL`, migration 009), and the party must be attached to the
    campaign: exactly the pair rule `dnd_ai.api.access.resolve_party_perspective` accepts and the
    session bootstrap's `authorized_parties` lists. Archived parties are hidden unless the caller
    may see them (editors), like every other party read. This performs no authorization of its
    own: the character's perspective must already have been authorized by the caller."""
    rows = connection.execute(
        text("""
            SELECT p.party_id, p.name, p.description, p.row_version, ls.code AS lifecycle_status
            FROM campaign.party_memberships pm
            JOIN campaign.parties p ON p.party_id = pm.party_id
            JOIN campaign.campaign_parties cp ON cp.party_id = p.party_id AND cp.campaign_id = :c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = p.lifecycle_status_id
            WHERE pm.timeline_id = :t
              AND pm.member_entity_id = :ch
              AND pm.effective_to_world_time_id IS NULL
              AND (CAST(:inc AS boolean) OR ls.code = :active)
            ORDER BY lower(p.name), p.party_id
        """),
        {
            "c": campaign_id,
            "t": timeline_id,
            "ch": character_id,
            "inc": include_archived,
            "active": PARTY_ACTIVE,
        },
    ).all()
    return [_view(row) for row in rows]
