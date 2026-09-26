"""World-ownership-scope invariants (ADR 0014,
docs/architecture/DATABASE_MODEL.md §19.9): `dnd_ai.commands.ownership` and
`dnd_ai.domain.access.is_world_administrator`, plus the database
constraints backing them (per-scope slug uniqueness, `ownership_scope_id
NOT NULL`).

Deliberately proves ownership is independent of every other authorization
primitive in this codebase — campaign membership/roles
(`security.campaign_memberships`/`.roles`) and
`security.users.is_platform_administrator` — never combined with it, in
either direction.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.ownership import (
    AlreadyClaimedOwnershipScopeError,
    LastActiveOwnerError,
    OwnershipScopeMembershipNotFoundError,
    OwnershipScopeNotAuthorizedError,
    add_ownership_scope_member,
    claim_unclaimed_ownership_scope,
    create_ownership_scope,
    remove_ownership_scope_member,
)
from dnd_ai.domain.access import is_world_administrator
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_ownership_scope,
    make_ownership_scope_membership,
    make_platform_administrator,
    make_role,
    make_timeline,
    make_user,
    make_world,
    status_id,
)

pytestmark = pytest.mark.database


def _backdate_joined_at(connection: Connection, ownership_scope_membership_id: uuid.UUID) -> None:
    """`now()` is transaction-start time in PostgreSQL, so a plain `now()` in
    `remove_ownership_scope_member`'s `ended_at = now()` would equal
    `joined_at`'s own `now()` from a create/add call earlier in this same
    test transaction and fail `ck_ownership_scope_memberships_ended_after_
    joined` (strictly `>`, not `>=`) — mirrors
    `tests/database/test_security_identity_and_access.py`'s identical
    documented workaround for `security.campaign_memberships`."""
    connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships "
            "SET joined_at = now() - interval '1 second' "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": ownership_scope_membership_id},
    )


def test_world_cannot_exist_without_an_ownership_scope(db_connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO core.worlds (name, slug, lifecycle_status_id)
                VALUES (
                    'No Owner', 'no-owner-world',
                    (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active')
                )
            """)
        )


def test_two_ownership_scopes_may_each_own_a_world_with_the_same_slug(
    db_connection: Connection,
) -> None:
    scope_a = make_ownership_scope(db_connection, "Scope A")
    scope_b = make_ownership_scope(db_connection, "Scope B")

    world_a = make_world(db_connection, "shared-slug", ownership_scope_id=scope_a)
    world_b = make_world(db_connection, "shared-slug", ownership_scope_id=scope_b)

    assert world_a != world_b


def test_two_worlds_in_the_same_ownership_scope_cannot_share_a_slug(
    db_connection: Connection,
) -> None:
    scope = make_ownership_scope(db_connection)
    make_world(db_connection, "duplicate-slug", ownership_scope_id=scope)

    with pytest.raises(IntegrityError):
        make_world(db_connection, "duplicate-slug", ownership_scope_id=scope)


def test_a_user_may_belong_to_multiple_ownership_scopes(db_connection: Connection) -> None:
    user_id = make_user(db_connection)

    result_a = create_ownership_scope(db_connection, name="First Scope", owner_user_id=user_id)
    result_b = create_ownership_scope(db_connection, name="Second Scope", owner_user_id=user_id)

    assert result_a.ownership_scope_id != result_b.ownership_scope_id

    scope_count = db_connection.execute(
        text(
            "SELECT count(*) FROM security.ownership_scope_memberships "
            "WHERE user_id = :user AND ended_at IS NULL"
        ),
        {"user": user_id},
    ).scalar_one()
    assert scope_count == 2


