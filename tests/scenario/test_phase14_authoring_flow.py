"""Phase 14 exit scenario: a GM sets up a world, timelines, a campaign and a
canon record using only the HTTP API — a real signed-in cookie session, CSRF
token and Origin check on every write — with no SQL, seeds, import, AI or VTT.

The only direct SQL is (a) the second player's campaign membership, because
invitation delivery is Phase 16 collaboration work already covered elsewhere,
and (b) the draft world record the lifecycle section walks, because the
authoring commands for world content are Phase 15 (the lifecycle commands are
the shared Phase 14 kernel those phases will use).
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.factories import make_location, status_id

pytestmark = pytest.mark.scenario


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def _ok(response, status: int = 200):  # type: ignore[no-untyped-def]
    assert response.status_code == status, response.text
    return response.json()


def _add_player(connection: Connection, campaign_id: str, user_id: uuid.UUID) -> None:
    connection.execute(
        text("""
            INSERT INTO security.campaign_memberships
                (campaign_id, user_id, membership_status_id, joined_at)
            VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                             WHERE code = 'active'), now())
        """),
        {"c": campaign_id, "u": user_id},
    )
    connection.execute(
        text("""
            INSERT INTO security.membership_roles (campaign_membership_id, role_id)
            SELECT cm.campaign_membership_id, r.role_id
            FROM security.campaign_memberships cm, security.roles r
            WHERE cm.campaign_id = :c AND cm.user_id = :u
              AND r.code = 'player' AND r.campaign_id IS NULL
        """),
        {"c": campaign_id, "u": user_id},
    )


def _search_names(actor: Actor, campaign_id: str, **flags: str) -> set[str]:
    body = _ok(actor.get(f"/campaigns/{campaign_id}/world/search", **flags))
    return {item["name"] for item in body["items"]}


def test_a_gm_can_author_a_world_a_campaign_a_branch_and_canon_through_the_portal_api(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM")
    stranger = harness.new_actor("Stranger")

    # 1. The session says this human may create worlds (server-computed).
    assert _ok(gm.get("/auth/session"))["global_capabilities"] == ["world.create"]

    # 2. Rulesets come from the server.
    ruleset = next(r for r in _ok(gm.get("/rulesets"))["items"] if r["code"] == "dnd5e")
    ruleset_id = ruleset["ruleset_id"]
    ruleset_version_id = ruleset["current_versions"][0]["ruleset_version_id"]

    # 3. Create a world with its primary timeline in one command.
    created = _ok(
        gm.post(
            "/worlds",
            {
                "name": "Eberron",
                "description": "A world of airships.",
                "ruleset_ids": [ruleset_id],
                "default_ruleset_id": ruleset_id,
                "primary_timeline": {"name": "Main", "description": None},
            },
            key=gm.fresh_key(),
        ),
        201,
    )
    world_id, main = created["world_id"], created["primary_timeline_id"]

    # 4. The world is listed for its owner and only its owner.
    assert [w["world_id"] for w in _ok(gm.get("/worlds", status="active"))["items"]] == [world_id]
    assert _ok(stranger.get("/worlds", status="active"))["items"] == []
    assert stranger.get(f"/worlds/{world_id}").status_code == 404

    # 5. An additional timeline.
    side = _ok(
        gm.post(
            f"/worlds/{world_id}/timelines",
            {"name": "Side", "description": None},
            key=gm.fresh_key(),
        ),
        201,
    )["timeline_id"]
    detail = _ok(gm.get(f"/worlds/{world_id}"))
    assert {t["name"] for t in detail["timelines"]} == {"Main", "Side"}
    assert "create_campaign" in detail["available_actions"]

    # 6. Create the campaign. A stranger cannot, and learns nothing.
    campaign_body = {
        "timeline_id": main,
        "ruleset_version_id": ruleset_version_id,
        "name": "The Last War",
        "description": None,
    }
    assert stranger.post("/campaigns", campaign_body, key=stranger.fresh_key()).status_code in (
        403,
        404,
    )
    campaign = _ok(gm.post("/campaigns", campaign_body, key=gm.fresh_key()), 201)
    cid = campaign["campaign_id"]

    # 7. The creator holds the owner membership; the bootstrap lists it.
    listed = _ok(gm.get("/auth/session"))["campaigns"]
    assert [(c["campaign_id"], "access.manage" in c["capabilities"]) for c in listed] == [
        (cid, True)
    ]

    # 8. Settings are readable and editable, versioned.
    settings = _ok(gm.get(f"/campaigns/{cid}/settings"))
    assert (settings["name"], settings["world"]["name"], settings["timeline"]["name"]) == (
        "The Last War",
        "Eberron",
        "Main",
    )
    version = settings["row_version"]
    renamed = _ok(
        gm.post(
            f"/campaigns/{cid}/update",
            {"expected_row_version": version, "name": "The Last War, Reforged", "description": "d"},
            key=gm.fresh_key(),
        )
    )
    assert renamed["row_version"] == version + 1
    stale = gm.post(
        f"/campaigns/{cid}/update",
        {"expected_row_version": version, "name": "Lost update", "description": None},
        key=gm.fresh_key(),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"

    # 9. The empty campaign is usable.
    _ok(gm.get(f"/campaigns/{cid}/summary"))
    _ok(gm.get(f"/campaigns/{cid}/sessions"))
    _ok(gm.get(f"/campaigns/{cid}/quests"))

    # 10. A branch from the present, then the lineage is visible.
    branch = _ok(
        gm.post(
            f"/worlds/{world_id}/timelines/{main}/branches",
            {
                "name": "What if the war never ended",
                "description": None,
                "branch_point": {"kind": "latest", "label": "Day of Mourning"},
            },
            key=gm.fresh_key(),
        ),
        201,
    )
    child = _ok(gm.get(f"/worlds/{world_id}/timelines/{branch['timeline_id']}"))
    assert child["parent_timeline_id"] == main
    assert child["branch_point"]["label"] == "Day of Mourning"
    assert side != branch["timeline_id"]

    # 11. Canon lifecycle on a world record, visible to a player only once published.
    player = harness.new_actor("Player")
    _add_player(db_connection, cid, player.user_id)
    place = make_location(db_connection, uuid.UUID(world_id), name="Sharn")
    db_connection.execute(
        text("UPDATE core.entities SET canon_status_id = :s WHERE entity_id = :e"),
        {"s": status_id(db_connection, "canon_statuses", "draft"), "e": place},
    )
    lifecycle = f"/campaigns/{cid}/entities/{place}/lifecycle"

    view = _ok(gm.get(lifecycle))
    assert "submit_for_review" in view["available_actions"]
    assert _ok(player.get(f"/campaigns/{cid}/world/search")) is not None
    assert "Sharn" not in _search_names(player, cid)
    assert player.get(lifecycle).status_code == 403

    for step, expected in (
        ("submit-for-review", "proposed"),
        ("approve", "approved"),
        ("publish", "canon"),
    ):
        view = _ok(gm.get(lifecycle))
        result = _ok(
            gm.post(
                f"{lifecycle}/{step}",
                {"expected_row_version": view["row_version"]},
                key=gm.fresh_key(),
            )
        )
        assert result["canon_status"] == expected
    assert "Sharn" in _search_names(player, cid)

    # 12. Archive hides it from players and lists; the GM can still preview it.
    view = _ok(gm.get(lifecycle))
    _ok(
        gm.post(
            f"{lifecycle}/archive",
            {"expected_row_version": view["row_version"], "reason": "demolished"},
            key=gm.fresh_key(),
        )
    )
    assert "Sharn" not in _search_names(player, cid)
    assert "Sharn" not in _search_names(gm, cid)
    assert "Sharn" in _search_names(gm, cid, include_archived="true")

    # 13. Archive the campaign: it leaves the bootstrap and authorizes nothing but settings/reactivate.
    version = _ok(gm.get(f"/campaigns/{cid}/settings"))["row_version"]
    archived = _ok(
        gm.post(
            f"/campaigns/{cid}/archive",
            {"expected_row_version": version, "reason": None},
            key=gm.fresh_key(),
        )
    )
    assert _ok(gm.get("/auth/session"))["campaigns"] == []
    assert gm.get(f"/campaigns/{cid}/summary").status_code == 404
    assert [c["campaign_id"] for c in _ok(gm.get("/campaigns/archived"))["items"]] == [cid]

    # 14. Reactivate: everything is back, nothing lost.
    _ok(
        gm.post(
            f"/campaigns/{cid}/reactivate",
            {"expected_row_version": archived["row_version"]},
            key=gm.fresh_key(),
        )
    )
    assert [c["campaign_id"] for c in _ok(gm.get("/auth/session"))["campaigns"]] == [cid]
    _ok(gm.get(f"/campaigns/{cid}/summary"))
    assert _ok(gm.get(f"/campaigns/{cid}/settings"))["name"] == "The Last War, Reforged"

    # 15. Replay is durable: the same key returns the same stored answer and creates nothing twice.
    key = gm.fresh_key()
    first = gm.post(f"/worlds/{world_id}/timelines", {"name": "Once", "description": None}, key=key)
    second = gm.post(
        f"/worlds/{world_id}/timelines", {"name": "Once", "description": None}, key=key
    )
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM campaign.timelines WHERE world_id = :w AND name = 'Once'"),
            {"w": world_id},
        ).scalar_one()
        == 1
    )
