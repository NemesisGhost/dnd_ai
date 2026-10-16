"""World-creation eligibility (docs/adr/0018-world-creation-eligibility.md).

Only an active platform administrator, or an active user with an effective
assignment of the built-in (`campaign_id IS NULL`) `gm` role, may create a
world. One table of account shapes drives four checks so they cannot drift
apart: the policy function, the `create_world` command, `POST /worlds`, and the
session bootstrap's `world.create`.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.worlds import claim_unowned_world, create_world
from dnd_ai.domain.authoring import WorldCreationNotAuthorizedError
from dnd_ai.queries.world_authority import holds_effective_system_gm_role, may_create_worlds
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids, make_authored_campaign, make_authored_world
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_platform_administrator,
    make_role,
    make_user,
    make_world,
    status_id,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


# --- account shapes ----------------------------------------------------------------


@dataclass(frozen=True)
class GmCampaign:
    campaign_id: uuid.UUID


def _system_role_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text("SELECT role_id FROM security.roles WHERE code = :c AND campaign_id IS NULL"),
        {"c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _campaign(connection: Connection) -> uuid.UUID:
    """An active campaign authored through the production commands by a
    separate administrator, so it satisfies the access-manager invariant."""
    world = make_authored_world(
        connection,
        owner_user_id=make_platform_administrator(connection, "Campaign Host"),
        name=f"Host World {uuid.uuid4().hex[:6]}",
    )
    return make_authored_campaign(connection, world)


def _assign(
    connection: Connection,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None = None,
    membership_status: str = "active",
    ended: bool = False,
    revoked: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    campaign_id = campaign_id or _campaign(connection)
    membership_id = make_campaign_membership(
        connection, campaign_id, user_id, status_code=membership_status, ended=ended
    )
    return campaign_id, make_membership_role(connection, membership_id, role_id, revoked=revoked)


def _system_role(code: str) -> Callable[[Connection, uuid.UUID], None]:
    def setup(connection: Connection, user_id: uuid.UUID) -> None:
        _assign(connection, user_id, _system_role_id(connection, code))

    return setup


def _nothing(connection: Connection, user_id: uuid.UUID) -> None:
    return None


def _administrator(connection: Connection, user_id: uuid.UUID) -> None:
    connection.execute(
        text("UPDATE security.users SET is_platform_administrator = true WHERE user_id = :u"),
        {"u": user_id},
    )


def _world_owner(connection: Connection, user_id: uuid.UUID) -> None:
    # Owning a world (here, a claimed legacy one) is world authority, not
    # creation eligibility.
    world_id = make_world(connection, f"owned-{uuid.uuid4().hex[:8]}")
    claim_unowned_world(connection, world_id=world_id, user_id=user_id)


def _custom_role_named_gm(connection: Connection, user_id: uuid.UUID) -> None:
    campaign_id = _campaign(connection)
    _assign(
        connection,
        user_id,
        make_role(connection, campaign_id=campaign_id, code="gm"),
        campaign_id=campaign_id,
    )


def _revoked_gm(connection: Connection, user_id: uuid.UUID) -> None:
    _assign(connection, user_id, _system_role_id(connection, "gm"), revoked=True)


def _expired_gm(connection: Connection, user_id: uuid.UUID) -> None:
    _, membership_role_id = _assign(connection, user_id, _system_role_id(connection, "gm"))
    connection.execute(
        text("""
            UPDATE security.membership_roles
            SET granted_at = now() - interval '2 days', expires_at = now() - interval '1 day'
            WHERE membership_role_id = :m
        """),
        {"m": membership_role_id},
    )


def _suspended_gm(connection: Connection, user_id: uuid.UUID) -> None:
    _assign(connection, user_id, _system_role_id(connection, "gm"), membership_status="suspended")


def _ended_gm(connection: Connection, user_id: uuid.UUID) -> None:
    _assign(connection, user_id, _system_role_id(connection, "gm"), ended=True)


def _gm_in_archived_campaign(connection: Connection, user_id: uuid.UUID) -> None:
    campaign_id, _ = _assign(connection, user_id, _system_role_id(connection, "gm"))
    connection.execute(
        text("UPDATE campaign.campaigns SET lifecycle_status_id = :s WHERE campaign_id = :c"),
        {"s": status_id(connection, "lifecycle_statuses", "archived"), "c": campaign_id},
    )


def _gm_with_inactive_role(connection: Connection, user_id: uuid.UUID) -> None:
    role_id = _system_role_id(connection, "gm")
    _assign(connection, user_id, role_id)
    connection.execute(
        text("UPDATE security.roles SET is_active = false WHERE role_id = :r"), {"r": role_id}
    )


# Every shape a signed-in human can have; inactive accounts cannot sign in and
# are covered separately below.
SHAPES: dict[str, tuple[Callable[[Connection, uuid.UUID], None], bool]] = {
    "platform administrator without campaign membership": (_administrator, True),
    "effective built-in gm": (_system_role("gm"), True),
    "ordinary user": (_nothing, False),
    "player": (_system_role("player"), False),
    "observer": (_system_role("observer"), False),
    "assistant_gm": (_system_role("assistant_gm"), False),
    "campaign_owner": (_system_role("campaign_owner"), False),
    "world_owner": (_world_owner, False),
    "custom campaign-scoped role named gm": (_custom_role_named_gm, False),
    "revoked gm assignment": (_revoked_gm, False),
    "expired gm assignment": (_expired_gm, False),
    "suspended gm membership": (_suspended_gm, False),
    "ended gm membership": (_ended_gm, False),
    "gm in an archived campaign": (_gm_in_archived_campaign, False),
    "gm role deactivated": (_gm_with_inactive_role, False),
}


def _counts(connection: Connection, user_id: uuid.UUID) -> tuple[int, ...]:
    """Everything a world creation by `user_id` could leave behind."""
    row = connection.execute(
        text("""
            SELECT
                (SELECT count(*) FROM core.worlds),
                (SELECT count(*) FROM campaign.timelines),
                (SELECT count(*) FROM security.world_memberships WHERE user_id = :u),
                (SELECT count(*) FROM audit.change_log WHERE command_name = 'create_world'),
                (SELECT count(*) FROM security.actor_idempotent_requests
                 WHERE actor_user_id = :u)
        """),
        {"u": user_id},
    ).one()
    return tuple(int(v) for v in row)


def _body(connection: Connection, name: str) -> dict:
    ruleset_id, _ = dnd5e_ids(connection)
    return {
        "name": name,
        "description": None,
        "ruleset_ids": [str(ruleset_id)],
        "default_ruleset_id": str(ruleset_id),
        "primary_timeline": {"name": "Main", "description": None},
    }


# --- the policy, the command, the route, and the bootstrap agree -------------------


@pytest.mark.parametrize("shape", list(SHAPES))
def test_policy_command_route_and_bootstrap_agree(
    harness: AuthoringHarness, db_connection: Connection, shape: str
) -> None:
    setup, eligible = SHAPES[shape]
    actor = harness.new_actor("Subject")
    setup(db_connection, actor.user_id)

    assert may_create_worlds(db_connection, user_id=actor.user_id) is eligible

    # The bootstrap advertises world.create exactly when the command would
    # authorize the caller.
    session = actor.get("/auth/session")
    assert session.status_code == 200
    assert session.json()["global_capabilities"] == (["world.create"] if eligible else [])

    before = _counts(db_connection, actor.user_id)
    response = actor.post("/worlds", _body(db_connection, f"{shape} world"), key="policy-key")
    if eligible:
        assert response.status_code == 201, response.text
        return
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    # No world, timeline, membership, audit row, or idempotency reservation.
    assert _counts(db_connection, actor.user_id) == before

    # The command refuses on its own, without the route in front of it.
    ruleset_id, _ = dnd5e_ids(db_connection)
    savepoint = db_connection.begin_nested()
    with pytest.raises(WorldCreationNotAuthorizedError):
        create_world(
            db_connection,
            creator_user_id=actor.user_id,
            name="Direct",
            description=None,
            ruleset_ids=[ruleset_id],
            default_ruleset_id=ruleset_id,
            primary_timeline_name="Main",
        )
    savepoint.rollback()
    assert _counts(db_connection, actor.user_id) == before


def test_a_refused_request_reserves_no_key_so_a_later_eligible_retry_succeeds(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    actor = harness.new_actor("Late GM")
    body = _body(db_connection, "Retry World")
    assert actor.post("/worlds", body, key="retry-key").status_code == 403

    _administrator(db_connection, actor.user_id)
    assert actor.post("/worlds", body, key="retry-key").status_code == 201


def test_losing_eligibility_blocks_replaying_an_earlier_success(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    actor = harness.new_actor("Former GM")
    _administrator(db_connection, actor.user_id)
    body = _body(db_connection, "Once")
    assert actor.post("/worlds", body, key="replay-key").status_code == 201

    db_connection.execute(
        text("UPDATE security.users SET is_platform_administrator = false WHERE user_id = :u"),
        {"u": actor.user_id},
    )
    assert actor.post("/worlds", body, key="replay-key").status_code == 403
    assert actor.get("/auth/session").json()["global_capabilities"] == []


def test_invalid_input_from_an_ineligible_user_is_refused_before_validation(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    actor = harness.new_actor("Prober")
    body = {**_body(db_connection, "Probe"), "ruleset_ids": [str(uuid.uuid4())]}
    body["default_ruleset_id"] = body["ruleset_ids"][0]
    response = actor.post("/worlds", body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# --- accounts that cannot sign in --------------------------------------------------


@pytest.mark.parametrize("make_eligible", [_administrator, _system_role("gm")])
def test_an_inactive_account_is_never_eligible(
    db_connection: Connection, make_eligible: Callable[[Connection, uuid.UUID], None]
) -> None:
    user_id = make_user(db_connection, "Dormant")
    make_eligible(db_connection, user_id)
    assert may_create_worlds(db_connection, user_id=user_id)

    db_connection.execute(
        text("UPDATE security.users SET lifecycle_status_id = :s WHERE user_id = :u"),
        {"s": status_id(db_connection, "lifecycle_statuses", "inactive"), "u": user_id},
    )
    assert not may_create_worlds(db_connection, user_id=user_id)
    ruleset_id, _ = dnd5e_ids(db_connection)
    with pytest.raises(WorldCreationNotAuthorizedError):
        create_world(
            db_connection,
            creator_user_id=user_id,
            name="Dormant World",
            description=None,
            ruleset_ids=[ruleset_id],
            default_ruleset_id=ruleset_id,
            primary_timeline_name="Main",
        )


def test_an_unknown_user_is_not_eligible(db_connection: Connection) -> None:
    assert not may_create_worlds(db_connection, user_id=uuid.uuid4())


def test_one_effective_gm_assignment_suffices_among_lapsed_ones(
    db_connection: Connection,
) -> None:
    user_id = make_user(db_connection, "Veteran")
    _revoked_gm(db_connection, user_id)
    _ended_gm(db_connection, user_id)
    assert not holds_effective_system_gm_role(db_connection, user_id=user_id)
    _system_role("gm")(db_connection, user_id)
    assert holds_effective_system_gm_role(db_connection, user_id=user_id)


# --- eligibility grants creation only -----------------------------------------------


def test_creation_eligibility_grants_no_authority_over_other_worlds(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    owner = harness.new_actor("Owner", world_creator=True)
    world_id = owner.post("/worlds", _body(db_connection, "Private World")).json()["world_id"]

    admin = harness.new_actor("Other Admin")
    _administrator(db_connection, admin.user_id)
    gm = harness.new_actor("Other GM")
    _system_role("gm")(db_connection, gm.user_id)
    for other in (admin, gm):
        assert other.get(f"/worlds/{world_id}").status_code == 404
        assert other.get("/worlds").json()["items"] == []
        assert (
            other.post(
                f"/worlds/{world_id}/update", {"expected_row_version": 1, "name": "Mine"}
            ).status_code
            == 404
        )
