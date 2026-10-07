"""Campaign setup authorization, settings, archive, and reactivation (Phase 14)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Setup:
    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.harness = harness
        self.connection = connection
        self.gm: Actor = harness.new_actor("GM", world_creator=True)
        self.ruleset_id, self.ruleset_version_id = dnd5e_ids(connection)
        created = self.gm.post(
            "/worlds",
            {
                "name": "World",
                "description": None,
                "ruleset_ids": [str(self.ruleset_id)],
                "default_ruleset_id": str(self.ruleset_id),
                "primary_timeline": {"name": "Main", "description": None},
            },
            key=self.gm.fresh_key(),
        ).json()
        self.world_id: str = created["world_id"]
        self.timeline_id: str = created["primary_timeline_id"]

    def campaign_body(self, name: str = "Campaign", timeline_id: str | None = None) -> dict:
        return {
            "timeline_id": timeline_id or self.timeline_id,
            "ruleset_version_id": str(self.ruleset_version_id),
            "name": name,
            "description": None,
        }

    def create_campaign(self, actor: Actor | None = None, **kw) -> dict:  # type: ignore[no-untyped-def]
        actor = actor or self.gm
        response = actor.post("/campaigns", self.campaign_body(**kw), key=actor.fresh_key())
        assert response.status_code == 201, response.text
        return response.json()

    def settings(self, campaign_id: str, actor: Actor | None = None):  # type: ignore[no-untyped-def]
        return (actor or self.gm).get(f"/campaigns/{campaign_id}/settings")

    def audit(self, command: str) -> list:
        return list(
            self.connection.execute(
                text(
                    "SELECT table_name, previous_status, new_status, reason, changed_fields "
                    "FROM audit.change_log WHERE command_name = :c ORDER BY change_log_id"
                ),
                {"c": command},
            ).all()
        )


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> Setup:
    return Setup(harness, db_connection)


# --- creation authorization (path A) ---------------------------------------------------


def test_a_world_owner_creates_a_campaign_without_a_bootstrap_grant(s: Setup) -> None:
    created = s.create_campaign()
    bootstrap = s.gm.get("/auth/session").json()
    listed = [c for c in bootstrap["campaigns"] if c["campaign_id"] == created["campaign_id"]]
    assert len(listed) == 1
    campaign = listed[0]
    assert campaign["roles"] == ["campaign_owner", "gm"]
    assert {"access.manage", "campaign.view", "canon.edit"} <= set(campaign["capabilities"])
    assert campaign["world_id"] == s.world_id
    assert bootstrap["startup_campaign_id"] == created["campaign_id"]
    assert (
        s.connection.execute(
            text("SELECT count(*) FROM security.timeline_bootstrap_grants")
        ).scalar()
        == 0
    )


def test_a_world_owner_gets_no_membership_in_campaigns_they_did_not_create(
    harness: AuthoringHarness, s: Setup
) -> None:
    """Path A authorizes creation only: a second user who also owns... nothing —
    and the original owner is not a member of someone else's campaign."""
    other = harness.new_actor("Other GM", system_roles=("gm",))
    # `other` is a system GM with no authority over s.world_id and no grant: 404, not 403/409.
    response = other.post("/campaigns", s.campaign_body(), key=other.fresh_key())
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


def test_lifecycle_is_checked_only_after_authorization(harness: AuthoringHarness, s: Setup) -> None:
    other = harness.new_actor("Stranger", system_roles=("gm",))
    side = s.gm.post(f"/worlds/{s.world_id}/timelines", {"name": "Side", "description": None})
    side_id, side_version = side.json()["timeline_id"], side.json()["row_version"]
    assert (
        s.gm.post(
            f"/worlds/{s.world_id}/timelines/{side_id}/archive",
            {"expected_row_version": side_version},
        ).status_code
        == 200
    )

    owner_view = s.gm.post("/campaigns", s.campaign_body(timeline_id=side_id))
    assert owner_view.status_code == 409
    assert owner_view.json()["error"]["code"] == "timeline_archived"
    stranger_view = other.post("/campaigns", s.campaign_body(timeline_id=side_id))
    assert stranger_view.status_code == 404

    world = s.gm.get(f"/worlds/{s.world_id}").json()
    archived = s.gm.post(
        f"/worlds/{s.world_id}/archive", {"expected_row_version": world["row_version"]}
    )
    assert archived.status_code == 200
    blocked = s.gm.post("/campaigns", s.campaign_body())
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "world_archived"
    assert other.post("/campaigns", s.campaign_body()).status_code == 404


