"""HTTP contract for the canon-lifecycle routes (Phase 14)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids
from tests.factories import make_character, make_location, make_world, status_id

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Setup:
    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.harness = harness
        self.connection = connection
        self.gm: Actor = harness.new_actor("GM", world_creator=True)
        ruleset_id, ruleset_version_id = dnd5e_ids(connection)
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
        self.world_id = uuid.UUID(created["world_id"])
        campaign = self.gm.post(
            "/campaigns",
            {
                "timeline_id": created["primary_timeline_id"],
                "ruleset_version_id": str(ruleset_version_id),
                "name": "Campaign",
                "description": None,
            },
            key=self.gm.fresh_key(),
        ).json()
        self.cid: str = campaign["campaign_id"]
        self.player: Actor = harness.new_actor("Player")
        connection.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at)
                VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                                 WHERE code = 'active'), now())
            """),
            {"c": self.cid, "u": self.player.user_id},
        )
        connection.execute(
            text("""
                INSERT INTO security.membership_roles (campaign_membership_id, role_id)
                SELECT cm.campaign_membership_id, r.role_id
                FROM security.campaign_memberships cm, security.roles r
                WHERE cm.campaign_id = :c AND cm.user_id = :u
                  AND r.code = 'player' AND r.campaign_id IS NULL
            """),
            {"c": self.cid, "u": self.player.user_id},
        )

    def entity(
        self, name: str = "Place", canon: str = "draft", world: uuid.UUID | None = None
    ) -> str:
        location_id = make_location(self.connection, world or self.world_id, name=name)
        self.connection.execute(
            text("UPDATE core.entities SET canon_status_id = :s WHERE entity_id = :e"),
            {"s": status_id(self.connection, "canon_statuses", canon), "e": location_id},
        )
        return str(location_id)

    def url(self, entity: str, suffix: str = "") -> str:
        return f"/campaigns/{self.cid}/entities/{entity}/lifecycle{suffix}"

    def view(self, entity: str) -> dict:
        return self.gm.get(self.url(entity)).json()

    def audit(self, command: str) -> list:
        return list(
            self.connection.execute(
                text(
                    "SELECT schema_name, table_name, action.code AS action, previous_status, "
                    "new_status, reason, changed_fields, entity_id, record_id "
                    "FROM audit.change_log cl JOIN audit.change_actions action "
                    "ON action.change_action_id = cl.change_action_id "
                    "WHERE command_name = :c ORDER BY change_log_id"
                ),
                {"c": command},
            ).all()
        )


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> Setup:
    return Setup(harness, db_connection)


def test_the_read_model_reports_state_and_server_computed_actions(s: Setup) -> None:
    place = s.entity("Draft Place", canon="draft")
    view = s.view(place)
    assert (view["canon_status"], view["lifecycle_status"], view["lifecycle_managed"]) == (
        "draft",
        "active",
        True,
    )
    assert view["row_version"] >= 1 and view["superseded_by"] is None
    assert set(view["available_actions"]) == {
        "submit_for_review",
        "reject",
        "archive",
        "delete_draft",
    }
    reasons = {b["action"]: b["reason"] for b in view["blocked_actions"]}
    assert reasons["publish"] == "wrong_canon_status"
    assert reasons["restore"] == "entity_not_archived"


