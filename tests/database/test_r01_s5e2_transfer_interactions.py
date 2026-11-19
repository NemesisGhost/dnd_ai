# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E2 E10 correction (plan 6.29): the ownership transfer's weaker lock modes against its neighbours.

Historical local design: docs/R01_S5E2_E10_CORRECTION_DESIGN_2026-11-15.md sections 3.4, 4.4 and 7.3. M1 (campaign `FOR KEY SHARE`
when no role UPDATE is owed) and M2 (the actor's role rows `FOR KEY SHARE` when not relinquishing) must neither
introduce a cycle nor let a request that owes a role UPDATE reach COMMIT holding only a campaign KEY SHARE: the deferred
retention trigger (`tr_membership_roles_retain_access_manager`) takes the campaign `FOR UPDATE` at COMMIT, and a
KEY SHARE -> UPDATE upgrade is exactly the shape that deadlocks two concurrent requests.

Each case parks one request at a named statement, starts the other, observes whether and on what it queued, releases,
and asserts: no driver exception, deadlock counter unchanged, exact statuses, exact final rows and audit.
"""

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dnd_ai.commands.campaign_invitations import (
    accept_campaign_invitation,
    create_campaign_invitation,
)
from dnd_ai.commands.recovery import recover_campaign_access_manager
from dnd_ai.queries.stranded import campaign_has_active_access_manager
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_authoring_transfer_cycles import (
    WAIT_CAMPAIGN_UPDATE,
    expired_owner,
    live_owner,
    owner_rows,
)
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    ACTOR_ACCOUNT,
    END_ACTOR_KEY_SHARE,
    NOT_OWNER,
    OK200,
    PATIENCE,
    ROLE_CATALOGUE,
    NthGate,
    Pool,
    blocked_view,
    deadlocks_now,
    finish,
    insert_role,
    membership_pair,
    pool,
    post,
    rows,
    settled_deadlock_delta,
    transfer_audits,
    transfer_body,
    wait_expired,
)
from tests.deadline_diagnostics import deadline_message
from tests.factories import (
    make_campaign_membership,
    make_system_role_assignment,
    make_user,
    system_role_id,
)
from tests.http_race_support import StatementGate, run_in_thread, sessions_blocked_by
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

WAIT_CAMPAIGN_KEY_SHARE = re.compile(
    r"^SELECT campaign\.campaigns\.campaign_id FROM campaign\.campaigns WHERE .*FOR KEY SHARE$"
)
WAIT_MEMBERSHIP = re.compile(r"FROM security\.campaign_memberships")
RECOVERY_CAMPAIGN_NKU = (
    r"^SELECT 1 FROM campaign\.campaigns WHERE campaign_id = \S+ FOR NO KEY UPDATE$"
)
RECOVERY_MEMBERSHIP = (
    r"^SELECT campaign_membership_id FROM security\.campaign_memberships WHERE campaign_id = \S+ "
    r"AND user_id = \S+ AND ended_at IS NULL FOR UPDATE$"
)
ACCEPT_CAMPAIGN_SHARE = (
    r"^SELECT lifecycle_status_id FROM campaign\.campaigns WHERE campaign_id = \S+ FOR SHARE$"
)
ARCHIVE_AFTER_CAMPAIGN_LOCK = (
    r"^SELECT c\.name, c\.description, c\.row_version, c\.lifecycle_status_id, c\.timeline_id "
    r"FROM campaign\.campaigns c WHERE c\.campaign_id = \S+$"
)


# -- orchestration -----------------------------------------------------------------------------------------------


@dataclass
class Raw:
    results: dict[
        str, Any
    ]  # "parked" / "second" -> (status, error code) | ("raised", exception class name)
    queued: list[dict[str, Any]] | None
    failures: list[tuple[str | None, str]]
    deadlock_delta: int
    gate: str | None

    def summary(self) -> str:
        return (
            f"results={self.results} queued={[q['query'].strip()[:110] for q in self.queued or []]} "
            f"failures={self.failures} deadlocks={self.deadlock_delta} gate={self.gate!r}"
        )


def normalised(call: Callable[[], Any]) -> Callable[[], Any]:
    """An HTTP response becomes (status, error code); a raised command exception becomes ("raised", its class)."""

    def run() -> Any:
        try:
            value = call()
        except Exception as exc:  # noqa: BLE001 - the case asserts the class
            return ("raised", type(exc).__name__)
        if hasattr(value, "status_code"):
            return (code(value), error_of(value))
        return ("ok", value)

    return run


def orchestrate(
    w: World,
    p: Pool,
    *,
    gate_pattern: str,
    parked: Callable[[], Any],
    second: Callable[[], Any],
    nth: int = 1,
) -> Raw:
    before = deadlocks_now(w.engine)
    with NthGate(p.engine, gate_pattern, nth) as gate:
        first = run_in_thread("parked", normalised(parked))
        if not gate.reached.wait(PATIENCE):
            gate.release()
            finish(first, "parked finishes")
            raise AssertionError(
                f"INCOMPATIBLE GATE (not a finding): {gate_pattern!r} never executed"
            )
        later = run_in_thread("second", normalised(second))
        queued: list[dict[str, Any]] | None = None
        assert gate.pid is not None
        deadline = time.monotonic() + PATIENCE
        while time.monotonic() < deadline:
            if sessions_blocked_by(w.engine, gate.pid) >= 1:
                queued = blocked_view(w.engine, gate.pid)
                break
            if later.finished():
                break
            time.sleep(0.02)
        else:
            raise AssertionError(
                "the second request neither queued nor finished"
                f"{deadline_message('second request neither queued nor finished', engine=w.engine)}"
            )
        statement = gate.matched
        gate.release()
        results = {
            "parked": finish(first, "parked finishes"),
            "second": finish(later, "second finishes"),
        }
    delta = settled_deadlock_delta(w.engine, p, before)
    return Raw(results, queued, list(p.failures), delta, statement)


def assert_no_deadlock(raw: Raw) -> None:
    assert not raw.failures, f"driver exceptions (40P01 = deadlock): {raw.summary()}"
    assert raw.deadlock_delta == 0, raw.summary()


def assert_queued_on(raw: Raw, pattern: re.Pattern[str] | None) -> None:
    if pattern is None:
        assert raw.queued is None, f"the second request queued: {raw.summary()}"
        return
    assert raw.queued, f"the second request never queued: {raw.summary()}"
    for row in raw.queued:
        assert len(row["blockers"]) == 1, f"more than one blocker: {raw.summary()}"
        assert pattern.search(row["query"].strip()), f"waited on {row['query']!r}: {raw.summary()}"


def owners_of(w: World, **members: uuid.UUID) -> dict[str, bool]:
    return {name: live_owner(w, m) for name, m in members.items()}


# ======================================================================================================================
# 1. The COMMIT-time upgrade guard: a request that owes a role UPDATE must hold the campaign FOR UPDATE
# ======================================================================================================================


@pytest.mark.parametrize("kind", ("relinquishing", "expired_replacement"))
def test_two_role_updating_transfers_never_upgrade_a_campaign_lock_at_commit(
    kind: str, w: World, pool: Pool
) -> None:
    """Two owners A and B transfer to two different recipients; each request owes a role-row UPDATE (A and B
    relinquish, or each replaces its recipient's expired owner row). Each UPDATE queues the deferred retention trigger,
    which takes the campaign `FOR UPDATE` at COMMIT. If the transfers took the campaign only `FOR KEY SHARE` they would
    both hold it and each COMMIT would wait for the other's: a deadlock. With the campaign `FOR UPDATE` taken *before*
    the writes, the second transfer queues on the campaign statement (observed here, behind the parked first) and both
    answer 200."""
    make_managers(w.engine, w.campaign_id, label="UG")
    relinquish = kind == "relinquishing"
    with w.engine.begin() as c:
        owner = system_role_id(c, "campaign_owner")
        a_user, b_user = make_user(c, "UG A"), make_user(c, "UG B")
        a_m = make_campaign_membership(c, w.campaign_id, a_user)
        b_m = make_campaign_membership(c, w.campaign_id, b_user)
        r1_m = make_campaign_membership(c, w.campaign_id, make_user(c, "UG R1"))
        r2_m = make_campaign_membership(c, w.campaign_id, make_user(c, "UG R2"))
        for m in (a_m, b_m):
            insert_role(c, None, m, owner)
        if not relinquish:
            for m in (r1_m, r2_m):
                expired_owner(c, m)
        else:
            for m in (r1_m, r2_m):
                insert_role(c, None, m, system_role_id(c, "player"))
    audits = transfer_audits(w.engine)

    def transfer(user: uuid.UUID, target: uuid.UUID) -> Any:
        return post(pool, user, f"{w.base}/ownership-transfer", transfer_body(target, relinquish))

    raw = orchestrate(
        w,
        pool,
        gate_pattern=ROLE_CATALOGUE,  # parked after the campaign lock: A holds the campaign
        parked=lambda: transfer(a_user, r1_m),
        second=lambda: transfer(b_user, r2_m),
    )
    assert_no_deadlock(raw)
    assert_queued_on(raw, WAIT_CAMPAIGN_UPDATE)
    assert raw.results == {"parked": OK200, "second": OK200}, raw.summary()
    assert transfer_audits(w.engine) == audits + 2
    assert owners_of(w, a=a_m, b=b_m, r1=r1_m, r2=r2_m) == {
        "a": not relinquish,
        "b": not relinquish,
        "r1": True,
        "r2": True,
    }
    if not relinquish:
        for m in (r1_m, r2_m):
            assert [r for r in owner_rows(w, m) if r[1] and not r[2]] == [], (
                "the expired rows were closed"
            )


# ======================================================================================================================
# 2. Pairs whose role-class wait M2 removes (design 3.4; BA-E10-1)
# ======================================================================================================================


@pytest.mark.parametrize("arrival", ("relinquishing_parked", "non_relinquishing_parked"))
def test_same_owner_relinquishing_and_non_relinquishing_transfers(
    arrival: str, w: World, pool: Pool
) -> None:
    """BA-E10-1: owner A transfers to B relinquishing and to C not relinquishing at once. The role-class wait
    (NO KEY UPDATE x NO KEY UPDATE) is gone, so they serialize at the campaign/catalogue rows and the *unparked*
    request is decided first; both outcomes are ones the pre-correction code produced in the other arrival."""
    make_managers(w.engine, w.campaign_id, label="SO")
    with w.engine.begin() as c:
        owner = system_role_id(c, "campaign_owner")
        a_user = make_user(c, "SO A")
        a_m = make_campaign_membership(c, w.campaign_id, a_user)
        insert_role(c, None, a_m, owner)
        b_m = make_campaign_membership(c, w.campaign_id, make_user(c, "SO B"))
        c_m = make_campaign_membership(c, w.campaign_id, make_user(c, "SO C"))
    audits = transfer_audits(w.engine)

    def relinquishing() -> Any:
        return post(pool, a_user, f"{w.base}/ownership-transfer", transfer_body(b_m, True))

    def plain() -> Any:
        return post(pool, a_user, f"{w.base}/ownership-transfer", transfer_body(c_m, False))

    if arrival == "relinquishing_parked":
        raw = orchestrate(w, pool, gate_pattern=ACTOR_ACCOUNT, parked=relinquishing, second=plain)
        expected = {"parked": OK200, "second": OK200}
        final = {"a": False, "b": True, "c": True}
        audit_delta = 2
    else:
        raw = orchestrate(w, pool, gate_pattern=ACTOR_ACCOUNT, parked=plain, second=relinquishing)
        expected = {"parked": NOT_OWNER, "second": OK200}
        final = {"a": False, "b": True, "c": False}
        audit_delta = 1
    assert_no_deadlock(raw)
    assert_queued_on(raw, None)  # the second request is never held up by the parked one
    assert raw.results == expected, raw.summary()
    assert owners_of(w, a=a_m, b=b_m, c=c_m) == final
    assert transfer_audits(w.engine) == audits + audit_delta


@pytest.mark.parametrize("arrival", ("relinquishing_parked", "non_relinquishing_parked"))
def test_mixed_mutual_transfers_between_two_owners(arrival: str, w: World, pool: Pool) -> None:
    """Owners A and C transfer to each other, C relinquishing and A not. Unchanged by the correction: they serialize at
    the memberships. If C's relinquish commits first, A's request meets a changed recipient (409); if A's no-op
    commits first, C's relinquish then succeeds. A is the owner afterwards in both."""
    make_managers(w.engine, w.campaign_id, label="MM")
    cast = membership_pair(
        w, "cmC_below_cmX", "MM", c_roles=("campaign_owner",), x_roles=("campaign_owner",)
    )
    audits = transfer_audits(w.engine)

    def c_to_a_relinquishing() -> Any:
        return post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, True)
        )

    def a_to_c() -> Any:
        return post(
            pool, cast.x_user, f"{w.base}/ownership-transfer", transfer_body(cast.c_m, False)
        )

    if arrival == "relinquishing_parked":
        raw = orchestrate(
            w, pool, gate_pattern=ACTOR_ACCOUNT, parked=c_to_a_relinquishing, second=a_to_c
        )
        expected = {"parked": OK200, "second": (409, "ownership_transfer_recipient_changed")}
    else:
        raw = orchestrate(
            w, pool, gate_pattern=ACTOR_ACCOUNT, parked=a_to_c, second=c_to_a_relinquishing
        )
        expected = {"parked": OK200, "second": OK200}
    assert_no_deadlock(raw)
    assert_queued_on(raw, WAIT_MEMBERSHIP)
    assert raw.results == expected, raw.summary()
    assert owners_of(w, c=cast.c_m, a=cast.x_m) == {"c": False, "a": True}
    assert transfer_audits(w.engine) == audits + 1