def test_invalid_campaign_bodies_are_rejected(s: Setup) -> None:
    for patch in ({"name": ""}, {"name": "x" * 201}, {"description": "x" * 4001}):
        response = s.gm.post("/campaigns", s.campaign_body() | patch)
        assert response.status_code == 422, patch


def test_a_ruleset_version_outside_the_world_is_rejected(s: Setup) -> None:
    response = s.gm.post(
        "/campaigns", s.campaign_body() | {"ruleset_version_id": str(uuid.uuid4())}
    )
    assert response.status_code == 400


# --- settings, update ------------------------------------------------------------------


def test_settings_read_requires_access_manage(harness: AuthoringHarness, s: Setup) -> None:
    created = s.create_campaign()
    body = s.settings(created["campaign_id"]).json()
    assert body["name"] == "Campaign"
    assert body["lifecycle_status"] == "active"
    assert body["world"]["name"] == "World"
    assert body["timeline"]["name"] == "Main"
    assert body["ruleset_version"]["ruleset_display_name"]
    assert body["available_actions"] == ["update", "archive"]
    assert {"action": "reactivate", "reason": "lifecycle_transition_not_allowed"} in body[
        "blocked_actions"
    ]
    assert s.settings(created["campaign_id"], harness.new_actor("Nobody")).status_code == 404


