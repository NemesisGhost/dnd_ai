"""Read-only party roster for `campaign.view` (the campaign Parties directory)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_party_members import add, new_party, parties_url, published_pc
from tests.factories import make_membership_character_relationship

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def grant_owner(s: ContentSetup, character_id: str) -> None:
    """Give the player a character relationship (and so the character-view tier) for one PC."""
    membership = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": s.player.user_id},
    ).scalar()
    owner_type = s.connection.execute(
        text(
            "SELECT character_relationship_type_id FROM security.character_relationship_types "
            "WHERE code = 'owner'"
        )
    ).scalar()
    make_membership_character_relationship(
        s.connection, membership, uuid.UUID(character_id), owner_type
    )


def roster(s: ContentSetup, party_id: str, actor: str = "player", cid: str | None = None):  # type: ignore[no-untyped-def]
    return getattr(s, actor).get(f"/campaigns/{cid or s.cid}/parties/{party_id}/roster")


def test_a_viewer_with_no_membership_lists_and_opens_every_active_party(s: ContentSetup) -> None:
    times = Times(s)
    first, second = new_party(s, "Alpha"), new_party(s, "Beta")
    pc = published_pc(s, "Aldric")
    assert add(s, first["party_id"], pc, times.at(1), reason="SECRET REASON").status_code == 201
    listing = s.player.get(parties_url(s)).json()
    assert [p["name"] for p in listing["items"]] == ["Alpha", "Beta"]
    assert listing["can_create"] is False

    # Without any character access the published member is neither listed nor counted.
    hidden = roster(s, first["party_id"]).json()
    assert hidden["members"] == [] and hidden["member_count"] == 0
    assert "Aldric" not in str(hidden) and pc not in str(hidden)

    grant_owner(s, pc)
    body = roster(s, first["party_id"]).json()
    assert body["member_count"] == 1
    assert body["members"] == [{"character_id": pc, "character_name": "Aldric"}]
    assert "available_actions" not in body["party"]
    assert "SECRET REASON" not in str(body)
    assert roster(s, second["party_id"]).json() == {
        "party": body_party(s, second["party_id"]),
        "member_count": 0,
        "members": [],
    }


def body_party(s: ContentSetup, party_id: str) -> dict:
    return s.player.get(parties_url(s, f"/{party_id}")).json()


def test_browsing_grants_nothing_and_writes_nothing(s: ContentSetup) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s)
    assert add(s, party["party_id"], pc, times.at(1)).status_code == 201
    grant_owner(s, pc)
    tables = (
        "campaign.party_memberships",
        "campaign.parties",
        "narrative.events",
        "knowledge.party_discoveries",
        "knowledge.entity_knowledge",
        "audit.change_log",
    )
    before = {t: s.count(t) for t in tables}
    parties_before = [
        p.party_id
        for c in get_session_bootstrap(s.connection, user_id=s.player.user_id).campaigns
        for p in getattr(c, "authorized_parties", [])
    ]
    assert roster(s, party["party_id"]).status_code == 200
    assert s.player.get(parties_url(s)).status_code == 200
    assert {t: s.count(t) for t in tables} == before
    parties_after = [
        p.party_id
        for c in get_session_bootstrap(s.connection, user_id=s.player.user_id).campaigns
        for p in getattr(c, "authorized_parties", [])
    ]
    assert parties_after == parties_before


def test_the_roster_does_not_open_management(s: ContentSetup) -> None:
    party = new_party(s)
    assert s.player.get(parties_url(s, f"/{party['party_id']}/members")).status_code == 403
    for suffix in ("/update", "/archive", "/restore", "/members"):
        response = s.player.post_raw(
            parties_url(s, f"/{party['party_id']}{suffix}"), {}, key=s.player.fresh_key()
        )
        assert response.status_code == 403


def test_a_manager_keeps_the_management_fields(s: ContentSetup) -> None:
    party = new_party(s)
    body = roster(s, party["party_id"], actor="gm").json()
    assert body["party"]["available_actions"] == ["update", "archive"]


def test_denied_without_campaign_view_and_across_campaigns(s: ContentSetup) -> None:
    party = new_party(s)
    assert roster(s, party["party_id"], actor="stranger").status_code in (403, 404)
    # A party of this campaign asked for through the stranger's own campaign, and the reverse.
    assert roster(s, party["party_id"], actor="stranger", cid=s.other_cid).status_code == 404
    assert roster(s, str(uuid.uuid4())).status_code == 404
    other = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/parties", {"name": "Elsewhere"}, key=s.stranger.fresh_key()
    ).json()
    assert roster(s, other["party_id"]).status_code == 404


def test_an_archived_party_is_hidden_from_viewers_but_not_editors(s: ContentSetup) -> None:
    party = new_party(s)
    archived = s.gm.post_raw(
        parties_url(s, f"/{party['party_id']}/archive"),
        {"expected_row_version": party["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200
    assert roster(s, party["party_id"]).status_code == 404
    assert roster(s, party["party_id"], actor="gm").status_code == 200


def test_only_current_members_are_listed(s: ContentSetup) -> None:
    times = Times(s)
    party, stayer, leaver = new_party(s), published_pc(s, "Stayer"), published_pc(s, "Leaver")
    grant_owner(s, stayer)
    grant_owner(s, leaver)
    add(s, party["party_id"], stayer, times.at(1))
    joined = add(s, party["party_id"], leaver, times.at(1)).json()
    ended = s.gm.post_raw(
        parties_url(s, f"/{party['party_id']}/members/{joined['party_membership_id']}/end"),
        {
            "effective_to_world_time_id": times.at(3),
            "expected_party_row_version": s.gm.get(parties_url(s, f"/{party['party_id']}")).json()[
                "row_version"
            ],
        },
        key=s.gm.fresh_key(),
    )
    assert ended.status_code == 200, ended.text
    body = roster(s, party["party_id"]).json()
    assert [m["character_name"] for m in body["members"]] == ["Stayer"]
    assert body["member_count"] == 1


def test_a_member_the_viewer_cannot_open_is_left_out_and_not_counted(s: ContentSetup) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s, "Hidden")
    add(s, party["party_id"], pc, times.at(1))
    grant_owner(s, pc)
    s.connection.execute(
        text(
            "UPDATE core.entities SET canon_status_id = "
            "(SELECT canon_status_id FROM core.canon_statuses WHERE code = 'draft') "
            "WHERE entity_id = :e"
        ),
        {"e": pc},
    )
    assert roster(s, party["party_id"]).json()["members"] == []
    assert roster(s, party["party_id"]).json()["member_count"] == 0
    assert [m["character_name"] for m in roster(s, party["party_id"], "gm").json()["members"]] == [
        "Hidden"
    ]


def test_only_characters_the_viewer_may_open_are_listed_and_counted(s: ContentSetup) -> None:
    times = Times(s)
    party, mine, other = new_party(s), published_pc(s, "Mine"), published_pc(s, "Other")
    add(s, party["party_id"], mine, times.at(1))
    add(s, party["party_id"], other, times.at(1))
    grant_owner(s, mine)
    body = roster(s, party["party_id"]).json()
    assert body["members"] == [{"character_id": mine, "character_name": "Mine"}]
    assert body["member_count"] == 1
    assert "Other" not in str(body) and other not in str(body)
    managed = roster(s, party["party_id"], actor="gm").json()
    assert managed["member_count"] == 2
