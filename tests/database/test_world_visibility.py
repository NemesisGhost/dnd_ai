"""World visibility and the read-only `world_viewer` role
(docs/adr/0019-world-visibility-and-viewer-role.md).

- `world_viewer` resolves to `world.view` only: it lists and reads the world
  and its timelines with no available or blocked action, and every authoring
  route and command refuses it.
- `campaign.view` never becomes world authority: a campaign player gets no
  `/worlds` entry for the campaign's world, and no world route answers them.
- The trusted-infrastructure membership commands and
  `scripts/manage_world_membership.py` remediate a historical player-owned
  world by transfer, never by deletion, and the former owner keeps their
  campaign-scoped viewing.
- The observed local defect, end to end through the API.
"""

import uuid
from collections.abc import Iterator

import manage_world_membership
import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.timelines import create_timeline
from dnd_ai.commands.world_memberships import (
    end_world_membership,
    set_world_role,
    transfer_world_ownership,
)
from dnd_ai.commands.worlds import claim_unowned_world, update_world
from dnd_ai.domain.authoring import WorldMembershipChangeRefusedError, WorldNotAuthorizedError
from dnd_ai.queries.world_authority import resolve_world_authority
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import AuthoredWorld, make_authored_campaign, make_authored_world
from tests.database.test_api_world_time import CALENDAR
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_world,
    system_role_id,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def _world(harness: AuthoringHarness, name: str) -> AuthoredWorld:
    owner = harness.new_actor(f"{name} Owner", world_creator=True)
    return make_authored_world(harness.connection, owner_user_id=owner.user_id, name=name)


def _open_roles(connection: Connection, world_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = connection.execute(
        text("""
            SELECT wm.user_id, wr.code FROM security.world_memberships wm
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            WHERE wm.world_id = :w AND wm.ended_at IS NULL
        """),
        {"w": world_id},
    ).all()
    return {row.user_id: str(row.code) for row in rows}


def _membership_rows(connection: Connection, world_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM security.world_memberships WHERE world_id = :w AND user_id = :u"
            ),
            {"w": world_id, "u": user_id},
        ).scalar_one()
    )