class HoldAllGate(StatementGate):
    """Holds EVERY statement matching `pattern` (a `StatementGate` stops only the first) until released, and signals
    `reached` once `expected` of them are held."""

    def __init__(self, engine: Any, pattern: str, expected: int) -> None:
        super().__init__(engine, pattern)
        self.expected = expected
        self.held = 0
        self._lock = threading.Lock()

    def _hook(self, conn: Any, cursor: Any, statement: Any, *rest: Any) -> None:
        if not self.pattern.search(" ".join(str(statement).split())):
            return
        with self._lock:
            self.held += 1
            if self.held >= self.expected:
                self.reached.set()
        self.resume.wait(PATIENCE)


def test_a_lapsed_owners_self_transfer_twice_at_once_refuses_both_without_a_deadlock(
    w: World, pool: Pool
) -> None:
    """An owner whose own owner row expires after the route admitted it (unrevoked, now expired) self-transfers twice
    at once: the actor rows are locked KEY SHARE and the recipient-expired lock then takes NO KEY UPDATE on that same
    row (a compatible KS -> NKU step, never an S -> NKU upgrade). The two requests serialize on that row; both are
    refused by the owner gate (403) and neither deadlocks. Both are held after the route's access check and before any
    transfer lock until the row has expired."""
    make_managers(w.engine, w.campaign_id, label="LS")
    with w.engine.begin() as c:
        user = make_user(c, "LS lapsing")
        m = make_campaign_membership(c, w.campaign_id, user)
        row = insert_role(c, None, m, system_role_id(c, "campaign_owner"))
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = clock_timestamp() + interval '3 seconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": row},
        )
    audits = transfer_audits(w.engine)
    before = deadlocks_now(w.engine)
    first_statement = r"^SELECT role_id FROM security\.roles WHERE code = 'campaign_owner' AND campaign_id IS NULL$"
    with HoldAllGate(pool.engine, first_statement, 2) as gate:
        requests = [
            run_in_thread(
                f"lapsing-{i}",
                lambda: post(pool, user, f"{w.base}/ownership-transfer", transfer_body(m, False)),
            )
            for i in range(2)
        ]
        assert gate.reached.wait(PATIENCE), (
            "both requests passed the route's access check and were held"
        )
        wait_expired(w.engine, row)
        gate.release()
        results = [finish(r, "lapsed self-transfer finishes") for r in requests]
    delta = settled_deadlock_delta(w.engine, pool, before)
    assert not pool.failures, f"driver exceptions (40P01 = deadlock): {pool.failures}"
    assert delta == 0
    assert [(code(r), error_of(r)) for r in results] == [NOT_OWNER, NOT_OWNER]
    assert transfer_audits(w.engine) == audits


