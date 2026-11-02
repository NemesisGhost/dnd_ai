"""The World Reader surface (docs/adr/0020-scoped-system-world-and-campaign-roles.md,
decision D5, checkpoint SR-7): published canon only, in the player-safe card form,
and nothing from any campaign."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _location(s: ContentSetup, name: str, summary: str | None = None) -> dict:
    response = s.gm.post(
        s.url("locations"),
        {"category": "region", "name": name, "summary": summary},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _share_reader(s: ContentSetup, harness: AuthoringHarness, name: str = "Reader"):  # type: ignore[no-untyped-def]
    reader = harness.new_actor(name)
    response = s.gm.post(
        f"/worlds/{s.world_id}/roles",
        {"login_name": reader.login_name, "role_code": "world_reader"},
    )
    assert response.status_code == 201, response.text
    return reader


def test_a_reader_sees_published_canon_only(s: ContentSetup, harness: AuthoringHarness) -> None:
    published = _location(s, "Published Citadel", "Visible to all")
    s.publish(published["location_id"], published["row_version"])
    draft = _location(s, "Secret Draft Keep", "Not yet")
    archived = _location(s, "Old Ruin")
    version = s.publish(archived["location_id"], archived["row_version"])
    s.gm.post(
        s.lifecycle(archived["location_id"], "/archive"),
        {"expected_row_version": version},
        key=s.gm.fresh_key(),
    )
    reader = _share_reader(s, harness)

    response = reader.get(f"/worlds/{s.world_id}/canon")
    assert response.status_code == 200, response.text
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["Published Citadel"]
    assert draft["location_id"] not in response.text
    item = response.json()["items"][0]
    assert set(item) == {"entity_id", "category", "name", "summary"}
    assert item["summary"] == "Visible to all"


def test_a_reader_gets_no_private_side_and_no_campaign_data(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    location = _location(s, "Hall")
    s.publish(location["location_id"], location["row_version"])
    reader = _share_reader(s, harness)
    for path in (
        f"/worlds/{s.world_id}/access",
        f"/campaigns/{s.cid}/clock",
        f"/campaigns/{s.cid}/world/search",
        f"/campaigns/{s.cid}/review-queue",
        f"/campaigns/{s.cid}/entities/{location['location_id']}/revisions",
        f"/campaigns/{s.cid}/entities/{location['location_id']}/provenance",
        f"/campaigns/{s.cid}/sessions",
    ):
        assert reader.get(path).status_code in (403, 404), path


def test_search_and_paging_work_over_published_canon(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    for name in ("Alder Vale", "Birch Vale", "Cedar Hollow"):
        item = _location(s, name)
        s.publish(item["location_id"], item["row_version"])
    reader = _share_reader(s, harness)
    found = reader.get(f"/worlds/{s.world_id}/canon", q="Vale").json()["items"]
    assert [i["name"] for i in found] == ["Alder Vale", "Birch Vale"]
    first = reader.get(f"/worlds/{s.world_id}/canon", limit=2).json()
    assert len(first["items"]) == 2 and first["next_cursor"] is not None
    second = reader.get(f"/worlds/{s.world_id}/canon", limit=2, cursor=first["next_cursor"]).json()
    assert [i["name"] for i in second["items"]] == ["Cedar Hollow"]


def test_only_readers_and_other_world_role_holders_may_browse(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    host = harness.new_actor("Host", system_roles=("gm",))
    s.gm.post(f"/worlds/{s.world_id}/use-grants", {"login_name": host.login_name})
    stranger = harness.new_actor("Stranger")
    # A use grant is permission to host a campaign, not to read.
    assert host.get(f"/worlds/{s.world_id}/canon").status_code == 403
    assert stranger.get(f"/worlds/{s.world_id}/canon").status_code == 404
    assert s.gm.get(f"/worlds/{s.world_id}/canon").status_code == 200
