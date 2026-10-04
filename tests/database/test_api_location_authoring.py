"""HTTP contract and command behavior for typed Location authoring (Phase 15.1)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database

CATEGORIES = [
    "location",
    "plane",
    "realm",
    "continent",
    "nation",
    "region",
    "district",
    "geographic_feature",
    "settlement",
    "building",
]


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def create(s: ContentSetup, name: str = "Place", category: str = "region", **extra: object) -> dict:
    response = s.gm.post(
        s.url("locations"),
        {"category": category, "name": name, "summary": None, **extra},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def update(s: ContentSetup, location: dict, **fields: object) -> object:
    body = {
        "expected_row_version": location["row_version"],
        "name": location["name"],
        "summary": location["summary"],
        "parent_location_id": location["parent"] and location["parent"]["location_id"],
        "population": location["population"],
        "building_use": location["building_use"],
        **fields,
    }
    return s.gm.post(
        s.url(f"locations/{location['location_id']}/update"), body, key=s.gm.fresh_key()
    )


# --- create ---------------------------------------------------------------------


@pytest.mark.parametrize("category", CATEGORIES)
def test_each_category_creates_a_complete_draft(s: ContentSetup, category: str) -> None:
    extra: dict[str, object] = {}
    if category == "settlement":
        extra["population"] = 1200
    if category == "building":
        extra["building_use"] = "Tavern"
    view = create(s, f"A {category}", category, **extra)
    assert view["category"]["code"] == category
    assert (view["canon_status"], view["lifecycle_status"], view["changed"]) == (
        "draft",
        "active",
        True,
    )
    assert view["row_version"] >= 1
    assert "update" in view["available_actions"] and "archive" in view["available_actions"]
    row = s.connection.execute(
        text("""
            SELECT et.code, e.created_by_user_id, src.title, st.code AS source_type
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.sources src ON src.source_id = e.source_id
            JOIN core.source_types st ON st.source_type_id = src.source_type_id
            WHERE e.entity_id = :e
        """),
        {"e": view["location_id"]},
    ).one()
    assert (row.code, row.source_type, row.created_by_user_id) == (
        category,
        "gm_entry",
        s.gm.user_id,
    )
    assert (
        s.connection.execute(
            text("SELECT count(*) FROM world.locations WHERE location_id = :e"),
            {"e": view["location_id"]},
        ).scalar()
        == 1
    )
    assert view["population"] == extra.get("population")
    assert view["building_use"] == extra.get("building_use")


def test_create_writes_one_created_audit_row_and_no_timeline_state(s: ContentSetup) -> None:
    states = {
        t: s.count(t)
        for t in (
            "campaign.location_state",
            "narrative.events",
            "knowledge.entity_knowledge",
            "campaign.party_knowledge",
        )
    }
    view = create(s, "Harbor", "settlement", population=10)
    rows = s.audit("create_location")
    assert len(rows) == 1
    row = rows[0]
    assert (row.action, str(row.entity_id), row.world_id, row.actor_user_id) == (
        "created",
        view["location_id"],
        s.world_id,
        s.gm.user_id,
    )
    assert row.changed_fields["name"] == "Harbor" and row.changed_fields["category"] == "settlement"
    assert row.source_id is not None and row.correlation_id is not None
    assert states == {t: s.count(t) for t in states}


@pytest.mark.parametrize(
    "body",
    [
        {"category": "region", "name": ""},
        {"category": "region", "name": "   "},
        {"category": "region", "name": "x" * 201},
        {"category": "region", "name": "ok", "summary": "x" * 4001},
        {"category": "region", "name": "ok", "population": -1},
        {"category": "region", "name": "ok", "unknown_field": 1},
        {"category": "region", "name": "ok", "world_id": str(uuid.uuid4())},
        {"category": "region", "name": "ok", "entity_type_code": "npc"},
        {"name": "missing category"},
    ],
)
def test_malformed_create_bodies_are_rejected_and_write_nothing(
    s: ContentSetup, body: dict
) -> None:
    before = s.count("core.entities")
    response = s.gm.post(s.url("locations"), body, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)
    assert s.count("core.entities") == before


@pytest.mark.parametrize(
    "category", ["dungeon", "dungeon_area", "npc", "character", "bogus", "Region"]
)
def test_categories_outside_the_closed_set_are_refused(s: ContentSetup, category: str) -> None:
    response = s.gm.post(
        s.url("locations"), {"category": category, "name": "x"}, key=s.gm.fresh_key()
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "validation_failed"


def test_typed_fields_must_match_the_category(s: ContentSetup) -> None:
    for body in (
        {"category": "region", "name": "x", "population": 5},
        {"category": "settlement", "name": "x", "building_use": "inn"},
        {"category": "building", "name": "x", "population": 5},
    ):
        response = s.gm.post(s.url("locations"), body, key=s.gm.fresh_key())
        assert response.status_code == 400, body


def test_a_failure_after_the_root_insert_leaves_no_rows(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dnd_ai.commands.locations as locations

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected failure after the root insert")

    monkeypatch.setattr(locations, "_insert_location_rows", boom)
    tables = (
        "core.entities",
        "core.sources",
        "world.locations",
        "audit.change_log",
        "security.idempotent_requests",
    )
    before = {t: s.count(t) for t in tables}
    response = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": "Doomed"}, key=s.gm.fresh_key()
    )
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}


# --- update ---------------------------------------------------------------------


def test_update_changes_fields_bumps_the_version_and_audits_from_to(s: ContentSetup) -> None:
    created = create(s, "Old name", "settlement", population=10)
    response = update(s, created, name="New name", summary="Seen from afar", population=99)
    assert response.status_code == 200, response.text
    view = response.json()
    assert (view["name"], view["summary"], view["population"], view["changed"]) == (
        "New name",
        "Seen from afar",
        99,
        True,
    )
    assert view["row_version"] > created["row_version"]
    rows = s.audit("update_location")
    assert len(rows) == 1 and rows[0].action == "updated"
    assert rows[0].changed_fields["name"] == {"from": "Old name", "to": "New name"}
    assert rows[0].changed_fields["population"] == {"from": 10, "to": 99}
    assert "category" not in rows[0].changed_fields


def test_an_identical_resubmission_is_a_no_op(s: ContentSetup) -> None:
    created = create(s, "Same", "building", building_use="Inn")
    response = update(s, created)
    assert response.status_code == 200
    view = response.json()
    assert view["changed"] is False and view["row_version"] == created["row_version"]
    assert s.audit("update_location") == []


def test_a_subtype_only_change_still_bumps_the_root_version(s: ContentSetup) -> None:
    created = create(s, "Town", "settlement", population=1)
    view = update(s, created, population=2).json()
    assert view["row_version"] > created["row_version"]


def test_category_is_immutable(s: ContentSetup) -> None:
    created = create(s, "Fixed", "region")
    response = update(s, created, category="settlement")
    assert response.status_code == 422
    assert (
        s.gm.get(s.url(f"locations/{created['location_id']}")).json()["category"]["code"]
        == "region"
    )


def test_a_stale_write_is_a_409_with_no_change_and_no_audit(s: ContentSetup) -> None:
    created = create(s, "Race", "region")
    first = update(s, created, name="First")
    assert first.status_code == 200
    stale = update(s, created, name="Second")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    assert s.gm.get(s.url(f"locations/{created['location_id']}")).json()["name"] == "First"
    assert len(s.audit("update_location")) == 1


@pytest.mark.parametrize("canon", ["proposed", "approved", "rejected", "superseded"])
def test_records_outside_draft_and_canon_cannot_be_edited(s: ContentSetup, canon: str) -> None:
    created = create(s, "Locked", "region")
    s.set_status(created["location_id"], canon=canon)
    current = s.gm.get(s.url(f"locations/{created['location_id']}")).json()
    assert "update" not in current["available_actions"]
    assert any(b["action"] == "update" for b in current["blocked_actions"])
    response = update(s, current, name="Nope")
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "content_not_editable"
    )


def test_archived_records_cannot_be_edited_until_restored(s: ContentSetup) -> None:
    created = create(s, "Old", "region")
    archived = s.transition(created["location_id"], "archive", created["row_version"])
    current = s.gm.get(s.url(f"locations/{created['location_id']}")).json()
    assert update(s, current, name="Nope").status_code == 409
    s.transition(created["location_id"], "restore", archived["row_version"], reason="back")
    current = s.gm.get(s.url(f"locations/{created['location_id']}")).json()
    assert update(s, current, name="Back").status_code == 200


def test_a_canon_edit_stays_canon_and_is_audited(s: ContentSetup) -> None:
    created = create(s, "Published", "region")
    version = s.publish(created["location_id"], created["row_version"])
    current = s.gm.get(s.url(f"locations/{created['location_id']}")).json()
    assert current["row_version"] == version and current["canon_status"] == "canon"
    view = update(s, current, summary="Revised", change_note="typo fix").json()
    assert view["canon_status"] == "canon" and view["summary"] == "Revised"
    row = s.audit("update_location")[0]
    assert row.reason == "typo fix" and row.changed_fields["summary"] == {
        "from": None,
        "to": "Revised",
    }


def test_long_text_in_the_audit_diff_is_bounded(s: ContentSetup) -> None:
    created = create(s, "Long", "region")
    update(s, created, summary="y" * 4000)
    changed = s.audit("update_location")[0].changed_fields["summary"]["to"]
    assert changed["truncated"] is True and len(changed["value"]) == 1000


# --- hierarchy ------------------------------------------------------------------


def test_parent_assignment_and_unassignment(s: ContentSetup) -> None:
    region = create(s, "Region", "region")
    town = create(s, "Town", "settlement", parent_location_id=region["location_id"])
    assert town["parent"]["location_id"] == region["location_id"]
    assert town["parent"]["name"] == "Region"
    cleared = update(s, town, parent_location_id=None).json()
    assert cleared["parent"] is None
    assert s.audit("update_location")[0].changed_fields["parent_location_id"] == {
        "from": region["location_id"],
        "to": None,
    }


def test_a_location_cannot_be_its_own_parent(s: ContentSetup) -> None:
    place = create(s, "Self", "region")
    response = update(s, place, parent_location_id=place["location_id"])
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "location_hierarchy_cycle"
    )


def test_two_and_three_hop_cycles_are_refused(s: ContentSetup) -> None:
    a = create(s, "A", "region")
    b = create(s, "B", "region", parent_location_id=a["location_id"])
    c = create(s, "C", "region", parent_location_id=b["location_id"])
    for target in (b, c):
        current = s.gm.get(s.url(f"locations/{a['location_id']}")).json()
        response = update(s, current, parent_location_id=target["location_id"])
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "location_hierarchy_cycle"
    assert s.gm.get(s.url(f"locations/{a['location_id']}")).json()["parent"] is None
    assert s.audit("update_location") == []


def test_unusable_parents_all_look_the_same(s: ContentSetup) -> None:
    from tests.factories import make_dungeon, make_location, make_world

    unusable: dict[str, str] = {}
    archived = create(s, "Archived parent", "region")
    s.transition(archived["location_id"], "archive", archived["row_version"])
    unusable["archived"] = archived["location_id"]
    rejected = create(s, "Rejected parent", "region")
    s.set_status(rejected["location_id"], canon="rejected")
    unusable["rejected"] = rejected["location_id"]
    superseded = create(s, "Superseded parent", "region")
    s.set_status(superseded["location_id"], canon="superseded")
    unusable["superseded"] = superseded["location_id"]
    unusable["missing"] = str(uuid.uuid4())
    other_world = make_world(s.connection, "foreign-parent")
    unusable["other world"] = str(make_location(s.connection, other_world))
    unusable["dungeon"] = str(make_dungeon(s.connection, s.world_id))
    seen = set()
    for label, parent in unusable.items():
        response = s.gm.post(
            s.url("locations"),
            {"category": "region", "name": f"Child of {label}", "parent_location_id": parent},
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 400, label
        seen.add((response.json()["error"]["code"], response.json()["error"]["message"]))
    assert seen == {("parent_location_invalid", "The selected parent location is not valid.")}


def test_changing_to_an_unusable_parent_is_refused_on_update_too(s: ContentSetup) -> None:
    place = create(s, "Child", "region")
    gone = create(s, "Gone", "region")
    s.transition(gone["location_id"], "archive", gone["row_version"])
    response = update(s, place, parent_location_id=gone["location_id"])
    assert (
        response.status_code == 400
        and response.json()["error"]["code"] == "parent_location_invalid"
    )


def test_an_existing_archived_parent_is_kept_when_editing_other_fields(s: ContentSetup) -> None:
    parent = create(s, "Parent", "region")
    child = create(s, "Child", "region", parent_location_id=parent["location_id"])
    s.transition(parent["location_id"], "archive", parent["row_version"])
    view = update(s, child, name="Renamed child")
    assert view.status_code == 200 and view.json()["parent"]["lifecycle_status"] == "archived"


def test_parent_options_exclude_self_descendants_unusable_and_other_worlds(s: ContentSetup) -> None:
    a = create(s, "A", "region")
    b = create(s, "B", "district", parent_location_id=a["location_id"])
    create(s, "C", "region")
    gone = create(s, "Gone", "region")
    s.transition(gone["location_id"], "archive", gone["row_version"])
    create_other = s.stranger.post(
        s.url("locations", s.other_cid),
        {"category": "region", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    )
    assert create_other.status_code == 201
    names = lambda params: [  # noqa: E731
        i["name"] for i in s.gm.get(s.url("locations/parent-options"), **params).json()["items"]
    ]
    assert names({}) == ["A", "B", "C"]
    assert names({"for": a["location_id"]}) == ["C"]
    assert names({"for": b["location_id"]}) == ["A", "C"]
    assert names({"q": "c"}) == ["C"]


def test_parent_options_page_with_a_keyset_cursor(s: ContentSetup) -> None:
    for index in range(5):
        create(s, f"Place {index}", "region")
    first = s.gm.get(s.url("locations/parent-options"), limit=2).json()
    second = s.gm.get(
        s.url("locations/parent-options"), limit=2, cursor=first["next_cursor"]
    ).json()
    names = [i["name"] for i in first["items"] + second["items"]]
    assert names == ["Place 0", "Place 1", "Place 2", "Place 3"]
    assert s.gm.get(s.url("locations/parent-options"), cursor="nonsense").status_code == 422


def test_the_options_catalog_describes_typed_fields(s: ContentSetup) -> None:
    body = s.gm.get(s.url("locations/options")).json()
    by_code = {c["code"]: c for c in body["categories"]}
    assert set(by_code) == set(CATEGORIES)
    assert [f["name"] for f in by_code["settlement"]["fields"]] == ["population"]
    assert [f["name"] for f in by_code["building"]["fields"]] == ["building_use"]
    assert by_code["region"]["fields"] == []
    assert body["can_create"] is True and body["limits"]["name_max_length"] == 200


# --- publish preconditions ----------------------------------------------------------


def test_publishing_waits_for_a_published_parent(s: ContentSetup) -> None:
    parent = create(s, "Parent", "region")
    child = create(s, "Child", "settlement", parent_location_id=parent["location_id"])
    version = child["row_version"]
    for action in ("submit-for-review", "approve"):
        version = s.transition(child["location_id"], action, version)["row_version"]
    blocked = s.gm.post(
        s.lifecycle(child["location_id"], "/publish"),
        {"expected_row_version": version},
        key=s.gm.fresh_key(),
    )
    assert (
        blocked.status_code == 409 and blocked.json()["error"]["code"] == "reference_not_published"
    )
    view = s.gm.get(s.url(f"locations/{child['location_id']}")).json()
    assert {"action": "publish", "reason": "reference_not_published"} in view["blocked_actions"]
    lifecycle = s.gm.get(s.lifecycle(child["location_id"])).json()
    assert {"action": "publish", "reason": "reference_not_published"} in lifecycle[
        "blocked_actions"
    ]

    s.publish(parent["location_id"], parent["row_version"])
    assert s.transition(child["location_id"], "publish", version)["canon_status"] == "canon"


# --- authorization --------------------------------------------------------------------


def test_players_stranger_and_anonymous_callers_are_refused(
    harness: AuthoringHarness, s: ContentSetup
) -> None:
    place = create(s, "Secret draft", "region")
    paths = [
        ("get", s.url("locations/options")),
        ("get", s.url("locations/parent-options")),
        ("get", s.url(f"locations/{place['location_id']}")),
        ("post", s.url("locations")),
        ("post", s.url(f"locations/{place['location_id']}/update")),
    ]
    body = {"category": "region", "name": "x", "expected_row_version": 1}
    for method, path in paths:
        call = getattr(s.player, method)
        response = call(path) if method == "get" else call(path, body, key=s.player.fresh_key())
        assert response.status_code == 403, path
    stranger = s.stranger
    for method, path in paths:
        call = getattr(stranger, method)
        response = call(path) if method == "get" else call(path, body, key=stranger.fresh_key())
        assert response.status_code == 404, path
    assert harness.anonymous_client().get(s.url("locations/options")).status_code == 401
    assert s.count("core.entities") >= 1
    names = s.connection.execute(text("SELECT canonical_name FROM core.entities")).scalars().all()
    assert "x" not in names


def test_foundry_principals_csrf_and_origin_are_enforced(s: ContentSetup) -> None:
    foundry = AuthenticatedPrincipal(
        user_id=s.gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.UUID(s.cid),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    client = s.harness.principal_client(foundry)
    assert client.get(s.url("locations/options")).status_code == 403
    assert (
        client.post(s.url("locations"), json={"category": "region", "name": "x"}).status_code == 403
    )
    body = {"category": "region", "name": "x"}
    assert s.gm.post(s.url("locations"), body, csrf=False).status_code == 403
    assert s.gm.post(s.url("locations"), body, origin=False).status_code == 403


def test_cross_world_and_missing_locations_are_the_same_404(s: ContentSetup) -> None:
    foreign = s.stranger.post(
        s.url("locations", s.other_cid),
        {"category": "region", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    ).json()
    for target in (foreign["location_id"], str(uuid.uuid4())):
        assert s.gm.get(s.url(f"locations/{target}")).status_code == 404
        body = {"expected_row_version": 1, "name": "x", "summary": None, "parent_location_id": None}
        assert s.gm.post(s.url(f"locations/{target}/update"), body).status_code == 404
        assert (
            s.gm.post(s.lifecycle(target, "/archive"), {"expected_row_version": 1}).status_code
            == 404
        )


def test_a_non_location_entity_at_the_location_route_is_a_404(s: ContentSetup) -> None:
    from tests.factories import make_character

    npc = make_character(s.connection, s.world_id, name="NPC")
    assert s.gm.get(s.url(f"locations/{npc}")).status_code == 404


def test_authoring_reads_are_never_cacheable(s: ContentSetup) -> None:
    place = create(s, "Cache me not", "region")
    for path in (
        "locations/options",
        "locations/parent-options",
        f"locations/{place['location_id']}",
    ):
        assert s.gm.get(s.url(path)).headers["cache-control"] == "no-store"


def test_drafts_never_reach_players_through_the_world_explorer(s: ContentSetup) -> None:
    place = create(s, "Hidden", "region")
    assert (
        s.player.get(f"/campaigns/{s.cid}/world/locations/{place['location_id']}").status_code
        == 404
    )
    search = s.player.get(f"/campaigns/{s.cid}/world/search", q="Hidden").json()
    assert all(item["name"] != "Hidden" for item in search.get("items", []))
    published = create(s, "Visible", "region")
    s.publish(published["location_id"], published["row_version"])
    assert (
        s.player.get(f"/campaigns/{s.cid}/world/locations/{published['location_id']}").status_code
        == 200
    )


# --- idempotency ------------------------------------------------------------------------


def test_replay_returns_the_stored_response_without_new_rows_or_audit(s: ContentSetup) -> None:
    body = {"category": "region", "name": "Once"}
    first = s.gm.post(s.url("locations"), body, key="loc-create-1")
    second = s.gm.post(s.url("locations"), body, key="loc-create-1")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert len(s.audit("create_location")) == 1
    assert (
        s.connection.execute(
            text("SELECT count(*) FROM core.entities WHERE canonical_name = 'Once'")
        ).scalar()
        == 1
    )


def test_the_same_key_with_a_different_body_is_a_conflict(s: ContentSetup) -> None:
    assert (
        s.gm.post(s.url("locations"), {"category": "region", "name": "A"}, key="k-1").status_code
        == 201
    )
    conflict = s.gm.post(s.url("locations"), {"category": "region", "name": "B"}, key="k-1")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] not in ("stale_write", "content_not_editable")


def test_a_failed_attempt_does_not_consume_the_key(s: ContentSetup) -> None:
    bad = s.gm.post(
        s.url("locations"), {"category": "region", "name": "x", "population": 5}, key="k-retry"
    )
    assert bad.status_code == 400
    good = s.gm.post(s.url("locations"), {"category": "region", "name": "Fixed"}, key="k-retry")
    assert good.status_code == 201


def test_update_replay_precedes_the_version_check(s: ContentSetup) -> None:
    created = create(s, "Replay", "region")
    body = {
        "expected_row_version": created["row_version"],
        "name": "Renamed",
        "summary": None,
        "parent_location_id": None,
    }
    path = s.url(f"locations/{created['location_id']}/update")
    first = s.gm.post(path, body, key="upd-1")
    replay = s.gm.post(path, body, key="upd-1")
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    assert len(s.audit("update_location")) == 1
    fresh = s.gm.post(path, body, key="upd-2")
    assert fresh.status_code == 409 and fresh.json()["error"]["code"] == "stale_write"


def test_a_removed_role_cannot_replay_a_stored_response(s: ContentSetup) -> None:
    from tests.content_support import add_member

    deputy = s.harness.new_actor("Deputy")
    add_member(s.connection, s.cid, deputy.user_id, "campaign_owner")
    body = {"category": "region", "name": "Deputy's"}
    assert deputy.post(s.url("locations"), body, key="dep-1").status_code == 201
    s.connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE campaign_membership_id = "
            "(SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u)"
        ),
        {"c": s.cid, "u": deputy.user_id},
    )
    assert deputy.post(s.url("locations"), body, key="dep-1").status_code == 403


# --- authority lost under lock ---------------------------------------------------------------


def test_the_command_re_checks_canon_edit_after_the_route(s: ContentSetup) -> None:
    from dnd_ai.commands.locations import create_location
    from dnd_ai.domain.authoring import CampaignNotAuthorizedError

    with pytest.raises(CampaignNotAuthorizedError):
        create_location(
            s.connection,
            campaign_id=uuid.UUID(s.cid),
            actor_user_id=s.player.user_id,
            category_code="region",
            name="Sneaky",
            summary=None,
        )
    with pytest.raises(CampaignNotAuthorizedError):
        create_location(
            s.connection,
            campaign_id=uuid.UUID(s.cid),
            actor_user_id=s.stranger.user_id,
            category_code="region",
            name="Sneaky",
            summary=None,
        )


def test_an_archived_campaign_or_world_refuses_authoring(s: ContentSetup) -> None:
    from dnd_ai.commands.locations import create_location
    from dnd_ai.domain.authoring import CampaignArchivedError

    s.connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
            "WHERE campaign_id = :c"
        ),
        {"c": s.cid},
    )
    with pytest.raises(CampaignArchivedError):
        create_location(
            s.connection,
            campaign_id=uuid.UUID(s.cid),
            actor_user_id=s.gm.user_id,
            category_code="region",
            name="Late",
            summary=None,
        )


def test_a_disabled_account_cannot_author(s: ContentSetup) -> None:
    from dnd_ai.commands.locations import create_location
    from dnd_ai.domain.authoring import CampaignNotAuthorizedError

    s.connection.execute(
        text(
            "UPDATE security.users SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive') "
            "WHERE user_id = :u"
        ),
        {"u": s.gm.user_id},
    )
    with pytest.raises(CampaignNotAuthorizedError):
        create_location(
            s.connection,
            campaign_id=uuid.UUID(s.cid),
            actor_user_id=s.gm.user_id,
            category_code="region",
            name="Ghost",
            summary=None,
        )


def test_lifecycle_commands_also_require_an_active_campaign_and_account(s: ContentSetup) -> None:
    from dnd_ai.commands.entity_lifecycle import archive_entity
    from dnd_ai.domain.authoring import CampaignArchivedError, CampaignNotAuthorizedError

    place = create(s, "Lifecycle scope", "region")
    kwargs = {
        "campaign_id": uuid.UUID(s.cid),
        "entity_id": uuid.UUID(place["location_id"]),
        "expected_row_version": place["row_version"],
    }
    with pytest.raises(CampaignNotAuthorizedError):
        archive_entity(s.connection, actor_user_id=s.player.user_id, **kwargs)  # type: ignore[arg-type]
    s.connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
            "WHERE campaign_id = :c"
        ),
        {"c": s.cid},
    )
    with pytest.raises(CampaignArchivedError):
        archive_entity(s.connection, actor_user_id=s.gm.user_id, **kwargs)  # type: ignore[arg-type]
