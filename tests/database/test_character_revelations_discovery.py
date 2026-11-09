# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Revelation-derived discovery over HTTP (P03-A A3b, plan sections 10.5 to 10.13).

A revelation is a distinct access source: it makes one released character discoverable to its
audience, projects the deliberately released summary instead of the canonical one (D5-c), and
confers nothing else. These tests run the real create, revoke, end and reopen commands and read
the audience surfaces through `TestClient`:

- the T82 audience matrix (member, group, campaign-current, campaign-current-and-future, against a
  player in the group, a player outside it, an observer, a late joiner, a member who left and
  rejoined, and a member of another campaign on the same timeline);
- independent sources (T6), denies, and what a revelation never grants;
- the released-summary projection in search, counts and pagination;
- the effective-access explanation and the access overview.

The party roster exception (D4-C) is in test_api_party_roster.py.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.knowledge import resolve_member_knowledge_perspective
from dnd_ai.commands.access_grants import (
    grant_character_relationship,
    revoke_character_relationship,
)
from dnd_ai.commands.access_groups import reactivate_access_group
from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.domain.access import resolve_access_context
from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _template_role_id,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import deny
from tests.database.test_character_public_profile_grant_denies import (
    deny_via_route,
    remove_from_group,
    revoke_via_route,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import (  # noqa: F401 - fixtures used by name
    REASON_MARKER,
    SUMMARY_MARKER,
    Rev,
    _reopen,
    campaign_body,
    create,
    group_body,
    member_body,
    rev,
    revoke,
)
from tests.factories import (
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_location,
    make_membership_role,
    make_relationship,
    make_relationship_participant,
    make_user,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
CANON_MARKER = "CANONICAL-SUMMARY-MARKER-7731"


# --- the cast ---------------------------------------------------------------------------------


@dataclass
class Person:
    user: uuid.UUID
    membership: uuid.UUID


@dataclass
class People:
    """`p1` is the Gate player (in the revealed group); the rest are added here."""

    p2: Person  # a player in no group
    ob: Person  # an observer
    x: Person  # a player who is in the group, then leaves and rejoins
    r: Person  # a player in another campaign on the same timeline
    campaign_b: uuid.UUID
    b_owner: Person


def _person(engine: Engine, campaign: uuid.UUID, name: str, role_code: str) -> Person:
    with engine.begin() as connection:
        user = make_user(connection, name)
        membership = make_campaign_membership(connection, campaign, user)
        make_membership_role(connection, membership, _template_role_id(connection, role_code))
    return Person(user, membership)


@pytest.fixture
def people(postgres_engine: Engine, g: Gate, rev: Rev) -> People:
    p2 = _person(postgres_engine, g.campaign_id, "Matrix P2", "player")
    ob = _person(postgres_engine, g.campaign_id, "Matrix Observer", "observer")
    x = _person(postgres_engine, g.campaign_id, "Matrix X", "player")
    with postgres_engine.begin() as connection:
        campaign_b = make_campaign(
            connection, g.timeline_id, "Campaign B", lifecycle_status_code="active"
        )
        # A campaign must keep an access manager, so its owner joins in the same transaction.
        owner_user = make_user(connection, "Matrix B Owner")
        owner_membership = make_campaign_membership(connection, campaign_b, owner_user)
        make_membership_role(
            connection, owner_membership, _template_role_id(connection, "campaign_owner")
        )
        make_access_group_membership(connection, rev.group_id, x.membership)
        connection.execute(
            text("UPDATE core.entities SET summary = :s WHERE entity_id = :c"),
            {"s": CANON_MARKER, "c": rev.character_id},
        )
    b_owner = Person(owner_user, owner_membership)
    r = _person(postgres_engine, campaign_b, "Matrix R", "player")
    return People(p2=p2, ob=ob, x=x, r=r, campaign_b=campaign_b, b_owner=b_owner)


# --- helpers ----------------------------------------------------------------------------------


def search_url(campaign: uuid.UUID, suffix: str = "") -> str:
    return f"/campaigns/{campaign}/world/search{suffix}"


def pages(
    factory: Factory,
    user: uuid.UUID,
    campaign: uuid.UUID,
    *,
    q: str | None = None,
    limit: int = 100,
) -> list[list[dict[str, Any]]]:
    """Every page of a character search, following the cursor."""
    out: list[list[dict[str, Any]]] = []
    cursor: str | None = None
    with factory(user) as client:
        while True:
            params: dict[str, Any] = {"category": "character", "limit": limit}
            if q:
                params["q"] = q
            if cursor:
                params["cursor"] = cursor
            response = client.get(search_url(campaign), params=params)
            assert response.status_code == 200, response.text
            body = response.json()
            out.append(body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                return out


def cards(
    factory: Factory, user: uuid.UUID, campaign: uuid.UUID, *, q: str | None = None
) -> dict[str, dict[str, Any]]:
    return {c["entity_id"]: c for page in pages(factory, user, campaign, q=q) for c in page}


def total(factory: Factory, user: uuid.UUID, campaign: uuid.UUID, *, q: str | None = None) -> int:
    with factory(user) as client:
        params: dict[str, Any] = {"category": "character"}
        if q:
            params["q"] = q
        response = client.get(search_url(campaign, "/counts"), params=params)
    assert response.status_code == 200, response.text
    return int(response.json()["counts"]["character"])


def sees(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> bool:
    """Whether the character is listed, with the count and the list in agreement."""
    listed = cards(factory, user, g.campaign_id)
    assert total(factory, user, g.campaign_id) == len(listed)
    return str(character) in listed


def make_id(revelation: Any) -> uuid.UUID:
    return uuid.UUID(revelation.json()["character_revelation_id"])


def revealed(
    factory: Factory, g: Gate, character: uuid.UUID, payload: dict[str, object]
) -> uuid.UUID:
    response = create(factory, g.o1_user_id, g, character, payload)
    assert response.status_code == 201, response.text
    return make_id(response)


def revoke_ok(factory: Factory, g: Gate, character: uuid.UUID, revelation: uuid.UUID) -> None:
    response = revoke(factory, g.o1_user_id, g, character, revelation)
    assert response.status_code == 200 and response.json()["revoked"] is True, response.text


def join_late(engine: Engine, g: Gate, name: str = "Matrix Late") -> Person:
    return _person(engine, g.campaign_id, name, "player")


def group_membership_id(engine: Engine, group: uuid.UUID, membership: uuid.UUID) -> uuid.UUID:
    with engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT access_group_membership_id FROM security.access_group_memberships "
                "WHERE access_group_id = :g AND campaign_membership_id = :m AND removed_at IS NULL"
            ),
            {"g": group, "m": membership},
        ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def reopen(engine: Engine, person: Person) -> None:
    """An invitation reopen: the same membership id is open and active again, with a freshly
    assigned role (ending revoked the old ones), and in no access group."""
    _reopen(engine, person.membership)
    with engine.begin() as connection:
        make_membership_role(connection, person.membership, _template_role_id(connection, "player"))


def end_membership(factory: Factory, g: Gate, membership: uuid.UUID) -> None:
    with factory(g.o1_user_id) as client:
        response = client.post(f"/campaigns/{g.campaign_id}/memberships/{membership}/end", json={})
    assert response.status_code == 200, response.text


def assert_not_a_member_of_a(factory: Factory, person: Person, g: Gate) -> None:
    """Another campaign's member has no access to campaign A's routes at all."""
    with factory(person.user) as client:
        assert client.get(search_url(g.campaign_id)).status_code in (403, 404)


# --- the T82 audience matrix ------------------------------------------------------------------


def test_member_revelations_reach_only_their_target_and_are_never_restored(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    to_p1 = revealed(f, g, c, member_body(g.player))
    revealed(f, g, c, member_body(people.x.membership))
    assert sees(f, g.player_user_id, g, c) and sees(f, people.x.user, g, c)
    late = join_late(postgres_engine, g)
    for who in (people.p2, people.ob, late):
        assert not sees(f, who.user, g, c)
    assert_not_a_member_of_a(f, people.r, g)
    assert str(c) not in cards(f, people.r.user, people.campaign_b)

    end_membership(f, g, people.x.membership)
    reopen(postgres_engine, people.x)
    assert not sees(f, people.x.user, g, c)  # targeted before leaving: not restored
    assert sees(f, g.player_user_id, g, c)

    revoke_ok(f, g, c, to_p1)
    assert not sees(f, g.player_user_id, g, c)  # the next request shows nothing


def test_access_group_revelations_follow_the_group_and_not_a_rejoined_member(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    revealed(f, g, c, group_body(rev.group_id))
    assert sees(f, g.player_user_id, g, c) and sees(f, people.x.user, g, c)
    late = join_late(postgres_engine, g)
    for who in (people.p2, people.ob, late):
        assert not sees(f, who.user, g, c)
    assert_not_a_member_of_a(f, people.r, g)

    with postgres_engine.begin() as connection:
        make_access_group_membership(connection, rev.group_id, late.membership)
    assert sees(f, late.user, g, c)  # only if added to the group

    end_membership(f, g, people.x.membership)
    reopen(postgres_engine, people.x)
    assert not sees(f, people.x.user, g, c)  # a reopened membership starts in no groups
    with postgres_engine.begin() as connection:
        make_access_group_membership(connection, rev.group_id, people.x.membership)
    assert sees(f, people.x.user, g, c)  # visible again once re-added

    remove_from_group(f, g, group_membership_id(postgres_engine, rev.group_id, late.membership))
    assert not sees(f, late.user, g, c)  # removal: excluded from the next read
    assert sees(f, g.player_user_id, g, c)


def test_a_deactivated_group_stops_the_revelation_and_reactivation_does_not_restore_it(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    revealed(f, g, c, group_body(rev.group_id))
    assert sees(f, g.player_user_id, g, c)
    with f(g.o1_user_id) as client:
        done = client.post(
            f"/campaigns/{g.campaign_id}/access-groups/{rev.group_id}/deactivate", json={}
        )
    assert done.status_code == 200, done.text
    assert not sees(f, g.player_user_id, g, c)
    with postgres_engine.begin() as connection:
        reactivate_access_group(connection, access_group_id=rev.group_id, campaign_id=g.campaign_id)
    assert not sees(f, g.player_user_id, g, c)  # active and empty, and the revelation is closed


def test_campaign_current_reaches_the_snapshot_and_not_later_or_returning_members(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    revelation = revealed(f, g, c, campaign_body("campaign_current"))
    for who in (g.player_user_id, people.p2.user, people.ob.user, people.x.user):
        assert sees(f, who, g, c)
    late = join_late(postgres_engine, g)
    assert not sees(f, late.user, g, c)  # joins after the revelation
    assert_not_a_member_of_a(f, people.r, g)
    end_membership(f, g, people.x.membership)
    reopen(postgres_engine, people.x)
    assert not sees(f, people.x.user, g, c)  # not restored on rejoin
    revoke_ok(f, g, c, revelation)
    assert not sees(f, people.p2.user, g, c)


def test_campaign_current_and_future_reaches_late_and_returning_members(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    revelation = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    for who in (g.player_user_id, people.p2.user, people.ob.user, people.x.user):
        assert sees(f, who, g, c)
    late = join_late(postgres_engine, g)
    assert sees(f, late.user, g, c)  # future members are covered
    end_membership(f, g, people.x.membership)
    with f(people.x.user) as client:
        assert client.get(search_url(g.campaign_id)).status_code in (403, 404)  # left
    reopen(postgres_engine, people.x)
    assert sees(f, people.x.user, g, c)  # active again (D9-c)
    assert_not_a_member_of_a(f, people.r, g)
    assert str(c) not in cards(f, people.r.user, people.campaign_b)
    revoke_ok(f, g, c, revelation)
    for who in (g.player_user_id, people.p2.user, late.user, people.x.user):
        assert not sees(f, who, g, c)


def test_an_archived_character_is_inert_and_applies_again_when_restored(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))

    def set_status(code: str) -> None:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE core.entities SET lifecycle_status_id = (SELECT lifecycle_status_id "
                    "FROM core.lifecycle_statuses WHERE code = :code) WHERE entity_id = :c"
                ),
                {"code": code, "c": c},
            )

    assert sees(f, g.player_user_id, g, c)
    set_status("archived")
    assert not sees(f, g.player_user_id, g, c)
    set_status("active")
    assert sees(f, g.player_user_id, g, c)


# --- independent sources (T6) -----------------------------------------------------------------


def relate(
    engine: Engine, g: Gate, membership: uuid.UUID, character: uuid.UUID, kind: str
) -> uuid.UUID:
    with engine.begin() as connection:
        return grant_character_relationship(
            connection,
            campaign_membership_id=membership,
            character_id=character,
            relationship_type_code=kind,
            campaign_id=g.campaign_id,
            expected_world_id=g.world_id,
            granted_by_membership_id=g.o1,
        ).membership_character_relationship_id


def unrelate(engine: Engine, g: Gate, relationship: uuid.UUID) -> None:
    with engine.begin() as connection:
        revoke_character_relationship(
            connection, membership_character_relationship_id=relationship, campaign_id=g.campaign_id
        )


def test_a_relationship_and_a_revelation_are_independent_sources(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    p2 = people.p2
    # Revelation revoked, relationship remains.
    first = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    link = relate(postgres_engine, g, p2.membership, c, "observer_approved_viewer")
    assert sees(f, p2.user, g, c)
    revoke_ok(f, g, c, first)
    assert sees(f, p2.user, g, c)
    # Relationship revoked, a new revelation remains.
    second = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    unrelate(postgres_engine, g, link)
    assert sees(f, p2.user, g, c)
    revoke_ok(f, g, c, second)
    assert not sees(f, p2.user, g, c)


def test_a_summary_grant_and_a_revelation_are_independent_and_a_revelation_opens_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    detail = f"/campaigns/{g.campaign_id}/characters/{c}"
    with postgres_engine.begin() as connection:
        from tests.factories import lookup_id, make_resource_grant

        make_resource_grant(
            connection,
            g.campaign_id,
            lookup_id(
                connection, "security", "capabilities", "capability_id", "character.view_summary"
            ),
            timeline_id=g.timeline_id,
            grantee_campaign_membership_id=people.p2.membership,
            character_id=c,
        )
    revelation = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    with f(people.p2.user) as client:
        assert client.get(detail).status_code == 200  # the grant's summary tier
    with f(g.player_user_id) as client:
        assert client.get(detail).status_code == 404  # a revelation alone opens no detail
    revoke_ok(f, g, c, revelation)
    with f(people.p2.user) as client:
        assert client.get(detail).status_code == 200  # unchanged by the revocation


def test_two_revelations_for_one_caller_are_two_sources_and_either_alone_suffices(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    by_member = revealed(f, g, c, member_body(g.player))
    by_campaign = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    assert sees(f, g.player_user_id, g, c)
    revoke_ok(f, g, c, by_member)
    assert sees(f, g.player_user_id, g, c)
    by_group = revealed(f, g, c, group_body(rev.group_id))
    revoke_ok(f, g, c, by_campaign)
    assert sees(f, g.player_user_id, g, c)
    revoke_ok(f, g, c, by_group)
    assert not sees(f, g.player_user_id, g, c)


def test_the_explanation_and_overview_list_each_revelation_as_its_own_source(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory

    def explanation() -> dict[str, Any]:
        with f(g.o1_user_id) as client:
            response = client.get(f"/campaigns/{g.campaign_id}/members/{g.player}/effective-access")
        assert response.status_code == 200, response.text
        assert REASON_MARKER not in response.text
        return response.json()  # type: ignore[no-any-return]

    def sources(body: dict[str, Any], code: str) -> list[dict[str, Any]]:
        for capability in body["capabilities"]:
            if capability["code"] == code:
                return [s for s in capability["sources"] if s["kind"] == "revelation"]
        return []

    def overview() -> list[dict[str, Any]]:
        with f(g.o1_user_id) as client:
            response = client.get(f"/campaigns/{g.campaign_id}/access-overview")
        assert response.status_code == 200, response.text
        member = next(
            x for x in response.json()["members"] if x["campaign_membership_id"] == str(g.player)
        )
        return member["revelations"]  # type: ignore[no-any-return]

    assert sources(explanation(), "character.discover") == [] and overview() == []
    first = revealed(f, g, c, member_body(g.player, REASON_MARKER))
    second = revealed(f, g, c, group_body(rev.group_id, REASON_MARKER))
    body = explanation()
    for code in ("character.discover", "character.view_public_profile"):
        listed = sources(body, code)
        assert len(listed) == 2 and {s["target_display_name"] for s in listed} == {
            "Revealed Subject"
        }
    assert {s["label"] for s in sources(body, "character.discover")} == {
        "Member",
        "Access group",
    }
    assert {e["audience_kind_code"] for e in overview()} == {"member", "access_group"}
    assert all(
        set(e)
        == {
            "character_id",
            "character_display_name",
            "audience_kind_code",
            "audience_kind_display_name",
        }
        for e in overview()
    )
    revoke_ok(f, g, c, first)
    assert len(sources(explanation(), "character.discover")) == 1
    assert [e["audience_kind_code"] for e in overview()] == ["access_group"]
    revoke_ok(f, g, c, second)
    assert sources(explanation(), "character.discover") == [] and overview() == []


# --- denies -----------------------------------------------------------------------------------


@pytest.mark.parametrize("via", ["member", "group"])
@pytest.mark.parametrize(
    "kind", ["member", "access_group", "campaign_current", "campaign_current_and_future"]
)
def test_a_whole_character_deny_suppresses_every_revelation_kind(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, kind: str, via: str
) -> None:
    c, f = rev.character_id, client_factory
    payload = {
        "member": member_body(g.player),
        "access_group": group_body(rev.group_id),
        "campaign_current": campaign_body("campaign_current"),
        "campaign_current_and_future": campaign_body("campaign_current_and_future"),
    }[kind]
    revealed(f, g, c, payload)
    assert sees(f, g.player_user_id, g, c)
    grant = deny_via_route(
        f,
        g,
        "campaign.view",
        c,
        member=g.player if via == "member" else None,
        group=rev.group_id if via == "group" else None,
    )
    assert not sees(f, g.player_user_id, g, c)  # list, count and page agree: nothing is left
    assert "Revealed Subject" not in str(cards(f, g.player_user_id, g.campaign_id))
    revoke_via_route(f, g, grant)
    assert sees(f, g.player_user_id, g, c)


def test_a_raw_discover_deny_hides_a_revealed_character_and_a_profile_deny_does_not(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    deny(postgres_engine, g, g.player, "character.view_public_profile", c, key="character_id")
    assert sees(f, g.player_user_id, g, c)  # a profile deny blocks the profile, not discovery
    with postgres_engine.connect() as connection:
        access = resolve_access_context(
            connection, user_id=g.player_user_id, campaign_id=g.campaign_id
        )
    assert access is not None
    assert access.has_capability("character.discover", character_id=c)
    assert not access.has_capability("character.view_public_profile", character_id=c)
    assert not access.has_capability("character.discover")  # a role-only check gains nothing
    deny(postgres_engine, g, g.player, "character.discover", c, key="character_id")
    assert not sees(f, g.player_user_id, g, c)
    assert sees(f, g.o1_user_id, g, c)  # another reader is unaffected


# --- what a revelation never grants ------------------------------------------------------------


def test_a_revelation_grants_no_detail_sheet_inventory_perspective_or_roster_link(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    assert sees(f, g.player_user_id, g, c)
    base = f"/campaigns/{g.campaign_id}/characters/{c}"
    with f(g.player_user_id) as client:
        for suffix in ("", "/sheet", "/builds", "/inventory", "/public-profile", "/relationships"):
            response = client.get(base + suffix)
            assert response.status_code in (403, 404), suffix
            assert "Revealed Subject" not in response.text and CANON_MARKER not in response.text
    with postgres_engine.connect() as connection:
        bootstrap = get_session_bootstrap(connection, user_id=g.player_user_id)
        access = resolve_access_context(
            connection, user_id=g.player_user_id, campaign_id=g.campaign_id
        )
    assert access is not None
    with postgres_engine.connect() as connection:
        perspective = resolve_member_knowledge_perspective(
            connection,
            access=access,
            campaign_id=g.campaign_id,
            character_id=c,
            party_id=None,
        )
    assert perspective.knower_id is None and perspective.eligible_party_ids == ()
    for capability in (
        "character.view_summary",
        "character.view_full",
        "character.view_inventory",
        "character.view_knowledge",
        "character.view_private",
        "canon.edit",
    ):
        assert not access.has_capability(capability, character_id=c), capability
    from dnd_ai.api.access import can_open_participant

    assert can_open_participant(access, "character", c) is False
    for campaign in bootstrap.campaigns:
        assert str(c) not in str([p.character_id for p in campaign.character_perspectives])


def test_a_preview_subject_inherits_exactly_their_own_revelations(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    revealed(f, g, c, member_body(g.player))
    with postgres_engine.connect() as connection:
        own = resolve_access_context(
            connection, user_id=g.player_user_id, campaign_id=g.campaign_id
        )
        owner = resolve_access_context(connection, user_id=g.o1_user_id, campaign_id=g.campaign_id)
        from dnd_ai.api.preview import resolve_preview_subject

        assert own is not None and owner is not None
        subject = resolve_preview_subject(connection, actor=owner, campaign_membership_id=g.player)
    assert subject is not None
    assert subject.access.revelations == own.revelations and c in own.revelations
    assert c not in owner.revelations  # the actor's own context is untouched


# --- the released-summary projection (D5-c) -----------------------------------------------------


def test_a_revelation_only_reader_gets_the_released_summary_and_never_the_canonical_one(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    relate(postgres_engine, g, people.p2.membership, c, "observer_approved_viewer")
    revealed(f, g, c, member_body(g.player))
    only, related, gm = g.player_user_id, people.p2.user, g.o1_user_id

    assert cards(f, only, g.campaign_id)[str(c)]["summary"] == SUMMARY_MARKER
    assert cards(f, related, g.campaign_id)[str(c)]["summary"] == CANON_MARKER
    assert cards(f, gm, g.campaign_id)[str(c)]["summary"] == CANON_MARKER

    def hits(user: uuid.UUID, q: str) -> tuple[int, int]:
        listed = [i for page in pages(f, user, g.campaign_id, q=q) for i in page]
        return len(listed), total(f, user, g.campaign_id, q=q)

    assert hits(only, SUMMARY_MARKER) == (1, 1)
    assert hits(only, CANON_MARKER) == (0, 0)  # an unreleased canonical word never matches
    assert hits(only, "Revealed Subject") == (1, 1)  # the name always matches
    assert hits(related, CANON_MARKER) == (1, 1) and hits(related, SUMMARY_MARKER) == (0, 0)
    assert hits(gm, CANON_MARKER) == (1, 1)
    assert hits(related, "Revealed Subject") == (1, 1)
    # Gaining a relationship moves the reader to the canonical summary on the next request.
    relate(postgres_engine, g, g.player, c, "observer_approved_viewer")
    assert cards(f, only, g.campaign_id)[str(c)]["summary"] == CANON_MARKER


def test_a_later_release_without_a_summary_shows_null_with_no_fallback(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    assert cards(f, g.player_user_id, g.campaign_id)[str(c)]["summary"] == SUMMARY_MARKER
    with postgres_engine.begin() as connection:
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_user_id=g.o1_user_id,
            expected_row_version=1,
            fields={"public_summary": None},
        )
    with postgres_engine.begin() as connection:
        release_character_public_profile(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_membership_id=g.o1,
            expected_draft_row_version=2,
            release_note=None,
        )
    card = cards(f, g.player_user_id, g.campaign_id)[str(c)]
    assert card["summary"] is None  # the latest release wins as a whole snapshot
    for word in (SUMMARY_MARKER, CANON_MARKER):
        assert pages(f, g.player_user_id, g.campaign_id, q=word) == [[]]
        assert total(f, g.player_user_id, g.campaign_id, q=word) == 0
    assert cards(f, g.player_user_id, g.campaign_id, q="Revealed Subject")  # the name still matches


def released(
    engine: Engine,
    g: Gate,
    name: str,
    *,
    summary: str | None,
    campaign: uuid.UUID | None = None,
    actor_user: uuid.UUID | None = None,
    actor_membership: uuid.UUID | None = None,
    character: uuid.UUID | None = None,
) -> uuid.UUID:
    with engine.begin() as connection:
        if character is None:
            character = make_character(connection, g.world_id, name=name)
        connection.execute(
            text("UPDATE core.entities SET summary = :s WHERE entity_id = :c"),
            {"s": f"{CANON_MARKER} {name}", "c": character},
        )
        save_character_public_profile_draft(
            connection,
            campaign_id=campaign or g.campaign_id,
            character_id=character,
            actor_user_id=actor_user or g.o1_user_id,
            expected_row_version=None,
            fields={"public_summary": summary},
        )
    with engine.begin() as connection:
        release_character_public_profile(
            connection,
            campaign_id=campaign or g.campaign_id,
            character_id=character,
            actor_membership_id=actor_membership or g.o1,
            expected_draft_row_version=1,
            release_note=None,
        )
    return character


def test_paging_and_counts_filter_before_the_page_and_the_cursor_carries_no_summary(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    f = client_factory
    chars = [
        released(postgres_engine, g, f"Page {i}", summary=f"{SUMMARY_MARKER} {i}") for i in range(5)
    ]
    for char in chars:
        revealed(f, g, char, campaign_body("campaign_current_and_future"))
        relate(postgres_engine, g, people.p2.membership, char, "observer_approved_viewer")
    only, related = g.player_user_id, people.p2.user

    def walk(user: uuid.UUID) -> tuple[list[str], list[str | None]]:
        ids: list[str] = []
        cursors: list[str | None] = []
        cursor: str | None = None
        with f(user) as client:
            while True:
                params: dict[str, Any] = {"category": "character", "limit": 2}
                if cursor:
                    params["cursor"] = cursor
                body = client.get(search_url(g.campaign_id), params=params).json()
                ids.extend(i["entity_id"] for i in body["items"])
                cursors.append(body["next_cursor"])
                cursor = body["next_cursor"]
                if cursor is None:
                    return ids, cursors

    ids_only, cursors_only = walk(only)
    ids_related, cursors_related = walk(related)
    wanted = {str(x) for x in chars}
    assert wanted <= set(ids_only) and len(ids_only) == len(set(ids_only))
    # Neither reader sees anything else here, so the order and every cursor are identical: the
    # projection changes the summary text only, never the sort key or the keyset.
    assert ids_only == ids_related and cursors_only == cursors_related
    assert total(f, only, g.campaign_id) == len(ids_only)
    assert total(f, related, g.campaign_id) == len(ids_related)
    for cursor in cursors_only + cursors_related:
        assert cursor is None or (SUMMARY_MARKER not in cursor and CANON_MARKER not in cursor)
    # The summary filter applies before the page: a word in only some released summaries.
    only_matches = [
        i for page in pages(f, only, g.campaign_id, q=f"{SUMMARY_MARKER} 3") for i in page
    ]
    assert [i["entity_id"] for i in only_matches] == [str(chars[3])]
    assert total(f, only, g.campaign_id, q=f"{SUMMARY_MARKER} 3") == 1


def test_a_release_in_another_campaign_never_reaches_this_campaigns_reader(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    f, c = client_factory, rev.character_id
    # Campaign B releases the same character with its own summary and reveals it to its player.
    other = "OTHER-CAMPAIGN-SUMMARY-4410"
    released(
        postgres_engine,
        g,
        "Revealed Subject",
        summary=other,
        campaign=people.campaign_b,
        actor_user=people.b_owner.user,
        actor_membership=people.b_owner.membership,
        character=c,
    )
    with f(people.b_owner.user) as client:
        made = client.post(
            f"/campaigns/{people.campaign_b}/characters/{c}/revelations",
            json={"audience_kind": "campaign_current_and_future", "reason": "B reveals"},
        )
    assert made.status_code == 201, made.text
    revealed(f, g, c, member_body(g.player))
    assert cards(f, people.r.user, people.campaign_b)[str(c)]["summary"] == other
    assert cards(f, g.player_user_id, g.campaign_id)[str(c)]["summary"] == SUMMARY_MARKER
    assert not sees(f, people.p2.user, g, c)  # B's revelation reaches no one in A
    assert other not in str(cards(f, g.player_user_id, g.campaign_id))


# --- surfaces that read the shared discovery policy ---------------------------------------------


def test_a_revealed_character_appears_in_relationships_only_where_every_participant_is_visible(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c, f = rev.character_id, client_factory
    with postgres_engine.begin() as connection:
        place = make_location(connection, g.world_id, name="Revealed Place")
        relationship = make_relationship(connection, g.world_id)
        make_relationship_participant(connection, relationship, c)
        make_relationship_participant(connection, relationship, place, role_code="object")

    def listed() -> list[str]:
        with f(g.player_user_id) as client:
            response = client.get(
                f"/campaigns/{g.campaign_id}/world/relationships", params={"limit": 100}
            )
        assert response.status_code == 200, response.text
        return [i["relationship_id"] for i in response.json()["items"]]

    assert str(relationship) not in listed()
    revelation = revealed(f, g, c, member_body(g.player))
    assert str(relationship) in listed()  # D10: shared discovery across consumers
    grant = deny_via_route(f, g, "campaign.view", c, member=g.player)
    assert str(relationship) not in listed()
    revoke_via_route(f, g, grant)
    revoke_ok(f, g, c, revelation)
    assert str(relationship) not in listed()


def test_no_audience_body_contains_a_revelation_id_reason_or_unrevealed_name(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, people: People
) -> None:
    c, f = rev.character_id, client_factory
    revelation = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    reason_revelation = revealed(f, g, c, member_body(g.player, REASON_MARKER))
    paths = [
        search_url(g.campaign_id) + "?category=character&limit=100",
        search_url(g.campaign_id, "/counts") + "?category=character",
        f"/campaigns/{g.campaign_id}/world/relationships?limit=100",
        f"/campaigns/{g.campaign_id}/characters/{c}",
        f"/campaigns/{g.campaign_id}/characters/{rev.unreleased_id}",
    ]
    for person in (g.player_user_id, people.p2.user, people.ob.user):
        with f(person) as client:
            for path in paths:
                body = client.get(path).text
                for marker in (
                    str(revelation),
                    str(reason_revelation),
                    REASON_MARKER,
                    CANON_MARKER,
                ):
                    assert marker not in body, (path, marker)
                assert "Unreleased Subject" not in body, path
    revoke_ok(f, g, c, revelation)
    revoke_ok(f, g, c, reason_revelation)
    for person in (g.player_user_id, people.p2.user, people.ob.user):
        assert not sees(f, person, g, c)
