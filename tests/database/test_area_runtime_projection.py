"""The "Area now" runtime projection (`GET .../dungeon-areas/{id}/runtime`).

The panel that records what is happening in a published dungeon area used to read the area through
its authoring view, which is the private side of shared canon (`world.canon.read_private`), so a
campaign GM with no world role could not use it. The projection returns only what recording state
needs and authorizes like the audience-safe area read: campaign `canon.edit`, per-area
`campaign.view` deny, and unpublished areas are a non-disclosing 404 for a caller without the
private-read capability. Recording state is its own command; nothing here grants it or any edit.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.database.test_scoped_roles_current_surfaces import CALENDAR, Roles
from tests.factories import make_resource_grant

pytestmark = pytest.mark.database

# Fields of the authoring read that are definition or preparation, never part of the projection.
PRIVATE_KEYS = {
    "summary",
    "dimensions",
    "environmental_properties",
    "description",
    "is_hidden",
    "severity",
    "condition_description",
    "available_actions",
    "blocked_actions",
    "structure_actions",
    "row_version",
    "canon_status",
    "lifecycle_status",
    "dungeon_row_version",
}


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def x(harness: AuthoringHarness, db_connection: Connection) -> Roles:
    return Roles(harness, db_connection)


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


class Area:
    """A dungeon of two areas built by the world Owner in campaign A: `hall` has a hazard, a
    lever and a mural, a door to `vault`. `publish_vault=False` leaves the vault a draft."""

    def __init__(self, x: Roles, *, publish_hall: bool = True, publish_vault: bool = True) -> None:
        self.x = x
        s = x.s
        owner = x.a
        dungeon = owner.post(
            s.url("dungeons"),
            {"name": "The Sunken Vault", "summary": "Secret plans.", "danger_level": 6},
            key=owner.fresh_key(),
        ).json()
        self.dungeon_id = dungeon["dungeon_id"]
        base = s.url(f"dungeons/{self.dungeon_id}")

        def post(suffix: str, body: dict) -> dict:
            current = owner.get(base).json()
            response = owner.post(
                base + suffix,
                {"expected_row_version": current["row_version"], **body},
                key=owner.fresh_key(),
            )
            assert response.status_code in (200, 201), response.text
            return response.json()

        self.hall = owner.post(
            base + "/areas",
            {"name": "Entry Hall", "area_type": "hall", "dimensions": "30 ft by 40 ft"},
            key=owner.fresh_key(),
        ).json()
        self.vault = owner.post(
            base + "/areas", {"name": "Vault", "area_type": "vault"}, key=owner.fresh_key()
        ).json()
        hall_id, vault_id = self.hall["dungeon_area_id"], self.vault["dungeon_area_id"]
        post(
            "/connections",
            {"from_area_id": hall_id, "to_area_id": vault_id, "connection_type": "door"},
        )
        post(
            "/features",
            {"dungeon_area_id": hall_id, "child_type": "mural", "description": "GM-only lore."},
        )
        post(
            "/hazards",
            {"dungeon_area_id": hall_id, "child_type": "trap", "severity": 5, "is_hidden": True},
        )
        post("/interactables", {"dungeon_area_id": hall_id, "child_type": "lever"})
        s.publish(self.dungeon_id, owner.get(base).json()["row_version"])
        if publish_hall:
            s.publish(hall_id, owner.get(s.url(f"dungeon-areas/{hall_id}")).json()["row_version"])
        if publish_vault:
            s.publish(vault_id, owner.get(s.url(f"dungeon-areas/{vault_id}")).json()["row_version"])

    @property
    def id(self) -> str:
        return str(self.hall["dungeon_area_id"])

    def runtime(self, who, campaign: str | None = None):  # type: ignore[no-untyped-def]
        return who.get(f"/campaigns/{campaign or self.x.cid_b}/dungeon-areas/{self.id}/runtime")


def _set_clock(x: Roles) -> str:
    calendar = x.a.post(f"/worlds/{x.world_id}/calendars", CALENDAR, key=x.a.fresh_key()).json()
    time_point = x.b.post(
        f"{x.base_b}/world-times",
        {"calendar_id": calendar["calendar_id"], "year": 1},
        key=x.b.fresh_key(),
    ).json()["world_time_id"]
    clock = x.b.get(f"{x.base_b}/clock").json()
    advanced = x.b.post(
        f"{x.base_b}/clock/advance",
        {"world_time_id": time_point, "expected_row_version": clock["row_version"]},
        key=x.b.fresh_key(),
    )
    assert advanced.status_code == 200, advanced.text
    return str(time_point)


def test_a_campaign_only_gm_reads_the_projection_and_records_state(x: Roles) -> None:
    area = Area(x)
    response = area.runtime(x.b)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_set_state"] is True
    assert body["dungeon"]["name"] == "The Sunken Vault"
    assert {
        c["child_type"] for c in body["hazards"] + body["interactables"] + body["features"]
    } == {
        "trap",
        "lever",
        "mural",
    }
    assert [c["to_area"]["name"] for c in body["connections"]] == ["Vault"]
    assert body["limits"]["alarm_level_max"] >= 1
    assert body["state_choices"]["hazard_status"]
    # None of the authoring read's private fields travels, and the GM-only prose never does.
    assert not _keys(body) & PRIVATE_KEYS
    assert "Secret plans" not in response.text and "GM-only lore" not in response.text

    # The private authoring read of the same area stays refused for the same caller.
    private = x.b.get(f"{x.base_b}/authoring/dungeon-areas/{area.id}")
    assert private.status_code == 403
    assert private.json()["error"]["code"] == "world_authority_required"

    # Recording state is the campaign's own command, authorized independently of the read.
    _set_clock(x)
    hazard = body["hazards"][0]["child_id"]
    recorded = x.b.post_raw(
        f"{x.base_b}/dungeon-areas/{area.id}/state",
        {
            "kind": "hazard",
            "target_id": hazard,
            "expected_last_event_id": body["hazards"][0]["state_event_id"],
            "hazard_status": "triggered",
        },
        key=x.b.fresh_key(),
    )
    assert recorded.status_code == 200, recorded.text
    assert area.runtime(x.b).json()["hazards"][0]["status"] == "triggered"


def test_the_projection_grants_no_definition_edit_or_review(x: Roles) -> None:
    area = Area(x)
    assert area.runtime(x.b).status_code == 200
    edited = x.b.post(
        f"{x.base_b}/authoring/dungeon-areas/{area.id}/update",
        {"expected_row_version": 1, "name": "Renamed by B"},
        key=x.b.fresh_key(),
    )
    assert (
        edited.status_code == 403 and edited.json()["error"]["code"] == "world_authority_required"
    )
    archived = x.b.post(
        x.lifecycle_b(area.id, "/archive"), {"expected_row_version": 1}, key=x.b.fresh_key()
    )
    assert archived.status_code == 403


def test_world_editor_and_reviewer_with_campaign_access_read_it_too(x: Roles) -> None:
    area = Area(x)
    for who in (x.editor, x.reviewer, x.both):
        response = area.runtime(who)
        assert response.status_code == 200, response.text
        assert not _keys(response.json()) & PRIVATE_KEYS


def test_a_world_role_without_campaign_access_gets_nothing(
    x: Roles, harness: AuthoringHarness
) -> None:
    area = Area(x)
    stranger = harness.new_actor("World Editor, no membership".replace(",", ""))
    x.role(stranger, "world_editor")
    assert area.runtime(stranger).status_code == 404
    # Nor does the world Owner become a member of the other campaign.
    assert area.runtime(x.a).status_code == 404


def test_players_and_observers_are_refused_as_before(x: Roles) -> None:
    area = Area(x)
    assert area.runtime(x.player).status_code == 403
    assert area.runtime(x.reader).status_code == 200, "the Reader here is a campaign GM too"


def test_an_unpublished_area_is_a_non_disclosing_404_for_a_campaign_only_gm(x: Roles) -> None:
    area = Area(x, publish_hall=False)
    assert area.runtime(x.b).status_code == 404
    # The private side belongs to the world Editor, who may look (but nothing can be recorded yet).
    seen = area.runtime(x.editor)
    assert seen.status_code == 200 and seen.json()["can_set_state"] is False
    assert area.runtime(x.b, campaign=x.cid_a).status_code == 404


def test_a_connection_to_an_unpublished_area_is_not_listed(x: Roles) -> None:
    area = Area(x, publish_vault=False)
    body = area.runtime(x.b).json()
    assert body["connections"] == []
    assert 'Vault"' not in area.runtime(x.b).text.replace("Sunken Vault", "")


def test_an_explicit_view_deny_on_the_area_reads_as_not_found(
    x: Roles, db_connection: Connection
) -> None:
    area = Area(x)
    capability = db_connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = 'campaign.view'")
    ).scalar_one()
    membership = db_connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": x.cid_b, "u": x.b.user_id},
    ).scalar_one()
    timeline = db_connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": x.cid_b}
    ).scalar_one()
    make_resource_grant(
        db_connection,
        uuid.UUID(x.cid_b),
        capability,
        timeline_id=timeline,
        grantee_campaign_membership_id=membership,
        entity_id=uuid.UUID(area.id),
        effect="deny",
    )
    assert area.runtime(x.b).status_code == 404
    assert area.runtime(x.editor).status_code == 200
