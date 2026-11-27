# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S02 correction S02-R2: the delegation grant judges its recipient in the final authorization statement.

Plan section 3.2 ("Recipient"; the final-recipient instant). The finding: after the last lock wait the grant read
the grantee's live `assistant_gm` assignment with a plain statement bound to a preceding `clock_timestamp()`, and
`plan.finalize` re-judged only the grantor. The grantee's `assistant_gm` row is locked `FOR UPDATE` and the grantee's
membership `FOR NO KEY UPDATE`, which stop concurrent row changes, but neither stops wall time (expiry) and the
grantee's **account** row is not locked at all. So a recipient that stopped being eligible between that read and the
final statement still received a delegation and its audit row.

The correction judges the recipient (membership of this campaign, open and active; account active; the bound built-in
`assistant_gm` row unrevoked, unexpired at the final `t_auth`, its role active; and that row the one the grant locked)
inside `plan.finalize`'s one statement. A refusal there is before any write, so nothing is written and nothing is
audited.

Synchronization is observable: the request is parked by statement gates and released after the change is committed
(or, for expiry, after the database reports the role lapsed, `wait_lapsed`). The expiry case's one timing dependency
is stated and checked: `expires_at` is set to one second after the moment the request is parked before its role lock,
and the case asserts from the request's own bound parameter that its eligibility read judged an instant before that
expiry (otherwise the case is inconclusive and fails, never passes).

Test-first record: at the correction baseline (`7339d3e`) the expiry and the account cases fail (201, one delegation and
one audit row); the positive control and the membership-protection case pass (guards).
"""

import re
import uuid
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine, event, text

from tests.database.test_assign_control_delegation import (  # noqa: F401 - fixtures used by name
    DELEGATION_COMMANDS,
    _tidy_delegation_audit,
    assistant_row,
    audits,
    delegations,
    grant,
)
from tests.database.test_control_assignment_commands import (  # noqa: F401 - fixtures used by name
    Env,
    Factory,
    _tidy,
    env,
)
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    Scene,
    m,
    s,
)
from tests.http_race_support import StatementGate, run_in_thread
from tests.lock_race_support import LockRace
from tests.r01_s5d_support import wait_lapsed

pytestmark = pytest.mark.database

#: The grant's lock of the grantee's `assistant_gm` row (the role class, `FOR UPDATE`): the request takes no lock on that
#: row before it, so the row can still be updated while the request is parked here.
ASSISTANT_LOCK = r"^SELECT security\.membership_roles\.membership_role_id FROM security\.membership_roles WHERE .* FOR UPDATE$"
#: The grant's pre-finalization eligibility read (the plain statement bound to a preceding `clock_timestamp()`).
PRECHECK = re.compile(
    r"r\.code = 'assistant_gm' AND r\.is_active AND mr\.revoked_at IS NULL "
    r"AND \(mr\.expires_at IS NULL OR mr\.expires_at > %\(t\)s\)"
)
NOT_ASSISTANT = "assign_control_recipient_not_assistant_gm"


class PrecheckInstant:
    """Records the instant the grant's eligibility read was bound to (its `t` parameter)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.instants: list[datetime] = []

    def _hook(self, _c: Any, _cur: Any, statement: Any, parameters: Any, *_: Any) -> None:
        if PRECHECK.search(" ".join(str(statement).split())) and isinstance(parameters, dict):
            self.instants.append(parameters["t"])

    def __enter__(self) -> "PrecheckInstant":
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *_: Any) -> None:
        event.remove(self.engine, "before_cursor_execute", self._hook)


def nothing_written(sc: Scene) -> None:
    assert delegations(sc) == []
    assert audits(sc) == {}


# --- guards (pass at the baseline) --------------------------------------------------------------------------------


