"""Character revelations: create and revoke (P03-A slice A3a, plan section 10).

A revelation makes one character discoverable, and its latest public-profile release readable, to
one audience in one campaign: a member, an access group, the campaign's current members (a snapshot)
or its current and future members. A3a stores revelations and nothing reads them yet.

Authority is `character.reveal` (an owner, or a GM holding a live delegation), re-judged at a fresh
database instant after the last lock wait, and a whole-character deny refuses the caller outright
(404). A `canon.edit` deny does not: revealing is not editing.

**Lock order** (plan section 10.4). The route has already taken the idempotency key lock (step 0)
when a key was given. Then: the caller's authority rows `FOR SHARE`; a group target `FOR KEY SHARE`;
the caller's membership `FOR SHARE`; a member target `FOR KEY SHARE`; for `campaign_current`, every
open membership of the campaign `FOR KEY SHARE` by id (step 4a: the candidate set, and the D9-a
cutoff is the start of that statement); the campaign `FOR KEY SHARE`; the caller's account
`FOR KEY SHARE`; the character's entity row `FOR KEY SHARE`. Only then are authority and the
whole-character deny judged, and only then does `reserve()` run the idempotency reservation or
replay lookup, so a caller who lost authority is never handed a stored receipt and the reservation
cannot wait on anything.

No lock-taking read joins a status table (DEF-017): statuses are read in separate statements.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import CampaignArchivedError, CampaignNotAuthorizedError
from dnd_ai.domain.public_profiles import (
    AUDIENCE_ACCESS_GROUP,
    AUDIENCE_CAMPAIGN_CURRENT,
    AUDIENCE_CAMPAIGN_CURRENT_AND_FUTURE,
    AUDIENCE_KINDS,
    AUDIENCE_MEMBER,
    AUTHORITY_DELEGATION,
    AUTHORITY_OWNER,
    END_REASON_REVOKED,
    REVELATION_REASON_MAX_LENGTH,
    CharacterRevealRequiredError,
    PublicProfileNotFoundError,
    PublicProfileNotReleasedError,
    RevelationTargetNotActiveError,
    whole_character_denied,
)
from dnd_ai.domain.reveal_authority import resolve_reveal_authority

from ._shared import lifecycle_code
from .character_public_profile import (
    _character_row,
    _database_clock,
    _require_canon_and_active,
    _resolve_membership_access,
)


class InvalidRevelationRequestError(ValueError):
    """A body whose target shape does not match its audience kind, or an unknown kind. The API
    layer maps it to 422."""


@dataclass(frozen=True)
class CreateCharacterRevelationResult:
    character_revelation_id: uuid.UUID
    created: bool
    audience_kind: str
    audience_size: int
    authority_source_code: str


@dataclass(frozen=True)
class RevokeCharacterRevelationResult:
    character_revelation_id: uuid.UUID
    revoked: bool


def validate_revelation_shape(
    *,
    audience_kind: str,
    target_campaign_membership_id: uuid.UUID | None,
    target_access_group_id: uuid.UUID | None,
    reason: str,
) -> None:
    """The kind/target pairing and the reason's length, before any database work."""
    if audience_kind not in AUDIENCE_KINDS:
        raise InvalidRevelationRequestError("unknown audience kind")
    wants_member = audience_kind == AUDIENCE_MEMBER
    wants_group = audience_kind == AUDIENCE_ACCESS_GROUP
    if wants_member != (target_campaign_membership_id is not None) or wants_group != (
        target_access_group_id is not None
    ):
        raise InvalidRevelationRequestError("the target does not match the audience kind")
    if not 1 <= len(reason) <= REVELATION_REASON_MAX_LENGTH:
        raise InvalidRevelationRequestError("the reason must be 1 to 1000 characters")


def _campaign_world_id(connection: Connection, campaign_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("""
            SELECT t.world_id FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = :campaign
        """),
        {"campaign": campaign_id},
    ).scalar()
    if world_id is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
    return world_id


