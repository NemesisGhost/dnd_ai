# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 O-2 (design 1.2 R-C, 1.3, decision D-3): the two revelation routes are not opted in, and their reservation follows
their own campaign `FOR KEY SHARE`.

The create and revoke commands lock the caller's reveal authority, the target and the membership, then the campaign
(`_lock_caller_and_campaign`), judge the fresh authority and only then call `reserve()`, which runs the idempotency
reservation. Their reservation's campaign foreign-key check therefore re-locks a row the request already holds and cannot
wait. This test runs both routes keyed on a real connection and pins that order at run time: a campaign `FOR KEY SHARE`
precedes the reservation `INSERT`, no `SET CONSTRAINTS` (the deferral) is issued, and no evidence statement is taken. The
static pin of the same facts is `tests/unit/test_r01_o2_structure.py`.
"""

import re
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine

from tests.database.test_character_revelations import member_body
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures by name
    Factory,
    Gate,
    Members,
    Recorder,
    _seed_release,
    code,
    g,
    m,
    npc,
    pooled,
    pooled_factory,
)
from tests.http_race_support import new_key

pytestmark = pytest.mark.database

_CAMPAIGN_KEY_SHARE = re.compile(r"FROM campaign\.campaigns\b.*FOR KEY SHARE", re.IGNORECASE)
_RESERVATION = "INSERT INTO security.idempotent_requests"


def _assert_late(events: list[str], what: str) -> None:
    statements = [e for e in events if e != "COMMIT"]
    reserved = [i for i, s in enumerate(statements) if s.startswith(_RESERVATION)]
    assert len(reserved) == 1, (what, "exactly one reservation INSERT", reserved)
    locks = [i for i, s in enumerate(statements) if _CAMPAIGN_KEY_SHARE.search(s)]
    assert locks and locks[0] < reserved[0], (
        what,
        "the campaign KEY SHARE precedes the reservation",
        locks,
        reserved,
    )
    assert not any("SET CONSTRAINTS" in s for s in statements), (what, "the route never defers")
    # the plan's evidence statement carries the plan's own bind and is a distinct, validated statement
    assert not any("CAST(%(campaign)s::UUID AS pg_catalog.uuid)" in s for s in statements), (
        what,
        "no campaign-evidence validation statements",
    )


def test_a_keyed_revelation_create_and_revoke_reserve_after_their_own_campaign_lock(
    postgres_engine: Engine,
    pooled: Engine,
    pooled_factory: Factory,
    g: Gate,
    m: Members,
    npc: uuid.UUID,
) -> None:
    _seed_release(postgres_engine, g, npc)
    with pooled_factory(m.gm_user_id) as client:
        with Recorder(pooled) as created_events:
            created = client.post(
                f"/campaigns/{g.campaign_id}/characters/{npc}/revelations",
                json=member_body(m.gm),
                headers={"Idempotency-Key": new_key()},
            )
        assert code(created) == 201, created.text
        revelation = created.json()["character_revelation_id"]
        _assert_late(created_events.events, "create")
        with Recorder(pooled) as revoked_events:
            revoked: Any = client.post(
                f"/campaigns/{g.campaign_id}/characters/{npc}/revelations/{revelation}/revoke",
                json={"reason": "No longer needed"},
                headers={"Idempotency-Key": new_key()},
            )
        assert code(revoked) == 200, revoked.text
        _assert_late(revoked_events.events, "revoke")
