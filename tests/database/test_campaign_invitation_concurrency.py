"""Real PostgreSQL concurrency regression coverage for campaign invitations.

Covers the two same-row races the Phase 13E-B invitation-management
checkpoint adds:

1. revoke vs accept on the identical invitation row;
2. revoke vs revoke on the identical invitation row.

Every scenario uses separate real connections and PostgreSQL row locks,
never a mocked delay. The command layer owns the lock behavior; the audit
assertion in the revoke-vs-revoke case mirrors the API route's own
`result.revoked` guard by conditionally writing a `change_log` row in the
same shape the route uses.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.campaign_invitations import (
    InvitationNotAcceptableError,
    InvitationNotRevocableError,
    accept_campaign_invitation,
    create_campaign_invitation,
    revoke_campaign_invitation,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

_UPDATED_ACTION = "updated"
_REVOKE_COMMAND_NAME = "revoke_campaign_invitation"


class _InvitationFixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection,
            self.timeline_id,
            "Invitation Race Campaign",
            lifecycle_status_code="pending",
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)

        self.manager_user_id = make_user(connection, "Invitation Race Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.manager_user_id
        )
        from tests.factories import make_membership_role

        make_membership_role(connection, self.manager_membership_id, manager_role_id)

        self.accepting_user_id = make_user(connection, "Invitation Race Accepting User")


def _cleanup_invitation_fixture(
    engine: Engine, timeline_id: uuid.UUID, world_id: uuid.UUID
) -> None:
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(text("DELETE FROM audit.change_log WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text(
                "DELETE FROM security.campaign_invitations WHERE campaign_id IN ("
                "    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t"
                ")"
            ),
            {"t": timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.membership_roles WHERE campaign_membership_id IN ("
                "    SELECT campaign_membership_id FROM security.campaign_memberships "
                "    WHERE campaign_id IN (SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
                ")"
            ),
            {"t": timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.role_capabilities WHERE role_id IN ("
                "    SELECT role_id FROM security.roles WHERE campaign_id IN ("
                "        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t"
                "    )"
                ")"
            ),
            {"t": timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.roles WHERE campaign_id IN ("
                "    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t"
                ")"
            ),
            {"t": timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.campaign_memberships WHERE campaign_id IN ("
                "    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t"
                ")"
            ),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"), {"t": timeline_id}
        )
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE timeline_id = :t"), {"t": timeline_id}
        )
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})


def test_revoke_then_accept_of_the_same_invitation_serialize_and_leave_no_membership(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-invitation-revoke-accept-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _InvitationFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        result = create_campaign_invitation(
            setup,
            campaign_id=rf.campaign_id,
            invited_by_membership_id=rf.manager_membership_id,
        )
        invitation_id = result.campaign_invitation_id
        raw_token = result.token

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            revoke_campaign_invitation(
                first,
                campaign_id=rf.campaign_id,
                campaign_invitation_id=invitation_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                accept_campaign_invitation(
                    second,
                    token=raw_token,
                    accepting_user_id=rf.accepting_user_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected accept to block on revoke's FOR UPDATE lock, got: {message}"
            )
            second.rollback()
            first.commit()

        with engine.begin() as third, pytest.raises(InvitationNotAcceptableError):
            accept_campaign_invitation(
                third,
                token=raw_token,
                accepting_user_id=rf.accepting_user_id,
            )

        with engine.connect() as verify:
            membership_count = verify.execute(
                text(
                    "SELECT count(*) FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id = :u"
                ),
                {"c": rf.campaign_id, "u": rf.accepting_user_id},
            ).scalar_one()
            assert membership_count == 0
    finally:
        _cleanup_invitation_fixture(engine, timeline_id, world_id)


def test_accept_then_revoke_of_the_same_invitation_serialize_and_keep_membership(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-invitation-accept-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _InvitationFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        result = create_campaign_invitation(
            setup,
            campaign_id=rf.campaign_id,
            invited_by_membership_id=rf.manager_membership_id,
        )
        invitation_id = result.campaign_invitation_id
        raw_token = result.token

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            accepted = accept_campaign_invitation(
                first,
                token=raw_token,
                accepting_user_id=rf.accepting_user_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                revoke_campaign_invitation(
                    second,
                    campaign_id=rf.campaign_id,
                    campaign_invitation_id=invitation_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected revoke to block on accept's FOR UPDATE lock, got: {message}"
            )
            second.rollback()
            first.commit()

        with engine.begin() as third, pytest.raises(InvitationNotRevocableError):
            revoke_campaign_invitation(
                third,
                campaign_id=rf.campaign_id,
                campaign_invitation_id=invitation_id,
            )

        with engine.connect() as verify:
            membership_row = verify.execute(
                text(
                    "SELECT campaign_membership_id, ended_at FROM security.campaign_memberships "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": accepted.campaign_membership_id},
            ).one()
            assert membership_row.ended_at is None
    finally:
        _cleanup_invitation_fixture(engine, timeline_id, world_id)


def test_two_concurrent_revokes_of_the_same_invitation_serialize_and_produce_one_audit_worthy_change(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-invitation-revoke-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _InvitationFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        invitation_id = create_campaign_invitation(
            setup,
            campaign_id=rf.campaign_id,
            invited_by_membership_id=rf.manager_membership_id,
        ).campaign_invitation_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            first_result = revoke_campaign_invitation(
                first,
                campaign_id=rf.campaign_id,
                campaign_invitation_id=invitation_id,
            )
            assert first_result.revoked is True
            record_change_log(
                first,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="campaign_invitations",
                record_id=invitation_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.manager_user_id,
                correlation_id=None,
                command_name=_REVOKE_COMMAND_NAME,
                event_id=None,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                revoke_campaign_invitation(
                    second,
                    campaign_id=rf.campaign_id,
                    campaign_invitation_id=invitation_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the second revoke to block on the shared invitation row, got: {message}"
            )
            second.rollback()
            first.commit()

        with engine.begin() as third:
            third_result = revoke_campaign_invitation(
                third,
                campaign_id=rf.campaign_id,
                campaign_invitation_id=invitation_id,
            )
            assert third_result.revoked is False
            if third_result.revoked:
                record_change_log(
                    third,
                    change_action_code=_UPDATED_ACTION,
                    schema_name="security",
                    table_name="campaign_invitations",
                    record_id=invitation_id,
                    entity_id=None,
                    world_id=rf.world_id,
                    actor_user_id=rf.manager_user_id,
                    correlation_id=None,
                    command_name=_REVOKE_COMMAND_NAME,
                    event_id=None,
                )

        with engine.connect() as verify:
            audit_count = verify.execute(
                text(
                    "SELECT count(*) FROM audit.change_log "
                    "WHERE table_name = 'campaign_invitations' "
                    "AND record_id = :i AND command_name = :command"
                ),
                {"i": invitation_id, "command": _REVOKE_COMMAND_NAME},
            ).scalar_one()
            assert audit_count == 1
    finally:
        _cleanup_invitation_fixture(engine, timeline_id, world_id)