def _lock_caller_and_campaign(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    group_id: uuid.UUID | None,
    member_target_id: uuid.UUID | None,
    snapshot_candidates: bool,
) -> tuple[str, list[uuid.UUID]]:
    """Steps 1 to 5a. Returns the locked authority source and the step 4a candidate ids."""
    source = resolve_reveal_authority(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=actor_membership_id,
        lock="share",
    )
    if source == "none":
        raise CharacterRevealRequiredError(f"membership {actor_membership_id} cannot reveal")

    if group_id is not None:
        group_campaign = connection.execute(
            text(
                "SELECT campaign_id FROM security.access_groups "
                "WHERE access_group_id = :group FOR KEY SHARE"
            ),
            {"group": group_id},
        ).scalar()
        if group_campaign != campaign_id:
            raise PublicProfileNotFoundError(f"group {group_id} is not in this campaign")

    caller_user = connection.execute(
        text(
            "SELECT user_id FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :membership FOR SHARE"
        ),
        {"membership": actor_membership_id},
    ).scalar()
    if caller_user is None:
        raise CampaignNotAuthorizedError(f"membership {actor_membership_id} does not exist")

    if member_target_id is not None:
        target_campaign = connection.execute(
            text(
                "SELECT campaign_id FROM security.campaign_memberships "
                "WHERE campaign_membership_id = :target FOR KEY SHARE"
            ),
            {"target": member_target_id},
        ).scalar()
        if target_campaign != campaign_id:
            raise PublicProfileNotFoundError(
                f"membership {member_target_id} is not in this campaign"
            )

    candidates: list[uuid.UUID] = []
    if snapshot_candidates:
        # Step 4a. The D9-a cutoff: a membership is a candidate exactly when this statement returns
        # it, so one whose end is in flight is waited for here, and a join that commits after the
        # statement starts is excluded. No join: statuses are read at step 11.
        candidates = list(
            connection.execute(
                text("""
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id = :campaign AND ended_at IS NULL
                    ORDER BY campaign_membership_id
                    FOR KEY SHARE
                """),
                {"campaign": campaign_id},
            ).scalars()
        )

    campaign = connection.execute(
        text(
            "SELECT lifecycle_status_id FROM campaign.campaigns "
            "WHERE campaign_id = :campaign FOR KEY SHARE"
        ),
        {"campaign": campaign_id},
    ).one_or_none()
    if campaign is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")
    if lifecycle_code(connection, campaign.lifecycle_status_id) != "active":
        raise CampaignArchivedError(f"campaign {campaign_id} is not active")
    # Step 5a: the caller's account, after the campaign row (plan section 10.4).
    connection.execute(
        text("SELECT 1 FROM security.users WHERE user_id = :user FOR KEY SHARE"),
        {"user": caller_user},
    ).all()
    return source, candidates


def _judge_caller(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    source: str,
) -> None:
    """Steps 7 and 8: authority at a fresh instant (the same source the locked read found), then
    the whole-character deny. Every wait is behind us."""
    fresh = resolve_reveal_authority(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=actor_membership_id,
        as_of=_database_clock(connection),
    )
    if fresh != source:
        raise CharacterRevealRequiredError(f"membership {actor_membership_id} cannot reveal now")
    access = _resolve_membership_access(connection, campaign_id, actor_membership_id)
    if whole_character_denied(access, character_id):
        raise PublicProfileNotFoundError(f"character {character_id} is not visible")