# ======================================================================================================================
# 3. The transfer against the membership end, both arrivals (E4)
# ======================================================================================================================


@pytest.mark.parametrize("arrival", ("transfer_parked", "end_parked"))
def test_e4_ending_the_recipients_membership_and_the_transfer_to_it_serialize(
    arrival: str, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="E4")
    cast = membership_pair(
        w, "cmC_below_cmX", "E4", c_roles=("campaign_owner",), x_roles=("player",)
    )
    audits = transfer_audits(w.engine)

    def end() -> Any:
        return post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end")

    def transfer() -> Any:
        return post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
        )

    if arrival == "end_parked":
        raw = orchestrate(w, pool, gate_pattern=END_ACTOR_KEY_SHARE, parked=end, second=transfer)
        expected = {"parked": OK200, "second": (409, "conflict")}
        recipient_owner, audit_delta = False, 0
    else:
        raw = orchestrate(w, pool, gate_pattern=ACTOR_ACCOUNT, parked=transfer, second=end)
        expected = {"parked": OK200, "second": OK200}
        recipient_owner, audit_delta = None, 1  # decided below
    assert_no_deadlock(raw)
    assert_queued_on(raw, WAIT_MEMBERSHIP)
    assert raw.results == expected, raw.summary()
    assert transfer_audits(w.engine) == audits + audit_delta
    open_membership = rows(
        w.engine,
        "SELECT ended_at IS NULL AS open FROM security.campaign_memberships WHERE campaign_membership_id = :m",
        m=cast.x_m,
    )[0]["open"]
    assert open_membership is False, "the recipient's membership ended"
    if recipient_owner is not None:
        assert live_owner(w, cast.x_m) is recipient_owner
    assert live_owner(w, cast.c_m), "the actor keeps its ownership"


