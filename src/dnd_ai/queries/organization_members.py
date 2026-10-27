"""The members of one organization, audience-filtered (Phase 15 checkpoint 15.3A-2b, D-19).

An office is a membership's `role` and `rank` (decision D-19, option a: no vacancy table). A reader
who cannot edit canon sees a member only when the membership is active and public and the member
is independently discoverable to them (the rule every relationship read applies); an editor sees
every stint, private and archived ones included, with a flag for each. The organization's
current operational status rides along.

A withheld membership leaves no trace in the result: no row, count, name or placeholder. Because an
office exists only on its membership, an office whose holder is withheld is not shown either, and
nothing here can say an office is vacant. Each row carries where the caller's timeline clock sits
against its period (`period_status`, the same derivation the character reader uses) and the World
category of its member, from which the route decides whether the name may link.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.relationship_authoring import relationship_period_status

from .campaign_clock import resolve_effective_clock, world_time_point
from .world_explorer import (
    WorldEntityVisibility,
    discoverable_entity_ids,
    world_category_for_type_code,
)


@dataclass(frozen=True)
class MemberRow:
    relationship_id: uuid.UUID
    member_entity_id: uuid.UUID
    member_name: str
    member_type_code: str
    role: str | None
    rank: str | None
    is_public: bool
    started: str
    ended: str | None
    current: bool
    lifecycle_status: str
    row_version: int
    period_status: str
    category: str | None


@dataclass(frozen=True)
class OrganizationMembers:
    organization_id: uuid.UUID
    status: str | None
    members: list[MemberRow] = field(default_factory=list)
    status_choices: list[tuple[str, str]] = field(default_factory=list)
    as_of: str | None = None
    """The caller's effective timeline clock as display text, or `None` when it is unset."""


def list_organization_members(
    connection: Connection,
    *,
    organization_id: uuid.UUID,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    visibility: WorldEntityVisibility,
    include_private: bool,
) -> OrganizationMembers | None:
    """`None` when the entity is not an organization of this world."""
    exists = connection.execute(
        text("""
            SELECT 1 FROM world.organizations o JOIN core.entities e ON e.entity_id = o.organization_id
            WHERE o.organization_id = :o AND e.world_id = :w
        """),
        {"o": organization_id, "w": world_id},
    ).scalar()
    if exists is None:
        return None
    rows = connection.execute(
        text("""
            SELECT m.relationship_id, m.member_entity_id, e.canonical_name, et.code AS member_type,
                   m.role, m.rank, m.is_public, m.effective_from_world_time_id,
                   m.effective_to_world_time_id, ls.code AS lifecycle, r.row_version,
                   sw.sort_key AS start_key, ew.sort_key AS end_key
            FROM world.organization_memberships m
            JOIN world.relationships r ON r.relationship_id = m.relationship_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = r.lifecycle_status_id
            JOIN core.entities e ON e.entity_id = m.member_entity_id
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            LEFT JOIN core.world_times sw ON sw.world_time_id = m.effective_from_world_time_id
            LEFT JOIN core.world_times ew ON ew.world_time_id = m.effective_to_world_time_id
            WHERE m.organization_id = :o
            ORDER BY lower(m.membership_period), lower(e.canonical_name), m.relationship_id
        """),
        {"o": organization_id},
    ).all()
    discoverable = (
        frozenset(r.member_entity_id for r in rows)
        if include_private
        else discoverable_entity_ids(
            connection,
            [r.member_entity_id for r in rows],
            world_id=world_id,
            timeline_id=timeline_id,
            visibility=visibility,
        )
    )
    clock = resolve_effective_clock(connection, timeline_id=timeline_id)
    clock_key = None if clock is None else clock.sort_key
    members: list[MemberRow] = []
    for r in rows:
        if not include_private and (
            str(r.lifecycle) != "active"
            or not r.is_public
            or r.member_entity_id not in discoverable
        ):
            continue
        members.append(
            MemberRow(
                relationship_id=r.relationship_id,
                member_entity_id=r.member_entity_id,
                member_name=str(r.canonical_name),
                member_type_code=str(r.member_type),
                role=r.role,
                rank=r.rank,
                is_public=bool(r.is_public),
                started=world_time_point(connection, r.effective_from_world_time_id)[1],
                ended=(
                    None
                    if r.effective_to_world_time_id is None
                    else world_time_point(connection, r.effective_to_world_time_id)[1]
                ),
                current=r.effective_to_world_time_id is None and str(r.lifecycle) == "active",
                lifecycle_status=str(r.lifecycle),
                row_version=int(r.row_version),
                period_status=relationship_period_status(r.start_key, r.end_key, clock_key),
                category=world_category_for_type_code(str(r.member_type)),
            )
        )
    status = connection.execute(
        text("""
            SELECT st.code FROM campaign.organization_state os
            JOIN campaign.organization_statuses st
              ON st.organization_status_id = os.organization_status_id
            WHERE os.timeline_id = :t AND os.organization_id = :o
        """),
        {"t": timeline_id, "o": organization_id},
    ).scalar()
    choices: list[tuple[str, str]] = []
    if include_private:
        choices = [
            (str(c.code), str(c.display_name))
            for c in connection.execute(
                text(
                    "SELECT code, display_name FROM campaign.organization_statuses "
                    "ORDER BY sort_order, code"
                )
            )
        ]
    return OrganizationMembers(
        organization_id=organization_id,
        status=None if status is None else str(status),
        members=members,
        status_choices=choices,
        as_of=None if clock is None else clock.display,
    )