def test_campaign_gm_status_alone_does_not_create_world_ownership(
    db_connection: Connection,
) -> None:
    scope = make_ownership_scope(db_connection)
    world_id = make_world(db_connection, "gm-test-world", ownership_scope_id=scope)
    timeline_id = make_timeline(db_connection, world_id)
    campaign_id = make_campaign(db_connection, timeline_id, lifecycle_status_code="pending")

    gm_user_id = make_user(db_connection, "GM")
    membership_id = make_campaign_membership(db_connection, campaign_id, gm_user_id)
    gm_role_id = make_role(db_connection, campaign_id=campaign_id, code="gm")
    make_membership_role(db_connection, membership_id, gm_role_id)

    assert is_world_administrator(db_connection, world_id=world_id, user_id=gm_user_id) is False


def test_world_ownership_grants_no_campaign_membership(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(db_connection, name="Owner Scope", owner_user_id=owner_user_id)
    world_id = make_world(
        db_connection, "owner-only-world", ownership_scope_id=result.ownership_scope_id
    )

    assert is_world_administrator(db_connection, world_id=world_id, user_id=owner_user_id) is True

    campaign_membership_count = db_connection.execute(
        text("SELECT count(*) FROM security.campaign_memberships WHERE user_id = :user"),
        {"user": owner_user_id},
    ).scalar_one()
    assert campaign_membership_count == 0


def test_platform_administrator_is_not_silently_a_world_owner(db_connection: Connection) -> None:
    admin_user_id = make_platform_administrator(db_connection)
    other_owner_id = make_user(db_connection)
    scope = create_ownership_scope(
        db_connection, name="Admin-Excluded Scope", owner_user_id=other_owner_id
    ).ownership_scope_id
    world_id = make_world(db_connection, "admin-excluded-world", ownership_scope_id=scope)

    assert is_world_administrator(db_connection, world_id=world_id, user_id=admin_user_id) is False
    assert is_world_administrator(db_connection, world_id=world_id, user_id=other_owner_id) is True


def test_revoked_membership_does_not_authorize_ownership_actions(
    db_connection: Connection,
) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(db_connection, name="Two Owners", owner_user_id=owner_user_id)
    second_owner_id = make_user(db_connection)
    added = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=second_owner_id,
        role_code="owner",
        actor_user_id=owner_user_id,
    )
    world_id = make_world(
        db_connection, "revoked-member-world", ownership_scope_id=result.ownership_scope_id
    )

    _backdate_joined_at(db_connection, added.ownership_scope_membership_id)
    remove_ownership_scope_member(
        db_connection,
        ownership_scope_membership_id=added.ownership_scope_membership_id,
        actor_user_id=owner_user_id,
    )

    assert (
        is_world_administrator(db_connection, world_id=world_id, user_id=second_owner_id) is False
    )
    with pytest.raises(OwnershipScopeMembershipNotFoundError):
        remove_ownership_scope_member(
            db_connection,
            ownership_scope_membership_id=added.ownership_scope_membership_id,
            actor_user_id=owner_user_id,
        )


def test_final_active_owner_cannot_be_removed(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(db_connection, name="Sole Owner", owner_user_id=owner_user_id)

    with pytest.raises(LastActiveOwnerError):
        remove_ownership_scope_member(
            db_connection,
            ownership_scope_membership_id=result.ownership_scope_membership_id,
            actor_user_id=owner_user_id,
        )

    # Adding a second owner makes removing the first one safe.
    second_owner_id = make_user(db_connection)
    added = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=second_owner_id,
        role_code="owner",
        actor_user_id=owner_user_id,
    )
    _backdate_joined_at(db_connection, result.ownership_scope_membership_id)
    remove_ownership_scope_member(
        db_connection,
        ownership_scope_membership_id=result.ownership_scope_membership_id,
        actor_user_id=second_owner_id,
    )
    assert (
        is_world_administrator(
            db_connection,
            world_id=make_world(db_connection, ownership_scope_id=result.ownership_scope_id),
            user_id=second_owner_id,
        )
        is True
    )
    assert added.ownership_scope_membership_id != result.ownership_scope_membership_id


