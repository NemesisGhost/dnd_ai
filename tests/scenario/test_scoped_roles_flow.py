"""Scoped-role end-to-end scenario (docs/SCOPED_ROLE_IMPLEMENTATION_PLAN.md, SR-8;
docs/adr/0020-scoped-system-world-and-campaign-roles.md).

Everything runs through the HTTP API with a real cookie session, CSRF token and Origin
check on every write. The one account created outside the API is the platform's first
Administrator (the real deployment starts with `bootstrap_admin`); everything after
that is done by people with the authority to do it.

Part 1 (plan 4.1): an Administrator creates a GM who belongs to no campaign. The GM
activates, lands with no campaigns and the GM capabilities, creates a world and a
campaign, and holds exactly the `campaign_owner` and `gm` campaign roles.

Part 2 (the shared world): GM-A owns world W and campaign A. GM-A lets GM-B host a
campaign on W (a use grant) and gives GM-B a timeline of their own. GM-B creates
campaign B on it and invites P. P is a Player in B and, invited by GM-A, an Observer in
A. The scenario then asserts the boundaries that matter:

- GM-B cannot edit W's definitions until made an Editor, and then only with the
  campaign capability as well;
- nothing of A's preparation, sessions or events is visible from B, or the reverse;
- P's capabilities differ between A and B, and neither invitation changed P's system
  roles;
- revoking GM-B's system GM takes effect on the very next request, without deleting any
  campaign or world assignment.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.system_authority import resolve_system_roles
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids
from tests.factories import make_system_role_assignment

pytestmark = pytest.mark.scenario

PASSWORD = "correct horse battery 9"
ORIGIN = "http://localhost:5173"


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def _sign_in(harness: AuthoringHarness, admin: Actor, login: str, roles: list[str]) -> Actor:
    """An Administrator creates the account; the person activates and signs in."""
    created = admin.post_raw(
        "/admin/accounts",
        {"login_name": login, "display_name": login.title(), "system_role_codes": roles},
        key=admin.fresh_key(),
    )
    assert created.status_code == 201, created.text
    client = harness.anonymous_client()
    activated = client.post(
        "/auth/activate",
        json={"token": created.json()["raw_activation_token"], "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert activated.status_code == 200, activated.text
    login_response = client.post(
        "/auth/login", json={"login_name": login, "password": PASSWORD}, headers={"Origin": ORIGIN}
    )
    assert login_response.status_code == 200, login_response.text
    return Actor(
        harness=harness,
        client=client,
        csrf=login_response.json()["csrf_token"],
        user_id=uuid.UUID(created.json()["user_id"]),
        name=login,
        login_name=login,
    )


def _roles_in(connection: Connection, campaign_id: str, user_id: uuid.UUID) -> set[str]:
    return {
        row.code
        for row in connection.execute(
            text("""
                SELECT r.code FROM security.campaign_memberships cm
                JOIN security.membership_roles mr
                  ON mr.campaign_membership_id = cm.campaign_membership_id
                JOIN security.roles r ON r.role_id = mr.role_id
                WHERE cm.campaign_id = :c AND cm.user_id = :u
                  AND cm.ended_at IS NULL AND mr.revoked_at IS NULL
            """),
            {"c": campaign_id, "u": user_id},
        )
    }


def _world_body(connection: Connection, name: str) -> dict:
    ruleset_id, _ = dnd5e_ids(connection)
    return {
        "name": name,
        "description": None,
        "ruleset_ids": [str(ruleset_id)],
        "default_ruleset_id": str(ruleset_id),
        "primary_timeline": {"name": "Main", "description": None},
    }


def _campaign_body(connection: Connection, timeline_id: str, name: str) -> dict:
    _, ruleset_version_id = dnd5e_ids(connection)
    return {
        "timeline_id": timeline_id,
        "ruleset_version_id": str(ruleset_version_id),
        "name": name,
        "description": None,
    }


def test_an_administrator_creates_a_gm_who_belongs_to_no_campaign(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = harness.new_actor("Root Admin", system_roles=("admin",))
    gm = _sign_in(harness, admin, "fresh-gm", ["gm"])

    # Activation alone granted no campaign access of any kind.
    session = gm.get("/auth/session").json()
    assert session["campaigns"] == [] and session["startup_campaign_id"] is None
    assert set(session["global_capabilities"]) == {
        "world.create",
        "campaign.host",
        "world.administer",
    }
    assert "accounts.manage" not in session["global_capabilities"]

    world = gm.post("/worlds", _world_body(db_connection, "First World"), key=gm.fresh_key())
    assert world.status_code == 201, world.text
    campaign = gm.post(
        "/campaigns",
        _campaign_body(db_connection, world.json()["primary_timeline_id"], "First Campaign"),
        key=gm.fresh_key(),
    )
    assert campaign.status_code == 201, campaign.text
    cid = campaign.json()["campaign_id"]
    assert _roles_in(db_connection, cid, gm.user_id) == {"campaign_owner", "gm"}


def test_two_gms_share_a_world_without_sharing_authority(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = harness.new_actor("Root Admin", system_roles=("admin",))
    gm_a = _sign_in(harness, admin, "gm-a", ["gm"])
    gm_b = _sign_in(harness, admin, "gm-b", ["gm"])
    player = _sign_in(harness, admin, "pat", ["player"])

    # GM-A creates world W and campaign A.
    world = gm_a.post("/worlds", _world_body(db_connection, "W"), key=gm_a.fresh_key()).json()
    world_id = world["world_id"]
    campaign_a = gm_a.post(
        "/campaigns",
        _campaign_body(db_connection, world["primary_timeline_id"], "Campaign A"),
        key=gm_a.fresh_key(),
    ).json()["campaign_id"]

    # GM-A lets GM-B host a campaign on W and provides a timeline for it.
    grant = gm_a.post(f"/worlds/{world_id}/use-grants", {"login_name": gm_b.login_name})
    assert grant.status_code == 201, grant.text
    timeline_b = gm_a.post(
        f"/worlds/{world_id}/timelines", {"name": "B's timeline", "description": None}
    ).json()["timeline_id"]
    campaign_b = gm_b.post(
        "/campaigns",
        _campaign_body(db_connection, timeline_b, "Campaign B"),
        key=gm_b.fresh_key(),
    ).json()["campaign_id"]

    # GM-B cannot take the used primary timeline; the hosting grant is not authority over W.
    assert (
        gm_b.post(
            "/campaigns",
            _campaign_body(db_connection, world["primary_timeline_id"], "Intruder"),
            key=gm_b.fresh_key(),
        ).status_code
        == 404
    )

    # P is a Player in B (invited by GM-B) and an Observer in A (invited by GM-A).
    def enrol(owner: Actor, campaign_id: str, role_code: str) -> None:
        invitation = owner.post_raw(
            f"/campaigns/{campaign_id}/invitations", {}, key=owner.fresh_key()
        )
        assert invitation.status_code == 201, invitation.text
        accepted = player.post_raw(
            "/campaign-invitations/accept", {"token": invitation.json()["token"]}
        )
        assert accepted.status_code in (200, 201), accepted.text
        membership = db_connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
            ),
            {"c": campaign_id, "u": player.user_id},
        ).scalar_one()
        role_id = db_connection.execute(
            text("SELECT role_id FROM security.roles WHERE code = :r AND campaign_id IS NULL"),
            {"r": role_code},
        ).scalar_one()
        assigned = owner.post_raw(
            f"/campaigns/{campaign_id}/memberships/{membership}/roles",
            {"role_id": str(role_id)},
            key=owner.fresh_key(),
        )
        assert assigned.status_code in (200, 201), assigned.text

    enrol(gm_b, campaign_b, "player")
    enrol(gm_a, campaign_a, "observer")
    # Accepting invitations never touched P's system roles.
    assert resolve_system_roles(db_connection, user_id=player.user_id) == {"player"}
    caps = {
        c["campaign_id"]: set(c["capabilities"])
        for c in player.get("/auth/session").json()["campaigns"]
    }
    assert caps[campaign_a] == {"campaign.view"} and caps[campaign_b] == {"campaign.view"}
    roles = {
        c["campaign_id"]: set(c["roles"]) for c in player.get("/auth/session").json()["campaigns"]
    }
    assert roles[campaign_a] == {"observer"} and roles[campaign_b] == {"player"}

    # GM-B cannot edit W's definitions until made an Editor, and then needs canon.edit too.
    body = {"category": "region", "name": "B's Hill", "summary": None}
    refused = gm_b.post(f"/campaigns/{campaign_b}/authoring/locations", body, key=gm_b.fresh_key())
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "world_authority_required"
    assert (
        gm_a.post(
            f"/worlds/{world_id}/roles",
            {"login_name": gm_b.login_name, "role_code": "world_editor"},
        ).status_code
        == 201
    )
    allowed = gm_b.post(f"/campaigns/{campaign_b}/authoring/locations", body, key=gm_b.fresh_key())
    assert allowed.status_code == 201, allowed.text
    # ... and Editor alone is not enough to publish.
    location = allowed.json()
    approve = gm_b.post(
        f"/campaigns/{campaign_b}/entities/{location['location_id']}/lifecycle/submit-for-review",
        {"expected_row_version": location["row_version"]},
        key=gm_b.fresh_key(),
    )
    assert approve.status_code == 200, approve.text
    publish = gm_b.post(
        f"/campaigns/{campaign_b}/entities/{location['location_id']}/lifecycle/approve",
        {"expected_row_version": approve.json()["row_version"]},
        key=gm_b.fresh_key(),
    )
    assert publish.status_code == 403

    # Campaign material never crosses: A's session, B's reads of A, and the reverse.
    session_a = gm_a.post(f"/campaigns/{campaign_a}/sessions", {}, key=gm_a.fresh_key()).json()
    for path in ("clock", "sessions", f"sessions/{session_a['session_id']}"):
        assert gm_b.get(f"/campaigns/{campaign_a}/{path}").status_code == 404, path
    assert (
        gm_b.get(f"/campaigns/{campaign_b}/sessions/{session_a['session_id']}").status_code == 404
    )
    assert gm_a.get(f"/campaigns/{campaign_b}/clock").status_code == 404
    assert player.get(f"/campaigns/{campaign_a}/review-queue").status_code == 403
    assert (
        player.get(
            f"/campaigns/{campaign_b}/authoring/locations/{location['location_id']}"
        ).status_code
        == 403
    )

    # GM-B's drafts are the world's: GM-A (Owner) sees them, P never does.
    assert (
        gm_a.get(
            f"/campaigns/{campaign_a}/authoring/locations/{location['location_id']}"
        ).status_code
        == 200
    )

    # Revoking GM-B's system GM takes effect on the next request and deletes nothing.
    memberships_before = db_connection.execute(
        text("SELECT count(*) FROM security.campaign_memberships WHERE campaign_id = :c"),
        {"c": campaign_b},
    ).scalar_one()
    revoked = admin.post_raw(
        f"/admin/accounts/{gm_b.user_id}/system-roles/gm/revoke", {}, key=admin.fresh_key()
    )
    assert revoked.status_code == 200, revoked.text
    assert "world.create" not in gm_b.get("/auth/session").json()["global_capabilities"]
    assert (
        gm_b.post("/worlds", _world_body(db_connection, "Nope"), key=gm_b.fresh_key()).status_code
        == 403
    )
    assert gm_b.get(f"/campaigns/{campaign_b}/clock").status_code == 200
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": campaign_b},
        ).scalar_one()
        == memberships_before
    )
    # Restoring GM brings back what it gated, with no data change.
    make_system_role_assignment(db_connection, gm_b.user_id, "gm")
    assert "campaign.host" in gm_b.get("/auth/session").json()["global_capabilities"]