def test_update_is_versioned_audited_and_noop_safe(s: Setup) -> None:
    created = s.create_campaign()
    cid = created["campaign_id"]
    version = s.settings(cid).json()["row_version"]

    updated = s.gm.post(
        f"/campaigns/{cid}/update",
        {"expected_row_version": version, "name": "Renamed", "description": "d"},
        key=s.gm.fresh_key(),
    )
    assert updated.status_code == 200
    assert updated.json()["row_version"] == version + 1
    rows = s.audit("update_campaign")
    assert len(rows) == 1 and rows[0].changed_fields["name"] == {
        "from": "Campaign",
        "to": "Renamed",
    }

    stale = s.gm.post(
        f"/campaigns/{cid}/update",
        {"expected_row_version": version, "name": "Again", "description": None},
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"

    noop = s.gm.post(
        f"/campaigns/{cid}/update",
        {"expected_row_version": version + 1, "name": "Renamed", "description": "d"},
        key=s.gm.fresh_key(),
    )
    assert noop.status_code == 200 and noop.json()["row_version"] == version + 1
    assert len(s.audit("update_campaign")) == 1


def test_update_replays_with_the_same_key(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    version = s.settings(cid).json()["row_version"]
    body = {"expected_row_version": version, "name": "Once", "description": None}
    first = s.gm.post(f"/campaigns/{cid}/update", body, key="camp-key")
    second = s.gm.post(f"/campaigns/{cid}/update", body, key="camp-key")
    assert first.json() == second.json() and second.status_code == 200
    assert len(s.audit("update_campaign")) == 1
    other = s.gm.post(f"/campaigns/{cid}/update", body | {"name": "Different"}, key="camp-key")
    assert other.status_code == 409 and other.json()["error"]["code"] == "conflict"


def test_a_member_without_access_manage_gets_403_on_settings_mutations(
    harness: AuthoringHarness, s: Setup
) -> None:
    cid = s.create_campaign()["campaign_id"]
    player = harness.new_actor("Player")
    s.connection.execute(
        text("""
            INSERT INTO security.campaign_memberships
                (campaign_id, user_id, membership_status_id, joined_at)
            VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                             WHERE code = 'active'), now())
        """),
        {"c": cid, "u": player.user_id},
    )
    s.connection.execute(
        text("""
            INSERT INTO security.membership_roles (campaign_membership_id, role_id)
            SELECT cm.campaign_membership_id, r.role_id
            FROM security.campaign_memberships cm, security.roles r
            WHERE cm.campaign_id = :c AND cm.user_id = :u
              AND r.code = 'player' AND r.campaign_id IS NULL
        """),
        {"c": cid, "u": player.user_id},
    )
    for path, body in (
        (f"/campaigns/{cid}/update", {"expected_row_version": 1, "name": "X"}),
        (f"/campaigns/{cid}/archive", {"expected_row_version": 1}),
        (f"/campaigns/{cid}/reactivate", {"expected_row_version": 1}),
    ):
        assert player.post(path, body).status_code == 403, path
    assert player.get(f"/campaigns/{cid}/settings").status_code == 403


# --- archive, gate, reactivate -----------------------------------------------------------


def _archive(s: Setup, cid: str) -> int:
    version = s.settings(cid).json()["row_version"]
    response = s.gm.post(
        f"/campaigns/{cid}/archive",
        {"expected_row_version": version, "reason": "season over"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["lifecycle_status"] == "archived"
    return int(response.json()["row_version"])


def test_archiving_removes_the_campaign_from_the_bootstrap_and_lists_it_as_archived(
    s: Setup,
) -> None:
    cid = s.create_campaign()["campaign_id"]
    assert s.gm.get("/auth/session").json()["startup_campaign_id"] == cid
    version = _archive(s, cid)

    bootstrap = s.gm.get("/auth/session").json()
    assert bootstrap["campaigns"] == []
    assert bootstrap["startup_campaign_id"] is None

    archived = s.gm.get("/campaigns/archived").json()
    assert [(c["campaign_id"], c["world_name"], c["timeline_name"]) for c in archived["items"]] == [
        (cid, "World", "Main")
    ]
    assert archived["items"][0]["row_version"] == version
    assert s.gm.get("/campaigns/archived").json()["next_cursor"] is None

    rows = s.audit("archive_campaign")
    assert [(r.previous_status, r.new_status, r.reason) for r in rows] == [
        ("active", "archived", "season over")
    ]


def test_the_archived_list_excludes_other_peoples_and_active_campaigns(
    harness: AuthoringHarness, s: Setup
) -> None:
    cid = s.create_campaign(name="Mine")["campaign_id"]
    s.create_campaign(name="Active")
    _archive(s, cid)
    stranger = harness.new_actor("Stranger")
    assert stranger.get("/campaigns/archived").json()["items"] == []
    assert [c["name"] for c in s.gm.get("/campaigns/archived").json()["items"]] == ["Mine"]


READ_ROUTES = [
    "/campaigns/{c}/summary",
    "/campaigns/{c}/quests",
    "/campaigns/{c}/sessions",
    "/campaigns/{c}/knowledge",
    "/campaigns/{c}/access-overview",
    "/campaigns/{c}/audit-history",
    "/campaigns/{c}/invitations",
    "/campaigns/{c}/world/search?q=x",
    "/campaigns/{c}/world/relationships",
    "/campaigns/{c}/foundry/devices",
]
COMMAND_ROUTES = [
    "/campaigns/{c}/invitations",
    "/campaigns/{c}/memberships",
    "/campaigns/{c}/events",
    "/campaigns/{c}/encounters",
    "/campaigns/{c}/resource-grants",
    "/campaigns/{c}/access-groups",
    "/campaigns/{c}/foundry/pairing-codes",
    "/campaigns/{c}/update",
    "/campaigns/{c}/archive",
]


def test_an_archived_campaign_authorizes_no_route_except_settings_and_reactivate(
    s: Setup,
) -> None:
    cid = s.create_campaign()["campaign_id"]
    # Control: every sampled route is reachable (not 404) while active.
    for template in READ_ROUTES:
        assert s.gm.get(template.format(c=cid)).status_code != 404, template
    _archive(s, cid)
    for template in READ_ROUTES:
        assert s.gm.get(template.format(c=cid)).status_code == 404, template
    for template in COMMAND_ROUTES:
        response = s.gm.post(template.format(c=cid), {"expected_row_version": 1})
        assert response.status_code == 404, template
    assert s.settings(cid).status_code == 200


def test_the_archived_gate_covers_foundry_enabled_routes(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    foundry = AuthenticatedPrincipal(
        user_id=s.gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.UUID(cid),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"combat_sync"}),
    )
    client = s.harness.principal_client(foundry)
    path = f"/campaigns/{cid}/characters/{uuid.uuid4()}"
    assert client.get(path).status_code == 403  # active: missing scope
    _archive(s, cid)
    assert client.get(path).status_code == 404  # archived: the campaign is gone


def test_reactivation_restores_access_and_the_bootstrap_listing(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    version = _archive(s, cid)
    reactivated = s.gm.post(
        f"/campaigns/{cid}/reactivate", {"expected_row_version": version}, key=s.gm.fresh_key()
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["lifecycle_status"] == "active"
    assert [c["campaign_id"] for c in s.gm.get("/auth/session").json()["campaigns"]] == [cid]
    assert s.gm.get(f"/campaigns/{cid}/summary").status_code == 200
    assert [(r.previous_status, r.new_status) for r in s.audit("reactivate_campaign")] == [
        ("archived", "active")
    ]


def test_reactivation_requires_an_active_world_and_timeline(s: Setup) -> None:
    side = s.gm.post(
        f"/worlds/{s.world_id}/timelines", {"name": "Side", "description": None}
    ).json()
    cid = s.create_campaign(timeline_id=side["timeline_id"])["campaign_id"]
    version = _archive(s, cid)
    archived_timeline = s.gm.post(
        f"/worlds/{s.world_id}/timelines/{side['timeline_id']}/archive",
        {"expected_row_version": side["row_version"]},
    )
    assert archived_timeline.status_code == 200
    blocked = s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": version})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "timeline_archived"
    settings = s.settings(cid).json()
    assert settings["available_actions"] == []
    assert {"action": "reactivate", "reason": "timeline_archived"} in settings["blocked_actions"]

    world = s.gm.get(f"/worlds/{s.world_id}").json()
    assert (
        s.gm.post(
            f"/worlds/{s.world_id}/archive", {"expected_row_version": world["row_version"]}
        ).status_code
        == 200
    )
    blocked = s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": version})
    assert blocked.json()["error"]["code"] == "world_archived"


def test_reactivation_without_a_permanent_access_manager_is_a_classified_409(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    version = _archive(s, cid)
    # The only manager's role becomes expiring: the database would reject the
    # reactivation at commit, so the command must pre-check and classify it.
    s.connection.execute(
        text("""
            UPDATE security.membership_roles SET expires_at = now() + interval '1 day'
            WHERE campaign_membership_id IN (
                SELECT campaign_membership_id FROM security.campaign_memberships
                WHERE campaign_id = :c)
        """),
        {"c": cid},
    )
    response = s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": version})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "campaign_access_manager_required"
    assert s.settings(cid).json()["lifecycle_status"] == "archived"


def test_archive_and_reactivate_enforce_legal_transitions_and_versions(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    version = s.settings(cid).json()["row_version"]
    illegal = s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": version})
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "lifecycle_transition_not_allowed"
    stale = s.gm.post(f"/campaigns/{cid}/archive", {"expected_row_version": version + 9})
    assert stale.json()["error"]["code"] == "stale_write"
    new_version = _archive(s, cid)
    again = s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": version})
    assert again.json()["error"]["code"] == "stale_write"
    assert new_version == version + 1


def test_archived_campaign_stops_a_stored_startup_preference_applying_then_it_returns(
    s: Setup,
) -> None:
    cid = s.create_campaign()["campaign_id"]
    pref = s.gm.client.put(
        "/auth/preferences/campaign-startup",
        json={"preferred_campaign_id": cid},
        headers=s.gm.headers(),
    )
    assert pref.status_code == 204
    version = _archive(s, cid)
    dropped = s.gm.get("/auth/session").json()
    assert dropped["startup_campaign_id"] is None
    assert dropped["campaign_preferences"]["preferred_campaign_id"] is None
    s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": version})
    restored = s.gm.get("/auth/session").json()
    assert restored["startup_campaign_id"] == cid
    assert restored["campaign_preferences"]["preferred_campaign_id"] == cid


def test_a_brand_new_campaign_has_a_usable_empty_home(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    response = s.gm.get(f"/campaigns/{cid}/summary")
    assert response.status_code == 200, response.text
    assert s.gm.get(f"/campaigns/{cid}/sessions").status_code == 200
    assert s.gm.get(f"/campaigns/{cid}/quests").status_code == 200


def test_audit_history_shows_the_campaign_lifecycle_commands_without_reasons(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    version = s.settings(cid).json()["row_version"]
    updated = s.gm.post(
        f"/campaigns/{cid}/update",
        {"expected_row_version": version, "name": "Secret Rename", "description": None},
    ).json()
    archived_version = _archive(s, cid)
    s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": archived_version})
    assert updated["row_version"] == version + 1

    response = s.gm.get(f"/campaigns/{cid}/audit-history", category="campaign")
    assert response.status_code == 200, response.text
    labels = [item["action_label"] for item in response.json()["items"]]
    assert {
        "Campaign created",
        "Campaign settings updated",
        "Campaign archived",
        "Campaign reactivated",
    } <= set(labels)
    assert "season over" not in response.text and "Secret Rename" not in response.text


# --- invitations into archived campaigns ----------------------------------------------------


def test_an_archived_campaign_refuses_invitation_acceptance_without_disclosure(
    harness: AuthoringHarness, s: Setup
) -> None:
    cid = s.create_campaign()["campaign_id"]
    invite = s.gm.post(f"/campaigns/{cid}/invitations", {}, key=s.gm.fresh_key())
    assert invite.status_code == 201, invite.text
    token = invite.json()["token"]
    invited = harness.new_actor("Invitee")

    _archive(s, cid)
    refused = invited.post("/campaign-invitations/accept", {"token": token})
    unknown = invited.post("/campaign-invitations/accept", {"token": "no-such-token-123456"})
    assert refused.status_code == unknown.status_code
    assert refused.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert refused.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert (
        s.connection.execute(
            text("SELECT count(*) FROM security.campaign_memberships WHERE user_id = :u"),
            {"u": invited.user_id},
        ).scalar()
        == 0
    )


def test_acceptance_works_again_after_reactivation(harness: AuthoringHarness, s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    token = s.gm.post(f"/campaigns/{cid}/invitations", {}, key=s.gm.fresh_key()).json()["token"]
    invited = harness.new_actor("Invitee")
    version = _archive(s, cid)
    assert invited.post("/campaign-invitations/accept", {"token": token}).status_code == 404
    s.gm.post(f"/campaigns/{cid}/reactivate", {"expected_row_version": version})
    accepted = invited.post("/campaign-invitations/accept", {"token": token})
    assert accepted.status_code in (200, 201), accepted.text


def test_new_campaign_routes_reject_foundry_principals_and_enforce_csrf(s: Setup) -> None:
    cid = s.create_campaign()["campaign_id"]
    foundry = AuthenticatedPrincipal(
        user_id=s.gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.UUID(cid),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    client = s.harness.principal_client(foundry)
    assert client.get(f"/campaigns/{cid}/settings").status_code == 403
    assert client.get("/campaigns/archived").status_code == 403
    for suffix in ("update", "archive", "reactivate"):
        assert (
            client.post(f"/campaigns/{cid}/{suffix}", json={"expected_row_version": 1}).status_code
            == 403
        )
        body = {"expected_row_version": 1, "name": "X"}
        assert s.gm.post(f"/campaigns/{cid}/{suffix}", body, csrf=False).status_code == 403
        assert s.gm.post(f"/campaigns/{cid}/{suffix}", body, origin=False).status_code == 403
