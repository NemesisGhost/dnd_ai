"""HTTP contract for the timeline authoring routes (Phase 14)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids
from tests.factories import make_event, make_world_time

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Setup:
    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.connection = connection
        self.gm: Actor = harness.new_actor("GM", world_creator=True)
        ruleset_id, _ = dnd5e_ids(connection)
        created = self.gm.post(
            "/worlds",
            {
                "name": "World",
                "description": None,
                "ruleset_ids": [str(ruleset_id)],
                "default_ruleset_id": str(ruleset_id),
                "primary_timeline": {"name": "Main", "description": None},
            },
            key=self.gm.fresh_key(),
        ).json()
        self.world_id: str = created["world_id"]
        self.primary: str = created["primary_timeline_id"]

    def tl(self, suffix: str = "") -> str:
        return f"/worlds/{self.world_id}/timelines{suffix}"

    def event(self, timeline_id: str, key: int, name: str = "Secret Event") -> str:
        time = make_world_time(self.connection, uuid.UUID(self.world_id), key)
        make_event(
            self.connection, uuid.UUID(self.world_id), uuid.UUID(timeline_id), time, name=name
        )
        return str(time)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> Setup:
    return Setup(harness, db_connection)


def _audit(connection: Connection, command: str) -> list:
    return list(
        connection.execute(
            text(
                "SELECT schema_name, table_name, correlation_id, previous_status, new_status "
                "FROM audit.change_log WHERE command_name = :c ORDER BY change_log_id"
            ),
            {"c": command},
        ).all()
    )


def test_create_root_timeline_then_read_detail(s: Setup) -> None:
    created = s.gm.post(s.tl(), {"name": "Side", "description": "d"}, key=s.gm.fresh_key())
    assert created.status_code == 201
    detail = s.gm.get(s.tl(f"/{created.json()['timeline_id']}")).json()
    assert detail["is_primary"] is False
    assert detail["parent_timeline_id"] is None and detail["branch_point"] is None
    assert detail["children"] == []
    assert set(detail["available_actions"]) == {
        "update",
        "archive",
        "create_branch",
        "create_campaign",
    }
    assert detail["blocked_actions"] == [
        {"action": "restore", "reason": "lifecycle_transition_not_allowed"}
    ]
    assert len(_audit(s.connection, "create_timeline")) == 1


def test_primary_timeline_detail_blocks_archive_with_a_reason(s: Setup) -> None:
    detail = s.gm.get(s.tl(f"/{s.primary}")).json()
    assert {"action": "archive", "reason": "primary_timeline_not_archivable"} in detail[
        "blocked_actions"
    ]


def test_branch_latest_on_a_new_world_without_any_sql(s: Setup) -> None:
    response = s.gm.post(
        s.tl(f"/{s.primary}/branches"),
        {
            "name": "Bridge Branch",
            "description": None,
            "branch_point": {"kind": "latest", "label": "The Night the Bridge Fell"},
        },
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"timeline_id", "branch_world_time_id", "row_version"}

    rows = _audit(s.connection, "create_timeline_branch")
    assert sorted((r.schema_name, r.table_name) for r in rows) == [
        ("campaign", "timelines"),
        ("core", "world_times"),
    ]
    assert len({r.correlation_id for r in rows}) == 1

    detail = s.gm.get(s.tl(f"/{body['timeline_id']}")).json()
    assert detail["parent_timeline_id"] == s.primary
    assert detail["branch_point"]["label"] == "The Night the Bridge Fell"
    assert detail["branch_point"]["sort_key"] == 0
    parent = s.gm.get(s.tl(f"/{s.primary}")).json()
    assert [c["timeline_id"] for c in parent["children"]] == [body["timeline_id"]]


def test_branch_replay_creates_one_branch(s: Setup) -> None:
    body = {
        "name": "Once",
        "description": None,
        "branch_point": {"kind": "latest", "label": "Now"},
    }
    first = s.gm.post(s.tl(f"/{s.primary}/branches"), body, key="branch-key")
    second = s.gm.post(s.tl(f"/{s.primary}/branches"), body, key="branch-key")
    assert first.json() == second.json()
    assert (
        s.connection.execute(
            text("SELECT count(*) FROM campaign.timelines WHERE name = 'Once'")
        ).scalar()
        == 1
    )
    assert len(_audit(s.connection, "create_timeline_branch")) == 2


def test_branch_points_list_world_times_only_never_event_identity(s: Setup) -> None:
    older = s.event(s.primary, 100, name="The Betrayal At Dawn")
    newer = s.event(s.primary, 200, name="Hidden Campaign Secret")
    response = s.gm.get(s.tl(f"/{s.primary}/branch-points"))
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["world_time_id"] for i in items] == [newer, older]
    assert set(items[0]) == {"world_time_id", "label", "year", "month_number", "day", "sort_key"}
    assert "Betrayal" not in response.text and "Secret" not in response.text


def test_branch_points_paginate(s: Setup) -> None:
    for key in (10, 20, 30):
        s.event(s.primary, key)
    first = s.gm.get(s.tl(f"/{s.primary}/branch-points"), limit=2).json()
    assert [i["sort_key"] for i in first["items"]] == [30, 20]
    second = s.gm.get(
        s.tl(f"/{s.primary}/branch-points"), limit=2, cursor=first["next_cursor"]
    ).json()
    assert [i["sort_key"] for i in second["items"]] == [10]
    assert second["next_cursor"] is None
    assert s.gm.get(s.tl(f"/{s.primary}/branch-points"), cursor="junk").status_code == 422


def test_existing_world_time_branch_and_invalid_points_share_one_400(s: Setup) -> None:
    chosen = s.event(s.primary, 100)
    ok = s.gm.post(
        s.tl(f"/{s.primary}/branches"),
        {
            "name": "From Event",
            "description": None,
            "branch_point": {"kind": "existing_world_time", "world_time_id": chosen},
        },
    )
    assert ok.status_code == 201
    bodies = set()
    for point in (str(uuid.uuid4()), str(make_world_time(s.connection, uuid.UUID(s.world_id), 5))):
        bad = s.gm.post(
            s.tl(f"/{s.primary}/branches"),
            {
                "name": "Bad",
                "description": None,
                "branch_point": {"kind": "existing_world_time", "world_time_id": point},
            },
        )
        assert bad.status_code == 400
        assert bad.json()["error"]["code"] == "branch_point_invalid"
        bodies.add(bad.json()["error"]["message"])
    assert len(bodies) == 1


@pytest.mark.parametrize(
    "branch_point",
    [
        {"kind": "latest"},
        {"kind": "latest", "label": ""},
        {"kind": "mystery"},
        {"kind": "existing_world_time"},
        {"kind": "existing_world_time", "world_time_id": "not-a-uuid"},
    ],
)
def test_malformed_branch_points_are_422(s: Setup, branch_point: dict) -> None:
    response = s.gm.post(
        s.tl(f"/{s.primary}/branches"),
        {"name": "B", "description": None, "branch_point": branch_point},
    )
    assert response.status_code == 422


def test_update_archive_restore_flow_with_audit(s: Setup) -> None:
    side = s.gm.post(s.tl(), {"name": "Side", "description": None}).json()
    tid, version = side["timeline_id"], side["row_version"]

    updated = s.gm.post(
        s.tl(f"/{tid}/update"),
        {"expected_row_version": version, "name": "Side Renamed", "description": None},
        key=s.gm.fresh_key(),
    )
    assert updated.status_code == 200
    stale = s.gm.post(
        s.tl(f"/{tid}/update"),
        {"expected_row_version": version, "name": "Again", "description": None},
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"

    archived = s.gm.post(
        s.tl(f"/{tid}/archive"),
        {"expected_row_version": updated.json()["row_version"], "reason": "unused"},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200
    assert archived.json()["lifecycle_status"] == "archived"
    audit = _audit(s.connection, "archive_timeline")
    assert [(r.previous_status, r.new_status) for r in audit] == [("active", "archived")]

    blocked = s.gm.post(
        s.tl(f"/{tid}/branches"),
        {"name": "B", "description": None, "branch_point": {"kind": "latest", "label": "x"}},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "timeline_archived"

    restored = s.gm.post(
        s.tl(f"/{tid}/restore"),
        {"expected_row_version": archived.json()["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert restored.status_code == 200 and restored.json()["lifecycle_status"] == "active"


def test_primary_timeline_archive_is_a_409(s: Setup) -> None:
    detail = s.gm.get(s.tl(f"/{s.primary}")).json()
    response = s.gm.post(
        s.tl(f"/{s.primary}/archive"), {"expected_row_version": detail["row_version"]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "primary_timeline_not_archivable"


def test_a_noop_update_writes_no_audit(s: Setup) -> None:
    side = s.gm.post(s.tl(), {"name": "Side", "description": None}).json()
    noop = s.gm.post(
        s.tl(f"/{side['timeline_id']}/update"),
        {"expected_row_version": side["row_version"], "name": "Side", "description": None},
    )
    assert noop.status_code == 200 and noop.json()["row_version"] == side["row_version"]
    assert _audit(s.connection, "update_timeline") == []


def test_cross_world_and_unauthorized_access_is_a_uniform_404(
    harness: AuthoringHarness, s: Setup, db_connection: Connection
) -> None:
    other = Setup(harness, db_connection)
    stranger_paths = [
        ("get", s.tl(f"/{s.primary}"), None),
        ("get", s.tl(f"/{s.primary}/branch-points"), None),
        ("post", s.tl(), {"name": "X", "description": None}),
        (
            "post",
            s.tl(f"/{s.primary}/update"),
            {"expected_row_version": 1, "name": "X", "description": None},
        ),
        ("post", s.tl(f"/{s.primary}/archive"), {"expected_row_version": 1}),
    ]
    for method, path, body in stranger_paths:
        response = other.gm.get(path) if method == "get" else other.gm.post(path, body)
        assert response.status_code == 404, (method, path)

    # The owner of world A naming world B's timeline under world A's path.
    foreign = s.gm.get(s.tl(f"/{other.primary}"))
    assert foreign.status_code == 404
    assert (
        s.gm.post(
            s.tl(f"/{other.primary}/branches"),
            {"name": "X", "description": None, "branch_point": {"kind": "latest", "label": "x"}},
        ).status_code
        == 404
    )
    assert s.gm.get(s.tl(f"/{other.primary}/branch-points")).status_code == 404


def test_timeline_mutations_enforce_csrf_and_origin(s: Setup) -> None:
    for suffix, body in (
        ("", {"name": "X", "description": None}),
        (
            f"/{s.primary}/branches",
            {"name": "X", "description": None, "branch_point": {"kind": "latest", "label": "x"}},
        ),
        (f"/{s.primary}/update", {"expected_row_version": 1, "name": "X"}),
        (f"/{s.primary}/archive", {"expected_row_version": 1}),
        (f"/{s.primary}/restore", {"expected_row_version": 1}),
    ):
        assert s.gm.post(s.tl(suffix), body, csrf=False).status_code == 403
        assert s.gm.post(s.tl(suffix), body, origin=False).status_code == 403
