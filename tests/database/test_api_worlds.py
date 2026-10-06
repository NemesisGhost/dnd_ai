"""HTTP contract for the world authoring routes (Phase 14).

Real cookie sessions with CSRF and Origin enforcement, on one rolled-back
connection (tests/authoring_support.py).
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids, make_world_creator
from tests.factories import make_campaign, make_user, make_world, oidc_principal

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def _create_body(name: str = "Eberron", connection: Connection | None = None) -> dict:
    assert connection is not None
    ruleset_id, _ = dnd5e_ids(connection)
    return {
        "name": name,
        "description": "A world",
        "ruleset_ids": [str(ruleset_id)],
        "default_ruleset_id": str(ruleset_id),
        "primary_timeline": {"name": "Main", "description": None},
    }


def _create(actor, connection: Connection, name: str = "Eberron", **kw):  # type: ignore[no-untyped-def]
    return actor.post("/worlds", _create_body(name, connection), key=actor.fresh_key(), **kw)


def _audit(connection: Connection, command: str) -> list:
    return list(
        connection.execute(
            text(
                "SELECT table_name, schema_name, record_id, correlation_id, reason, "
                "previous_status, new_status, changed_fields, actor_user_id "
                "FROM audit.change_log WHERE command_name = :c ORDER BY change_log_id"
            ),
            {"c": command},
        ).all()
    )


# --- bootstrap and reference data ------------------------------------------------


def test_the_bootstrap_advertises_world_create_to_eligible_humans_only(
    harness: AuthoringHarness,
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    assert gm.get("/auth/session").json()["global_capabilities"] == ["world.create"]
    player = harness.new_actor("Player")
    assert player.get("/auth/session").json()["global_capabilities"] == []

    foundry = AuthenticatedPrincipal(
        user_id=gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    response = harness.principal_client(foundry).get("/auth/session")
    assert response.status_code == 200
    assert response.json()["global_capabilities"] == []


def test_rulesets_lists_canon_rulesets_with_a_current_version(
    harness: AuthoringHarness,
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    body = gm.get("/rulesets").json()
    codes = [item["code"] for item in body["items"]]
    assert "dnd5e" in codes
    dnd5e = next(i for i in body["items"] if i["code"] == "dnd5e")
    assert len(dnd5e["current_versions"]) == 1


def test_rulesets_is_not_available_to_foundry_or_anonymous(harness: AuthoringHarness) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    foundry = AuthenticatedPrincipal(
        user_id=gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    assert harness.principal_client(foundry).get("/rulesets").status_code == 403
    assert harness.anonymous_client().get("/rulesets").status_code == 401


# --- create ------------------------------------------------------------------------


def test_create_world_returns_ids_and_audits_three_records_with_one_correlation(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    response = _create(gm, db_connection)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"world_id", "primary_timeline_id", "row_version"}

    rows = _audit(db_connection, "create_world")
    assert sorted((r.schema_name, r.table_name) for r in rows) == [
        ("campaign", "timelines"),
        ("core", "worlds"),
        ("security", "world_memberships"),
    ]
    assert len({r.correlation_id for r in rows}) == 1
    assert all(r.actor_user_id == gm.user_id for r in rows)
    # No request body, token, or idempotency key is stored.
    assert all(r.changed_fields is None for r in rows)


def test_the_creator_then_sees_the_world_with_full_capabilities(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    listing = gm.get("/worlds").json()
    assert [w["world_id"] for w in listing["items"]] == [created["world_id"]]
    assert listing["items"][0]["capabilities"] == [
        "campaign.create",
        "timeline.manage",
        "world.manage",
        "world.view",
    ]
    assert listing["items"][0]["primary_timeline_id"] == created["primary_timeline_id"]
    assert listing["next_cursor"] is None


def test_replay_with_the_same_key_creates_nothing_new(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    body = _create_body("Replay", db_connection)
    first = gm.post("/worlds", body, key="replay-key-1")
    second = gm.post("/worlds", body, key="replay-key-1")
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json() == second.json()
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM core.worlds WHERE name = 'Replay'")
        ).scalar()
        == 1
    )
    assert len(_audit(db_connection, "create_world")) == 3


def test_reusing_a_key_with_a_different_body_conflicts(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    assert gm.post("/worlds", _create_body("One", db_connection), key="same-key").status_code == 201
    other = gm.post("/worlds", _create_body("Two", db_connection), key="same-key")
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "conflict"


def test_unknown_ruleset_is_a_field_mappable_400(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    body = _create_body("Bad", db_connection)
    ghost = str(uuid.uuid4())
    body["ruleset_ids"] = [ghost]
    body["default_ruleset_id"] = ghost
    response = gm.post("/worlds", body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ruleset_not_available"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(name=""),
        lambda b: b.update(name="x" * 201),
        lambda b: b.update(extra_field=1),
        lambda b: b.update(ruleset_ids=[]),
        lambda b: b.pop("primary_timeline"),
    ],
)
def test_malformed_bodies_are_422(
    harness: AuthoringHarness, db_connection: Connection, mutate
) -> None:  # type: ignore[no-untyped-def]
    gm = harness.new_actor("GM", world_creator=True)
    body = _create_body("Bad", db_connection)
    mutate(body)
    response = gm.post("/worlds", body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


# --- authentication, CSRF, Origin, principals ---------------------------------------


def test_unauthenticated_requests_are_401(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    anonymous = harness.anonymous_client()
    assert anonymous.get("/worlds").status_code == 401
    assert anonymous.post("/worlds", json=_create_body("X", db_connection)).status_code == 401
    assert anonymous.get(f"/worlds/{uuid.uuid4()}").status_code == 401


def test_missing_csrf_token_is_rejected_and_writes_nothing(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    response = gm.post("/worlds", _create_body("NoCsrf", db_connection), csrf=False)
    assert response.status_code == 403
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM core.worlds WHERE name = 'NoCsrf'")
        ).scalar()
        == 0
    )


def test_a_wrong_csrf_token_and_a_disallowed_origin_are_rejected(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    body = _create_body("Nope", db_connection)
    bad_token = gm.client.post(
        "/worlds", json=body, headers={"Origin": "http://localhost:5173", "X-CSRF-Token": "nope"}
    )
    assert bad_token.status_code == 403
    bad_origin = gm.client.post(
        "/worlds",
        json=body,
        headers={"Origin": "https://evil.example.com", "X-CSRF-Token": gm.csrf},
    )
    assert bad_origin.status_code == 403
    no_origin = gm.post("/worlds", body, origin=False)
    assert no_origin.status_code == 403


def test_every_world_mutation_enforces_csrf(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    world_id = created["world_id"]
    for suffix, body in (
        ("update", {"expected_row_version": 1, "name": "X"}),
        ("archive", {"expected_row_version": 1}),
        ("restore", {"expected_row_version": 1}),
    ):
        assert gm.post(f"/worlds/{world_id}/{suffix}", body, csrf=False).status_code == 403
        assert gm.post(f"/worlds/{world_id}/{suffix}", body, origin=False).status_code == 403


def test_foundry_principals_cannot_create_read_or_manage_worlds(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    world_id = _create(gm, db_connection).json()["world_id"]
    foundry = AuthenticatedPrincipal(
        user_id=gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    client = harness.principal_client(foundry)
    assert client.post("/worlds", json=_create_body("F", db_connection)).status_code == 403
    assert client.get("/worlds").status_code == 403
    assert client.get(f"/worlds/{world_id}").status_code == 403
    assert (
        client.post(
            f"/worlds/{world_id}/update", json={"expected_row_version": 1, "name": "X"}
        ).status_code
        == 403
    )


def test_an_oidc_bearer_principal_needs_no_csrf_but_gets_no_extra_authority(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    world_id = _create(gm, db_connection).json()["world_id"]
    other = make_world_creator(db_connection, make_user(db_connection, "Bearer Other"))
    client = harness.principal_client(oidc_principal(other))
    created = client.post("/worlds", json=_create_body("Bearer World", db_connection))
    assert created.status_code == 201
    assert client.get(f"/worlds/{world_id}").status_code == 404

    # A bearer principal is held to the same creation policy as a cookie one.
    ordinary = harness.principal_client(oidc_principal(make_user(db_connection, "Bearer Plain")))
    assert ordinary.post("/worlds", json=_create_body("Nope", db_connection)).status_code == 403


# --- non-disclosure ---------------------------------------------------------------


def test_missing_other_and_unclaimed_worlds_are_the_same_404(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    owner = harness.new_actor("Owner", world_creator=True)
    stranger = harness.new_actor("Stranger")
    owned = _create(owner, db_connection).json()["world_id"]
    legacy = str(make_world(db_connection, "legacy-world"))
    missing = str(uuid.uuid4())

    bodies = []
    for actor, world_id in ((stranger, owned), (stranger, missing), (owner, legacy)):
        got = actor.get(f"/worlds/{world_id}")
        assert got.status_code == 404
        bodies.append(got.json()["error"])
        for suffix, body in (
            ("update", {"expected_row_version": 1, "name": "X"}),
            ("archive", {"expected_row_version": 1}),
            ("restore", {"expected_row_version": 1}),
        ):
            assert actor.post(f"/worlds/{world_id}/{suffix}", body).status_code == 404
    assert {(b["code"], b["message"]) for b in bodies} == {
        (bodies[0]["code"], bodies[0]["message"])
    }
    assert stranger.get("/worlds").json()["items"] == []


def test_a_campaign_owner_with_no_world_membership_has_no_world_authority(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    owner = harness.new_actor("Owner", world_creator=True)
    world_id = _create(owner, db_connection).json()["world_id"]
    assert harness.new_actor("Other").get(f"/worlds/{world_id}").status_code == 404


# --- detail, update, archive, restore ----------------------------------------------


def test_world_detail_reports_rulesets_timelines_and_server_computed_actions(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    detail = gm.get(f"/worlds/{created['world_id']}").json()

    assert detail["name"] == "Eberron"
    assert detail["lifecycle_status"] == "active"
    assert [r["code"] for r in detail["allowed_rulesets"]] == ["dnd5e"]
    assert detail["allowed_rulesets"][0]["is_default"] is True
    assert detail["allowed_rulesets"][0]["current_version"]["version_label"]
    assert [t["is_primary"] for t in detail["timelines"]] == [True]
    assert detail["managed_campaigns"] == []
    assert set(detail["available_actions"]) == {
        "update",
        "archive",
        "create_timeline",
        "create_campaign",
        "create_calendar",
    }
    assert detail["blocked_actions"] == [
        {"action": "restore", "reason": "lifecycle_transition_not_allowed"}
    ]


def test_update_changes_the_world_and_audits_only_real_changes(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    wid, version = created["world_id"], created["row_version"]

    updated = gm.post(
        f"/worlds/{wid}/update",
        {"expected_row_version": version, "name": "Renamed", "description": None},
        key=gm.fresh_key(),
    )
    assert updated.status_code == 200
    assert updated.json()["row_version"] == version + 1
    rows = _audit(db_connection, "update_world")
    assert len(rows) == 1
    assert rows[0].changed_fields["name"] == {"from": "Eberron", "to": "Renamed"}

    noop = gm.post(
        f"/worlds/{wid}/update",
        {"expected_row_version": version + 1, "name": "Renamed", "description": None},
        key=gm.fresh_key(),
    )
    assert noop.status_code == 200
    assert noop.json()["row_version"] == version + 1
    assert len(_audit(db_connection, "update_world")) == 1


def test_a_stale_update_is_a_distinct_409_and_writes_nothing(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    wid = created["world_id"]
    stale = gm.post(
        f"/worlds/{wid}/update",
        {"expected_row_version": created["row_version"] + 5, "name": "Late"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_write"
    assert _audit(db_connection, "update_world") == []


def test_a_retried_successful_update_replays_instead_of_reporting_stale(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    wid, version = created["world_id"], created["row_version"]
    body = {"expected_row_version": version, "name": "Once", "description": None}
    first = gm.post(f"/worlds/{wid}/update", body, key="update-key")
    retry = gm.post(f"/worlds/{wid}/update", body, key="update-key")
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert len(_audit(db_connection, "update_world")) == 1


def test_archive_refuses_with_an_active_campaign_then_succeeds_and_restores(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    wid = created["world_id"]
    campaign = make_campaign(
        db_connection, uuid.UUID(created["primary_timeline_id"]), lifecycle_status_code="pending"
    )
    blocked = gm.post(f"/worlds/{wid}/archive", {"expected_row_version": created["row_version"]})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "world_has_active_campaigns"
    assert str(campaign) not in blocked.text
    detail = gm.get(f"/worlds/{wid}").json()
    assert {"action": "archive", "reason": "world_has_active_campaigns"} in detail[
        "blocked_actions"
    ]

    db_connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = (SELECT lifecycle_status_id "
            "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE campaign_id = :c"
        ),
        {"c": campaign},
    )
    archived = gm.post(
        f"/worlds/{wid}/archive",
        {"expected_row_version": created["row_version"], "reason": "season over"},
        key=gm.fresh_key(),
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["lifecycle_status"] == "archived"
    audit = _audit(db_connection, "archive_world")
    assert len(audit) == 1
    assert (audit[0].reason, audit[0].previous_status, audit[0].new_status) == (
        "season over",
        "active",
        "archived",
    )
    assert "season over" not in archived.text

    assert gm.get("/worlds", status="active").json()["items"] == []
    assert len(gm.get("/worlds", status="archived").json()["items"]) == 1
    assert len(gm.get("/worlds", status="all").json()["items"]) == 1

    restored = gm.post(
        f"/worlds/{wid}/restore",
        {"expected_row_version": archived.json()["row_version"]},
        key=gm.fresh_key(),
    )
    assert restored.status_code == 200
    assert restored.json()["lifecycle_status"] == "active"
    assert len(_audit(db_connection, "restore_world")) == 1


def test_illegal_transitions_are_409_not_allowed(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    created = _create(gm, db_connection).json()
    restore = gm.post(
        f"/worlds/{created['world_id']}/restore",
        {"expected_row_version": created["row_version"]},
    )
    assert restore.status_code == 409
    assert restore.json()["error"]["code"] == "lifecycle_transition_not_allowed"


def test_world_list_is_paginated_and_ordered(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("GM", world_creator=True)
    for name in ("Charlie", "alpha", "Bravo"):
        assert _create(gm, db_connection, name).status_code == 201
    first = gm.get("/worlds", limit=2).json()
    assert [w["name"] for w in first["items"]] == ["alpha", "Bravo"]
    assert first["next_cursor"]
    second = gm.get("/worlds", limit=2, cursor=first["next_cursor"]).json()
    assert [w["name"] for w in second["items"]] == ["Charlie"]
    assert second["next_cursor"] is None
    assert gm.get("/worlds", cursor="garbage").status_code == 422