def test_an_ineligible_entity_reads_as_unmanaged_and_every_transition_is_409(s: Setup) -> None:
    hero = str(make_character(s.connection, s.world_id, name="Hero"))
    view = s.view(hero)
    assert view["lifecycle_managed"] is False and view["available_actions"] == []
    assert view["blocked_actions"] == [{"action": "all", "reason": "lifecycle_not_supported"}]
    response = s.gm.post(
        s.url(hero, "/submit-for-review"), {"expected_row_version": view["row_version"]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lifecycle_not_supported"


def test_draft_to_canon_with_audit_for_every_transition(s: Setup) -> None:
    place = s.entity("Journey")
    steps = [
        ("submit-for-review", "submit_entity_for_review", "draft", "proposed"),
        ("approve", "approve_entity", "proposed", "approved"),
        ("publish", "publish_entity_as_canon", "approved", "canon"),
    ]
    for suffix, command, before, after in steps:
        version = s.view(place)["row_version"]
        response = s.gm.post(
            s.url(place, f"/{suffix}"),
            {"expected_row_version": version},
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["canon_status"], body["lifecycle_status"]) == (after, "active")
        assert body["row_version"] > version
        rows = s.audit(command)
        assert [(r.action, r.previous_status, r.new_status) for r in rows] == [
            ("status_changed", before, after)
        ]
        assert rows[0].entity_id == uuid.UUID(place)


def test_reject_and_return_to_draft_record_reasons_that_are_never_returned(s: Setup) -> None:
    place = s.entity("Reject Me", canon="proposed")
    rejected = s.gm.post(
        s.url(place, "/reject"),
        {"expected_row_version": s.view(place)["row_version"], "reason": "off-tone"},
    )
    assert rejected.status_code == 200
    assert "off-tone" not in rejected.text
    assert s.audit("reject_entity")[0].reason == "off-tone"
    returned = s.gm.post(
        s.url(place, "/return-to-draft"),
        {"expected_row_version": s.view(place)["row_version"], "reason": None},
    )
    assert returned.json()["canon_status"] == "draft"


def test_illegal_transitions_stale_versions_and_replays(s: Setup) -> None:
    place = s.entity("Fussy", canon="draft")
    version = s.view(place)["row_version"]
    illegal = s.gm.post(s.url(place, "/publish"), {"expected_row_version": version})
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "lifecycle_transition_not_allowed"
    stale = s.gm.post(s.url(place, "/submit-for-review"), {"expected_row_version": version + 4})
    assert stale.json()["error"]["code"] == "stale_write"

    first = s.gm.post(
        s.url(place, "/submit-for-review"), {"expected_row_version": version}, key="life-key"
    )
    again = s.gm.post(
        s.url(place, "/submit-for-review"), {"expected_row_version": version}, key="life-key"
    )
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert len(s.audit("submit_entity_for_review")) == 1
    other = s.gm.post(s.url(place, "/approve"), {"expected_row_version": version}, key="life-key")
    assert other.status_code == 409 and other.json()["error"]["code"] == "conflict"


def test_supersede_archive_restore_and_delete_draft(s: Setup) -> None:
    old = s.entity("Old", canon="canon")
    new = s.entity("New", canon="approved")
    candidates = s.gm.get(s.url(old, "/replacement-candidates")).json()
    assert [c["canonical_name"] for c in candidates["items"]] == ["New"]
    superseded = s.gm.post(
        s.url(old, "/supersede"),
        {
            "expected_row_version": s.view(old)["row_version"],
            "replacement_entity_id": new,
            "replacement_expected_row_version": candidates["items"][0]["row_version"],
        },
        key=s.gm.fresh_key(),
    )
    assert superseded.status_code == 200, superseded.text
    assert superseded.json()["canon_status"] == "superseded"
    assert s.view(new)["canon_status"] == "canon"
    assert s.view(old)["superseded_by"] == {"entity_id": new, "canonical_name": "New"}
    audit = s.audit("supersede_entity")
    assert sorted((r.previous_status, r.new_status) for r in audit) == [
        ("approved", "canon"),
        ("canon", "superseded"),
    ]

    archived = s.gm.post(
        s.url(old, "/archive"),
        {"expected_row_version": s.view(old)["row_version"], "reason": "obsolete"},
    )
    assert archived.status_code == 200 and archived.json()["lifecycle_status"] == "archived"
    assert [(r.action, r.previous_status, r.new_status) for r in s.audit("archive_entity")] == [
        ("archived", "active", "archived")
    ]
    no_reason = s.gm.post(
        s.url(old, "/restore"), {"expected_row_version": s.view(old)["row_version"]}
    )
    assert no_reason.status_code == 422
    restored = s.gm.post(
        s.url(old, "/restore"),
        {"expected_row_version": s.view(old)["row_version"], "reason": "mistaken"},
    )
    assert restored.status_code == 200 and restored.json()["canon_status"] == "superseded"

    draft = s.entity("Throwaway", canon="draft")
    deleted = s.gm.post(
        s.url(draft, "/delete-draft"),
        {"expected_row_version": s.view(draft)["row_version"], "reason": "typo"},
    )
    assert deleted.status_code == 200 and deleted.json() == {"entity_id": draft, "deleted": True}
    row = s.audit("delete_draft_entity")[0]
    assert (row.action, row.reason) == ("deleted", "typo")
    assert row.changed_fields == {"canonical_name": "Throwaway", "entity_type_code": "location"}
    assert row.entity_id is None and row.record_id == uuid.UUID(draft)
    assert s.gm.get(s.url(draft)).status_code == 404


def test_invalid_replacements_are_a_uniform_400_and_a_referenced_draft_a_409(s: Setup) -> None:
    old = s.entity("Old", canon="canon")
    foreign = s.entity(
        "Foreign", canon="canon", world=make_world(s.connection, "other-lifecycle-world")
    )
    for target in (str(uuid.uuid4()), foreign, s.entity("Draft", canon="draft")):
        response = s.gm.post(
            s.url(old, "/supersede"),
            {
                "expected_row_version": s.view(old)["row_version"],
                "replacement_entity_id": target,
                "replacement_expected_row_version": 1,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "supersession_target_invalid"

    parent = s.entity("Parent", canon="draft")
    make_location(s.connection, s.world_id, name="Child", parent_location_id=uuid.UUID(parent))
    blocked = s.gm.post(
        s.url(parent, "/delete-draft"),
        {"expected_row_version": s.view(parent)["row_version"], "reason": "cleanup"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "entity_referenced"


def test_cross_world_and_missing_entities_are_the_same_404(s: Setup) -> None:
    foreign = s.entity("Foreign", world=make_world(s.connection, "foreign-lifecycle"))
    for target in (foreign, str(uuid.uuid4())):
        assert s.gm.get(s.url(target)).status_code == 404
        assert s.gm.get(s.url(target, "/replacement-candidates")).status_code == 404
        for suffix in ("submit-for-review", "approve", "publish", "archive", "reject"):
            response = s.gm.post(s.url(target, f"/{suffix}"), {"expected_row_version": 1})
            assert response.status_code == 404, suffix


def test_a_player_and_a_draft_creator_without_canon_edit_get_403_before_any_lookup(
    s: Setup,
) -> None:
    place = s.entity("Mine", canon="draft")
    s.connection.execute(
        text("UPDATE core.entities SET created_by_user_id = :u WHERE entity_id = :e"),
        {"u": s.player.user_id, "e": place},
    )
    missing = str(uuid.uuid4())
    for target in (place, missing):
        assert s.player.get(s.url(target)).status_code == 403
        assert s.player.get(s.url(target, "/replacement-candidates")).status_code == 403
        for suffix in (
            "submit-for-review",
            "return-to-draft",
            "approve",
            "reject",
            "publish",
            "archive",
        ):
            response = s.player.post(s.url(target, f"/{suffix}"), {"expected_row_version": 1})
            assert response.status_code == 403, suffix
        for suffix in ("restore", "delete-draft"):
            body = {"expected_row_version": 1, "reason": "x"}
            assert s.player.post(s.url(target, f"/{suffix}"), body).status_code == 403
    assert s.view(place)["canon_status"] == "draft"


def test_a_non_member_cannot_reach_the_routes_at_all(harness: AuthoringHarness, s: Setup) -> None:
    place = s.entity()
    stranger = harness.new_actor("Stranger")
    assert stranger.get(s.url(place)).status_code == 404
    assert stranger.post(s.url(place, "/approve"), {"expected_row_version": 1}).status_code == 404


def test_lifecycle_routes_reject_foundry_principals_and_enforce_csrf(s: Setup) -> None:
    place = s.entity()
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
    assert client.get(s.url(place)).status_code == 403
    assert (
        client.post(s.url(place, "/approve"), json={"expected_row_version": 1}).status_code == 403
    )
    for suffix in ("submit-for-review", "approve", "publish", "archive"):
        body = {"expected_row_version": 1}
        assert s.gm.post(s.url(place, f"/{suffix}"), body, csrf=False).status_code == 403
        assert s.gm.post(s.url(place, f"/{suffix}"), body, origin=False).status_code == 403


def test_malformed_lifecycle_bodies_are_422(s: Setup) -> None:
    place = s.entity()
    for body in ({}, {"expected_row_version": 0}, {"expected_row_version": 1, "extra": 1}):
        assert s.gm.post(s.url(place, "/submit-for-review"), body).status_code == 422
    assert (
        s.gm.post(
            s.url(place, "/supersede"), {"expected_row_version": 1, "replacement_entity_id": "x"}
        ).status_code
        == 422
    )


def test_the_candidates_list_paginates_and_filters(s: Setup) -> None:
    old = s.entity("Old", canon="canon")
    for name in ("Alpha", "Bravo", "Charlie"):
        s.entity(name, canon="canon")
    s.entity("Drafty", canon="draft")
    first = s.gm.get(s.url(old, "/replacement-candidates"), limit=2).json()
    assert [c["canonical_name"] for c in first["items"]] == ["Alpha", "Bravo"]
    second = s.gm.get(
        s.url(old, "/replacement-candidates"), limit=2, cursor=first["next_cursor"]
    ).json()
    assert [c["canonical_name"] for c in second["items"]] == ["Charlie"]
    filtered = s.gm.get(s.url(old, "/replacement-candidates"), q="bra").json()
    assert [c["canonical_name"] for c in filtered["items"]] == ["Bravo"]
    assert s.gm.get(s.url(old, "/replacement-candidates"), cursor="junk").status_code == 422
