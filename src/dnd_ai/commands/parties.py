"""Party definition commands (Phase 15 checkpoint 15.2C-1, decision D-30).

`create_party` writes the world-level party and attaches it to the campaign in one
transaction; `update_party` edits its name and description; `archive_party` and
`restore_party` move it between `active` and `archived`. A party is reachable only
through a campaign it is attached to: any other party id (nonexistent, another
world's, or attached only elsewhere) is the same non-disclosing 404.

Lock order: operation scope (world, membership rows, account, campaign `FOR
SHARE`), then the party row `FOR UPDATE`.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import StaleWriteError, normalize_reason
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.party_authoring import (
    PARTY_ACTIVE,
    PARTY_ARCHIVED,
    PartyNotActiveError,
    PartyNotArchivedError,
    normalize_description,
    normalize_name,
)

from ._operations import lock_operation_scope
from ._shared import PartyNotInCampaignError, lookup_id


@dataclass(frozen=True)
class PartyResult:
    party_id: uuid.UUID
    world_id: uuid.UUID
    row_version: int
    created: bool
    changed: bool
    changed_fields: dict[str, object]
    lifecycle_status: str
    previous_lifecycle_status: str | None = None


@dataclass(frozen=True)
class LockedParty:
    name: str
    description: str | None
    row_version: int
    lifecycle_status: str


def lock_campaign_party(
    connection: Connection, *, campaign_id: uuid.UUID, party_id: uuid.UUID
) -> LockedParty:
    row = connection.execute(
        text("""
            SELECT p.name, p.description, p.row_version, p.lifecycle_status_id
            FROM campaign.parties p
            JOIN campaign.campaign_parties cp ON cp.party_id = p.party_id
            WHERE p.party_id = :p AND cp.campaign_id = :c
            FOR UPDATE OF p
        """),
        {"p": party_id, "c": campaign_id},
    ).one_or_none()
    if row is None:
        raise PartyNotInCampaignError(f"party {party_id} is not attached to {campaign_id}")
    status = connection.execute(
        text("SELECT code FROM core.lifecycle_statuses WHERE lifecycle_status_id = :s"),
        {"s": row.lifecycle_status_id},
    ).scalar()
    return LockedParty(
        name=str(row.name),
        description=row.description,
        row_version=int(row.row_version),
        lifecycle_status=str(status),
    )


def create_party(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str | None,
    description: str | None = None,
) -> PartyResult:
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    row = connection.execute(
        text("""
            INSERT INTO campaign.parties
                (world_id, name, description, lifecycle_status_id, created_by_user_id)
            VALUES (:w, :n, :d, :s, :u)
            RETURNING party_id, row_version
        """),
        {
            "w": scope.world_id,
            "n": clean_name,
            "d": clean_description,
            "s": lookup_id(
                connection, "core", "lifecycle_statuses", "lifecycle_status_id", PARTY_ACTIVE
            ),
            "u": actor_user_id,
        },
    ).one()
    connection.execute(
        text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
        {"c": campaign_id, "p": row.party_id},
    )
    return PartyResult(
        party_id=row.party_id,
        world_id=scope.world_id,
        row_version=int(row.row_version),
        created=True,
        changed=True,
        changed_fields=initial_fields({"name": clean_name, "description": clean_description}),
        lifecycle_status=PARTY_ACTIVE,
    )


def update_party(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    party_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    description: str | None = None,
) -> PartyResult:
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    party = lock_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)
    if party.row_version != expected_row_version:
        raise StaleWriteError(f"party {party_id} is at {party.row_version}")
    if party.lifecycle_status != PARTY_ACTIVE:
        raise PartyNotActiveError(f"party {party_id} is {party.lifecycle_status}")
    changed = diff_fields(
        {"name": party.name, "description": party.description},
        {"name": clean_name, "description": clean_description},
    )
    if not changed:
        return PartyResult(
            party_id=party_id,
            world_id=scope.world_id,
            row_version=party.row_version,
            created=False,
            changed=False,
            changed_fields={},
            lifecycle_status=party.lifecycle_status,
        )
    version = connection.execute(
        text(
            "UPDATE campaign.parties SET name = :n, description = :d "
            "WHERE party_id = :p RETURNING row_version"
        ),
        {"n": clean_name, "d": clean_description, "p": party_id},
    ).scalar()
    assert isinstance(version, int)
    return PartyResult(
        party_id=party_id,
        world_id=scope.world_id,
        row_version=version,
        created=False,
        changed=True,
        changed_fields=dict(changed),
        lifecycle_status=party.lifecycle_status,
    )


def _transition(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    party_id: uuid.UUID,
    expected_row_version: int,
    to_status: str,
) -> PartyResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    party = lock_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)
    if party.row_version != expected_row_version:
        raise StaleWriteError(f"party {party_id} is at {party.row_version}")
    if to_status == PARTY_ARCHIVED and party.lifecycle_status != PARTY_ACTIVE:
        raise PartyNotActiveError(f"party {party_id} is {party.lifecycle_status}")
    if to_status == PARTY_ACTIVE and party.lifecycle_status != PARTY_ARCHIVED:
        raise PartyNotArchivedError(f"party {party_id} is {party.lifecycle_status}")
    version = connection.execute(
        text("""
            UPDATE campaign.parties
            SET lifecycle_status_id = :s,
                archived_at = CASE WHEN :archived THEN now() ELSE NULL END
            WHERE party_id = :p RETURNING row_version
        """),
        {
            "s": lookup_id(
                connection, "core", "lifecycle_statuses", "lifecycle_status_id", to_status
            ),
            "archived": to_status == PARTY_ARCHIVED,
            "p": party_id,
        },
    ).scalar()
    assert isinstance(version, int)
    return PartyResult(
        party_id=party_id,
        world_id=scope.world_id,
        row_version=version,
        created=False,
        changed=True,
        changed_fields={},
        lifecycle_status=to_status,
        previous_lifecycle_status=party.lifecycle_status,
    )


def archive_party(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    party_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> PartyResult:
    normalize_reason(reason)
    return _transition(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        party_id=party_id,
        expected_row_version=expected_row_version,
        to_status=PARTY_ARCHIVED,
    )


def restore_party(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    party_id: uuid.UUID,
    expected_row_version: int,
    reason: str,
) -> PartyResult:
    normalize_reason(reason, required=True)
    return _transition(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        party_id=party_id,
        expected_row_version=expected_row_version,
        to_status=PARTY_ACTIVE,
    )
