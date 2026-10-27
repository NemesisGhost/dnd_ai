"""The world canon boundary (docs/adr/0020-scoped-system-world-and-campaign-roles.md,
decision D6, checkpoint SR-5; findings F1 and F2).

Two campaigns share one world. Campaign A belongs to the world's Owner; campaign B
is hosted by a second GM through a world-use grant, with no world role. The GM of B
holds campaign `canon.edit` in B, which is not authority over the shared canon:

- every world-definition write needs the matching world capability *and* campaign
  `canon.edit`;
- the private side of the canon (drafts, revisions, provenance, sources, the review
  queue) needs `world.canon.read_private`;
- campaign-state operations and the three campaign-originated records (world-time
  points, item instances, player-character identity) stay campaign-authorized;
- nothing of campaign A's own material is reachable from campaign B.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup, add_member

pytestmark = pytest.mark.database

CALENDAR = {
    "name": "Common Reckoning",
    "description": None,
    "days_per_week": None,
    "epoch_label": None,
    "months": [{"name": "Only", "day_count": 100}],
}


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Shared:
    """Campaign A (owner = `a`) and campaign B (host = `b`, no world role) on one world."""

    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.s = ContentSetup(harness, connection)
        self.connection = connection
        self.harness = harness
        self.a: Actor = self.s.gm
        self.world_id = self.s.world_id
        self.cid_a = self.s.cid
        self.b: Actor = harness.new_actor("GM B", system_roles=("gm",))
        grant = self.a.post(
            f"/worlds/{self.world_id}/use-grants", {"login_name": self.b.login_name}
        )
        assert grant.status_code == 201, grant.text
        timeline = self.a.post(
            f"/worlds/{self.world_id}/timelines", {"name": "For B", "description": None}
        ).json()["timeline_id"]
        ruleset_version_id = connection.execute(
            text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": self.cid_a},
        ).scalar_one()
        created = self.b.post(
            "/campaigns",
            {
                "timeline_id": timeline,
                "ruleset_version_id": str(ruleset_version_id),
                "name": "Campaign B",
                "description": None,
            },
            key=self.b.fresh_key(),
        )
        assert created.status_code == 201, created.text
        self.cid_b = created.json()["campaign_id"]

    def location(self, name: str = "Founders Hall") -> dict:
        response = self.a.post(
            self.s.url("locations"),
            {"category": "region", "name": name, "summary": None},
            key=self.a.fresh_key(),
        )
        assert response.status_code == 201, response.text
        return response.json()

    def role(self, who: Actor, code: str) -> None:
        response = self.a.post(
            f"/worlds/{self.world_id}/roles",
            {"login_name": who.login_name, "role_code": code},
        )
        assert response.status_code == 201, response.text


@pytest.fixture
def x(harness: AuthoringHarness, db_connection: Connection) -> Shared:
    return Shared(harness, db_connection)


def _denied(response) -> bool:  # type: ignore[no-untyped-def]
    return (
        response.status_code == 403
        and response.json()["error"]["code"] == "world_authority_required"
    )


# --- writes (F1) ----------------------------------------------------------------------


def test_a_campaign_gm_without_a_world_role_cannot_write_shared_canon(x: Shared) -> None:
    existing = x.location()
    base = f"/campaigns/{x.cid_b}"
    attempts = [
        x.b.post(
            f"{base}/authoring/locations",
            {"category": "region", "name": "Hijacked", "summary": None},
            key=x.b.fresh_key(),
        ),
        x.b.post(
            f"{base}/authoring/religions",
            {"name": "False Faith", "summary": None, "pantheon_structure": "None"},
            key=x.b.fresh_key(),
        ),
        x.b.post(
            f"{base}/sources",
            {"source_type": "gm_entry", "title": "Fabricated", "reference": None},
            key=x.b.fresh_key(),
        ),
        x.b.post(
            f"{base}/authoring/locations/{existing['location_id']}/update",
            {
                "expected_row_version": existing["row_version"],
                "name": "Renamed by B",
                "summary": None,
                "parent_location_id": None,
                "population": None,
                "building_use": None,
            },
            key=x.b.fresh_key(),
        ),
    ]
    for response in attempts:
        assert _denied(response), response.text
    # Nothing was written, and the shared record is unchanged.
    assert (
        x.connection.execute(
            text("SELECT canonical_name FROM core.entities WHERE entity_id = :e"),
            {"e": existing["location_id"]},
        ).scalar_one()
        == "Founders Hall"
    )
    assert (
        x.connection.execute(
            text("SELECT count(*) FROM core.entities WHERE canonical_name = 'Hijacked'")
        ).scalar_one()
        == 0
    )


def test_a_campaign_gm_without_a_world_role_cannot_move_canon_through_its_lifecycle(
    x: Shared,
) -> None:
    location = x.location()
    base = f"/campaigns/{x.cid_b}/entities/{location['location_id']}/lifecycle"
    for action in ("submit-for-review", "approve", "publish", "archive"):
        response = x.b.post(
            f"{base}/{action}",
            {"expected_row_version": location["row_version"]},
            key=x.b.fresh_key(),
        )
        assert _denied(response), (action, response.text)


def test_the_owner_still_authors_and_publishes_in_their_own_campaign(x: Shared) -> None:
    location = x.location()
    version = x.s.publish(location["location_id"], location["row_version"])
    assert version > location["row_version"]


def test_an_editor_cannot_publish_and_a_reviewer_cannot_create(
    x: Shared, harness: AuthoringHarness, db_connection: Connection
) -> None:
    editor = harness.new_actor("Editor")
    reviewer = harness.new_actor("Reviewer")
    for who, role in ((editor, "world_editor"), (reviewer, "world_reviewer")):
        x.role(who, role)
        add_member(db_connection, x.cid_a, who.user_id, "gm")

    created = editor.post(
        x.s.url("locations"),
        {"category": "region", "name": "Edited", "summary": None},
        key=editor.fresh_key(),
    )
    assert created.status_code == 201, created.text
    entity = created.json()
    base = x.s.lifecycle(entity["location_id"])
    submitted = editor.post(
        f"{base}/submit-for-review",
        {"expected_row_version": entity["row_version"]},
        key=editor.fresh_key(),
    )
    assert submitted.status_code == 200, submitted.text
    version = submitted.json()["row_version"]
    assert _denied(
        editor.post(f"{base}/approve", {"expected_row_version": version}, key=editor.fresh_key())
    )

    approved = reviewer.post(
        f"{base}/approve", {"expected_row_version": version}, key=reviewer.fresh_key()
    )
    assert approved.status_code == 200, approved.text
    assert _denied(
        reviewer.post(
            x.s.url("locations"),
            {"category": "region", "name": "Reviewer Draft", "summary": None},
            key=reviewer.fresh_key(),
        )
    )


def test_ending_an_editor_role_is_honoured_by_the_next_command(
    x: Shared, harness: AuthoringHarness, db_connection: Connection
) -> None:
    editor = harness.new_actor("Editor")
    x.role(editor, "world_editor")
    add_member(db_connection, x.cid_a, editor.user_id, "gm")
    body = {"category": "region", "name": "First", "summary": None}
    assert editor.post(x.s.url("locations"), body, key=editor.fresh_key()).status_code == 201
    membership = db_connection.execute(
        text("""
            SELECT wm.world_membership_id FROM security.world_memberships wm
            WHERE wm.world_id = :w AND wm.user_id = :u AND wm.ended_at IS NULL
        """),
        {"w": x.world_id, "u": editor.user_id},
    ).scalar_one()
    assert x.a.post(f"/worlds/{x.world_id}/roles/{membership}/end", {}).status_code == 200
    assert _denied(
        editor.post(
            x.s.url("locations"),
            {"category": "region", "name": "Second", "summary": None},
            key=editor.fresh_key(),
        )
    )


# --- private reads (F2) -----------------------------------------------------------------


def test_a_campaign_gm_without_a_world_role_cannot_read_the_private_side_of_canon(
    x: Shared,
) -> None:
    draft = x.location("Secret Vault")
    base = f"/campaigns/{x.cid_b}"
    reads = [
        f"{base}/authoring/locations/{draft['location_id']}",
        f"{base}/authoring/locations/options",
        f"{base}/review-queue",
        f"{base}/sources",
        f"{base}/entities/{draft['location_id']}/revisions",
        f"{base}/entities/{draft['location_id']}/provenance",
        f"{base}/entities/{draft['location_id']}/lifecycle",
    ]
    for path in reads:
        response = x.b.get(path)
        assert _denied(response), (path, response.status_code, response.text)
        assert "Secret Vault" not in response.text


def test_world_roles_that_may_read_private_canon_can(
    x: Shared, harness: AuthoringHarness, db_connection: Connection
) -> None:
    draft = x.location("Visible To Editors")
    reviewer = harness.new_actor("Reviewer")
    x.role(reviewer, "world_reviewer")
    add_member(db_connection, x.cid_a, reviewer.user_id, "gm")
    assert reviewer.get(x.s.url(f"locations/{draft['location_id']}")).status_code == 200
    assert reviewer.get(f"/campaigns/{x.cid_a}/review-queue").status_code == 200


def test_the_world_reader_role_never_reaches_the_private_side(
    x: Shared, harness: AuthoringHarness, db_connection: Connection
) -> None:
    draft = x.location("Drafts Are Private")
    reader = harness.new_actor("Reader GM")
    x.role(reader, "world_reader")
    add_member(db_connection, x.cid_a, reader.user_id, "gm")
    assert _denied(reader.get(x.s.url(f"locations/{draft['location_id']}")))
    assert _denied(reader.get(f"/campaigns/{x.cid_a}/review-queue"))


# --- exceptions that stay campaign-authorized (D8) ---------------------------------------


def test_world_time_points_and_player_characters_stay_campaign_authorized(x: Shared) -> None:
    calendar = x.a.post(f"/worlds/{x.world_id}/calendars", CALENDAR, key=x.a.fresh_key()).json()
    time_point = x.b.post(
        f"/campaigns/{x.cid_b}/world-times",
        {"calendar_id": calendar["calendar_id"], "year": 3},
        key=x.b.fresh_key(),
    )
    assert time_point.status_code == 201, time_point.text

    species = next(
        o["species_id"]
        for o in x.b.get(f"/campaigns/{x.cid_b}/authoring/player-characters/options").json()[
            "species"
        ]
        if o["name"].lower() == "human"
    )
    pc = x.b.post(
        f"/campaigns/{x.cid_b}/authoring/player-characters",
        {"name": "Mira", "species_id": species, "size_category": "medium"},
        key=x.b.fresh_key(),
    )
    assert pc.status_code == 201, pc.text


def test_campaign_state_operations_never_need_a_world_role(x: Shared) -> None:
    scheduled = x.b.post(f"/campaigns/{x.cid_b}/sessions", {}, key=x.b.fresh_key())
    assert scheduled.status_code == 201, scheduled.text


# --- campaign-private material across the shared world (section 5.2) ---------------------


def test_nothing_of_campaign_a_is_reachable_from_campaign_b(x: Shared) -> None:
    session_a = x.a.post(f"/campaigns/{x.cid_a}/sessions", {}, key=x.a.fresh_key()).json()
    # B's GM is not a member of A: every campaign-scoped read of A is a 404.
    for path in ("clock", "sessions", f"sessions/{session_a['session_id']}", "review-queue"):
        assert x.b.get(f"/campaigns/{x.cid_a}/{path}").status_code == 404, path
    # A's session is not addressable through B, and B's own list does not contain it.
    assert x.b.get(f"/campaigns/{x.cid_b}/sessions/{session_a['session_id']}").status_code == 404
    listed = x.b.get(f"/campaigns/{x.cid_b}/sessions").json()
    assert session_a["session_id"] not in str(listed)


def test_campaign_search_and_world_reads_show_published_canon_only(x: Shared) -> None:
    draft = x.location("Unpublished Keep")
    published = x.location("Published Citadel")
    x.s.publish(published["location_id"], published["row_version"])
    found = x.b.get(f"/campaigns/{x.cid_b}/world/search", q="Keep")
    assert found.status_code == 200, found.text
    assert draft["location_id"] not in found.text
    assert (
        x.b.get(f"/campaigns/{x.cid_b}/world/locations/{draft['location_id']}").status_code == 404
    )
    assert (
        x.b.get(f"/campaigns/{x.cid_b}/world/locations/{published['location_id']}").status_code
        == 200
    )


def test_a_world_owner_does_not_become_a_member_of_other_campaigns(x: Shared) -> None:
    # The owner of the world has no membership in B, so B's material is a 404 to them.
    assert x.a.get(f"/campaigns/{x.cid_b}/clock").status_code == 404
    assert uuid.UUID(x.cid_b) != uuid.UUID(x.cid_a)


def test_a_draft_knowledge_definition_never_enters_another_campaigns_ai_context(
    x: Shared,
) -> None:
    from dnd_ai.domain.context_assembly import _revealable_knowledge

    options = x.a.get(x.s.url("npcs/options")).json()
    species = next(o["species_id"] for o in options["species"] if o["name"].lower() == "human")
    npc = x.a.post(
        x.s.url("npcs"),
        {"name": "Mira", "species_id": species, "size_category": "medium"},
        key=x.a.fresh_key(),
    ).json()
    item = x.a.post(
        x.s.url("knowledge"),
        {
            "statement": "Mira is the duke's daughter.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
            "subject_entity_id": npc["npc_id"],
        },
        key=x.a.fresh_key(),
    )
    assert item.status_code == 201, item.text

    def candidates() -> list[str]:
        rows = _revealable_knowledge(
            x.connection,
            timeline_id=uuid.uuid4(),
            party_id=uuid.uuid4(),
            npc_entity_id=uuid.UUID(npc["npc_id"]),
        )
        return [r.statement for r in rows]

    assert candidates() == []
    x.s.publish(npc["npc_id"], npc["row_version"])
    x.s.publish(item.json()["knowledge_item_id"], item.json()["row_version"])
    assert candidates() == ["Mira is the duke's daughter."]
