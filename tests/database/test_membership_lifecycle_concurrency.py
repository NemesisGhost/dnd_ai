"""Real PostgreSQL concurrency regression coverage for
`dnd_ai.commands.memberships.add_campaign_member`/`end_campaign_membership`
(Phase 13E-B checkpoint 3).

Mirrors `tests/database/test_membership_role_concurrency.py`'s own two
concerns and its exact idioms, rather than inventing new ones — reusing
that module's `_run_with_precommit_barrier`/`_cleanup_retention_fixture`/
`_manager_count`/`_audit_row_count`/`RetentionRaceFixture`/`CONSTRAINT_
ERRORS` helpers directly:

1. **Eligibility-check/write race**: `add_campaign_member`'s own row locks
   (the target campaign, the target account, the candidate role — in that
   order) and `end_campaign_membership`'s own row lock (the target
   membership) must make a concurrent conflicting write block, proven by
   genuine row-lock blocking (`SET LOCAL lock_timeout`, the same blocking-
   proof idiom `test_membership_role_concurrency.py` already established).
   A same-account add-vs-add race is a distinct case, proven the identical
   way: the second `add_campaign_member`'s own `INSERT` blocks on the
   first's uncommitted, potentially-conflicting `ux_campaign_memberships_
   open` row until the first transaction resolves.

2. **Campaign access-manager retention invariant**: proven exactly like
   `test_membership_role_concurrency.py`'s own retention-race tests —
   `_run_with_precommit_barrier` runs both workers' own `end_campaign_
   membership` calls (and their own in-process pre-checks, provably a
   no-op for both sides under barrier coordination) to completion before
   either commits, so a combined-effect rejection can only come from the
   database's own deferred `security.assert_campaign_retains_access_
   manager()` trigger."""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.memberships import (
    add_campaign_member,
    change_membership_role,
    end_campaign_membership,
)
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from tests.database.test_membership_role_concurrency import (
    CONSTRAINT_ERRORS,
    RetentionRaceFixture,
    _audit_row_count,
    _cleanup_retention_fixture,
    _manager_count,
    _run_with_precommit_barrier,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_external_identity,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

_END_COMMAND_NAME = "end_campaign_membership"
_UPDATED_ACTION = "updated"


class _ActiveCampaignSetup:
    """An *active* campaign (`add_campaign_member` requires one) with a
    single qualifying `access.manage` membership already committed —
    created and its manager role assigned in the same setup transaction so
    the deferred `tr_campaigns_retain_access_manager` trigger sees a
    satisfied invariant at that transaction's own commit, plus one
    unassigned target role and one target user with no membership yet, for
    the add-race tests below to use directly. `target_user_id` is given an
    unrevoked local-login identity — `add_campaign_member`'s own
    eligibility check (review correction) now requires one, matching
    `dnd_ai.queries.access_overview.find_eligible_campaign_account`'s
    identical bar."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Race Campaign", lifecycle_status_code="active"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)
        self.role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"role_{uuid.uuid4().hex[:8]}"
        )
        manager_user_id = make_user(connection, "Race Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, manager_user_id
        )
        make_membership_role(connection, self.manager_membership_id, manager_role_id)
        self.target_user_id = make_user(connection, "Race Target User")
        self.target_login_name = f"race-target-{uuid.uuid4().hex[:8]}"
        make_external_identity(
            connection,
            self.target_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=self.target_login_name,
        )


# ---------------------------------------------------------------------------
# 1. Eligibility-check/write races
# ---------------------------------------------------------------------------


def test_two_concurrent_adds_of_the_same_account_cannot_both_succeed(
    postgres_engine: Engine,
) -> None:
    """Neither `add_campaign_member` call locks a pre-existing membership
    row (there isn't one yet), so this race is resolved by `ux_campaign_
    memberships_open`'s own unique-index insertion lock, not by an
    explicit `FOR UPDATE` — the second `INSERT` blocks on the first's
    still-uncommitted row until it resolves, then either raises a unique
    violation (committed) or proceeds (rolled back)."""
    engine = postgres_engine
    slug = f"conc-add-add-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        acs = _ActiveCampaignSetup(setup, slug)
        world_id, timeline_id = acs.world_id, acs.timeline_id
        campaign_id, role_id = acs.campaign_id, acs.role_id
        manager_membership_id, target_user_id = acs.manager_membership_id, acs.target_user_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_campaign_member(
                first,
                campaign_id=campaign_id,
                user_id=target_user_id,
                role_id=role_id,
                added_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                add_campaign_member(
                    second,
                    campaign_id=campaign_id,
                    user_id=target_user_id,
                    role_id=role_id,
                    added_by_membership_id=manager_membership_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the second add to block on the first's uncommitted "
                f"ux_campaign_memberships_open row, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            count = verify.execute(
                text(
                    "SELECT count(*) FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id = :u"
                ),
                {"c": campaign_id, "u": target_user_id},
            ).scalar()
            assert count == 1
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_a_campaign_deactivation_cannot_race_an_add_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`add_campaign_member`'s own `FOR UPDATE OF c` lock on the target
    campaign row must make a concurrent transition of that campaign out of
    `active` block too."""
    engine = postgres_engine
    slug = f"conc-add-campaign-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        acs = _ActiveCampaignSetup(setup, slug)
        world_id, timeline_id = acs.world_id, acs.timeline_id
        campaign_id, role_id = acs.campaign_id, acs.role_id
        manager_membership_id, target_user_id = acs.manager_membership_id, acs.target_user_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_campaign_member(
                first,
                campaign_id=campaign_id,
                user_id=target_user_id,
                role_id=role_id,
                added_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE campaign.campaigns
                        SET lifecycle_status_id = (
                            SELECT lifecycle_status_id FROM core.lifecycle_statuses
                            WHERE code = 'pending'
                        )
                        WHERE campaign_id = :c
                    """),
                    {"c": campaign_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the campaign deactivation to block on add_campaign_member's own "
                f"lock of the campaign row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_a_role_deactivation_cannot_race_an_add_assigning_it(
    postgres_engine: Engine,
) -> None:
    """`add_campaign_member`'s own `FOR UPDATE` lock on the candidate role
    row must make a concurrent deactivation of that role block too."""
    engine = postgres_engine
    slug = f"conc-add-role-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        acs = _ActiveCampaignSetup(setup, slug)
        world_id, timeline_id = acs.world_id, acs.timeline_id
        campaign_id, role_id = acs.campaign_id, acs.role_id
        manager_membership_id, target_user_id = acs.manager_membership_id, acs.target_user_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_campaign_member(
                first,
                campaign_id=campaign_id,
                user_id=target_user_id,
                role_id=role_id,
                added_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
                    {"r": role_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the role deactivation to block on add_campaign_member's own "
                f"lock of the candidate role, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_an_account_disablement_cannot_race_an_add_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`add_campaign_member`'s own `FOR UPDATE OF u` lock on the target
    account row must make a concurrent disablement of that account block
    too."""
    engine = postgres_engine
    slug = f"conc-add-account-disable-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        acs = _ActiveCampaignSetup(setup, slug)
        world_id, timeline_id = acs.world_id, acs.timeline_id
        campaign_id, role_id = acs.campaign_id, acs.role_id
        manager_membership_id, target_user_id = acs.manager_membership_id, acs.target_user_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_campaign_member(
                first,
                campaign_id=campaign_id,
                user_id=target_user_id,
                role_id=role_id,
                added_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE security.users
                        SET lifecycle_status_id = (
                            SELECT lifecycle_status_id FROM core.lifecycle_statuses
                            WHERE code = 'inactive'
                        )
                        WHERE user_id = :u
                    """),
                    {"u": target_user_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the account disablement to block on add_campaign_member's own "
                f"lock of the target account row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_a_local_identity_revocation_cannot_race_an_add_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`add_campaign_member`'s own `FOR UPDATE` lock on the target
    account's `security.external_identities` row (review correction) must
    make a concurrent revocation of that identity block too — the same
    shape the pre-existing role-deactivation/account-disablement races
    above already prove for their own target rows. No application command
    currently revokes a local identity (confirmed by inspection of `dnd_ai.
    commands.local_auth`/`.integration` — neither ever writes `security.
    external_identities.revoked_at`), so the second worker below performs
    the raw SQL write directly, exactly like this module's own campaign-
    deactivation race test already does for a lifecycle transition with no
    dedicated command of its own; the schema-level operation (and the lock
    guarding it) is real and worth proving safe regardless of whether a
    command wraps it yet."""
    engine = postgres_engine
    slug = f"conc-add-identity-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        acs = _ActiveCampaignSetup(setup, slug)
        world_id, timeline_id = acs.world_id, acs.timeline_id
        campaign_id, role_id = acs.campaign_id, acs.role_id
        manager_membership_id, target_user_id = acs.manager_membership_id, acs.target_user_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_campaign_member(
                first,
                campaign_id=campaign_id,
                user_id=target_user_id,
                role_id=role_id,
                added_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE security.external_identities
                        SET revoked_at = now()
                        WHERE user_id = :u AND issuer = :issuer AND revoked_at IS NULL
                    """),
                    {"u": target_user_id, "issuer": LOCAL_AUTH_ISSUER},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the identity revocation to block on add_campaign_member's own "
                f"lock of the target account's local identity row, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            count = verify.execute(
                text(
                    "SELECT count(*) FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id = :u"
                ),
                {"c": campaign_id, "u": target_user_id},
            ).scalar()
            assert count == 1
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_two_concurrent_removals_of_the_identical_membership_serialize(
    postgres_engine: Engine,
) -> None:
    """`end_campaign_membership`'s own `FOR UPDATE` on its target row must
    make a second, concurrent removal of the identical membership block,
    then observe the first's committed effect (already ended) once
    unblocked — never an interleaved write, and never a raised error for
    the second caller (the documented harmless-no-op case)."""
    engine = postgres_engine
    slug = f"conc-end-end-same-row-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        role_id = make_role(setup, campaign_id=campaign_id, code=f"role_{uuid.uuid4().hex[:8]}")
        manager_user_id = make_user(setup, "Race Manager")
        manager_membership_id = make_campaign_membership(setup, campaign_id, manager_user_id)
        target_user_id = make_user(setup, "Race Target User")
        target_membership_id = make_campaign_membership(setup, campaign_id, target_user_id)
        make_membership_role(setup, target_membership_id, role_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            # Holds FOR UPDATE on target_membership_id without committing.
            end_campaign_membership(
                first,
                campaign_membership_id=target_membership_id,
                campaign_id=campaign_id,
                ended_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                end_campaign_membership(
                    second,
                    campaign_membership_id=target_membership_id,
                    campaign_id=campaign_id,
                    ended_by_membership_id=manager_membership_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent removal to block on the identical row's FOR UPDATE "
                f"lock, got: {message}"
            )
            second.rollback()

            first.commit()

        # Unblocked, and the row is already ended (by the committed first
        # removal) — the documented no-op behavior applies.
        with engine.begin() as third:
            result = end_campaign_membership(
                third,
                campaign_membership_id=target_membership_id,
                campaign_id=campaign_id,
                ended_by_membership_id=manager_membership_id,
            )
            assert result.ended is False
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_a_role_change_cannot_race_a_removal_of_the_same_membership(
    postgres_engine: Engine,
) -> None:
    """`end_campaign_membership`'s own `FOR UPDATE` on the target
    membership row must make a concurrent `change_membership_role` call
    against one of its role rows block too — `change_membership_role`
    locks the membership row as part of its own `FOR UPDATE OF mr, cm, r`."""
    engine = postgres_engine
    slug = f"conc-end-change-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        role_id = make_role(setup, campaign_id=campaign_id, code=f"role_{uuid.uuid4().hex[:8]}")
        new_role_id = make_role(
            setup, campaign_id=campaign_id, code=f"newrole_{uuid.uuid4().hex[:8]}"
        )
        manager_user_id = make_user(setup, "Race Manager")
        manager_membership_id = make_campaign_membership(setup, campaign_id, manager_user_id)
        target_user_id = make_user(setup, "Race Target User")
        target_membership_id = make_campaign_membership(setup, campaign_id, target_user_id)
        target_membership_role_id = make_membership_role(setup, target_membership_id, role_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            end_campaign_membership(
                first,
                campaign_membership_id=target_membership_id,
                campaign_id=campaign_id,
                ended_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                change_membership_role(
                    second,
                    membership_role_id=target_membership_role_id,
                    campaign_id=campaign_id,
                    new_role_id=new_role_id,
                    granted_by_membership_id=manager_membership_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent role change to block on end_campaign_membership's "
                f"own lock of the membership row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 2. Campaign access-manager retention invariant under real concurrency
# ---------------------------------------------------------------------------


def test_two_managers_concurrently_removing_their_own_memberships_cannot_both_leave_zero_managers(
    postgres_engine: Engine,
) -> None:
    """Both workers end a *distinct* manager-bearing membership on the same
    active campaign — `_run_with_precommit_barrier` guarantees both `end_
    campaign_membership` calls (and their own in-process retention
    pre-checks, provably a no-op for both sides) complete before either
    commits, so the rejection can only come from the database's own
    deferred retention trigger."""
    engine = postgres_engine
    slug = f"conc-end-end-retention-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = RetentionRaceFixture(setup, slug)

    try:
        # Each worker ends its *own* membership (ended_by_membership_id
        # self-references the row being closed) — deliberately never
        # cross-referencing the other worker's row: an earlier version of
        # this test had each worker record the *other* row as its actor,
        # which made each worker's own UPDATE request a FOR KEY SHARE lock
        # on the row the *other* worker already held FOR UPDATE (`security.
        # campaign_memberships.ended_by_membership_id`'s own FK), a genuine
        # cross-dependency the database's own deadlock detector correctly
        # killed — a real deadlock, but not the retention-trigger rejection
        # this test exists to prove.

        def end_first(connection: Connection) -> None:
            end_campaign_membership(
                connection,
                campaign_membership_id=rf.first_membership_id,
                campaign_id=rf.campaign_id,
                ended_by_membership_id=rf.first_membership_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="campaign_memberships",
                record_id=rf.first_membership_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.first_user_id,
                correlation_id=None,
                command_name=_END_COMMAND_NAME,
                event_id=None,
            )

        def end_second(connection: Connection) -> None:
            end_campaign_membership(
                connection,
                campaign_membership_id=rf.second_membership_id,
                campaign_id=rf.campaign_id,
                ended_by_membership_id=rf.second_membership_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="campaign_memberships",
                record_id=rf.second_membership_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.second_user_id,
                correlation_id=None,
                command_name=_END_COMMAND_NAME,
                event_id=None,
            )

        outcomes = _run_with_precommit_barrier(engine, {"first": end_first, "second": end_second})

        committed = [o for o in outcomes.values() if o.committed]
        rejected = [o for o in outcomes.values() if not o.committed]
        assert len(committed) == 1, f"expected exactly one commit, got: {outcomes}"
        assert len(rejected) == 1, f"expected exactly one rejection, got: {outcomes}"
        assert isinstance(rejected[0].error, CONSTRAINT_ERRORS), (
            f"expected the rejected removal to fail via the database's own deferred "
            f"retention trigger specifically, got: {rejected[0].error!r}"
        )
        assert "access.manage" in str(rejected[0].error) or "access_manager" in str(
            rejected[0].error
        ), f"expected the rejection to name the retention invariant, got: {rejected[0].error!r}"

        with engine.connect() as verify:
            assert _manager_count(verify, rf.campaign_id) == 1
            assert _audit_row_count(verify, rf.world_id) == 1
    finally:
        _cleanup_retention_fixture(engine, rf.timeline_id, rf.world_id)


def test_self_removal_racing_another_managers_removal_of_the_same_membership(
    postgres_engine: Engine,
) -> None:
    """A distinct pairing from the same-row test above and the retention
    race above it: the caller ending their *own* membership (self-removal,
    `ended_by_membership_id` self-referencing) races a *different* manager
    concurrently trying to end that exact same row on the caller's behalf.
    Two active managers exist (`RetentionRaceFixture`), so ending the
    targeted row alone never violates the retention invariant either way —
    this is a same-row lock-serialization proof, not a retention-trigger
    proof (see the two tests above for each of those separately): whichever
    call's `FOR UPDATE` wins acts once; the loser blocks, then observes the
    already-ended row as the documented harmless no-op — self-removal gets
    no special treatment in that race, exactly like `change_membership_
    role`/`revoke_membership_role`'s own self-mutation tests."""
    engine = postgres_engine
    slug = f"conc-self-removal-same-row-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = RetentionRaceFixture(setup, slug)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            # Self-removal: first_user ends their own membership.
            end_campaign_membership(
                first,
                campaign_membership_id=rf.first_membership_id,
                campaign_id=rf.campaign_id,
                ended_by_membership_id=rf.first_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                # A different manager (second_user) concurrently trying to
                # end the identical membership on the caller's behalf.
                end_campaign_membership(
                    second,
                    campaign_membership_id=rf.first_membership_id,
                    campaign_id=rf.campaign_id,
                    ended_by_membership_id=rf.second_membership_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent removal to block on the identical row's FOR UPDATE "
                f"lock, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.begin() as third:
            result = end_campaign_membership(
                third,
                campaign_membership_id=rf.first_membership_id,
                campaign_id=rf.campaign_id,
                ended_by_membership_id=rf.second_membership_id,
            )
            assert result.ended is False

        with engine.connect() as verify:
            assert _manager_count(verify, rf.campaign_id) == 1
    finally:
        _cleanup_retention_fixture(engine, rf.timeline_id, rf.world_id)
