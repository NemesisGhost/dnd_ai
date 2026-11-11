"""Read-only party roster for `campaign.view` (the campaign Parties directory)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup, add_member
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_party_members import (
    add,
    end,
    new_party,
    parties_url,
    published_pc,
    set_clock,
)
from tests.factories import make_resource_grant

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def control(
    s: ContentSetup, character: str, type_code: str = "owner", actor: str = "player"
) -> None:
    """Give `actor` a live relationship of `type_code` to `character`. Since P03-A A3b (decision
    D4-C) a roster lists a party's current members to that party's controllers, and otherwise only
    the members shared discovery lets the reader see."""
    s.connection.execute(
        text("""
            INSERT INTO security.membership_character_relationships
                (campaign_membership_id, character_id, character_relationship_type_id)
            SELECT cm.campaign_membership_id, :ch, crt.character_relationship_type_id
            FROM security.campaign_memberships cm, security.character_relationship_types crt
            WHERE cm.campaign_id = :c AND cm.user_id = :u AND cm.ended_at IS NULL
              AND crt.code = :t
        """),
        {"ch": character, "c": s.cid, "u": getattr(s, actor).user_id, "t": type_code},
    )


def roster(s: ContentSetup, party_id: str, actor: str = "player", cid: str | None = None):  # type: ignore[no-untyped-def]
    return getattr(s, actor).get(f"/campaigns/{cid or s.cid}/parties/{party_id}/roster")


def test_a_viewer_with_no_membership_lists_and_opens_every_active_party(s: ContentSetup) -> None:
    times = Times(s)
    first, second = new_party(s, "Alpha"), new_party(s, "Beta")
    pc = published_pc(s, "Aldric")
    y1 = times.at(1)
    assert add(s, first["party_id"], pc, y1, reason="SECRET REASON").status_code == 201
    set_clock(s, y1)  # B1-DEF7a: current membership is judged against the campaign clock
    control(s, pc)  # D4-C: a party's controller sees its roster
    listing = s.player.get(parties_url(s)).json()
    assert [p["name"] for p in listing["items"]] == ["Alpha", "Beta"]
    assert listing["can_create"] is False

    body = roster(s, first["party_id"]).json()
    assert body["member_count"] == 1
    assert body["members"] == [{"character_id": pc, "character_name": "Aldric"}]
    assert "available_actions" not in body["party"]
    assert "SECRET REASON" not in str(body)
    assert roster(s, second["party_id"]).json() == {
        "party": body_party(s, second["party_id"]),
        "member_count": 0,
        "members": [],
        "as_of": body["as_of"],
        "clock_unset": False,
    }
    assert body["as_of"] is not None and body["clock_unset"] is False


def body_party(s: ContentSetup, party_id: str) -> dict:
    return s.player.get(parties_url(s, f"/{party_id}")).json()


def test_browsing_grants_nothing_and_writes_nothing(s: ContentSetup) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s)
    assert add(s, party["party_id"], pc, times.at(1)).status_code == 201
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
    set_clock(s, times.at(3))  # the leave boundary is excluded, so Leaver is no longer current
    control(s, stayer)
    body = roster(s, party["party_id"]).json()
    assert [m["character_name"] for m in body["members"]] == ["Stayer"]
    assert body["member_count"] == 1


def test_a_member_the_viewer_cannot_open_is_left_out_and_not_counted(s: ContentSetup) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s, "Hidden")
    y1 = times.at(1)
    add(s, party["party_id"], pc, y1)
    set_clock(s, y1)
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


def test_a_member_is_named_without_character_access_and_nothing_else_opens(
    s: ContentSetup,
) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s, "Aldric")
    y1 = times.at(1)
    add(s, party["party_id"], pc, y1)
    set_clock(s, y1)
    mate = published_pc(s, "Mate")
    add(s, party["party_id"], mate, y1)
    control(s, mate)  # the player controls Mate, so D4-C lists Aldric too
    tables = ("campaign.party_memberships", "narrative.events", "security.resource_grants")
    before = {t: s.count(t) for t in tables}
    body = roster(s, party["party_id"]).json()
    assert body["members"] == [
        {"character_id": pc, "character_name": "Aldric"},
        {"character_id": mate, "character_name": "Mate"},
    ]
    assert body["member_count"] == 2
    # The roster is no character access: the player's character routes stay closed.
    for suffix in ("", "/sheet", "/builds"):
        response = s.player.get(f"/campaigns/{s.cid}/characters/{pc}{suffix}")
        assert response.status_code in (403, 404), suffix
    assert {t: s.count(t) for t in tables} == before
    assert roster(s, party["party_id"], actor="gm").json()["member_count"] == 2


def test_a_member_under_an_entity_level_campaign_view_deny_is_left_out(s: ContentSetup) -> None:
    times = Times(s)
    party, shown, denied = new_party(s), published_pc(s, "Shown"), published_pc(s, "Denied")
    y1 = times.at(1)
    add(s, party["party_id"], shown, y1)
    add(s, party["party_id"], denied, y1)
    set_clock(s, y1)
    control(s, shown)
    membership = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": s.player.user_id},
    ).scalar()
    capability = s.connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = 'campaign.view'")
    ).scalar()
    make_resource_grant(
        s.connection,
        uuid.UUID(s.cid),
        capability,
        grantee_campaign_membership_id=membership,
        entity_id=uuid.UUID(denied),
        effect="deny",
    )
    body = roster(s, party["party_id"]).json()
    assert [m["character_name"] for m in body["members"]] == ["Shown"]
    assert body["member_count"] == 1 and denied not in str(body)
    assert roster(s, party["party_id"], actor="gm").json()["member_count"] == 2


# --- D4-C: the controller exception and shared discovery (P03-A A3b, plan section 10.13) --------


class Cast:
    """A party of Alpha and Bravo (both current at year 1), a bystander character outside it, a
    player, an observer, and the owner GM."""

    def __init__(self, s: ContentSetup, *, clock: bool = True) -> None:
        self.s = s
        self.times = Times(s)
        self.y1 = self.times.at(1)
        self.party = new_party(s)
        self.alpha = published_pc(s, "Alpha")
        self.bravo = published_pc(s, "Bravo")
        self.loner = published_pc(s, "Loner")
        add(s, self.party["party_id"], self.alpha, self.y1)
        add(s, self.party["party_id"], self.bravo, self.y1)
        if clock:
            set_clock(s, self.y1)
        self.observer = s.harness.new_actor("Observer")
        add_member(s.connection, s.cid, self.observer.user_id, "observer")

    @property
    def pid(self) -> str:
        return str(self.party["party_id"])

    def names(self, actor: str | object = "player") -> list[str]:
        who = getattr(self.s, actor) if isinstance(actor, str) else actor
        body = who.get(f"/campaigns/{self.s.cid}/parties/{self.pid}/roster").json()
        assert body["member_count"] == len(body["members"])
        assert all(set(m) == {"character_id", "character_name"} for m in body["members"])
        return [m["character_name"] for m in body["members"]]

    def deny(self, character: str, capability: str, *, key: str, actor: str = "player") -> None:
        membership = self.s.connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": self.s.cid, "u": getattr(self.s, actor).user_id},
        ).scalar()
        capability_id = self.s.connection.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = :c"),
            {"c": capability},
        ).scalar()
        make_resource_grant(
            self.s.connection,
            uuid.UUID(self.s.cid),
            capability_id,
            grantee_campaign_membership_id=membership,
            effect="deny",
            **{key: uuid.UUID(character)},  # type: ignore[arg-type]
        )

    def reveal(self, character: str, kind: str = "campaign_current_and_future") -> str:
        """Release a public profile and reveal it, as the owner GM, through the real routes."""
        s = self.s
        base = f"/campaigns/{s.cid}/characters/{character}"
        drafted = s.gm.post_raw(
            base + "/public-profile/draft",
            {"expected_row_version": None, "public_summary": "Released words"},
            key=s.gm.fresh_key(),
        )
        assert drafted.status_code == 201, drafted.text
        released = s.gm.post_raw(
            base + "/public-profile/releases",
            {"expected_draft_row_version": 1},
            key=s.gm.fresh_key(),
        )
        assert released.status_code == 201, released.text
        made = s.gm.post_raw(
            base + "/revelations",
            {"audience_kind": kind, "reason": "The party knows"},
            key=s.gm.fresh_key(),
        )
        assert made.status_code == 201, made.text
        return str(made.json()["character_revelation_id"])


@pytest.mark.parametrize("type_code", ["owner", "primary_controller", "co_controller"])
def test_a_controller_of_a_current_member_sees_every_current_member(
    s: ContentSetup, type_code: str
) -> None:
    c = Cast(s)
    assert c.names() == []  # no relationship and no revelation: nothing is discoverable
    control(s, c.alpha, type_code)
    assert c.names() == ["Alpha", "Bravo"]
    assert c.names("gm") == ["Alpha", "Bravo"]


@pytest.mark.parametrize("type_code", ["viewer", "observer_approved_viewer", "portrayer"])
def test_other_relationship_types_get_discovery_only(s: ContentSetup, type_code: str) -> None:
    c = Cast(s)
    control(s, c.alpha, type_code)
    assert c.names() == ["Alpha"]  # Alpha is discoverable, Bravo is not


def test_a_controller_of_a_former_or_future_member_does_not_qualify(s: ContentSetup) -> None:
    c = Cast(s)
    former = published_pc(s, "Former")
    future = published_pc(s, "Future")
    joined = add(s, c.pid, former, c.y1).json()
    ended = end(s, c.pid, joined["party_membership_id"], c.times.at(2))
    assert ended.status_code == 200, ended.text
    assert add(s, c.pid, future, c.times.at(5)).status_code == 201
    set_clock(s, c.times.at(3))
    control(s, former)
    control(s, future)
    assert c.names() == []  # neither is a current member at year 3
    assert c.names("gm") == ["Alpha", "Bravo"]
    control(s, c.alpha)
    assert c.names() == ["Alpha", "Bravo"]


def test_with_no_effective_clock_nobody_qualifies_and_nothing_is_listed(s: ContentSetup) -> None:
    c = Cast(s, clock=False)
    control(s, c.alpha)
    body = roster(s, c.pid).json()
    assert body["members"] == [] and body["member_count"] == 0 and body["clock_unset"] is True
    assert roster(s, c.pid, "gm").json()["members"] == []


def test_a_controller_denied_their_own_character_does_not_qualify_through_it(
    s: ContentSetup,
) -> None:
    c = Cast(s)
    control(s, c.alpha)
    c.deny(c.alpha, "campaign.view", key="entity_id")
    assert c.names() == []  # not Alpha (denied), and not Bravo (no qualifying controller)
    other = published_pc(s, "Other")
    add(s, c.pid, other, c.y1)
    control(s, other)  # a second, undenied controlled member qualifies them again
    assert c.names() == ["Bravo", "Other"]


@pytest.mark.parametrize(
    ("capability", "key"), [("campaign.view", "entity_id"), ("character.discover", "character_id")]
)
def test_an_explicit_deny_on_a_member_omits_it_for_that_reader_only(
    s: ContentSetup, capability: str, key: str
) -> None:
    c = Cast(s)
    control(s, c.alpha)
    c.deny(c.bravo, capability, key=key)
    assert c.names() == ["Alpha"]
    body = roster(s, c.pid).json()
    assert c.bravo not in str(body) and body["member_count"] == 1
    assert c.names("gm") == ["Alpha", "Bravo"]  # another reader is unaffected


def test_a_discover_deny_hides_a_revealed_member_from_a_non_controller(s: ContentSetup) -> None:
    c = Cast(s)
    c.reveal(c.bravo)
    assert c.names() == ["Bravo"]
    c.deny(c.bravo, "character.discover", key="character_id")
    assert c.names() == []  # D12: a raw discover deny hides it from a revelation holder


def test_non_controllers_see_only_what_discovery_shows_and_a_revelation_adds_one(
    s: ContentSetup,
) -> None:
    c = Cast(s)
    assert c.names() == [] and c.names(c.observer) == []
    c.reveal(c.bravo)
    assert c.names() == ["Bravo"] and c.names(c.observer) == ["Bravo"]
    assert c.names("gm") == ["Alpha", "Bravo"]
    assert roster(s, c.pid).json()["member_count"] == 1


def test_the_controller_exception_confers_nothing_beyond_the_roster(s: ContentSetup) -> None:
    c = Cast(s)
    control(s, c.alpha)
    assert c.names() == ["Alpha", "Bravo"]
    listed = s.player.get(
        f"/campaigns/{s.cid}/world/search", category="character", q="Bravo", limit=50
    ).json()
    assert listed["items"] == []
    counts = s.player.get(f"/campaigns/{s.cid}/world/search/counts", category="character").json()
    assert counts["counts"]["character"] == 1  # only the controlled Alpha
    for suffix in ("", "/sheet", "/builds", "/inventory", "/public-profile"):
        response = s.player.get(f"/campaigns/{s.cid}/characters/{c.bravo}{suffix}")
        assert response.status_code in (403, 404), suffix
        assert "Bravo" not in response.text
