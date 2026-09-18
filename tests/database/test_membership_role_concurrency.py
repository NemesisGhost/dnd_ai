"""Real PostgreSQL concurrency regression coverage for
`dnd_ai.commands.memberships.change_membership_role`/`revoke_membership_role`
(Phase 13E-B checkpoint 1 correction).

Two independent concerns, each with its own locking mechanism, are
exercised against real concurrent transactions on separate connections —
never mocked, never a single shared connection:

1. **Eligibility-check/write race** (`change_membership_role`'s own new
   `FOR UPDATE OF mr, cm, r` lock on the target row/membership/current-role,
   and its separate `FOR UPDATE` lock on the candidate new role): a
   concurrent deactivation of either role must never slip in between this
   function's own read of "is this eligible" and its write, proven by
   genuine row-lock blocking (`SET LOCAL lock_timeout`, matching the
   blocking-proof idiom already established in `tests/database/
   test_world_ruleset_dependency_and_concurrency.py`).

2. **Campaign `access.manage` retention invariant**: this module adds no
   locking of its own for this — it relies entirely on the pre-existing
   `security.assert_campaign_retains_access_manager()` (migration 080),
   which locks `campaign.campaigns` `FOR UPDATE` and is invoked by a
   `DEFERRABLE INITIALLY DEFERRED` constraint trigger on `security.
   membership_roles`, evaluated against the *fully committed* final state
   at commit time. The tests here prove that guarantee actually holds for
   `change_membership_role` (added by this checkpoint) exactly as it
   already did for `revoke_membership_role`: two concurrent operations that
   would *individually* look safe (each still sees the other's
   not-yet-committed manager role) can never *both* commit when their
   combined effect leaves an active campaign with zero qualifying
   `access.manage` holders.

   Each racing worker targets a *distinct* management-granting row and, for
   `change_membership_role`, a *distinct* candidate new role — naming the
   same new-role row for both workers would let `change_membership_role`'s
   own `FOR UPDATE` on that shared row silently serialize the two workers
   (the second blocks until the first fully commits), which lets each
   side's own in-process pre-check (`_assert_active_campaign_retains_
   access_manager`, a plain `ValueError`) resolve the whole scenario
   sequentially — never exercising the *combined-effect* race this section
   exists to prove at all (a review finding against an earlier version of
   this file). `_run_with_precommit_barrier` below closes that gap
   properly: both workers run their own `change_membership_role`/`revoke_
   membership_role` call and audit write to completion — including each
   one's own in-process pre-check, which is therefore guaranteed to *pass*
   for both sides (neither has committed yet, so each still sees the other
   as an active manager) — and only then, synchronized by a two-party
   `threading.Barrier`, are both released to call `connection.commit()`
   concurrently. Because the pre-check is provably a no-op for both sides
   under this coordination, the loser can only ever be rejected by the
   database's own deferred constraint trigger — the specific mechanism
   this section exists to regression-test. Removing that trigger, or its
   `campaign.campaigns` `FOR UPDATE` lock, makes both workers commit
   successfully and fails these tests' `len(rejected) == 1` assertion.
"""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.memberships import (
    assign_membership_role,
    change_membership_role,
    revoke_membership_role,
)
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

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)

_CHANGE_COMMAND_NAME = "change_membership_role"
_REVOKE_COMMAND_NAME = "revoke_membership_role"
_UPDATED_ACTION = "updated"


@dataclass(frozen=True)
class _ThreadOutcome:
    label: str
    committed: bool
    error: BaseException | None


