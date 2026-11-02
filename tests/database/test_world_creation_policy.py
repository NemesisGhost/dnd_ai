"""World-creation eligibility (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

Only an active user holding an unrevoked system `gm` assignment may create a
world. Platform administration, campaign roles (including the built-in campaign
`gm` template), and world ownership never confer it. One table of account shapes
drives four checks so they cannot drift apart: the policy function, the
`create_world` command, `POST /worlds`, and the session bootstrap's `world.create`.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.worlds import claim_unowned_world, create_world
from dnd_ai.domain.authoring import WorldCreationNotAuthorizedError
from dnd_ai.queries.world_authority import may_create_worlds
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids, make_authored_campaign, make_authored_world
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_platform_administrator,
    make_role,
    make_system_role_assignment,
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
    make_system_role_assignment(connection, user_id, "admin")


def _system_gm(connection: Connection, user_id: uuid.UUID) -> None:
    make_system_role_assignment(connection, user_id, "gm")


def _system_player(connection: Connection, user_id: uuid.UUID) -> None:
    # Every account already holds `player` (the default classification).
    return None


def _system_observer(connection: Connection, user_id: uuid.UUID) -> None:
    make_system_role_assignment(connection, user_id, "observer")


def _administrator_and_gm(connection: Connection, user_id: uuid.UUID) -> None:
    _administrator(connection, user_id)
    _system_gm(connection, user_id)


def _revoked_system_gm(connection: Connection, user_id: uuid.UUID) -> None:
    make_system_role_assignment(connection, user_id, "gm", revoked=True)


def _campaign_gm(connection: Connection, user_id: uuid.UUID) -> None:
    """The built-in campaign `gm` template is a campaign role: it never confers
    platform-wide creation (finding F4)."""
    _system_role("gm")(connection, user_id)


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


# Every shape a signed-in human can have; inactive accounts cannot sign in and
# are covered separately below.
SHAPES: dict[str, tuple[Callable[[Connection, uuid.UUID], None], bool]] = {
    "system gm": (_system_gm, True),
    "system administrator and gm": (_administrator_and_gm, True),
    "platform administrator alone": (_administrator, False),
    "ordinary user": (_nothing, False),
    "system player": (_system_player, False),
    "system observer": (_system_observer, False),
    "revoked system gm": (_revoked_system_gm, False),
    "campaign gm template without system gm": (_campaign_gm, False),
    "assistant_gm": (_system_role("assistant_gm"), False),
    "campaign_owner": (_system_role("campaign_owner"), False),
    "world_owner": (_world_owner, False),
    "custom campaign-scoped role named gm": (_custom_role_named_gm, False),
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
    assert ("world.create" in session.json()["global_capabilities"]) is eligible

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

    _system_gm(db_connection, actor.user_id)
    assert actor.post("/worlds", body, key="retry-key").status_code == 201


def test_losing_eligibility_blocks_replaying_an_earlier_success(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    actor = harness.new_actor("Former GM")
    _system_gm(db_connection, actor.user_id)
    body = _body(db_connection, "Once")
    assert actor.post("/worlds", body, key="replay-key").status_code == 201

    db_connection.execute(
        text("""
            UPDATE security.user_system_roles SET revoked_at = now()
            WHERE user_id = :u AND revoked_at IS NULL
        """),
        {"u": actor.user_id},
    )
    assert actor.post("/worlds", body, key="replay-key").status_code == 403
    assert "world.create" not in actor.get("/auth/session").json()["global_capabilities"]


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


@pytest.mark.parametrize("make_eligible", [_system_gm, _administrator_and_gm])
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


def test_one_open_gm_assignment_suffices_among_revoked_ones(
    db_connection: Connection,
) -> None:
    user_id = make_user(db_connection, "Veteran")
    _revoked_system_gm(db_connection, user_id)
    _revoked_system_gm(db_connection, user_id)
    assert not may_create_worlds(db_connection, user_id=user_id)
    _system_gm(db_connection, user_id)
    assert may_create_worlds(db_connection, user_id=user_id)


# --- eligibility grants creation only -----------------------------------------------


def test_creation_eligibility_grants_no_authority_over_other_worlds(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    owner = harness.new_actor("Owner", world_creator=True)
    world_id = owner.post("/worlds", _body(db_connection, "Private World")).json()["world_id"]

    admin = harness.new_actor("Other Admin")
    _administrator_and_gm(db_connection, admin.user_id)
    gm = harness.new_actor("Other GM")
    _system_gm(db_connection, gm.user_id)
    for other in (admin, gm):
        assert other.get(f"/worlds/{world_id}").status_code == 404
        assert other.get("/worlds").json()["items"] == []
        assert (
            other.post(
                f"/worlds/{world_id}/update", {"expected_row_version": 1, "name": "Mine"}
            ).status_code
            == 404
        )