def test_ownership_changes_produce_audit_history(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Audited Scope", owner_user_id=owner_user_id
    )

    second_user_id = make_user(db_connection)
    added = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=second_user_id,
        role_code="member",
        actor_user_id=owner_user_id,
    )
    _backdate_joined_at(db_connection, added.ownership_scope_membership_id)
    remove_ownership_scope_member(
        db_connection,
        ownership_scope_membership_id=added.ownership_scope_membership_id,
        actor_user_id=owner_user_id,
    )

    rows = (
        db_connection.execute(
            text("""
                SELECT command_name, record_id, actor_user_id
                FROM audit.change_log
                WHERE record_id IN (:created, :added)
                ORDER BY change_log_id
            """),
            {
                "created": result.ownership_scope_membership_id,
                "added": added.ownership_scope_membership_id,
            },
        )
        .mappings()
        .all()
    )
    command_names = [row["command_name"] for row in rows]
    assert command_names == [
        "create_ownership_scope",
        "add_ownership_scope_member",
        "remove_ownership_scope_member",
    ]
    for row in rows:
        assert row["actor_user_id"] == owner_user_id


def test_cross_owner_world_administration_check_returns_false(db_connection: Connection) -> None:
    scope_a_owner = make_user(db_connection)
    scope_a = create_ownership_scope(
        db_connection, name="Scope A", owner_user_id=scope_a_owner
    ).ownership_scope_id
    scope_b_owner = make_user(db_connection)
    scope_b = create_ownership_scope(
        db_connection, name="Scope B", owner_user_id=scope_b_owner
    ).ownership_scope_id

    world_a = make_world(db_connection, "world-a", ownership_scope_id=scope_a)
    world_b = make_world(db_connection, "world-b", ownership_scope_id=scope_b)

    assert is_world_administrator(db_connection, world_id=world_a, user_id=scope_b_owner) is False
    assert is_world_administrator(db_connection, world_id=world_b, user_id=scope_a_owner) is False
    assert is_world_administrator(db_connection, world_id=world_a, user_id=uuid.uuid4()) is False


def _membership_count(connection: Connection, ownership_scope_id: uuid.UUID) -> int:
    return connection.execute(
        text(
            "SELECT count(*) FROM security.ownership_scope_memberships "
            "WHERE ownership_scope_id = :scope"
        ),
        {"scope": ownership_scope_id},
    ).scalar_one()


def _ownership_audit_count(connection: Connection) -> int:
    return connection.execute(
        text(
            "SELECT count(*) FROM audit.change_log "
            "WHERE command_name IN ("
            "  'create_ownership_scope', 'add_ownership_scope_member', "
            "  'remove_ownership_scope_member', 'claim_unclaimed_ownership_scope'"
            ")"
        )
    ).scalar_one()


def test_outsider_cannot_add_themselves_as_owner(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    scope = create_ownership_scope(
        db_connection, name="Guarded Scope", owner_user_id=owner_user_id
    ).ownership_scope_id
    outsider_id = make_user(db_connection, "Outsider")

    before_members = _membership_count(db_connection, scope)
    before_audit = _ownership_audit_count(db_connection)

    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=scope,
            user_id=outsider_id,
            role_code="owner",
            actor_user_id=outsider_id,
        )

    assert _membership_count(db_connection, scope) == before_members
    assert _ownership_audit_count(db_connection) == before_audit


def test_outsider_cannot_remove_an_existing_member(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Guarded Scope 2", owner_user_id=owner_user_id
    )
    target_id = make_user(db_connection, "Target")
    added = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=target_id,
        role_code="member",
        actor_user_id=owner_user_id,
    )
    outsider_id = make_user(db_connection, "Outsider")

    before_audit = _ownership_audit_count(db_connection)
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        remove_ownership_scope_member(
            db_connection,
            ownership_scope_membership_id=added.ownership_scope_membership_id,
            actor_user_id=outsider_id,
        )
    assert _ownership_audit_count(db_connection) == before_audit

    still_open = db_connection.execute(
        text(
            "SELECT ended_at FROM security.ownership_scope_memberships "
            "WHERE ownership_scope_membership_id = :m"
        ),
        {"m": added.ownership_scope_membership_id},
    ).scalar_one()
    assert still_open is None