def _run_with_precommit_barrier(
    engine: Engine,
    operations: dict[str, Callable[[Connection], None]],
) -> dict[str, _ThreadOutcome]:
    """Runs each callable in its own thread, on its own connection (opened
    and begun before the callable runs, closed after commit/rollback) —
    never a connection handed off across threads. Every worker pauses at a
    shared `threading.Barrier` sized to the number of operations,
    immediately after its own callable returns and *before* its own
    `connection.commit()`. A `Barrier.wait()` call only returns once every
    party has reached it, so by the time any worker is allowed to proceed
    to commit, every worker's own write (and, for `change_membership_role`/
    `revoke_membership_role`, its own in-process retention pre-check) is
    already complete — proving both writes reached the pre-commit point
    before any commit is released, rather than merely hoping two threads
    started close enough together. Every worker then calls its own
    `connection.commit()` immediately after the barrier releases, so both
    commits are attempted concurrently, genuinely racing PostgreSQL's own
    commit-time serialization. See this module's docstring.

    Never raises on a callable's own exception, or on a broken barrier (one
    worker failing before reaching it leaves the others waiting until the
    barrier's own timeout, then raises `BrokenBarrierError` for them) —
    both are recorded as that worker's outcome, not a test-harness
    failure."""
    barrier = threading.Barrier(len(operations), timeout=15.0)
    results: dict[str, _ThreadOutcome] = {}
    lock = threading.Lock()

    def _worker(label: str, operation: Callable[[Connection], None]) -> None:
        try:
            with engine.connect() as connection:
                connection.begin()
                operation(connection)
                barrier.wait()
                connection.commit()
        except Exception as exc:  # noqa: BLE001 - reported to the main thread, not swallowed
            with lock:
                results[label] = _ThreadOutcome(label=label, committed=False, error=exc)
        else:
            with lock:
                results[label] = _ThreadOutcome(label=label, committed=True, error=None)

    threads = [
        threading.Thread(target=_worker, args=(label, op)) for label, op in operations.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=25.0)
    for thread in threads:
        assert not thread.is_alive(), "a concurrency test thread did not finish within 25s"

    return results


class RetentionRaceFixture:
    """An *active* campaign with exactly two independent members, each
    holding their own `access.manage`-granting role assignment — the
    minimum needed to race two different management-granting rows against
    each other.

    Every row either worker's `change_membership_role()` call could lock is
    given a *distinct* copy per worker — a distinct current (manager-
    granting) role as well as a distinct candidate new role, not just the
    latter. `change_membership_role()` takes `FOR UPDATE OF mr, cm, r`,
    where `r` is the target assignment's *current* role — if both workers'
    memberships held the identical manager role, that shared row alone
    would serialize the two workers ahead of (and independently of) the
    barrier below: the second worker would block *inside* `change_
    membership_role()` itself, waiting on a lock only the first worker's
    eventual commit releases, while the first worker simultaneously waits
    at the barrier for the second to arrive — a real deadlock, broken only
    by the barrier's own timeout (`BrokenBarrierError` for both sides, a
    review finding against an earlier version of this fixture that reused
    one shared `manager_role_id` for both memberships)."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Concurrency Campaign", lifecycle_status_code="active"
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        # Two distinct manager-granting roles — see this class's own
        # docstring for why a single shared one deadlocks the barrier
        # below.
        self.first_manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager1_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.first_manager_role_id, access_manage_id)
        make_role_capability(connection, self.first_manager_role_id, view_capability_id)

        self.second_manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager2_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.second_manager_role_id, access_manage_id)
        make_role_capability(connection, self.second_manager_role_id, view_capability_id)

        # Two distinct non-manager roles — the change-role target for each
        # worker, equally distinct for the identical reason.
        self.first_non_manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"nonmanager1_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.first_non_manager_role_id, view_capability_id)

        self.second_non_manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"nonmanager2_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.second_non_manager_role_id, view_capability_id)

        self.first_user_id = make_user(connection, "Concurrency Manager One")
        self.first_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.first_user_id
        )
        self.first_membership_role_id = make_membership_role(
            connection, self.first_membership_id, self.first_manager_role_id
        )

        self.second_user_id = make_user(connection, "Concurrency Manager Two")
        self.second_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.second_user_id
        )
        self.second_membership_role_id = make_membership_role(
            connection, self.second_membership_id, self.second_manager_role_id
        )


def _cleanup_retention_fixture(engine: Engine, timeline_id: uuid.UUID, world_id: uuid.UUID) -> None:
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM audit.change_log WHERE world_id = :w
            """),
            {"w": world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"), {"t": timeline_id}
        )
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE timeline_id = :t"), {"t": timeline_id}
        )
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})


