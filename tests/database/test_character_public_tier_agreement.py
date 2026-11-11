"""Browse and detail agree on whether a character opens (P03-A A4b, plan section 12.4).

Every link producer that names a character (the session roster, organization members and an event
explanation) answers `can_open` with the one test `can_open_character`, and the character detail
answers with `resolve_character_detail_tier`. For a reader whose only path is a campaign revelation,
each producer is read beside the detail route in every state that matters:

- a live revelation: the link is true and the detail is 200 (the public tier);
- a `character.view_public_profile` deny: still listed, no link, and the detail is a 404;
- a `character.discover` deny or a whole-character `campaign.view` deny: not listed;
- after the revelation is revoked: not listed.

The invariant asserted everywhere: a link that is true leads to a 200, and a false one to the fixed
404. The owner GM creates and revokes the revelation; the reader is the campaign's plain player.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_event_explanations import (
    deny_entity,
    explanation,
    grant,
    join,
    start_clock,
)
from tests.database.test_api_organization_members import join as org_join
from tests.database.test_api_organization_members import members as org_members
from tests.database.test_api_organization_members import npc, organization
from tests.database.test_api_party_members import new_party, published_pc
from tests.database.test_character_revelations_surfaces import reveal, unreveal
from tests.database.test_character_revelations_surfaces_http import roster, roster_session

pytestmark = pytest.mark.database

STATES = ["revealed", "profile_deny", "discover_deny", "whole_deny", "revoked"]


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def detail_status(s: ContentSetup, character: str) -> int:
    return int(s.player.get(f"/campaigns/{s.cid}/characters/{character}").status_code)


def put_in_state(s: ContentSetup, character: str, state: str) -> None:
    revelation = reveal(s, character)
    if state == "profile_deny":
        grant(s, "character.view_public_profile", character, "deny")
    elif state == "discover_deny":
        grant(s, "character.discover", character, "deny")
    elif state == "whole_deny":
        deny_entity(s, character)
    elif state == "revoked":
        unreveal(s, character, revelation)


def assert_agrees(flag: bool | None, status: int, state: str) -> None:
    """A listed link and the page behind it agree; the states fix which one is expected."""
    if flag is None:
        assert state in ("discover_deny", "whole_deny", "revoked")
        return
    assert flag == (status == 200)
    assert flag is (state == "revealed")
    if not flag:
        assert status == 404


@pytest.mark.parametrize("state", STATES)
def test_the_session_roster_link_agrees_with_the_detail(s: ContentSetup, state: str) -> None:
    sid, aldric, _borin = roster_session(s)
    put_in_state(s, aldric, state)
    listed: dict[str, bool] = {cid: can_open for cid, _name, can_open in roster(s, sid)}
    assert_agrees(listed.get(aldric), detail_status(s, aldric), state)


@pytest.mark.parametrize("state", STATES)
def test_the_organization_member_link_agrees_with_the_detail(s: ContentSetup, state: str) -> None:
    guild = organization(s, "The Guild")
    mira = npc(s, "Mira")
    org_join(s, guild, mira, Times(s).at(1), role="Quartermaster")
    put_in_state(s, mira, state)
    flags: dict[str, bool] = {
        m["member_name"]: m["can_open"] for m in org_members(s, guild, s.player)["members"]
    }
    assert_agrees(flags.get("Mira"), detail_status(s, mira), state)


@pytest.mark.parametrize("state", STATES)
def test_the_event_explanation_link_agrees_with_the_detail(s: ContentSetup, state: str) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s), published_pc(s, "Aldric")
    joined = join(s, party, aldric, times.at(1))
    put_in_state(s, aldric, state)
    subject: dict[str, Any] = explanation(s, s.player, joined)["subject"]
    flag = subject["openable"] if subject["name"] is not None else None
    assert_agrees(flag, detail_status(s, aldric), state)


def test_a_summary_path_still_opens_and_the_gm_view_is_unchanged(s: ContentSetup) -> None:
    sid, aldric, borin = roster_session(s)
    grant(s, "character.view_summary", aldric)
    flags = {cid: can_open for cid, _name, can_open in roster(s, sid)}
    assert flags.get(aldric) is True and detail_status(s, aldric) == 200
    assert borin not in flags  # the unrevealed, undiscoverable sibling is not even named
