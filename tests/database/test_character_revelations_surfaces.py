"""Revelation reach across the other discovery surfaces (P03-A A3b, plan section 10.7).

The shared discovery bundle serves every consumer, so a revealed character is named wherever the
reader's other rules allow it and disappears the moment the revelation is revoked or a
whole-character deny applies. These tests drive the organization roster and the event explanation
through the production routes, with the owner GM creating and revoking the revelation.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_event_explanations import (
    deny_entity,
    explanation,
    join,
    start_clock,
    world_event,
)
from tests.database.test_api_organization_members import join as org_join
from tests.database.test_api_organization_members import members as org_members
from tests.database.test_api_organization_members import npc, organization
from tests.database.test_api_party_members import new_party, published_pc

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def reveal(s: ContentSetup, character: str, kind: str = "campaign_current_and_future") -> str:
    """Release a public profile and reveal it to the campaign, as the owner GM."""
    base = f"/campaigns/{s.cid}/characters/{character}"
    drafted = s.gm.post_raw(
        base + "/public-profile/draft",
        {"expected_row_version": None, "public_summary": "Released words"},
        key=s.gm.fresh_key(),
    )
    assert drafted.status_code == 201, drafted.text
    released = s.gm.post_raw(
        base + "/public-profile/releases", {"expected_draft_row_version": 1}, key=s.gm.fresh_key()
    )
    assert released.status_code == 201, released.text
    made = s.gm.post_raw(
        base + "/revelations", {"audience_kind": kind, "reason": "Known"}, key=s.gm.fresh_key()
    )
    assert made.status_code == 201, made.text
    return str(made.json()["character_revelation_id"])


def unreveal(s: ContentSetup, character: str, revelation: str) -> None:
    done = s.gm.post_raw(
        f"/campaigns/{s.cid}/characters/{character}/revelations/{revelation}/revoke",
        {"reason": "No longer"},
        key=s.gm.fresh_key(),
    )
    assert done.status_code == 200 and done.json()["revoked"] is True, done.text


def test_an_organization_roster_names_a_revealed_member_and_only_while_revealed(
    s: ContentSetup,
) -> None:
    guild = organization(s, "The Guild")
    mira, bank = npc(s, "Mira"), organization(s, "The Bank")
    start = Times(s).at(1)
    org_join(s, guild, bank, start, role="Patron")
    org_join(s, guild, mira, start, role="Quartermaster")

    def names() -> list[str]:
        return [m["member_name"] for m in org_members(s, guild, s.player)["members"]]

    assert names() == ["The Bank"]  # the unrevealed character is not named
    revelation = reveal(s, mira)
    assert names() == ["Mira", "The Bank"]  # D10: shared discovery
    listed = next(
        m for m in org_members(s, guild, s.player)["members"] if m["member_name"] == "Mira"
    )
    assert listed["can_open"] is True  # the public tier opens (A4)
    deny_entity(s, mira)
    assert names() == ["The Bank"]  # a whole-character deny wins
    unreveal(s, mira, revelation)
    assert names() == ["The Bank"]


def test_an_event_explanation_names_a_revealed_subject_and_opens_its_public_tier(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s), published_pc(s, "Aldric")
    joined = join(s, party, aldric, times.at(1))

    before = explanation(s, s.player, joined)["subject"]
    assert before["state"] == "unavailable" and before["name"] is None
    revelation = reveal(s, aldric)
    named = explanation(s, s.player, joined)["subject"]
    assert named["name"] == "Aldric" and named["entity_id"] == aldric
    assert named["openable"] is True  # the public tier opens (A4)
    unreveal(s, aldric, revelation)
    after = world_event(s, s.player, joined)
    assert after.status_code == 200
    assert "Aldric" not in after.text and aldric not in after.text
    assert uuid.UUID(revelation).hex not in after.text