def test_member_role_cannot_add_or_remove_members(db_connection: Connection) -> None:
    """`member` is a participant, not an administrator, of the scope — only
    `owner` may manage membership (this module's own documented policy)."""
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Member Role Scope", owner_user_id=owner_user_id
    )
    member_user_id = make_user(db_connection, "Plain Member")
    add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=member_user_id,
        role_code="member",
        actor_user_id=owner_user_id,
    )

    third_user_id = make_user(db_connection, "Third")
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=result.ownership_scope_id,
            user_id=third_user_id,
            role_code="member",
            actor_user_id=member_user_id,
        )


def test_revoked_owner_cannot_perform_further_mutations(db_connection: Connection) -> None:
    owner_a = make_user(db_connection, "Owner A")
    result = create_ownership_scope(
        db_connection, name="Revoked Owner Scope", owner_user_id=owner_a
    )
    owner_b = make_user(db_connection, "Owner B")
    added_b = add_ownership_scope_member(
        db_connection,
        ownership_scope_id=result.ownership_scope_id,
        user_id=owner_b,
        role_code="owner",
        actor_user_id=owner_a,
    )
    _backdate_joined_at(db_connection, result.ownership_scope_membership_id)
    remove_ownership_scope_member(
        db_connection,
        ownership_scope_membership_id=result.ownership_scope_membership_id,
        actor_user_id=owner_b,
    )

    third_user_id = make_user(db_connection, "Third")
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=result.ownership_scope_id,
            user_id=third_user_id,
            role_code="member",
            actor_user_id=owner_a,
        )
    assert added_b.ownership_scope_membership_id is not None


def test_archived_scope_owner_cannot_manage_membership(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Archived Scope", owner_user_id=owner_user_id
    )
    db_connection.execute(
        text(
            "UPDATE security.ownership_scopes SET lifecycle_status_id = :s "
            "WHERE ownership_scope_id = :scope"
        ),
        {
            "s": status_id(db_connection, "lifecycle_statuses", "archived"),
            "scope": result.ownership_scope_id,
        },
    )

    target_id = make_user(db_connection, "Target")
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=result.ownership_scope_id,
            user_id=target_id,
            role_code="member",
            actor_user_id=owner_user_id,
        )


def test_deactivated_owner_role_lookup_does_not_authorize(db_connection: Connection) -> None:
    """An `ownership_scope_roles` row with `code = 'owner'` but
    `is_active = false` must not authorize — mirrors `security.
    campaign_has_access_manager()`'s identical `is_active` requirement on
    its own lookups."""
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Deactivated Role Scope", owner_user_id=owner_user_id
    )
    db_connection.execute(
        text("UPDATE security.ownership_scope_roles SET is_active = false WHERE code = 'owner'")
    )

    target_id = make_user(db_connection, "Target")
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=result.ownership_scope_id,
            user_id=target_id,
            role_code="member",
            actor_user_id=owner_user_id,
        )


def test_deactivated_active_membership_status_lookup_does_not_authorize(
    db_connection: Connection,
) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Deactivated Status Scope", owner_user_id=owner_user_id
    )
    db_connection.execute(
        text("UPDATE security.membership_statuses SET is_active = false WHERE code = 'active'")
    )

    target_id = make_user(db_connection, "Target")
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=result.ownership_scope_id,
            user_id=target_id,
            role_code="member",
            actor_user_id=owner_user_id,
        )


def test_owner_of_one_scope_cannot_manage_a_different_scope(db_connection: Connection) -> None:
    """Non-disclosing cross-scope failure: an owner of scope A gets the
    same exception attempting to act on scope B as an outsider would —
    the caller cannot tell "wrong scope" from "scope doesn't exist"."""
    owner_a = make_user(db_connection, "Owner A")
    create_ownership_scope(db_connection, name="Scope A", owner_user_id=owner_a)
    owner_b = make_user(db_connection, "Owner B")
    scope_b = create_ownership_scope(
        db_connection, name="Scope B", owner_user_id=owner_b
    ).ownership_scope_id

    target_id = make_user(db_connection, "Target")
    with pytest.raises(OwnershipScopeNotAuthorizedError) as exc_cross_scope:
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=scope_b,
            user_id=target_id,
            role_code="member",
            actor_user_id=owner_a,
        )

    with pytest.raises(OwnershipScopeNotAuthorizedError) as exc_nonexistent:
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=uuid.uuid4(),
            user_id=target_id,
            role_code="member",
            actor_user_id=owner_a,
        )

    assert exc_cross_scope.value.safe_message == exc_nonexistent.value.safe_message