def _delegation_id(
    connection: Connection, *, campaign_id: uuid.UUID, membership_id: uuid.UUID
) -> uuid.UUID:
    value = connection.execute(
        text("""
            SELECT character_reveal_delegation_id
            FROM security.character_reveal_delegations
            WHERE campaign_id = :campaign AND grantee_campaign_membership_id = :membership
              AND revoked_at IS NULL
        """),
        {"campaign": campaign_id, "membership": membership_id},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def create_character_revelation(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    audience_kind: str,
    target_campaign_membership_id: uuid.UUID | None,
    target_access_group_id: uuid.UUID | None,
    reason: str,
    reserve: Callable[[], bool],
) -> CreateCharacterRevelationResult | None:
    """Creates the revelation, or returns the existing live one (`created=False`).

    `reserve()` is called once, at step 8a, after the locks and the fresh authority and deny checks.
    It runs the idempotency reservation or replay lookup and returns True when the stored response
    must be returned instead; the command then returns None and writes nothing."""
    validate_revelation_shape(
        audience_kind=audience_kind,
        target_campaign_membership_id=target_campaign_membership_id,
        target_access_group_id=target_access_group_id,
        reason=reason,
    )
    world_id = _campaign_world_id(connection, campaign_id)
    source, candidates = _lock_caller_and_campaign(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        group_id=target_access_group_id,
        member_target_id=target_campaign_membership_id,
        snapshot_candidates=audience_kind == AUDIENCE_CAMPAIGN_CURRENT,
    )
    character = _character_row(
        connection, world_id=world_id, character_id=character_id, lock_clause="FOR KEY SHARE"
    )
    _judge_caller(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        actor_membership_id=actor_membership_id,
        source=source,
    )

    if reserve():  # step 8a
        return None

    _require_canon_and_active(character, character_id)
    released = connection.execute(
        text("""
            SELECT 1 FROM campaign.character_public_profile_releases
            WHERE campaign_id = :campaign AND character_id = :character LIMIT 1
        """),
        {"campaign": campaign_id, "character": character_id},
    ).first()
    if released is None:
        raise PublicProfileNotReleasedError(f"{character_id} has no release in this campaign")

    if target_campaign_membership_id is not None:
        _require_active_open_membership(connection, target_campaign_membership_id)
    if target_access_group_id is not None:
        group_status = connection.execute(
            text(
                "SELECT lifecycle_status_id FROM security.access_groups WHERE access_group_id = :g"
            ),
            {"g": target_access_group_id},
        ).scalar_one()
        if lifecycle_code(connection, group_status) != "active":
            raise RevelationTargetNotActiveError(f"group {target_access_group_id} is archived")

    kind_id = connection.execute(
        text(
            "SELECT revelation_audience_kind_id FROM security.revelation_audience_kinds "
            "WHERE code = :code"
        ),
        {"code": audience_kind},
    ).scalar_one()
    existing = _live_revelation(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        kind_id=kind_id,
        target_campaign_membership_id=target_campaign_membership_id,
        target_access_group_id=target_access_group_id,
    )
    if existing is not None:
        return CreateCharacterRevelationResult(
            character_revelation_id=existing,
            created=False,
            audience_kind=audience_kind,
            audience_size=_audience_size(connection, existing, audience_kind, campaign_id),
            authority_source_code=source,
        )

    snapshot: list[uuid.UUID] = []
    if audience_kind == AUDIENCE_CAMPAIGN_CURRENT and candidates:
        # Step 11: the candidates that are `active` now.
        snapshot = list(
            connection.execute(
                text("""
                    SELECT cm.campaign_membership_id
                    FROM security.campaign_memberships cm
                    JOIN security.membership_statuses ms
                        ON ms.membership_status_id = cm.membership_status_id
                    WHERE cm.campaign_membership_id = ANY(:ids) AND ms.code = 'active'
                    ORDER BY cm.campaign_membership_id
                """),
                {"ids": candidates},
            ).scalars()
        )

    authority_code = AUTHORITY_OWNER if source == "owner" else AUTHORITY_DELEGATION
    delegation = (
        _delegation_id(connection, campaign_id=campaign_id, membership_id=actor_membership_id)
        if source == "delegation"
        else None
    )
    revelation_id = connection.execute(
        text("""
            INSERT INTO security.character_revelations (
                campaign_id, character_id, revelation_audience_kind_id,
                target_campaign_membership_id, target_access_group_id,
                created_by_membership_id, authority_source_code,
                character_reveal_delegation_id, reason
            )
            VALUES (:campaign, :character, :kind, :member, :group, :creator, :source,
                    :delegation, :reason)
            ON CONFLICT (campaign_id, character_id, revelation_audience_kind_id,
                         target_campaign_membership_id, target_access_group_id)
                WHERE ended_at IS NULL
            DO NOTHING
            RETURNING character_revelation_id
        """),
        {
            "campaign": campaign_id,
            "character": character_id,
            "kind": kind_id,
            "member": target_campaign_membership_id,
            "group": target_access_group_id,
            "creator": actor_membership_id,
            "source": authority_code,
            "delegation": delegation,
            "reason": reason,
        },
    ).scalar()
    if revelation_id is None:
        # A concurrent first creation committed between step 10 and here: a natural retry.
        winner = _live_revelation(
            connection,
            campaign_id=campaign_id,
            character_id=character_id,
            kind_id=kind_id,
            target_campaign_membership_id=target_campaign_membership_id,
            target_access_group_id=target_access_group_id,
        )
        assert winner is not None
        return CreateCharacterRevelationResult(
            character_revelation_id=winner,
            created=False,
            audience_kind=audience_kind,
            audience_size=_audience_size(connection, winner, audience_kind, campaign_id),
            authority_source_code=source,
        )
    assert isinstance(revelation_id, uuid.UUID)
    for membership_id in snapshot:
        connection.execute(
            text("""
                INSERT INTO security.character_revelation_members
                    (character_revelation_id, campaign_id, campaign_membership_id)
                VALUES (:revelation, :campaign, :membership)
            """),
            {"revelation": revelation_id, "campaign": campaign_id, "membership": membership_id},
        )
    return CreateCharacterRevelationResult(
        character_revelation_id=revelation_id,
        created=True,
        audience_kind=audience_kind,
        audience_size=_audience_size(connection, revelation_id, audience_kind, campaign_id),
        authority_source_code=source,
    )


def _require_active_open_membership(connection: Connection, membership_id: uuid.UUID) -> None:
    """The target is open and its status is `active`, read in separate statements."""
    row = connection.execute(
        text(
            "SELECT ended_at, membership_status_id FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :id"
        ),
        {"id": membership_id},
    ).one()
    status = connection.execute(
        text("SELECT code FROM security.membership_statuses WHERE membership_status_id = :status"),
        {"status": row.membership_status_id},
    ).scalar()
    if row.ended_at is not None or status != "active":
        raise RevelationTargetNotActiveError(f"membership {membership_id} is not active")


def _live_revelation(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    kind_id: uuid.UUID,
    target_campaign_membership_id: uuid.UUID | None,
    target_access_group_id: uuid.UUID | None,
) -> uuid.UUID | None:
    value = connection.execute(
        text("""
            SELECT character_revelation_id FROM security.character_revelations
            WHERE campaign_id = :campaign AND character_id = :character
              AND revelation_audience_kind_id = :kind
              AND target_campaign_membership_id IS NOT DISTINCT FROM :member
              AND target_access_group_id IS NOT DISTINCT FROM :group
              AND ended_at IS NULL
        """),
        {
            "campaign": campaign_id,
            "character": character_id,
            "kind": kind_id,
            "member": target_campaign_membership_id,
            "group": target_access_group_id,
        },
    ).scalar()
    return value if isinstance(value, uuid.UUID) else None


def _audience_size(
    connection: Connection,
    revelation_id: uuid.UUID,
    audience_kind: str,
    campaign_id: uuid.UUID,
) -> int:
    """Members the revelation reaches now: 1 for a member, the live group members, the unremoved
    snapshot rows, or every open active membership."""
    if audience_kind == AUDIENCE_MEMBER:
        return 1
    if audience_kind == AUDIENCE_ACCESS_GROUP:
        sql = """
            SELECT count(*) FROM security.access_group_memberships agm
            JOIN security.character_revelations r
                ON r.target_access_group_id = agm.access_group_id
            WHERE r.character_revelation_id = :r AND agm.removed_at IS NULL
        """
    elif audience_kind == AUDIENCE_CAMPAIGN_CURRENT:
        sql = """
            SELECT count(*) FROM security.character_revelation_members
            WHERE character_revelation_id = :r AND removed_at IS NULL
        """
    else:
        assert audience_kind == AUDIENCE_CAMPAIGN_CURRENT_AND_FUTURE
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM security.campaign_memberships cm
                    JOIN security.membership_statuses ms
                        ON ms.membership_status_id = cm.membership_status_id
                    WHERE cm.campaign_id = :c AND cm.ended_at IS NULL AND ms.code = 'active'
                """),
                {"c": campaign_id},
            ).scalar_one()
        )
    return int(connection.execute(text(sql), {"r": revelation_id}).scalar_one())


def revoke_character_revelation(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    character_revelation_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    reason: str,
    reserve: Callable[[], bool],
) -> RevokeCharacterRevelationResult | None:
    """Closes the revelation (`revoked`), or reports `revoked=False` for one already closed.
    Authority and the whole-character deny are re-judged under the same locks as a create, and
    `reserve()` runs after them (None return: the stored response is to be replayed)."""
    if not 1 <= len(reason) <= REVELATION_REASON_MAX_LENGTH:
        raise InvalidRevelationRequestError("the reason must be 1 to 1000 characters")
    source, _ = _lock_caller_and_campaign(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        group_id=None,
        member_target_id=None,
        snapshot_candidates=False,
    )
    row = connection.execute(
        text("""
            SELECT ended_at FROM security.character_revelations
            WHERE character_revelation_id = :id AND campaign_id = :campaign
              AND character_id = :character
            FOR UPDATE
        """),
        {"id": character_revelation_id, "campaign": campaign_id, "character": character_id},
    ).one_or_none()
    # Authority and the deny come before "not found", so a caller who may not know is never told
    # whether a revelation exists.
    _judge_caller(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        actor_membership_id=actor_membership_id,
        source=source,
    )
    if row is None:
        raise PublicProfileNotFoundError(f"revelation {character_revelation_id} not found")

    if reserve():
        return None

    if row.ended_at is not None:
        return RevokeCharacterRevelationResult(character_revelation_id, revoked=False)
    closed_at: datetime = _database_clock(connection)
    connection.execute(
        text("""
            UPDATE security.character_revelations
            SET ended_at = :closed_at, ended_by_membership_id = :actor,
                end_reason = :end_reason, revocation_reason = :reason
            WHERE character_revelation_id = :id
        """),
        {
            "closed_at": closed_at,
            "actor": actor_membership_id,
            "end_reason": END_REASON_REVOKED,
            "reason": reason,
            "id": character_revelation_id,
        },
    )
    return RevokeCharacterRevelationResult(character_revelation_id, revoked=True)


def close_member_revelations_for_ended_membership(
    connection: Connection, *, campaign_membership_id: uuid.UUID, closed_at: datetime
) -> tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]:
    """Called by `end_campaign_membership` after it holds the campaign row. Closes the live
    revelations that target this membership (`target_membership_ended`) and sets `removed_at` on
    its unremoved snapshot rows (`membership_ended`), so a reopened membership regains neither.
    Returns (closed revelation ids, removed snapshot row ids)."""
    closed = tuple(
        connection.execute(
            text("""
                UPDATE security.character_revelations
                SET ended_at = GREATEST(:closed_at, created_at),
                    end_reason = 'target_membership_ended'
                WHERE target_campaign_membership_id = :membership AND ended_at IS NULL
                RETURNING character_revelation_id
            """),
            {"membership": campaign_membership_id, "closed_at": closed_at},
        )
        .scalars()
        .all()
    )
    removed = tuple(
        connection.execute(
            text("""
                UPDATE security.character_revelation_members
                SET removed_at = :closed_at, removal_reason = 'membership_ended'
                WHERE campaign_membership_id = :membership AND removed_at IS NULL
                RETURNING character_revelation_member_id
            """),
            {"membership": campaign_membership_id, "closed_at": closed_at},
        )
        .scalars()
        .all()
    )
    return closed, removed


def close_group_revelations_for_deactivated_group(
    connection: Connection, *, access_group_id: uuid.UUID
) -> tuple[uuid.UUID, ...]:
    """Called by `deactivate_access_group` after its grant revocations: closes the group's live
    revelations (`access_group_deactivated`). A reactivated group does not restore them."""
    return tuple(
        connection.execute(
            text("""
                UPDATE security.character_revelations
                SET ended_at = GREATEST(clock_timestamp(), created_at),
                    end_reason = 'access_group_deactivated'
                WHERE target_access_group_id = :group AND ended_at IS NULL
                RETURNING character_revelation_id
            """),
            {"group": access_group_id},
        )
        .scalars()
        .all()
    )
