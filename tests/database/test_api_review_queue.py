"""Review queue and revision comparison (checkpoint 15.3C-2, decision D-25)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup, add_member

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def queue(s: ContentSetup, actor=None, cid: str | None = None, **params: object):  # type: ignore[no-untyped-def]
    return (actor or s.gm).get(f"/campaigns/{cid or s.cid}/review-queue", **params)


def new_place(s: ContentSetup, name: str, category: str = "settlement") -> dict:
    response = s.gm.post(
        s.url("locations"), {"category": category, "name": name}, key=s.gm.fresh_key()
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def names(response) -> list[str]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return [i["name"] for i in response.json()["items"]]


def stage(s: ContentSetup, place: dict, *actions: str) -> int:
    version = int(place["row_version"])
    for action in actions:
        version = int(s.transition(place["location_id"], action, version)["row_version"])
    return version


def test_the_queue_lists_unpublished_records_by_where_they_stand(s: ContentSetup) -> None:
    draft = new_place(s, "A Draft")
    review = new_place(s, "In Review")
    approved = new_place(s, "Approved")
    published = new_place(s, "Published")
    archived = new_place(s, "Archived")
    stage(s, review, "submit-for-review")
    stage(s, approved, "submit-for-review", "approve")
    stage(s, published, "submit-for-review", "approve", "publish")
    stage(s, archived, "submit-for-review", "approve", "publish", "archive")
    assert draft["location_id"]
    assert sorted(names(queue(s))) == ["A Draft", "Approved", "In Review"]
    assert names(queue(s, status="draft")) == ["A Draft"]
    assert names(queue(s, status="in_review")) == ["In Review"]
    assert names(queue(s, status="approved")) == ["Approved"]
    assert names(queue(s, status="archived")) == ["Archived"]
    assert names(queue(s, status="rejected")) == []
    body = queue(s).json()
    assert body["counts"] == {
        "draft": 1,
        "in_review": 1,
        "approved": 1,
        "rejected": 0,
        "archived": 1,
    }
    assert [x["value"] for x in body["statuses"]][0] == "pending"
    row = next(i for i in body["items"] if i["name"] == "In Review")
    assert row["category"] == "location" and row["entity_type_code"] == "settlement"
    assert row["canon_status"] == "proposed" and row["last_change_by_me"] is True
    assert row["last_change_by"] is not None


def test_the_queue_filters_by_type_and_pages_by_keyset(s: ContentSetup) -> None:
    for n in range(5):
        new_place(s, f"Town {n}")
    new_place(s, "A Region", category="region")
    only_regions = queue(s, type="region")
    assert names(only_regions) == ["A Region"]
    assert names(queue(s, type="quest")) == []
    assert names(queue(s, type="not_a_type")) == []
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        page = queue(s, limit=2, **({"cursor": cursor} if cursor else {}))
        assert page.status_code == 200, page.text
        seen += [i["name"] for i in page.json()["items"]]
        cursor = page.json()["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 6 and len(set(seen)) == 6
    assert queue(s, cursor="not-a-cursor").status_code == 422
    assert queue(s, status="nonsense").status_code == 422


def test_the_queue_never_shows_another_worlds_records_and_refuses_players(s: ContentSetup) -> None:
    new_place(s, "Mine")
    s.stranger.post(
        s.url("locations", s.other_cid),
        {"category": "settlement", "name": "Theirs"},
        key=s.stranger.fresh_key(),
    )
    assert names(queue(s)) == ["Mine"]
    assert names(queue(s, actor=s.stranger, cid=s.other_cid)) == ["Theirs"]
    assert queue(s, actor=s.player).status_code == 403


def test_history_lists_revisions_newest_first_and_compare_reads_the_authored_fields(
    s: ContentSetup,
) -> None:
    place = new_place(s, "Stonebridge")
    place_id = place["location_id"]
    updated = s.gm.post(
        s.url(f"locations/{place_id}/update"),
        {
            "expected_row_version": place["row_version"],
            "name": "Stonebridge",
            "summary": "A river town with a toll bridge",
        },
        key=s.gm.fresh_key(),
    )
    assert updated.status_code == 200, updated.text
    version = int(updated.json()["row_version"])
    submitted = int(s.transition(place_id, "submit-for-review", version)["row_version"])
    history = s.gm.get(f"/campaigns/{s.cid}/entities/{place_id}/revisions").json()
    assert [(r["row_version"], r["kind"]) for r in history["revisions"]] == [
        (submitted, "lifecycle"),
        (version, "updated"),
        (1, "created"),
    ]
    assert history["revisions"][0]["canon_status"] == "proposed"
    assert history["revisions"][1]["created_by_name"] is not None
    compared = s.gm.get(
        f"/campaigns/{s.cid}/entities/{place_id}/revisions/compare", **{"from": 1, "to": submitted}
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert body["from_authored_version"] == 1 and body["to_authored_version"] == version
    changes = {c["path"]: c for c in body["changes"]}
    assert changes["summary"]["kind"] in ("added", "changed")
    assert changes["summary"]["after"] == "A river town with a toll bridge"
    assert "canon_status" not in changes
    same = s.gm.get(
        f"/campaigns/{s.cid}/entities/{place_id}/revisions/compare",
        **{"from": version, "to": submitted},
    )
    assert same.status_code == 200 and same.json()["changes"] == []


def test_compare_refuses_unknown_versions_other_worlds_and_players(s: ContentSetup) -> None:
    place = new_place(s, "Stonebridge")
    place_id = place["location_id"]
    base = f"/campaigns/{s.cid}/entities/{place_id}/revisions"
    assert s.gm.get(base + "/compare", **{"from": 1, "to": 99}).status_code == 404
    assert s.gm.get(base + "/compare", **{"from": 0, "to": 1}).status_code == 422
    assert s.player.get(base).status_code == 403
    assert s.player.get(base + "/compare", **{"from": 1, "to": 1}).status_code == 403
    assert (
        s.stranger.get(f"/campaigns/{s.other_cid}/entities/{place_id}/revisions").status_code == 404
    )


def test_approving_ones_own_work_is_allowed_and_audited_but_a_reviewer_is_not_flagged(
    s: ContentSetup,
) -> None:
    mine = new_place(s, "My Own Work")
    stage(s, mine, "submit-for-review", "approve")
    reviewer = s.harness.new_actor("Reviewer")
    add_member(s.connection, s.cid, reviewer.user_id, "gm")
    assert (
        s.gm.post(
            f"/worlds/{s.world_id}/roles",
            {"login_name": reviewer.login_name, "role_code": "world_reviewer"},
        ).status_code
        == 201
    )
    theirs = new_place(s, "Reviewed By Another")
    version = stage(s, theirs, "submit-for-review")
    approved = reviewer.post(
        s.lifecycle(theirs["location_id"], "/approve"),
        {"expected_row_version": version},
        key=reviewer.fresh_key(),
    )
    assert approved.status_code == 200, approved.text
    rows = s.audit("approve_entity")
    flagged = {str(r.entity_id): "self_approved" in str(r.changed_fields) for r in rows}
    assert flagged[mine["location_id"]] is True
    assert flagged[theirs["location_id"]] is False
