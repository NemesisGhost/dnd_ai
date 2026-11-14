"""R01 S5-D test support: campaign managers whose authority can lapse, and the gates that make a lapse
land between a request's early check and its final authority statement.

`access.manage` is held through two campaign roles: a `keeper` whose role never expires or ends (it
satisfies the access-manager retention trigger, which refuses a change that would leave the campaign with
no non-expiring manager) and a `manager` whose role can be revoked or made to lapse. Nothing here sleeps for
a fixed time: every wait polls a DATABASE condition or a `pg_blocking_pids` relation.
"""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text

from tests.database.test_r01_s2_profile_routes import FINAL
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_user,
)
from tests.http_race_support import StatementGate, run_in_thread


@dataclass
class Managers:
    keeper_user: uuid.UUID
    keeper_membership: uuid.UUID
    manager_user: uuid.UUID
    manager_membership: uuid.UUID
    manager_role: uuid.UUID


def make_managers(engine: Engine, campaign_id: uuid.UUID, *, label: str) -> Managers:
    """A non-expiring manager and a revocable one, each through its own campaign role."""
    with engine.begin() as connection:
        capability = connection.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = 'access.manage'")
        ).scalar_one()
        keeper_user = make_user(connection, f"{label} Keeper")
        keeper_membership = make_campaign_membership(connection, campaign_id, keeper_user)
        keeper_role = make_role(connection, campaign_id=campaign_id)
        make_role_capability(connection, keeper_role, capability)
        make_membership_role(connection, keeper_membership, keeper_role)
        manager_user = make_user(connection, f"{label} Manager")
        manager_membership = make_campaign_membership(connection, campaign_id, manager_user)
        manager_role_template = make_role(connection, campaign_id=campaign_id)
        make_role_capability(connection, manager_role_template, capability)
        manager_role = make_membership_role(connection, manager_membership, manager_role_template)
    return Managers(keeper_user, keeper_membership, manager_user, manager_membership, manager_role)


def revoke_role(engine: Engine, role: uuid.UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() "
                "WHERE membership_role_id = :r"
            ),
            {"r": role},
        )


def wait_lapsed(engine: Engine, role: uuid.UUID) -> None:
    """Polls the DATABASE condition (never a fixed sleep): the role's `expires_at` is past."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.execute(
                text(
                    "SELECT expires_at <= clock_timestamp() FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": role},
            ).scalar_one():
                return
        threading.Event().wait(0.1)
    raise AssertionError("the role never lapsed")


def run_with_role_lapsing_before_final(
    engine: Engine,
    app_engine: Engine,
    role: uuid.UUID,
    call: Callable[[], Any],
    *,
    first_gate: str,
) -> Any:
    """Runs `call` (an HTTP request) so that `role` is valid for every early check and has lapsed by the
    final authority statement, however fast the request runs.

    The request is paused at `first_gate` (a statement it runs before taking any lock that conflicts with a
    role update: its key lock, or its first plan lock), after the route's early check. `expires_at` is set to
    the request's own transaction start plus one second (every early check judges at `now()`, that start; the
    final check judges at `clock_timestamp()`). The request then runs to the final authority statement,
    where it is paused until the database reports the role lapsed."""
    with (
        StatementGate(app_engine, first_gate) as first,
        StatementGate(app_engine, FINAL) as final,
    ):
        request = run_in_thread("s5d-request", call)
        first.wait_reached()
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            moved = connection.execute(
                text("""
                    UPDATE security.membership_roles
                    SET expires_at = (
                        SELECT xact_start FROM pg_stat_activity WHERE pid = :pid
                    ) + interval '1 second'
                    WHERE membership_role_id = :r AND revoked_at IS NULL
                """),
                {"pid": first.pid, "r": role},
            ).rowcount
            assert moved == 1
        first.release()
        final.wait_reached()
        wait_lapsed(engine, role)
        final.release()
        return request.wait("the gated request finishes")