def test_campaign_gm_cannot_manage_ownership_scope_membership(db_connection: Connection) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="GM-Guarded Scope", owner_user_id=owner_user_id
    )
    world_id = make_world(
        db_connection, "gm-guard-world", ownership_scope_id=result.ownership_scope_id
    )
    timeline_id = make_timeline(db_connection, world_id)
    campaign_id = make_campaign(db_connection, timeline_id, lifecycle_status_code="pending")

    gm_user_id = make_user(db_connection, "GM")
    membership_id = make_campaign_membership(db_connection, campaign_id, gm_user_id)
    gm_role_id = make_role(db_connection, campaign_id=campaign_id, code="gm")
    make_membership_role(db_connection, membership_id, gm_role_id)

    target_id = make_user(db_connection, "Target")
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=result.ownership_scope_id,
            user_id=target_id,
            role_code="member",
            actor_user_id=gm_user_id,
        )


def test_platform_administrator_cannot_manage_ownership_scope_membership(
    db_connection: Connection,
) -> None:
    owner_user_id = make_user(db_connection)
    result = create_ownership_scope(
        db_connection, name="Admin-Guarded Scope", owner_user_id=owner_user_id
    )
    admin_user_id = make_platform_administrator(db_connection)

    target_id = make_user(db_connection, "Target")
    with pytest.raises(OwnershipScopeNotAuthorizedError):
        add_ownership_scope_member(
            db_connection,
            ownership_scope_id=result.ownership_scope_id,
            user_id=target_id,
            role_code="member",
            actor_user_id=admin_user_id,
        )


def test_claim_unclaimed_ownership_scope_bootstrap_path(db_connection: Connection) -> None:
    """The narrow, unauthorized bootstrap path — only usable while the
    scope has zero membership rows of any status — and never again once
    it has been claimed."""
    scope = make_ownership_scope(db_connection, "Bootstrap Scope")
    claimant_id = make_user(db_connection, "Claimant")

    before_audit = _ownership_audit_count(db_connection)
    result = claim_unclaimed_ownership_scope(
        db_connection, ownership_scope_id=scope, user_id=claimant_id
    )
    assert _ownership_audit_count(db_connection) == before_audit + 1
    assert (
        is_world_administrator(
            db_connection,
            world_id=make_world(db_connection, ownership_scope_id=scope),
            user_id=claimant_id,
        )
        is True
    )

    second_claimant_id = make_user(db_connection, "Second Claimant")
    with pytest.raises(AlreadyClaimedOwnershipScopeError):
        claim_unclaimed_ownership_scope(
            db_connection, ownership_scope_id=scope, user_id=second_claimant_id
        )
    assert result.ownership_scope_membership_id is not None


def test_claim_unclaimed_ownership_scope_refuses_a_scope_with_only_revoked_history(
    db_connection: Connection,
) -> None:
    """A scope that once had a membership — even a since-revoked one — has
    been administered before and must never be reclaimed through the
    unauthorized bootstrap path again."""
    scope = make_ownership_scope(db_connection, "Once Claimed Scope")
    former_user_id = make_user(db_connection, "Former")
    make_ownership_scope_membership(db_connection, scope, former_user_id, ended=True)

    claimant_id = make_user(db_connection, "New Claimant")
    with pytest.raises(AlreadyClaimedOwnershipScopeError):
        claim_unclaimed_ownership_scope(
            db_connection, ownership_scope_id=scope, user_id=claimant_id
        )
