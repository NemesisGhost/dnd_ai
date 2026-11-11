"""The D3 ownership gate (P03-A A1, docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md).

Assigning the built-in `campaign_owner` role, changing a role to it, adding a member with it and
transferring ownership all require the caller to hold a live built-in owner assignment in the same
campaign, in addition to `access.manage`. Every other role is unchanged. Campaign creation and
administrative recovery are covered by their own suites (`test_api_campaigns.py`,
`test_stranding_and_recovery.py`) and pass unchanged.

Everything here runs against committed data: the gate takes row locks that only mean something
across real connections, and the HTTP routes open their own.
"""

import time
import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.memberships import (
    CampaignOwnerRequiredError,
    add_campaign_member,
    assign_membership_role,
    change_membership_role,
    revoke_membership_role,
    transfer_campaign_ownership,
)
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER, find_live_builtin_owner_assignment
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
    oidc_principal,
)

pytestmark = pytest.mark.database


def _template_role_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text("SELECT role_id FROM security.roles WHERE code = :code AND campaign_id IS NULL"),
        {"code": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


class Gate:
    """An active campaign with two built-in owners (`o1`, `o2`), a custom-role `access.manage`
    holder (`manager`), and a plain player (`player`). `new_user_id` is an addable account."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Owner Gate", lifecycle_status_code="active"
        )
        self.owner_role_id = _template_role_id(connection, "campaign_owner")
        self.gm_role_id = _template_role_id(connection, "gm")
        self.player_role_id = _template_role_id(connection, "player")

        access_manage = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        campaign_view = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        self.custom_manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"custom_admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.custom_manager_role_id, access_manage)
        make_role_capability(connection, self.custom_manager_role_id, campaign_view)
        # A campaign-scoped role that merely borrows the template's code: never the built-in.
        self.lookalike_role_id = make_role(
            connection, campaign_id=self.campaign_id, code="campaign_owner"
        )

        self.o1_user_id = make_user(connection, "Gate Owner One")
        self.o1 = make_campaign_membership(connection, self.campaign_id, self.o1_user_id)
        self.o1_role = make_membership_role(connection, self.o1, self.owner_role_id)
        self.o2_user_id = make_user(connection, "Gate Owner Two")
        self.o2 = make_campaign_membership(connection, self.campaign_id, self.o2_user_id)
        self.o2_role = make_membership_role(connection, self.o2, self.owner_role_id)

        self.manager_user_id = make_user(connection, "Gate Custom Manager")
        self.manager = make_campaign_membership(connection, self.campaign_id, self.manager_user_id)
        self.manager_role = make_membership_role(
            connection, self.manager, self.custom_manager_role_id
        )

        self.player_user_id = make_user(connection, "Gate Player")
        self.player = make_campaign_membership(connection, self.campaign_id, self.player_user_id)
        self.player_role = make_membership_role(connection, self.player, self.player_role_id)

        self.new_user_id = make_user(connection, "Gate Newcomer")
        make_external_identity(
            connection,
            self.new_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=f"gate-new-{uuid.uuid4().hex[:8]}",
        )


def drop_gate(engine: Engine, fixture: Gate) -> None:
    """Removes everything a `Gate` (and the tests using it) committed."""
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        params = {"t": fixture.timeline_id, "w": fixture.world_id}
        campaigns = "SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t"
        cleanup.execute(text("DELETE FROM audit.change_log WHERE world_id = :w"), params)
        # P03-A A2a public profiles and the grants/groups tests attach to a campaign.
        for table in (
            "security.character_revelation_members",
            "security.character_revelations",
            "campaign.character_public_profile_releases",
            "campaign.character_public_profiles",
            "security.resource_grants",
        ):
            cleanup.execute(
                text(f"DELETE FROM {table} WHERE campaign_id IN ({campaigns})"),  # noqa: S608
                params,
            )
        cleanup.execute(
            text(f"""
                DELETE FROM security.access_group_memberships WHERE access_group_id IN (
                    SELECT access_group_id FROM security.access_groups
                    WHERE campaign_id IN ({campaigns}))
            """),  # noqa: S608
            params,
        )
        cleanup.execute(
            text(f"DELETE FROM security.access_groups WHERE campaign_id IN ({campaigns})"),  # noqa: S608
            params,
        )
        cleanup.execute(
            text(
                f"DELETE FROM security.character_reveal_delegations WHERE campaign_id IN ({campaigns})"
            ),  # noqa: S608
            params,
        )
        cleanup.execute(
            text(f"""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN ({campaigns}))
            """),  # noqa: S608
            params,
        )
        cleanup.execute(
            text(f"""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN ({campaigns}))
            """),  # noqa: S608
            params,
        )
        cleanup.execute(
            text(f"DELETE FROM security.roles WHERE campaign_id IN ({campaigns})"),  # noqa: S608
            params,
        )
        cleanup.execute(
            text(f"DELETE FROM security.campaign_memberships WHERE campaign_id IN ({campaigns})"),  # noqa: S608
            params,
        )
        cleanup.execute(text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"), params)
        cleanup.execute(text("DELETE FROM campaign.timelines WHERE timeline_id = :t"), params)
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), params)
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), params)


@pytest.fixture
def g(postgres_engine: Engine) -> Iterator[Gate]:
    with postgres_engine.begin() as connection:
        fixture = Gate(connection, f"owner-gate-{uuid.uuid4().hex[:8]}")
    yield fixture
    drop_gate(postgres_engine, fixture)


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


# --- state probes ---------------------------------------------------------------------------


def _live_owner_memberships(connection: Connection, g: Gate) -> set[uuid.UUID]:
    rows = connection.execute(
        text("""
            SELECT mr.campaign_membership_id
            FROM security.membership_roles mr
            JOIN security.campaign_memberships cm
                ON cm.campaign_membership_id = mr.campaign_membership_id
            WHERE cm.campaign_id = :c AND mr.role_id = :owner AND mr.revoked_at IS NULL
        """),
        {"c": g.campaign_id, "owner": g.owner_role_id},
    ).scalars()
    return set(rows)


def _snapshot(engine: Engine, g: Gate) -> tuple[int, int, int]:
    """(membership_roles rows, memberships, audit rows): a refused request changes none."""
    with engine.connect() as connection:
        counts = connection.execute(
            text("""
                SELECT
                  (SELECT count(*) FROM security.membership_roles mr
                     JOIN security.campaign_memberships cm
                       ON cm.campaign_membership_id = mr.campaign_membership_id
                     WHERE cm.campaign_id = :c),
                  (SELECT count(*) FROM security.campaign_memberships WHERE campaign_id = :c),
                  (SELECT count(*) FROM audit.change_log WHERE world_id = :w)
            """),
            {"c": g.campaign_id, "w": g.world_id},
        ).one()
    return (counts[0], counts[1], counts[2])


# --- the refused paths ------------------------------------------------------------------------


def _requests(g: Gate) -> dict[str, tuple[str, dict[str, object]]]:
    base = f"/campaigns/{g.campaign_id}"
    return {
        "assign_to_self": (
            f"{base}/memberships/{g.manager}/roles",
            {"role_id": str(g.owner_role_id)},
        ),
        "assign_to_other": (
            f"{base}/memberships/{g.player}/roles",
            {"role_id": str(g.owner_role_id)},
        ),
        "change_own_role": (
            f"{base}/memberships/roles/{g.manager_role}/change",
            {"new_role_id": str(g.owner_role_id)},
        ),
        "change_other_role": (
            f"{base}/memberships/roles/{g.player_role}/change",
            {"new_role_id": str(g.owner_role_id)},
        ),
        "add_member_as_owner": (
            f"{base}/memberships",
            {"user_id": str(g.new_user_id), "role_id": str(g.owner_role_id)},
        ),
        "transfer_to_self": (
            f"{base}/ownership-transfer",
            {"target_campaign_membership_id": str(g.manager)},
        ),
        "transfer_to_other": (
            f"{base}/ownership-transfer",
            {"target_campaign_membership_id": str(g.player), "relinquish_own_ownership": True},
        ),
        "transfer_to_existing_owner": (
            f"{base}/ownership-transfer",
            {"target_campaign_membership_id": str(g.o1)},
        ),
    }


@pytest.mark.parametrize(
    "case",
    [
        "assign_to_self",
        "assign_to_other",
        "change_own_role",
        "change_other_role",
        "add_member_as_owner",
        "transfer_to_self",
        "transfer_to_other",
        "transfer_to_existing_owner",
    ],
)
def test_a_custom_access_manager_cannot_reach_the_owner_role_by_any_route(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    case: str,
) -> None:
    url, body = _requests(g)[case]
    before = _snapshot(postgres_engine, g)
    with client_factory(g.manager_user_id) as client:
        response = client.post(url, json=body)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "campaign_owner_required"
    assert _snapshot(postgres_engine, g) == before
    with postgres_engine.connect() as connection:
        assert _live_owner_memberships(connection, g) == {g.o1, g.o2}


def test_the_same_refusals_hold_when_the_commands_are_called_directly(
    postgres_engine: Engine, g: Gate
) -> None:
    calls: dict[str, Callable[[Connection], object]] = {
        "assign": lambda c: assign_membership_role(
            c,
            campaign_membership_id=g.manager,
            role_id=g.owner_role_id,
            campaign_id=g.campaign_id,
            granted_by_membership_id=g.manager,
        ),
        "change": lambda c: change_membership_role(
            c,
            membership_role_id=g.manager_role,
            campaign_id=g.campaign_id,
            new_role_id=g.owner_role_id,
            granted_by_membership_id=g.manager,
        ),
        "add": lambda c: add_campaign_member(
            c,
            campaign_id=g.campaign_id,
            user_id=g.new_user_id,
            role_id=g.owner_role_id,
            added_by_membership_id=g.manager,
        ),
        "transfer": lambda c: transfer_campaign_ownership(
            c,
            campaign_id=g.campaign_id,
            actor_membership_id=g.manager,
            target_campaign_membership_id=g.manager,
            relinquish_own_ownership=False,
        ),
    }
    for name, call in calls.items():
        before = _snapshot(postgres_engine, g)
        with pytest.raises(CampaignOwnerRequiredError), postgres_engine.begin() as connection:
            call(connection)
        assert _snapshot(postgres_engine, g) == before, name


def test_a_custom_manager_still_assigns_every_other_role(
    client_factory: Callable[[uuid.UUID], TestClient], g: Gate
) -> None:
    base = f"/campaigns/{g.campaign_id}"
    with client_factory(g.manager_user_id) as client:
        assert client.post(
            f"{base}/memberships/{g.player}/roles", json={"role_id": str(g.gm_role_id)}
        ).status_code in (200, 201)
        assert client.post(
            f"{base}/memberships",
            json={"user_id": str(g.new_user_id), "role_id": str(g.player_role_id)},
        ).status_code in (200, 201)


def test_a_campaign_role_named_campaign_owner_is_not_the_builtin(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Gated by role identity, not by code: the look-alike stays assignable by a custom manager and
    never makes its holder a live owner."""
    with client_factory(g.manager_user_id) as client:
        response = client.post(
            f"/campaigns/{g.campaign_id}/memberships/{g.player}/roles",
            json={"role_id": str(g.lookalike_role_id)},
        )
    assert response.status_code in (200, 201), response.text
    with postgres_engine.connect() as connection:
        assert (
            find_live_builtin_owner_assignment(
                connection, campaign_id=g.campaign_id, campaign_membership_id=g.player
            )
            is None
        )


