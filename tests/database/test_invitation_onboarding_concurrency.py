"""Real PostgreSQL concurrency regression coverage for single-link
invitation onboarding (Phase 13E checkpoint 8a, P-1).

`begin_invitation_onboarding` deliberately takes no lock on the invitation
row (a read-only validation); `complete_invitation_onboarding` and
`_register_invited_local_account_impl` lock both the onboarding-session
row and the invitation row `FOR UPDATE` before writing. This file proves
the two required outcomes from `PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md`
§8.2's race table using real independent connections and real PostgreSQL
row locks, never a mocked delay:

1. accept (via `complete`) vs. revoke of the same invitation serialize on
   the invitation row, and whichever commits first wins.
2. register vs. revoke of the same invitation serialize identically, and a
   losing registration rolls back entirely (zero new `security.users`
   rows) rather than leaving an orphan account with no accepted invitation.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.campaign_invitations import (
    InvitationNotRevocableError,
    create_campaign_invitation,
    revoke_campaign_invitation,
)
from dnd_ai.commands.invitation_onboarding import (
    OnboardingNotAvailableError,
    begin_invitation_onboarding,
    complete_invitation_onboarding,
)
from dnd_ai.commands.local_auth import _register_invited_local_account_impl
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

_VALID_PASSWORD = "correct-onboarding-password-15"


class _OnboardingRaceFixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection,
            self.timeline_id,
            "Onboarding Race Campaign",
            lifecycle_status_code="pending",
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)
        self.manager_user_id = make_user(connection, "Onboarding Race Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.manager_user_id
        )
        make_membership_role(connection, self.manager_membership_id, manager_role_id)


def _cleanup(engine: Engine, timeline_id: uuid.UUID, world_id: uuid.UUID) -> None:
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(text("DELETE FROM audit.change_log WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text(
                "DELETE FROM security.invitation_onboarding_sessions WHERE campaign_invitation_id IN ("
                "    SELECT campaign_invitation_id FROM security.campaign_invitations WHERE campaign_id IN ("
                "        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t"
                "    )"
                ")"
            ),
            {"t": timeline_id},
        )
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
                "DELETE FROM security.roles WHERE campaign_id IN (SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
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


def test_complete_vs_revoke_serialize_and_revoke_can_win(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-onb-complete-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _OnboardingRaceFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        raw_invitation_token = create_campaign_invitation(
            setup, campaign_id=rf.campaign_id, invited_by_membership_id=rf.manager_membership_id
        ).token
        begun = begin_invitation_onboarding(setup, invitation_token=raw_invitation_token)
        raw_onboarding_token = begun.raw_onboarding_token
        signed_in_user_id = make_user(setup, "Race Confirmer")

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            # `first` locks the invitation row via complete_invitation_onboarding's
            # own FOR UPDATE, before committing.
            complete_invitation_onboarding(
                first, onboarding_token=raw_onboarding_token, user_id=signed_in_user_id
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            invitation_id = second.execute(
                text(
                    "SELECT campaign_invitation_id FROM security.campaign_invitations WHERE campaign_id = :c"
                ),
                {"c": rf.campaign_id},
            ).scalar_one()
            with pytest.raises(Exception) as exc:
                revoke_campaign_invitation(
                    second, campaign_id=rf.campaign_id, campaign_invitation_id=invitation_id
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected revoke to block on complete's FOR UPDATE lock, got: {message}"
            )
            second.rollback()
            first.commit()

        # complete won: a subsequent revoke now fails as already-accepted.
        with engine.begin() as third:
            invitation_id = third.execute(
                text(
                    "SELECT campaign_invitation_id FROM security.campaign_invitations WHERE campaign_id = :c"
                ),
                {"c": rf.campaign_id},
            ).scalar_one()
            with pytest.raises(InvitationNotRevocableError):
                revoke_campaign_invitation(
                    third, campaign_id=rf.campaign_id, campaign_invitation_id=invitation_id
                )
    finally:
        _cleanup(engine, timeline_id, world_id)


def test_register_vs_revoke_serialize_and_a_losing_registration_leaves_no_orphan_user(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-onb-register-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _OnboardingRaceFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        raw_invitation_token = create_campaign_invitation(
            setup, campaign_id=rf.campaign_id, invited_by_membership_id=rf.manager_membership_id
        ).token
        begun = begin_invitation_onboarding(setup, invitation_token=raw_invitation_token)
        raw_onboarding_token = begun.raw_onboarding_token
        invitation_id = setup.execute(
            text(
                "SELECT campaign_invitation_id FROM security.campaign_invitations WHERE campaign_id = :c"
            ),
            {"c": rf.campaign_id},
        ).scalar_one()

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            first.execute(text("SET LOCAL lock_timeout = '2s'"))
            revoke_campaign_invitation(
                first, campaign_id=rf.campaign_id, campaign_invitation_id=invitation_id
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                _register_invited_local_account_impl(
                    second,
                    onboarding_token=raw_onboarding_token,
                    login_name=f"racer{uuid.uuid4().hex[:10]}",
                    display_name="Losing Registrant",
                    raw_password=_VALID_PASSWORD,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected register to block on revoke's FOR UPDATE lock, got: {message}"
            )
            second.rollback()
            first.commit()

        with engine.begin() as third, pytest.raises(OnboardingNotAvailableError):
            _register_invited_local_account_impl(
                third,
                onboarding_token=raw_onboarding_token,
                login_name=f"racer{uuid.uuid4().hex[:10]}",
                display_name="Retry Registrant",
                raw_password=_VALID_PASSWORD,
            )

        with engine.connect() as verify:
            new_member_count = verify.execute(
                text(
                    "SELECT count(*) FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id != :manager"
                ),
                {"c": rf.campaign_id, "manager": rf.manager_user_id},
            ).scalar_one()
            assert new_member_count == 0
            login_prefix_user_count = verify.execute(
                text(
                    "SELECT count(*) FROM security.user_activation_tokens "
                    "WHERE login_name LIKE 'racer%'"
                )
            ).scalar_one()
            assert login_prefix_user_count == 0
    finally:
        _cleanup(engine, timeline_id, world_id)