# ======================================================================================================================
# 4. Recovery (E8), invitation acceptance (E9) and campaign archive (E11) against the transfer
# ======================================================================================================================


def recovery_scene(
    w: World,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A campaign whose only non-expiring access manager (its creator) is on an ARCHIVED account, so recovery may run:
    the actor C holds only a FINITE owner row (30 days; it can still transfer), R is the recipient, M another member,
    ADMIN a platform administrator. Returns (c_user, c_m, r_user, r_m, m_user, admin)."""
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                "core.lifecycle_statuses WHERE code = 'archived') WHERE user_id = :u"
            ),
            {"u": w.owner},
        )
        c_user = make_user(c, "RC actor")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        c.execute(
            text(
                "INSERT INTO security.membership_roles (campaign_membership_id, role_id, expires_at) "
                "VALUES (:m, :r, now() + interval '30 days')"
            ),
            {"m": c_m, "r": system_role_id(c, "campaign_owner")},
        )
        r_user = make_user(c, "RC recipient")
        r_m = make_campaign_membership(c, w.campaign_id, r_user)
        m_user = make_user(c, "RC other")
        make_campaign_membership(c, w.campaign_id, m_user)
        admin = make_user(c, "RC admin")
        make_system_role_assignment(c, admin, "admin")
    with w.engine.connect() as c:
        assert not campaign_has_active_access_manager(c, campaign_id=w.campaign_id), (
            "premise: no non-expiring access manager on an active account, so recovery may run"
        )
    return c_user, c_m, r_user, r_m, m_user, admin


@pytest.mark.parametrize("promoted", ("the_recipient", "another_member"))
@pytest.mark.parametrize("arrival", ("transfer_parked", "recovery_parked"))
def test_e8_recovery_against_a_transfer_by_a_finite_owner(
    arrival: str, promoted: str, w: World, pool: Pool
) -> None:
    """Recovery takes the promoted member's membership `FOR UPDATE`, then the campaign `FOR NO KEY UPDATE`; the
    transfer (insert branch, campaign `FOR KEY SHARE`) takes the recipient's membership `FOR UPDATE` and then the
    campaign. Promoting the recipient serializes at the membership; promoting someone else does not serialize at the
    campaign (NKU x KS are compatible) and the outcome equals one serial order. The campaign always keeps a manager."""
    c_user, c_m, r_user, r_m, m_user, admin = recovery_scene(w)
    target_user = r_user if promoted == "the_recipient" else m_user
    audits = transfer_audits(w.engine)

    def transfer() -> Any:
        return post(pool, c_user, f"{w.base}/ownership-transfer", transfer_body(r_m, False))

    def recovery() -> Any:
        with pool.engine.begin() as connection:
            return recover_campaign_access_manager(
                connection,
                admin_user_id=admin,
                campaign_id=w.campaign_id,
                new_user_id=target_user,
                reason="E8 recovery",
            ).campaign_membership_id

    if arrival == "transfer_parked":
        raw = orchestrate(w, pool, gate_pattern=ACTOR_ACCOUNT, parked=transfer, second=recovery)
    else:
        raw = orchestrate(
            w,
            pool,
            gate_pattern=RECOVERY_CAMPAIGN_NKU
            if promoted == "the_recipient"
            else RECOVERY_MEMBERSHIP,
            nth=1 if promoted == "the_recipient" else 2,
            parked=recovery,
            second=transfer,
        )
    assert_no_deadlock(raw)
    transfer_result = raw.results["parked" if arrival == "transfer_parked" else "second"]
    recovery_result = raw.results["second" if arrival == "transfer_parked" else "parked"]
    expected = EXPECTED_E8[(arrival, promoted)]
    recovery_kind = (
        recovery_result[0],
        recovery_result[1] if recovery_result[0] == "raised" else None,
    )
    assert (transfer_result, *recovery_kind) == expected, raw.summary()
    assert transfer_audits(w.engine) == audits + (1 if transfer_result == OK200 else 0)
    # every combination: the campaign still has a non-expiring access manager, and nobody holds two live owner rows
    with w.engine.connect() as c:
        assert campaign_has_active_access_manager(c, campaign_id=w.campaign_id)
    assert len([r for r in owner_rows(w, r_m) if r[1] and r[2]]) <= 1
    assert live_owner(w, r_m) is (transfer_result == OK200 or promoted == "the_recipient")
    if recovery_kind[0] == "ok":
        assert live_owner(w, recovery_result[1]), "the promoted member holds a live owner row"


#: (arrival, promoted) -> (transfer result, recovery result kind, recovery exception class when it raised)
EXPECTED_E8: dict[tuple[str, str], tuple[Any, str, str | None]] = {
    # the transfer parked after the recipient's membership: recovery for the recipient queues, then finds a manager
    ("transfer_parked", "the_recipient"): (OK200, "raised", "RecoveryNotNeededError"),
    # recovery for another member does not queue: it promotes first (a finite actor leaves none), the transfer follows
    ("transfer_parked", "another_member"): (OK200, "ok", None),
    # recovery parked holding the recipient's membership: the transfer queues, then meets the owner row recovery wrote
    ("recovery_parked", "the_recipient"): (
        (409, "ownership_transfer_recipient_changed"),
        "ok",
        None,
    ),
    # recovery parked under the campaign NO KEY UPDATE, after its "no manager" check, for another member: the transfer
    # (campaign KEY SHARE) does not wait and commits; recovery then promotes (serial order: recovery, then transfer)
    ("recovery_parked", "another_member"): (OK200, "ok", None),
}


@pytest.mark.parametrize("arrival", ("accept_parked", "transfer_parked"))
def test_e9_invitation_acceptance_reopening_the_recipient_against_a_transfer(
    arrival: str, w: World, pool: Pool
) -> None:
    """The recipient's membership ended and its user accepts an invitation (reopening it) while the owner transfers
    to it. Acceptance takes the membership `FOR NO KEY UPDATE`, then the campaign `FOR SHARE`; reopening queues the
    retention trigger (campaign `FOR UPDATE` at COMMIT). The transfer's recipient-membership `FOR UPDATE` serializes
    them before either takes a campaign lock."""
    make_managers(w.engine, w.campaign_id, label="E9")
    cast = membership_pair(
        w, "cmC_below_cmX", "E9", c_roles=("campaign_owner",), x_roles=("player",)
    )
    ended = post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end")
    assert code(ended) == 200
    with w.engine.begin() as c:
        invitation = create_campaign_invitation(
            c,
            campaign_id=w.campaign_id,
            invited_by_membership_id=cast.c_m,
            ttl=timedelta(days=1),
        )
    audits = transfer_audits(w.engine)

    def accept() -> Any:
        with pool.engine.begin() as connection:
            return accept_campaign_invitation(
                connection, token=invitation.token, accepting_user_id=cast.x_user
            ).campaign_membership_id

    def transfer() -> Any:
        return post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
        )

    if arrival == "accept_parked":
        raw = orchestrate(
            w, pool, gate_pattern=ACCEPT_CAMPAIGN_SHARE, parked=accept, second=transfer
        )
        accept_result, transfer_result = raw.results["parked"], raw.results["second"]
        expect_owner = True
    else:
        raw = orchestrate(w, pool, gate_pattern=ACTOR_ACCOUNT, parked=transfer, second=accept)
        accept_result, transfer_result = raw.results["second"], raw.results["parked"]
        expect_owner = False
    assert_no_deadlock(raw)
    assert_queued_on(raw, WAIT_MEMBERSHIP)
    assert accept_result == ("ok", cast.x_m), raw.summary()
    # reopened in place: the same membership id is open afterwards
    assert rows(
        w.engine,
        "SELECT ended_at IS NULL AS open FROM security.campaign_memberships WHERE campaign_membership_id = :m",
        m=cast.x_m,
    )[0]["open"]
    if expect_owner:
        assert transfer_result == OK200, raw.summary()
        assert transfer_audits(w.engine) == audits + 1
    else:
        assert transfer_result == (409, "conflict"), raw.summary()
        assert transfer_audits(w.engine) == audits
    assert live_owner(w, cast.x_m) is expect_owner
    assert live_owner(w, cast.c_m)


@pytest.mark.parametrize("arrival", ("transfer_parked", "archive_parked"))
def test_e11_campaign_archive_against_a_transfer(arrival: str, w: World, pool: Pool) -> None:
    """Archive takes the campaign `FOR UPDATE`; the transfer (insert branch) takes it `FOR KEY SHARE`: they conflict,
    and `finalize` re-resolves the route requirement against the archived campaign. Exactly one of them wins; the
    archive commits and the transfer is refused after the wait, never both."""
    managers = make_managers(w.engine, w.campaign_id, label="E11")
    cast = membership_pair(
        w, "cmC_below_cmX", "E11", c_roles=("campaign_owner",), x_roles=("player",)
    )
    audits = transfer_audits(w.engine)
    version = rows(
        w.engine,
        "SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c",
        c=w.campaign_id,
    )[0]["row_version"]

    def archive() -> Any:
        return post(
            pool,
            managers.manager_user,
            f"{w.base}/archive",
            {"expected_row_version": version, "reason": "E11"},
        )

    def transfer() -> Any:
        return post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
        )

    if arrival == "transfer_parked":
        raw = orchestrate(w, pool, gate_pattern=ACTOR_ACCOUNT, parked=transfer, second=archive)
        archive_result, transfer_result = raw.results["second"], raw.results["parked"]
        queued: re.Pattern[str] | None = None
    else:
        raw = orchestrate(
            w, pool, gate_pattern=ARCHIVE_AFTER_CAMPAIGN_LOCK, parked=archive, second=transfer
        )
        archive_result, transfer_result = raw.results["parked"], raw.results["second"]
        queued = WAIT_CAMPAIGN_KEY_SHARE
    assert_no_deadlock(raw)
    assert_queued_on(raw, queued)
    assert archive_result == OK200, raw.summary()
    assert transfer_result == (404, "not_found"), (
        raw.summary()
    )  # finalize re-resolves the route against the archived campaign
    assert transfer_audits(w.engine) == audits, "the refused transfer wrote no audit row"
    assert not live_owner(w, cast.x_m), "the refused transfer wrote no owner row"
    status = rows(
        w.engine,
        "SELECT ls.code FROM campaign.campaigns c JOIN core.lifecycle_statuses ls "
        "ON ls.lifecycle_status_id = c.lifecycle_status_id WHERE c.campaign_id = :c",
        c=w.campaign_id,
    )[0]["code"]
    assert status == "archived"