def _manager_count(connection: Connection, campaign_id: uuid.UUID) -> int:
    count = connection.execute(
        text("""
            SELECT count(*)
            FROM security.campaign_memberships cm
            JOIN security.membership_roles mr ON mr.campaign_membership_id = cm.campaign_membership_id
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.role_capabilities rc ON rc.role_id = r.role_id
            JOIN security.capabilities c ON c.capability_id = rc.capability_id
            WHERE cm.campaign_id = :campaign
              AND cm.ended_at IS NULL
              AND mr.revoked_at IS NULL
              AND mr.expires_at IS NULL
              AND r.is_active
              AND c.code = 'access.manage'
              AND c.is_active
        """),
        {"campaign": campaign_id},
    ).scalar_one()
    assert isinstance(count, int)
    return count


def _audit_row_count(connection: Connection, world_id: uuid.UUID) -> int:
    count = connection.execute(
        text("SELECT count(*) FROM audit.change_log WHERE world_id = :w"),
        {"w": world_id},
    ).scalar_one()
    assert isinstance(count, int)
    return count


# ---------------------------------------------------------------------------
# 1. Eligibility-check/write race: concurrent role deactivation
# ---------------------------------------------------------------------------


def test_a_current_role_deactivation_cannot_race_a_change_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`change_membership_role()`'s `FOR UPDATE OF mr, cm, r` lock must make
    a concurrent deactivation of the target's *current* role block, not
    silently interleave with the eligibility check."""
    engine = postgres_engine
    slug = f"conc-current-role-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        current_role_id = make_role(
            setup, campaign_id=campaign_id, code=f"current_{uuid.uuid4().hex[:8]}"
        )
        new_role_id = make_role(setup, campaign_id=campaign_id, code=f"new_{uuid.uuid4().hex[:8]}")
        user_id = make_user(setup, "Race Target User")
        membership_id = make_campaign_membership(setup, campaign_id, user_id)
        membership_role_id = make_membership_role(setup, membership_id, current_role_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            # Holds FOR UPDATE OF mr, cm, r — including current_role_id's own row.
            change_membership_role(
                first,
                membership_role_id=membership_role_id,
                campaign_id=campaign_id,
                new_role_id=new_role_id,
                granted_by_membership_id=membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
                    {"r": current_role_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the deactivation to block on change_membership_role's own row "
                f"lock, got: {message}"
            )
            second.rollback()

            first.commit()

        # Unblocked now — the deactivation succeeds once the change committed.
        with engine.begin() as third:
            third.execute(
                text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
                {"r": current_role_id},
            )
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_a_new_role_deactivation_cannot_race_it_being_assigned_by_a_change(
    postgres_engine: Engine,
) -> None:
    """`change_membership_role()`'s separate `FOR UPDATE` on the candidate
    `new_role_id` row must make a concurrent deactivation of *that* role
    block too, not just the current-role lock."""
    engine = postgres_engine
    slug = f"conc-new-role-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        current_role_id = make_role(
            setup, campaign_id=campaign_id, code=f"current_{uuid.uuid4().hex[:8]}"
        )
        new_role_id = make_role(setup, campaign_id=campaign_id, code=f"new_{uuid.uuid4().hex[:8]}")
        user_id = make_user(setup, "Race Target User")
        membership_id = make_campaign_membership(setup, campaign_id, user_id)
        membership_role_id = make_membership_role(setup, membership_id, current_role_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            change_membership_role(
                first,
                membership_role_id=membership_role_id,
                campaign_id=campaign_id,
                new_role_id=new_role_id,
                granted_by_membership_id=membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
                    {"r": new_role_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the deactivation to block on change_membership_role's own lock "
                f"of the candidate new role, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.begin() as third:
            third.execute(
                text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
                {"r": new_role_id},
            )
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_a_membership_ending_cannot_race_an_assign_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`assign_membership_role()`'s own `FOR UPDATE OF cm` lock on the
    target membership (Phase 13E-B checkpoint 2 hardening) must make a
    concurrent ending of that same membership block, not silently
    interleave with the eligibility check — the assign-role counterpart to
    this module's `change_membership_role` current-role-deactivation
    tests above."""
    engine = postgres_engine
    slug = f"conc-assign-membership-end-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        role_id = make_role(setup, campaign_id=campaign_id, code=f"role_{uuid.uuid4().hex[:8]}")
        user_id = make_user(setup, "Race Target User")
        membership_id = make_campaign_membership(setup, campaign_id, user_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            # Holds FOR UPDATE OF cm on membership_id.
            assign_membership_role(
                first,
                campaign_membership_id=membership_id,
                role_id=role_id,
                campaign_id=campaign_id,
                granted_by_membership_id=membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text(
                        "UPDATE security.campaign_memberships SET ended_at = now() "
                        "WHERE campaign_membership_id = :m"
                    ),
                    {"m": membership_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the membership-ending update to block on assign_membership_role's "
                f"own row lock, got: {message}"
            )
            second.rollback()

            first.commit()

        # Unblocked now — ending the membership succeeds once the assign committed.
        with engine.begin() as third:
            third.execute(
                text(
                    "UPDATE security.campaign_memberships SET ended_at = now() "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": membership_id},
            )
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_a_role_deactivation_cannot_race_it_being_assigned(
    postgres_engine: Engine,
) -> None:
    """`assign_membership_role()`'s separate `FOR UPDATE` on the candidate
    `role_id` row must make a concurrent deactivation of that role block
    too, not just the membership lock."""
    engine = postgres_engine
    slug = f"conc-assign-role-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        role_id = make_role(setup, campaign_id=campaign_id, code=f"role_{uuid.uuid4().hex[:8]}")
        user_id = make_user(setup, "Race Target User")
        membership_id = make_campaign_membership(setup, campaign_id, user_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            assign_membership_role(
                first,
                campaign_membership_id=membership_id,
                role_id=role_id,
                campaign_id=campaign_id,
                granted_by_membership_id=membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
                    {"r": role_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the deactivation to block on assign_membership_role's own lock "
                f"of the candidate role, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.begin() as third:
            third.execute(
                text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
                {"r": role_id},
            )
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_an_account_disablement_cannot_race_an_assign_targeting_its_membership(
    postgres_engine: Engine,
) -> None:
    """`assign_membership_role()`'s separate `FOR UPDATE OF u` lock on the
    target membership's own `security.users` row must make a concurrent
    disablement of that account block too — the same shape
    `dnd_ai.commands.local_auth._set_local_account_lifecycle_status_impl`'s
    own `SELECT ... FOR UPDATE` already uses for its side of this race."""
    engine = postgres_engine
    slug = f"conc-assign-account-disable-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        role_id = make_role(setup, campaign_id=campaign_id, code=f"role_{uuid.uuid4().hex[:8]}")
        user_id = make_user(setup, "Race Target User")
        membership_id = make_campaign_membership(setup, campaign_id, user_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            assign_membership_role(
                first,
                campaign_membership_id=membership_id,
                role_id=role_id,
                campaign_id=campaign_id,
                granted_by_membership_id=membership_id,
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
                    {"u": user_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the account disablement to block on assign_membership_role's own "
                f"lock of the target membership's user row, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.begin() as third:
            third.execute(
                text("""
                    UPDATE security.users
                    SET lifecycle_status_id = (
                        SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive'
                    )
                    WHERE user_id = :u
                """),
                {"u": user_id},
            )
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


def test_two_concurrent_revokes_of_the_identical_row_serialize(
    postgres_engine: Engine,
) -> None:
    """Same-row coverage for revoke-vs-revoke specifically (the pre-existing
    change-vs-revoke same-row test above already covers that pairing):
    `revoke_membership_role()`'s own `FOR UPDATE` on its target row must
    make a second, concurrent revoke of the identical row block, then
    observe the first's committed effect (already revoked) once unblocked
    — never an interleaved write, and never a raised error for the second
    caller (the documented harmless-no-op case)."""
    engine = postgres_engine
    slug = f"conc-revoke-revoke-same-row-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        role_id = make_role(setup, campaign_id=campaign_id, code=f"role_{uuid.uuid4().hex[:8]}")
        user_id = make_user(setup, "Race Target User")
        membership_id = make_campaign_membership(setup, campaign_id, user_id)
        membership_role_id = make_membership_role(setup, membership_id, role_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            # Holds FOR UPDATE OF mr on membership_role_id without committing.
            revoke_membership_role(
                first, membership_role_id=membership_role_id, campaign_id=campaign_id
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                revoke_membership_role(
                    second, membership_role_id=membership_role_id, campaign_id=campaign_id
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent revoke to block on the identical row's FOR UPDATE "
                f"lock, got: {message}"
            )
            second.rollback()

            first.commit()

        # Unblocked, and the row is already revoked (by the committed first
        # revoke) — the documented no-op behavior applies, reported via
        # RevokeMembershipRoleResult.revoked rather than a fresh error.
        with engine.begin() as third:
            result = revoke_membership_role(
                third, membership_role_id=membership_role_id, campaign_id=campaign_id
            )
            assert result.revoked is False
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 2. Campaign access-manager retention invariant under real concurrency
# ---------------------------------------------------------------------------


def test_two_concurrent_changes_to_different_management_granting_rows_cannot_both_leave_zero_managers(
    postgres_engine: Engine,
) -> None:
    """Both workers target distinct rows throughout — distinct membership
    rows, distinct current roles, and (unlike an earlier version of this
    test) distinct candidate new roles — so no incidental shared-row lock
    can serialize them ahead of the barrier below. `_run_with_precommit_
    barrier` then guarantees both workers' own `change_membership_role`
    calls (and their own in-process retention pre-checks, which are
    therefore provably a no-op for both sides — see this module's
    docstring) complete before either is allowed to commit, so the
    rejection below can only come from the database's own deferred
    retention trigger."""
    engine = postgres_engine
    slug = f"conc-change-change-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = RetentionRaceFixture(setup, slug)

    try:

        def change_first(connection: Connection) -> None:
            change_membership_role(
                connection,
                membership_role_id=rf.first_membership_role_id,
                campaign_id=rf.campaign_id,
                new_role_id=rf.first_non_manager_role_id,
                granted_by_membership_id=rf.first_membership_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="membership_roles",
                record_id=rf.first_membership_role_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.first_user_id,
                correlation_id=None,
                command_name=_CHANGE_COMMAND_NAME,
                event_id=None,
            )

        def change_second(connection: Connection) -> None:
            change_membership_role(
                connection,
                membership_role_id=rf.second_membership_role_id,
                campaign_id=rf.campaign_id,
                new_role_id=rf.second_non_manager_role_id,
                granted_by_membership_id=rf.second_membership_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="membership_roles",
                record_id=rf.second_membership_role_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.second_user_id,
                correlation_id=None,
                command_name=_CHANGE_COMMAND_NAME,
                event_id=None,
            )

        outcomes = _run_with_precommit_barrier(
            engine, {"first": change_first, "second": change_second}
        )

        committed = [o for o in outcomes.values() if o.committed]
        rejected = [o for o in outcomes.values() if not o.committed]
        assert len(committed) == 1, f"expected exactly one commit, got: {outcomes}"
        assert len(rejected) == 1, f"expected exactly one rejection, got: {outcomes}"
        assert isinstance(rejected[0].error, CONSTRAINT_ERRORS), (
            f"expected the rejected change to fail via the database's own deferred "
            f"retention trigger specifically (both sides' in-process pre-checks are "
            f"provably a no-op under barrier coordination — see this module's "
            f"docstring), got: {rejected[0].error!r}"
        )
        assert "access.manage" in str(rejected[0].error) or "access_manager" in str(
            rejected[0].error
        ), f"expected the rejection to name the retention invariant, got: {rejected[0].error!r}"

        with engine.connect() as verify:
            assert _manager_count(verify, rf.campaign_id) == 1
            assert _audit_row_count(verify, rf.world_id) == 1
    finally:
        _cleanup_retention_fixture(engine, rf.timeline_id, rf.world_id)


def test_a_change_and_a_revoke_racing_different_management_granting_rows_cannot_both_leave_zero_managers(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-change-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = RetentionRaceFixture(setup, slug)

    try:

        def change_first(connection: Connection) -> None:
            change_membership_role(
                connection,
                membership_role_id=rf.first_membership_role_id,
                campaign_id=rf.campaign_id,
                new_role_id=rf.first_non_manager_role_id,
                granted_by_membership_id=rf.first_membership_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="membership_roles",
                record_id=rf.first_membership_role_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.first_user_id,
                correlation_id=None,
                command_name=_CHANGE_COMMAND_NAME,
                event_id=None,
            )

        def revoke_second(connection: Connection) -> None:
            revoke_membership_role(
                connection,
                membership_role_id=rf.second_membership_role_id,
                campaign_id=rf.campaign_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="membership_roles",
                record_id=rf.second_membership_role_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.second_user_id,
                correlation_id=None,
                command_name=_REVOKE_COMMAND_NAME,
                event_id=None,
            )

        # No shared-row lock connects these two calls at all (revoke_
        # membership_role locks only its own target row, no role row) — so
        # nothing accidentally serializes them the way two change calls
        # sharing a new-role row would. The barrier is still required here
        # (finding 7): without it, relying on both threads merely *starting*
        # close together is not deterministic — the OS could still let one
        # run to completion, including commit, before the other begins.
        outcomes = _run_with_precommit_barrier(
            engine, {"change": change_first, "revoke": revoke_second}
        )

        committed = [o for o in outcomes.values() if o.committed]
        rejected = [o for o in outcomes.values() if not o.committed]
        assert len(committed) == 1, f"expected exactly one commit, got: {outcomes}"
        assert len(rejected) == 1, f"expected exactly one rejection, got: {outcomes}"
        assert isinstance(rejected[0].error, CONSTRAINT_ERRORS), (
            f"expected the rejected side to fail via the database's own deferred "
            f"retention trigger specifically (both sides' in-process pre-checks are "
            f"provably a no-op under barrier coordination — see this module's "
            f"docstring), got: {rejected[0].error!r}"
        )
        assert "access.manage" in str(rejected[0].error) or "access_manager" in str(
            rejected[0].error
        ), f"expected the rejection to name the retention invariant, got: {rejected[0].error!r}"

        with engine.connect() as verify:
            assert _manager_count(verify, rf.campaign_id) == 1
            assert _audit_row_count(verify, rf.world_id) == 1
    finally:
        _cleanup_retention_fixture(engine, rf.timeline_id, rf.world_id)


def test_two_concurrent_revokes_of_different_management_granting_rows_cannot_both_leave_zero_managers(
    postgres_engine: Engine,
) -> None:
    """The revoke-vs-revoke counterpart to the change-vs-change and
    change-vs-revoke retention tests above: two managers, each revoking
    their own distinct management-granting row, racing to commit
    concurrently. Exactly one may succeed."""
    engine = postgres_engine
    slug = f"conc-revoke-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = RetentionRaceFixture(setup, slug)

    try:

        def revoke_first(connection: Connection) -> None:
            revoke_membership_role(
                connection,
                membership_role_id=rf.first_membership_role_id,
                campaign_id=rf.campaign_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="membership_roles",
                record_id=rf.first_membership_role_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.first_user_id,
                correlation_id=None,
                command_name=_REVOKE_COMMAND_NAME,
                event_id=None,
            )

        def revoke_second(connection: Connection) -> None:
            revoke_membership_role(
                connection,
                membership_role_id=rf.second_membership_role_id,
                campaign_id=rf.campaign_id,
            )
            record_change_log(
                connection,
                change_action_code=_UPDATED_ACTION,
                schema_name="security",
                table_name="membership_roles",
                record_id=rf.second_membership_role_id,
                entity_id=None,
                world_id=rf.world_id,
                actor_user_id=rf.second_user_id,
                correlation_id=None,
                command_name=_REVOKE_COMMAND_NAME,
                event_id=None,
            )

        outcomes = _run_with_precommit_barrier(
            engine, {"first": revoke_first, "second": revoke_second}
        )

        committed = [o for o in outcomes.values() if o.committed]
        rejected = [o for o in outcomes.values() if not o.committed]
        assert len(committed) == 1, f"expected exactly one commit, got: {outcomes}"
        assert len(rejected) == 1, f"expected exactly one rejection, got: {outcomes}"
        assert isinstance(rejected[0].error, CONSTRAINT_ERRORS), (
            f"expected the rejected revoke to fail via the database's own deferred "
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


# ---------------------------------------------------------------------------
# 3. Same-row concurrency: change vs. revoke targeting the identical row
# ---------------------------------------------------------------------------


def test_a_change_and_a_revoke_targeting_the_identical_row_serialize(
    postgres_engine: Engine,
) -> None:
    """Same-row coverage: both `change_membership_role()` and `revoke_
    membership_role()` lock their target `membership_role_id` `FOR UPDATE`
    — a concurrent call of either kind against the *identical* row must
    block, never interleave, regardless of which two operations race."""
    engine = postgres_engine
    slug = f"conc-same-row-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        world_id = make_world(setup, slug=slug)
        timeline_id = make_timeline(setup, world_id, is_primary=True)
        campaign_id = make_campaign(
            setup, timeline_id, "Race Campaign", lifecycle_status_code="pending"
        )
        current_role_id = make_role(
            setup, campaign_id=campaign_id, code=f"current_{uuid.uuid4().hex[:8]}"
        )
        new_role_id = make_role(setup, campaign_id=campaign_id, code=f"new_{uuid.uuid4().hex[:8]}")
        user_id = make_user(setup, "Race Target User")
        membership_id = make_campaign_membership(setup, campaign_id, user_id)
        membership_role_id = make_membership_role(setup, membership_id, current_role_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            # Holds FOR UPDATE OF mr on membership_role_id without committing.
            change_membership_role(
                first,
                membership_role_id=membership_role_id,
                campaign_id=campaign_id,
                new_role_id=new_role_id,
                granted_by_membership_id=membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                revoke_membership_role(
                    second, membership_role_id=membership_role_id, campaign_id=campaign_id
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent revoke to block on the identical row's FOR UPDATE "
                f"lock, got: {message}"
            )
            second.rollback()

            first.commit()

        # Unblocked, and the row is already revoked (by the committed change)
        # — revoke_membership_role's own documented no-op-on-already-revoked
        # behavior applies, not a fresh error.
        with engine.begin() as third:
            revoke_membership_role(
                third, membership_role_id=membership_role_id, campaign_id=campaign_id
            )

        with engine.connect() as verify:
            row_count = verify.execute(
                text(
                    "SELECT count(*) FROM security.membership_roles "
                    "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
                ),
                {"m": membership_id},
            ).scalar_one()
            # The committed change's *new* row is the only one still active;
            # the old row was revoked by the change itself, and the later
            # revoke_membership_role call was a harmless no-op against it.
            assert row_count == 1
    finally:
        _cleanup_retention_fixture(engine, timeline_id, world_id)