def test_r2_control_the_gated_grant_succeeds_when_nothing_changes(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*control*: the same gates, released with no change: 201, one delegation, one audit row. The gates themselves
    refuse nothing."""
    with StatementGate(pooled, FINAL, strict=True) as final:
        request = final.track(
            run_in_thread("grant", lambda: grant(pooled_factory, s, env.owner.user, env.assistant))
        )
        final.wait_reached()
        final.release()
        response = request.wait("the grant finishes")
    assert code(response) == 201, response.text
    assert [d["live"] for d in delegations(s)] == [True]
    assert audits(s) == {DELEGATION_COMMANDS[0]: 1}


def test_r2_existing_protection_a_recipient_membership_change_waits_for_the_grant(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*guard*: the grantee's membership row is held `FOR NO KEY UPDATE` by the grant, so suspending that membership
    while the grant is parked before its final statement waits for the grant (observed blocked by the request's pid)
    and applies after it. The final check does not replace this protection; it adds the account and the expiry."""
    suspended = """
        UPDATE security.campaign_memberships SET membership_status_id = (
            SELECT membership_status_id FROM security.membership_statuses WHERE code = 'suspended'
        ) WHERE campaign_membership_id = :m
    """
    with StatementGate(pooled, FINAL, strict=True) as final:
        request = final.track(
            run_in_thread("grant", lambda: grant(pooled_factory, s, env.owner.user, env.assistant))
        )
        final.wait_reached()
        with LockRace(s.w.engine) as race:
            change = race.start(
                "suspend",
                lambda c: c.execute(text(suspended), {"m": env.assistant.membership}),
            )
            race.wait_blocked_by(final, expected=1)
            final.release()
            response = request.wait("the grant finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert change.error is None
    assert [d["live"] for d in delegations(s)] == [True]


# --- the regressions (fail at the baseline) ------------------------------------------------------------------------


def test_r2_a_recipient_role_expiring_after_the_eligibility_read_is_refused_at_finalize(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """The grantee's `assistant_gm` row is live at the grant's eligibility read and expired at its final statement. The
    row lock cannot stop time; the final statement judges the expiry at its own `t_auth`: 409 not-assistant, no
    delegation, no audit row (before the correction: 201, a delegation bound to an expired role, and its audit row)."""
    role = assistant_row(s, env.assistant)
    with (
        PrecheckInstant(pooled) as precheck,
        StatementGate(pooled, ASSISTANT_LOCK, strict=True) as first,
        StatementGate(pooled, FINAL, strict=True) as final,
    ):
        request = final.track(
            first.track(
                run_in_thread(
                    "grant", lambda: grant(pooled_factory, s, env.owner.user, env.assistant)
                )
            )
        )
        first.wait_reached()
        with s.w.engine.begin() as c:
            c.execute(text("SET LOCAL lock_timeout = '5s'"))
            expiry = c.execute(
                text(
                    "UPDATE security.membership_roles SET expires_at = clock_timestamp() + interval '1 second' "
                    "WHERE membership_role_id = :r AND revoked_at IS NULL RETURNING expires_at"
                ),
                {"r": role},
            ).scalar_one()
        first.release()
        final.wait_reached()
        assert len(precheck.instants) == 1, precheck.instants
        assert precheck.instants[0] < expiry, (
            "inconclusive: the eligibility read already judged an instant after the expiry"
        )
        wait_lapsed(s.w.engine, role)
        final.release()
        response = request.wait("the grant finishes")
    assert code(response) == 409, response.text
    assert error_of(response) == NOT_ASSISTANT
    nothing_written(s)


def test_r2_a_recipient_account_deactivated_after_the_eligibility_read_is_refused_at_finalize(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """The grantee's account is deactivated (and committed, without waiting: the grant holds no lock on the account
    row) while the grant is parked before its final statement. The final statement sees an inactive account: 409
    not-assistant, nothing written (before the correction: 201 and a delegation for a deactivated account)."""
    user = _user_of(s, env.assistant.membership)
    with StatementGate(pooled, FINAL, strict=True) as final:
        request = final.track(
            run_in_thread("grant", lambda: grant(pooled_factory, s, env.owner.user, env.assistant))
        )
        final.wait_reached()
        with s.w.engine.begin() as c:
            c.execute(text("SET LOCAL lock_timeout = '5s'"))
            moved = c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'inactive') WHERE user_id = :u"
                ),
                {"u": user},
            ).rowcount
            assert moved == 1
        final.release()
        response = request.wait("the grant finishes")
    assert code(response) == 409, response.text
    assert error_of(response) == NOT_ASSISTANT
    nothing_written(s)


def test_r2_the_grants_final_statement_carries_the_recipient_and_the_revoke_declares_none(
    s: Scene, env: Env, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement capture: the grant's `finalize` judges the grantor, then the recipient (in that order, after the
    route's own requirement), and its one snapshot carries the grantee's live `assistant_gm` row, which is the row the
    delegation is bound to. The revoke needs no recipient and declares none."""
    from dnd_ai.domain.authorization import AuthorizationPlan
    from tests.database.test_assign_control_delegation import revoke

    calls: list[tuple[list[Any], Any]] = []
    original = AuthorizationPlan.finalize

    def spy(plan: AuthorizationPlan, connection: Any) -> Any:
        result = original(plan, connection)
        calls.append((list(plan.requirements), result))
        return result

    monkeypatch.setattr(AuthorizationPlan, "finalize", spy)
    granted = grant(pooled_factory, s, env.owner.user, env.assistant)
    assert code(granted) == 201, granted.text
    (requirements, snapshot), *_ = calls
    names = [r.name for r in requirements]
    assert names[-2:] == [
        "assign_control_delegation.grantor",
        "assign_control_delegation.recipient_assistant_gm",
    ], names
    assert [r.assistant_gm_subject for r in requirements if r.assistant_gm_subject] == [
        env.assistant.membership
    ]
    assert snapshot.subject_assistant_membership_id == env.assistant.membership
    assert snapshot.subject_assistant_gm_assignment == assistant_row(s, env.assistant)
    assert delegations(s)[0]["bound_role"] == snapshot.subject_assistant_gm_assignment
    calls.clear()
    revoked = revoke(pooled_factory, s, env.owner.user, env.assistant)
    assert code(revoked) == 200, revoked.text
    assert calls and all(
        r.assistant_gm_subject is None for requirements, _ in calls for r in requirements
    )


def _user_of(sc: Scene, membership: uuid.UUID) -> uuid.UUID:
    with sc.w.engine.connect() as c:
        value = c.execute(
            text(
                "SELECT user_id FROM security.campaign_memberships WHERE campaign_membership_id = :m"
            ),
            {"m": membership},
        ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value
