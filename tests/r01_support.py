"""Test support for callers of R01-migrated commands that are not testing authorization (R01 S2).

A migrated command takes a required `AuthorizationPlan` (plan section 6.5, rule 1). A test that only
needs the command's effect (a fixture seeding a draft, a lock-order race) binds a **pending** plan to
its own transaction: it registers requirements as the command runs, the commit guard admits it
unfinalized, and nothing is judged. That is exactly the marker S1 gave unmigrated routes, so a test
using it asserts nothing about the final check; the S2 tests (`test_r01_s2_*.py`) drive the real
routes and the real guard instead.
"""

import uuid

from sqlalchemy import Connection

from dnd_ai.domain.authorization import AuthorizationPlan

#: The actor of a pending fixture plan. A pending plan never reads a snapshot, so no actor is judged.
FIXTURE_ACTOR = uuid.UUID(int=0)


def fixture_plan(connection: Connection, campaign_id: uuid.UUID) -> AuthorizationPlan:
    """A pending plan on `connection`'s current transaction. It judges nothing."""
    return AuthorizationPlan.begin(
        connection, actor_user_id=FIXTURE_ACTOR, campaign_id=campaign_id, pending=True
    )