def test_the_assignable_role_list_hides_the_owner_role_from_a_non_owner(
    client_factory: Callable[[uuid.UUID], TestClient], g: Gate
) -> None:
    def codes_for(user_id: uuid.UUID) -> list[str]:
        with client_factory(user_id) as client:
            response = client.get(f"/campaigns/{g.campaign_id}/access-overview")
        assert response.status_code == 200, response.text
        return [(r["code"], r["role_id"]) for r in response.json()["assignable_roles"]]  # type: ignore[misc]

    manager_roles = codes_for(g.manager_user_id)
    assert str(g.owner_role_id) not in [role_id for _, role_id in manager_roles]
    assert str(g.gm_role_id) in [role_id for _, role_id in manager_roles]
    # The look-alike is the campaign's own role, so it stays listed.
    assert str(g.lookalike_role_id) in [role_id for _, role_id in manager_roles]
    owner_roles = codes_for(g.o1_user_id)
    assert str(g.owner_role_id) in [role_id for _, role_id in owner_roles]


# --- the permitted paths ----------------------------------------------------------------------


def test_an_owner_makes_a_co_owner_adds_an_owner_and_transfers(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    base = f"/campaigns/{g.campaign_id}"
    with client_factory(g.o1_user_id) as client:
        assert client.post(
            f"{base}/memberships/{g.player}/roles", json={"role_id": str(g.owner_role_id)}
        ).status_code in (200, 201)
        added = client.post(
            f"{base}/memberships",
            json={"user_id": str(g.new_user_id), "role_id": str(g.owner_role_id)},
        )
        assert added.status_code in (200, 201), added.text
        changed = client.post(
            f"{base}/memberships/roles/{g.manager_role}/change",
            json={"new_role_id": str(g.owner_role_id)},
        )
        assert changed.status_code in (200, 201), changed.text
        transferred = client.post(
            f"{base}/ownership-transfer",
            json={
                "target_campaign_membership_id": str(g.manager),
                "relinquish_own_ownership": True,
            },
        )
        assert transferred.status_code == 200, transferred.text
    with postgres_engine.connect() as connection:
        owners = _live_owner_memberships(connection, g)
    assert g.o1 not in owners
    assert {g.o2, g.player, g.manager} <= owners


@pytest.mark.parametrize("reason", ["expired", "membership_ended", "account_inactive", "revoked"])
def test_an_owner_who_is_no_longer_live_is_refused(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    reason: str,
) -> None:
    with postgres_engine.begin() as connection:
        if reason == "expired":
            connection.execute(
                text("""
                    UPDATE security.membership_roles
                    SET expires_at = now() + interval '1 second' WHERE membership_role_id = :r
                """),
                {"r": g.o1_role},
            )
            time.sleep(1.2)
        elif reason == "membership_ended":
            connection.execute(
                text("""
                    UPDATE security.campaign_memberships SET ended_at = now()
                    WHERE campaign_membership_id = :m
                """),
                {"m": g.o1},
            )
        elif reason == "account_inactive":
            connection.execute(
                text("""
                    UPDATE security.users SET lifecycle_status_id = (
                        SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived')
                    WHERE user_id = :u
                """),
                {"u": g.o1_user_id},
            )
        else:
            revoke_membership_role(
                connection, membership_role_id=g.o1_role, campaign_id=g.campaign_id
            )
    with postgres_engine.connect() as connection:
        assert (
            find_live_builtin_owner_assignment(
                connection, campaign_id=g.campaign_id, campaign_membership_id=g.o1
            )
            is None
        )
    with pytest.raises(CampaignOwnerRequiredError), postgres_engine.begin() as connection:
        assign_membership_role(
            connection,
            campaign_membership_id=g.player,
            role_id=g.owner_role_id,
            campaign_id=g.campaign_id,
            granted_by_membership_id=g.o1,
        )


def test_a_repeated_transfer_changes_nothing(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    url = f"/campaigns/{g.campaign_id}/ownership-transfer"
    body = {"target_campaign_membership_id": str(g.o2)}
    with client_factory(g.o1_user_id) as client:
        first = client.post(url, json=body)
        before = _snapshot(postgres_engine, g)
        second = client.post(url, json=body)
    assert first.status_code == second.status_code == 200
    assert second.json()["assigned"] is False
    assert _snapshot(postgres_engine, g) == before
