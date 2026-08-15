"""Effective organization query (docs/PLAN.md Phase 10 deliverable "query
services for the effective dungeon, character, quest, relationship,
inventory, encounter, and knowledge state required by the vertical
slice"). A sibling to `dnd_ai.queries.relationship`, over the other half
of workstream 8's command domain (`dnd_ai.commands.relationships.
update_organization_status`).

`world.organizations` describes what an organization is; `campaign.
organization_state` describes its current operational status on a
timeline — unlike `campaign.relationship_state`, there is exactly one
current row per `(timeline, organization)`
(`ux_organization_state_timeline_organization`, migration 076), no
shared-vs-subjective split.

Audience filtering follows the schema's own naming, not an inferred
policy: `world.organizations.public_description` and `.
internal_description` are two distinct columns (docs/architecture/
DATABASE_MODEL.md §10.3), and the latter's name is itself the contract —
returned only to a caller holding `canon.edit` (a GM), `None` for
everyone else, the same "fetch nothing rather than fetch-and-withhold"
discipline `dnd_ai.queries.character`/`.relationship` already established
for their own GM-only fields. Every other field (type, parent, founding/
dissolution, headquarters, current status) is structural or already
timeline-state a `campaign.view` caller is entitled to.

This module is framework-free and performs no authorization of its own:
`include_internal_description` must already be an authorized decision (a
resolved `canon.edit` capability check) by the time it reaches here.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class OrganizationNotFoundError(DomainAuthorizationError):
    """Raised by `get_organization_view()` for a nonexistent
    `organization_id`, or one whose own world does not match the caller's
    `expected_world_id` — identically, so a caller can never distinguish
    "doesn't exist" from "belongs to a different world" (mirroring
    `dnd_ai.queries.dungeon.DungeonAreaNotFoundError`'s identical
    reasoning). The supplied organization/world ids are included only in
    the constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


@dataclass(frozen=True)
class OrganizationView:
    organization_id: uuid.UUID
    organization_type_code: str
    parent_organization_id: uuid.UUID | None
    founded_world_time_id: uuid.UUID | None
    dissolved_world_time_id: uuid.UUID | None
    headquarters_location_id: uuid.UUID | None
    public_description: str | None
    internal_description: str | None
    """`None` unless the caller was authorized for it
    (`include_internal_description=True`) — see this module's docstring."""
    status_code: str | None


def get_organization_view(
    connection: Connection,
    *,
    organization_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    include_internal_description: bool,
) -> OrganizationView:
    """The effective state of one organization. Raises
    `OrganizationNotFoundError` for a nonexistent organization or one
    belonging to a different world than `expected_world_id` (always the
    caller's own resolved-timeline world — `dnd_ai.api._shared.
    timeline_world_id`, never caller-supplied)."""
    row = (
        connection.execute(
            text("""
                SELECT o.organization_id, e.world_id, ot.code AS organization_type_code,
                       o.parent_organization_id, o.founded_world_time_id,
                       o.dissolved_world_time_id, o.headquarters_location_id,
                       o.public_description, o.internal_description,
                       os.code AS status_code
                FROM world.organizations o
                JOIN core.entities e ON e.entity_id = o.organization_id
                JOIN world.organization_types ot
                    ON ot.organization_type_id = o.organization_type_id
                LEFT JOIN campaign.organization_state ost
                       ON ost.timeline_id = :timeline AND ost.organization_id = o.organization_id
                LEFT JOIN campaign.organization_statuses os
                       ON os.organization_status_id = ost.organization_status_id
                WHERE o.organization_id = :organization
            """),
            {"timeline": timeline_id, "organization": organization_id},
        )
        .mappings()
        .one_or_none()
    )

    if row is None or row["world_id"] != expected_world_id:
        raise OrganizationNotFoundError(
            f"organization {organization_id} does not exist in world {expected_world_id} "
            f"(actual world: {row['world_id'] if row is not None else None})"
        )

    return OrganizationView(
        organization_id=row["organization_id"],
        organization_type_code=row["organization_type_code"],
        parent_organization_id=row["parent_organization_id"],
        founded_world_time_id=row["founded_world_time_id"],
        dissolved_world_time_id=row["dissolved_world_time_id"],
        headquarters_location_id=row["headquarters_location_id"],
        public_description=row["public_description"],
        internal_description=(
            row["internal_description"] if include_internal_description else None
        ),
        status_code=row["status_code"],
    )
