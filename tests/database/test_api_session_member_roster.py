"""CP-8 / DR-3: the member-safe session roster.

A campaign member without `canon.edit` reads the participants they may *discover* (the World
Explorer's own rule, entity denies included) and nothing else: a hidden participant leaves no
id, name, placeholder or count in the serialized body. Presence grants no character access."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup, add_member
from tests.database.test_api_session_play import (
    base,
    detail,
    new_session,
    post,
    published_npc,
    published_pc,
)
from tests.factories import (
    lookup_id,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_relationship_type_capability,
    make_resource_grant,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _membership(s: ContentSetup, actor) -> uuid.UUID:  # type: ignore[no-untyped-def]
    value = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": actor.user_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _capability(s: ContentSetup, code: str) -> uuid.UUID:
    return lookup_id(s.connection, "security", "capabilities", "capability_id", code)


def _timeline(s: ContentSetup) -> uuid.UUID:
    value = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _relate(s: ContentSetup, actor, character_id: str, capability: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    relationship_type = make_character_relationship_type(s.connection)
    make_relationship_type_capability(s.connection, relationship_type, _capability(s, capability))
    return make_membership_character_relationship(
        s.connection,
        _membership(s, actor),
        uuid.UUID(character_id),
        relationship_type,
        timeline_id=_timeline(s),
    )


def _grant(
    s: ContentSetup,
    actor,
    capability: str,
    *,
    effect: str,
    character_id: str | None = None,  # type: ignore[no-untyped-def]
    entity_id: str | None = None,
) -> None:
    make_resource_grant(
        s.connection,
        uuid.UUID(s.cid),
        _capability(s, capability),
        timeline_id=_timeline(s),
        grantee_campaign_membership_id=_membership(s, actor),
        character_id=uuid.UUID(character_id) if character_id else None,
        entity_id=uuid.UUID(entity_id) if entity_id else None,
        effect=effect,
    )


def _roster(s: ContentSetup, sid: str, who: str = "player") -> list[dict]:
    return detail(s, sid, who)["participants"]


def _session(s: ContentSetup, *people: tuple[str, str]) -> str:
    sid = new_session(s)["session_id"]
    for character_id, role in people:
        added = post(
            s, sid, "/participants", {"character_id": character_id, "participation_role": role}
        )
        assert added.status_code == 201, added.text
    return sid


def test_a_player_sees_their_character_and_a_discoverable_npc_but_not_a_hidden_one(
    s: ContentSetup,
) -> None:
    pc, seen, hidden = published_pc(s), published_npc(s, "Mira"), published_npc(s, "Secret Agent")
    sid = _session(s, (pc, "player_character"), (seen, "npc"), (hidden, "npc"))
    _relate(s, s.player, pc, "character.view_summary")
    _grant(s, s.player, "character.discover", effect="allow", character_id=seen)
    # A player discovers nothing by baseline, so the undiscovered NPC is simply omitted.

    response = s.player.get(base(s, sid))
    assert response.status_code == 200, response.text
    body = response.json()
    assert [
        (p["character_name"], p["character_kind"], p["participation_role"])
        for p in body["participants"]
    ] == [
        ("Aldric", "player_character", "player_character"),
        ("Mira", "npc", "npc"),
    ]
    raw = response.text
    assert hidden not in raw and "Secret Agent" not in raw
    # Counts describe visible rows only, and nothing hints at the missing one.
    assert len(body["participants"]) == 2
    assert body["available_actions"] is None and body["participant_role_options"] is None
    assert not any("hidden" in key or "count" in key for key in body)
    # The GM still sees all three, with controls.
    assert len(_roster(s, sid, "gm")) == 3


def test_member_rows_are_present_only_and_carry_no_removed_history(s: ContentSetup) -> None:
    pc = published_pc(s)
    sid = _session(s, (pc, "player_character"))
    _relate(s, s.player, pc, "character.view_summary")
    first = _roster(s, sid, "gm")[0]
    assert (
        post(s, sid, f"/participants/{first['session_participant_id']}/remove", {}).status_code
        == 200
    )
    assert _roster(s, sid) == []
    assert len(_roster(s, sid, "gm")) == 1


def test_an_entity_deny_removes_a_participant_for_that_member_only(s: ContentSetup) -> None:
    pc = published_pc(s)
    sid = _session(s, (pc, "player_character"))
    _relate(s, s.player, pc, "character.view_summary")
    assert len(_roster(s, sid)) == 1
    _grant(s, s.player, "campaign.view", effect="deny", entity_id=pc)
    response = s.player.get(base(s, sid))
    assert response.status_code == 200
    assert response.json()["participants"] == []
    assert pc not in response.text
    assert len(_roster(s, sid, "gm")) == 1


def test_revoked_visibility_removes_the_row(s: ContentSetup) -> None:
    pc = published_pc(s)
    sid = _session(s, (pc, "player_character"))
    relationship = _relate(s, s.player, pc, "character.view_summary")
    assert len(_roster(s, sid)) == 1
    s.connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship},
    )
    visible = {p["character_id"] for p in _roster(s, sid)}
    assert pc not in visible


def test_a_roster_with_no_visible_participants_is_empty_and_not_absent(s: ContentSetup) -> None:
    npc = published_npc(s, "Shadow")
    sid = _session(s, (npc, "npc"))
    for capability in ("character.discover", "character.view_summary", "character.view_full"):
        _grant(s, s.player, capability, effect="deny", character_id=npc)
    response = s.player.get(base(s, sid))
    assert response.json()["participants"] == []
    assert npc not in response.text and "Shadow" not in response.text


def test_an_observer_sees_only_what_they_may_discover(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    observer = harness.new_actor("Observer")
    add_member(s.connection, s.cid, observer.user_id, "observer")
    pc, npc = published_pc(s), published_npc(s, "Mira")
    sid = _session(s, (pc, "player_character"), (npc, "npc"))
    body = observer.get(base(s, sid))
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["available_actions"] is None and data["participant_role_options"] is None
    # Observers hold no character discovery as a baseline: the roster is empty, and says nothing.
    assert data["participants"] == []
    assert pc not in body.text and npc not in body.text and "Mira" not in body.text
    # Once one character is made discoverable, only that one appears.
    _grant(s, observer, "character.discover", effect="allow", character_id=npc)
    (row,) = observer.get(base(s, sid)).json()["participants"]
    assert row["character_id"] == npc and row["can_open_character"] is False


def test_discovery_alone_does_not_offer_a_character_link(s: ContentSetup) -> None:
    npc = published_npc(s, "Mira")
    sid = _session(s, (npc, "npc"))
    _grant(s, s.player, "character.discover", effect="allow", character_id=npc)
    for capability in ("character.view_summary", "character.view_full"):
        _grant(s, s.player, capability, effect="deny", character_id=npc)
    (row,) = _roster(s, sid)
    assert row["character_name"] == "Mira"
    assert row["can_open_character"] is False
    assert s.player.get(f"/campaigns/{s.cid}/characters/{npc}").status_code in (403, 404)


def test_summary_access_offers_the_link_and_the_character_opens(s: ContentSetup) -> None:
    pc = published_pc(s)
    sid = _session(s, (pc, "player_character"))
    _relate(s, s.player, pc, "character.view_summary")
    (row,) = _roster(s, sid)
    assert row["can_open_character"] is True
    assert s.player.get(f"/campaigns/{s.cid}/characters/{pc}").status_code == 200


def test_presence_grants_no_character_or_session_permission(s: ContentSetup) -> None:
    npc = published_npc(s, "Mira")
    sid = _session(s, (npc, "npc"))
    _grant(s, s.player, "character.discover", effect="allow", character_id=npc)
    for capability in ("character.view_summary", "character.view_full"):
        _grant(s, s.player, capability, effect="deny", character_id=npc)
    assert _roster(s, sid)
    assert s.player.get(f"/campaigns/{s.cid}/characters/{npc}").status_code in (403, 404)
    added = s.player.post_raw(
        base(s, sid, "/participants"),
        {"expected_row_version": 1, "character_id": npc, "participation_role": "npc"},
        key=s.player.fresh_key(),
    )
    assert added.status_code in (403, 404)