def _player_in(connection: Connection, campaign_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    membership_id = make_campaign_membership(connection, campaign_id, user_id)
    make_membership_role(connection, membership_id, system_role_id(connection, "player"))
    return membership_id


def _assert_no_world_mutation(actor: Actor, world: AuthoredWorld, expected: int) -> None:
    """Every world/timeline authoring route refuses `actor` with `expected`."""
    detail = actor.get(f"/worlds/{world.world_id}")
    version = detail.json()["row_version"] if detail.status_code == 200 else 1
    timeline = f"/worlds/{world.world_id}/timelines/{world.primary_timeline_id}"
    attempts = [
        (f"/worlds/{world.world_id}/update", {"expected_row_version": version, "name": "Edited"}),
        (f"/worlds/{world.world_id}/archive", {"expected_row_version": version}),
        (f"/worlds/{world.world_id}/restore", {"expected_row_version": version}),
        (f"/worlds/{world.world_id}/timelines", {"name": "Side", "description": None}),
        (f"{timeline}/update", {"expected_row_version": 1, "name": "Renamed"}),
        (f"{timeline}/archive", {"expected_row_version": 1}),
        (f"{timeline}/restore", {"expected_row_version": 1}),
        (
            f"{timeline}/branches",
            {"name": "Branch", "description": None, "branch_point": {"kind": "latest"}},
        ),
        (f"/worlds/{world.world_id}/calendars", CALENDAR),
    ]
    for path, body in attempts:
        response = actor.post_raw(path, body, key=actor.fresh_key())
        assert response.status_code == expected, (path, response.text)
    campaign = actor.post_raw(
        "/campaigns",
        {
            "timeline_id": str(world.primary_timeline_id),
            "ruleset_version_id": str(world.ruleset_version_id),
            "name": "Not Mine",
        },
        key=actor.fresh_key(),
    )
    assert campaign.status_code == 404, campaign.text


# --- world_viewer -------------------------------------------------------------------------


def test_world_viewer_resolves_to_world_view_only(harness: AuthoringHarness) -> None:
    world = _world(harness, "Viewed")
    viewer = harness.new_actor("Viewer")
    set_world_role(
        harness.connection,
        world_id=world.world_id,
        user_id=viewer.user_id,
        role_code="world_viewer",
    )

    authority = resolve_world_authority(
        harness.connection, user_id=viewer.user_id, world_id=world.world_id
    )

    assert authority is not None
    assert authority.capabilities == {"world.view"}


def test_world_viewer_lists_and_reads_the_world_with_no_actions(harness: AuthoringHarness) -> None:
    world = _world(harness, "Viewed")
    viewer = harness.new_actor("Viewer")
    set_world_role(
        harness.connection,
        world_id=world.world_id,
        user_id=viewer.user_id,
        role_code="world_viewer",
    )

    listed = viewer.get("/worlds", status="all").json()["items"]
    detail = viewer.get(f"/worlds/{world.world_id}")
    timeline = viewer.get(f"/worlds/{world.world_id}/timelines/{world.primary_timeline_id}")
    calendars = viewer.get(f"/worlds/{world.world_id}/calendars")

    assert [(item["world_id"], item["capabilities"]) for item in listed] == [
        (str(world.world_id), ["world.view"])
    ]
    assert detail.status_code == 200, detail.text
    assert detail.json()["capabilities"] == ["world.view"]
    assert detail.json()["available_actions"] == []
    assert detail.json()["blocked_actions"] == []
    assert detail.json()["managed_campaigns"] == []
    assert [t["timeline_id"] for t in detail.json()["timelines"]] == [
        str(world.primary_timeline_id)
    ]
    assert timeline.status_code == 200, timeline.text
    assert timeline.json()["available_actions"] == []
    assert timeline.json()["blocked_actions"] == []
    assert calendars.status_code == 200, calendars.text


def test_world_viewer_cannot_mutate_the_world(harness: AuthoringHarness) -> None:
    world = _world(harness, "Viewed")
    viewer = harness.new_actor("Viewer")
    set_world_role(
        harness.connection,
        world_id=world.world_id,
        user_id=viewer.user_id,
        role_code="world_viewer",
    )
    before = harness.connection.execute(
        text("SELECT name, row_version FROM core.worlds WHERE world_id = :w"),
        {"w": world.world_id},
    ).one()

    # Authority exists, the capability does not: 403 on world/timeline routes.
    _assert_no_world_mutation(viewer, world, expected=403)
    # The commands re-check under their own locks, independent of the routes.
    with pytest.raises(WorldNotAuthorizedError):
        update_world(
            harness.connection,
            world_id=world.world_id,
            actor_user_id=viewer.user_id,
            expected_row_version=before.row_version,
            name="Edited",
            description=None,
        )
    with pytest.raises(WorldNotAuthorizedError):
        create_timeline(
            harness.connection,
            world_id=world.world_id,
            actor_user_id=viewer.user_id,
            name="Side",
            description=None,
        )

    after = harness.connection.execute(
        text("SELECT name, row_version FROM core.worlds WHERE world_id = :w"),
        {"w": world.world_id},
    ).one()
    assert tuple(after) == tuple(before)


def test_world_owner_still_sees_every_applicable_action(harness: AuthoringHarness) -> None:
    owner = harness.new_actor("Owner", world_creator=True)
    world = make_authored_world(harness.connection, owner_user_id=owner.user_id)

    detail = owner.get(f"/worlds/{world.world_id}").json()
    timeline = owner.get(f"/worlds/{world.world_id}/timelines/{world.primary_timeline_id}").json()

    assert set(detail["available_actions"]) == {
        "update",
        "archive",
        "create_timeline",
        "create_campaign",
        "create_calendar",
    }
    assert {b["action"] for b in detail["blocked_actions"]} == {"restore"}
    assert set(timeline["available_actions"]) == {"update", "create_branch", "create_campaign"}


# --- campaign.view is not world authority -------------------------------------------------


def test_campaign_player_gets_no_world_entry_or_world_route(harness: AuthoringHarness) -> None:
    world = _world(harness, "Campaign World")
    campaign_id = make_authored_campaign(harness.connection, world)
    player = harness.new_actor("Player")
    _player_in(harness.connection, campaign_id, player.user_id)

    assert player.get("/worlds", status="all").json()["items"] == []
    assert player.get(f"/worlds/{world.world_id}").status_code == 404
    assert (
        player.get(f"/worlds/{world.world_id}/timelines/{world.primary_timeline_id}").status_code
        == 404
    )
    # Campaign-scoped World Explorer reads are what campaign.view permits.
    assert player.get(f"/campaigns/{campaign_id}/world/search").status_code == 200
    # No world role was created for the player.
    assert player.user_id not in _open_roles(harness.connection, world.world_id)
    _assert_no_world_mutation(player, world, expected=404)


# --- membership commands ------------------------------------------------------------------


def test_set_world_role_refuses_an_ineligible_owner_and_writes_nothing(
    harness: AuthoringHarness,
) -> None:
    world = _world(harness, "Guarded")
    player = harness.new_actor("Player")

    with pytest.raises(WorldMembershipChangeRefusedError, match="may not own worlds"):
        set_world_role(
            harness.connection,
            world_id=world.world_id,
            user_id=player.user_id,
            role_code="world_owner",
        )
    assert _membership_rows(harness.connection, world.world_id, player.user_id) == 0


def test_set_world_role_is_idempotent_and_keeps_history_on_a_role_change(
    harness: AuthoringHarness,
) -> None:
    world = _world(harness, "Roles")
    user = harness.new_actor("Changing", world_creator=True)
    first = set_world_role(
        harness.connection, world_id=world.world_id, user_id=user.user_id, role_code="world_viewer"
    )
    again = set_world_role(
        harness.connection, world_id=world.world_id, user_id=user.user_id, role_code="world_viewer"
    )
    promoted = set_world_role(
        harness.connection, world_id=world.world_id, user_id=user.user_id, role_code="world_owner"
    )

    assert [c.action for c in first] == ["created"]
    assert again == []
    assert [(c.action, c.role_code) for c in promoted] == [
        ("ended", "world_viewer"),
        ("created", "world_owner"),
    ]
    assert _open_roles(harness.connection, world.world_id)[user.user_id] == "world_owner"
    assert _membership_rows(harness.connection, world.world_id, user.user_id) == 2


def test_the_last_owner_cannot_be_ended_or_demoted(harness: AuthoringHarness) -> None:
    world = _world(harness, "Sole Owner")

    with pytest.raises(WorldMembershipChangeRefusedError, match="no active world_owner"):
        end_world_membership(
            harness.connection, world_id=world.world_id, user_id=world.owner_user_id
        )
    with pytest.raises(WorldMembershipChangeRefusedError, match="no active world_owner"):
        set_world_role(
            harness.connection,
            world_id=world.world_id,
            user_id=world.owner_user_id,
            role_code="world_viewer",
        )
    assert _open_roles(harness.connection, world.world_id) == {world.owner_user_id: "world_owner"}


def test_world_viewer_membership_can_be_revoked(harness: AuthoringHarness) -> None:
    world = _world(harness, "Revocable")
    viewer = harness.new_actor("Viewer")
    set_world_role(
        harness.connection,
        world_id=world.world_id,
        user_id=viewer.user_id,
        role_code="world_viewer",
    )

    end_world_membership(harness.connection, world_id=world.world_id, user_id=viewer.user_id)

    assert viewer.get(f"/worlds/{world.world_id}").status_code == 404
    assert viewer.get("/worlds", status="all").json()["items"] == []
    assert _membership_rows(harness.connection, world.world_id, viewer.user_id) == 1


# --- legacy player-owned world remediation ------------------------------------------------


def _legacy_player_owned_world(harness: AuthoringHarness, player: Actor) -> uuid.UUID:
    """A world a player owns from before ADR 0018 (reproduced through the
    legacy claim path, which requires only an active account)."""
    world_id = make_world(harness.connection, f"legacy-{uuid.uuid4().hex[:8]}", name="test 1")
    claim_unowned_world(harness.connection, world_id=world_id, user_id=player.user_id)
    return world_id


@pytest.mark.parametrize("retain_viewer", [True, False])
def test_transfer_remediates_a_player_owned_world_without_deleting_it(
    harness: AuthoringHarness, retain_viewer: bool
) -> None:
    hosted = _world(harness, "Hosted")
    campaign_id = make_authored_campaign(harness.connection, hosted)
    player = harness.new_actor("Player")
    _player_in(harness.connection, campaign_id, player.user_id)
    legacy_id = _legacy_player_owned_world(harness, player)
    gm = harness.new_actor("Successor", world_creator=True)
    assert [
        w.user_id
        for w in manage_world_membership.list_ineligible_owners(harness.connection)
        if w.world_id == legacy_id
    ] == [player.user_id]

    transfer_world_ownership(
        harness.connection,
        world_id=legacy_id,
        from_user_id=player.user_id,
        to_user_id=gm.user_id,
        retain_viewer=retain_viewer,
    )

    # The world and its history survive.
    assert (
        harness.connection.execute(
            text("SELECT name FROM core.worlds WHERE world_id = :w"), {"w": legacy_id}
        ).scalar()
        == "test 1"
    )
    assert _membership_rows(harness.connection, legacy_id, player.user_id) == (
        2 if retain_viewer else 1
    )
    expected = {gm.user_id: "world_owner"}
    if retain_viewer:
        expected[player.user_id] = "world_viewer"
    assert _open_roles(harness.connection, legacy_id) == expected
    assert legacy_id not in {
        w.world_id for w in manage_world_membership.list_ineligible_owners(harness.connection)
    }

    # The former owner has no authoring access left...
    update = player.post_raw(
        f"/worlds/{legacy_id}/update", {"expected_row_version": 1, "name": "Mine"}
    )
    assert update.status_code == (403 if retain_viewer else 404), update.text
    listed = player.get("/worlds", status="all").json()["items"]
    if retain_viewer:
        assert [(w["world_id"], w["capabilities"]) for w in listed] == [
            (str(legacy_id), ["world.view"])
        ]
        assert player.get(f"/worlds/{legacy_id}").json()["available_actions"] == []
    else:
        assert listed == []
    # ...and keeps campaign-scoped viewing.
    assert player.get(f"/campaigns/{campaign_id}/world/search").status_code == 200
    session = player.get("/auth/session").json()
    assert [c["campaign_id"] for c in session["campaigns"]] == [str(campaign_id)]
    assert "world.create" not in session.get("global_capabilities", [])


def test_transfer_refuses_an_ineligible_successor_and_changes_nothing(
    harness: AuthoringHarness,
) -> None:
    player = harness.new_actor("Player")
    legacy_id = _legacy_player_owned_world(harness, player)
    other_player = harness.new_actor("Other Player")

    with pytest.raises(WorldMembershipChangeRefusedError, match="may not own worlds"):
        transfer_world_ownership(
            harness.connection,
            world_id=legacy_id,
            from_user_id=player.user_id,
            to_user_id=other_player.user_id,
            retain_viewer=True,
        )
    assert _open_roles(harness.connection, legacy_id) == {player.user_id: "world_owner"}


def test_the_script_previews_by_default_and_audits_an_applied_transfer(
    harness: AuthoringHarness,
) -> None:
    player = harness.new_actor("Player")
    legacy_id = _legacy_player_owned_world(harness, player)
    gm = harness.new_actor("Successor", world_creator=True)

    changes = manage_world_membership.apply_transfer(
        harness.connection,
        world_id=legacy_id,
        from_user_id=player.user_id,
        to_user_id=gm.user_id,
        retain_viewer=True,
    )

    audited = harness.connection.execute(
        text("""
            SELECT record_id, command_name, actor_service, changed_fields
            FROM audit.change_log
            WHERE table_name = 'world_memberships' AND world_id = :w
              AND command_name = 'transfer_world_ownership'
            ORDER BY change_log_id
        """),
        {"w": legacy_id},
    ).all()
    assert [row.record_id for row in audited] == [c.world_membership_id for c in changes]
    assert {row.actor_service for row in audited} == {"manage_world_membership_script"}
    assert [
        (row.changed_fields["membership"], row.changed_fields["world_role"]) for row in audited
    ] == [
        ("created", "world_owner"),
        ("ended", "world_owner"),
        ("created", "world_viewer"),
    ]


# --- the observed local defect, end to end -----------------------------------------------


def test_observed_player_with_a_legacy_world_and_a_roleless_membership(
    harness: AuthoringHarness,
) -> None:
    """Phase13E Dev Player A, reproduced: owns a legacy world ("test 1"); plays
    in Campaign A on another world; holds an active but roleless membership in
    Campaign B on that same world, which is also their last-visited campaign."""
    hosted = _world(harness, "Phase13C Dev World")
    campaign_a = make_authored_campaign(harness.connection, hosted, name="Campaign A")
    campaign_b = make_authored_campaign(harness.connection, hosted, name="Campaign B")
    player = harness.new_actor("Player A")
    _player_in(harness.connection, campaign_a, player.user_id)
    make_campaign_membership(harness.connection, campaign_b, player.user_id)
    owned_id = _legacy_player_owned_world(harness, player)
    harness.connection.execute(
        text("""
            INSERT INTO security.user_portal_preferences (user_id, last_visited_campaign_id)
            VALUES (:u, :c)
        """),
        {"u": player.user_id, "c": campaign_b},
    )

    session = player.get("/auth/session").json()
    worlds = player.get("/worlds", status="all").json()["items"]

    # Bootstrap: only the viewable campaign; the roleless one is not selectable.
    assert [c["campaign_id"] for c in session["campaigns"]] == [str(campaign_a)]
    assert session["startup_campaign_id"] == str(campaign_a)
    assert session["campaign_preferences"]["last_visited_campaign_id"] is None
    assert str(campaign_b) not in str(session)
    # The campaign-visible world comes from the bootstrap, the owned one from /worlds.
    assert session["campaigns"][0]["world_id"] == str(hosted.world_id)
    assert [(w["world_id"], w["capabilities"]) for w in worlds] == [
        (str(owned_id), ["campaign.create", "timeline.manage", "world.manage", "world.view"])
    ]
    # Campaign World opens through campaign.view; the inaccessible one does not.
    assert player.get(f"/campaigns/{campaign_a}/world/search").status_code == 200
    assert player.get(f"/campaigns/{campaign_b}/world/search").status_code == 403
    # The campaign-visible world exposes no world route, so no editing.
    assert player.get(f"/worlds/{hosted.world_id}").status_code == 404
    _assert_no_world_mutation(player, hosted, expected=404)
    # Only the owned world exposes editing.
    owned = player.get(f"/worlds/{owned_id}").json()
    assert "update" in owned["available_actions"]
    # The inaccessible campaign cannot be stored as a preference either.
    refused = player.client.put(
        "/auth/preferences/last-visited-campaign",
        json={"campaign_id": str(campaign_b)},
        headers=player.headers(),
    )
    assert refused.status_code == 404, refused.text
