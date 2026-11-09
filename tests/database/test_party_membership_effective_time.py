"""Effective-time party membership (B1-DEF7a).

Party membership is *current* when the timeline's effective campaign clock lies in the stored
half-open period (join included, leave excluded). With no effective clock current membership is
undetermined and nothing derived from it is granted. These tests pin that one rule across every
surface that used to test "the end is absent": the session bootstrap, the per-request perspective
guard, the implicit eligible parties of a character-only Knowledge request, the character Parties
list, the member roster, the GM management rows and the GM party inventory. They also pin what the
rule must not touch: independent authority, the non-disclosing 404, per-timeline membership scope,
historical/as-of reads and the travel command's party expansion.

Memberships are created through the real party-member commands; the clock is placed with a small
SQL helper (and once through the real advance route).
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries import party_membership_period as period_module
from dnd_ai.queries.bootstrap import get_session_bootstrap
from dnd_ai.queries.party_members import list_party_members
from dnd_ai.queries.party_membership_period import (
    MembershipClock,
    membership_period_status,
    resolve_membership_clock,
)
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup, add_member
from tests.database.test_api_campaign_clock import Times, _advance, _branch_campaign
from tests.database.test_api_party_members import (
    add,
    end,
    new_party,
    parties_url,
    published_pc,
    set_clock,
)
from tests.factories import (
    make_campaign_party,
    make_entity_knowledge,
    make_knowledge_item,
    make_location,
    make_membership_character_relationship,
    make_party_knowledge,
    make_party_membership,
    make_public_knowledge,
    make_resource_grant,
)

pytestmark = pytest.mark.database

# The probe schedule: Tobin is in party L for [ARRIVAL, MEETING) and again from DESCENT on.
BEFORE, ARRIVAL, BETWEEN, MEETING, LATER, DESCENT, AFTER = 1, 2, 3, 4, 5, 6, 7
TOBIN_IN_EFFECT = {ARRIVAL, BETWEEN, DESCENT, AFTER}
MIRA_IN_EFFECT = {ARRIVAL, BETWEEN, MEETING, LATER, DESCENT, AFTER}  # open-ended from ARRIVAL


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Scene:
    """Step G's shape: party L, Tobin (two stints), Mira (open-ended), a player who owns Tobin, a
    second player with no character relationship, and a GM."""

    def __init__(self, s: ContentSetup) -> None:
        self.s = s
        self.connection = s.connection
        self.times = Times(s)
        self.t = {y: self.times.at(y) for y in range(BEFORE, AFTER + 1)}
        self.timeline_id = uuid.UUID(
            str(
                self.connection.execute(
                    text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
                    {"c": s.cid},
                ).scalar()
            )
        )
        self.party = new_party(s, "Lantern Company")
        self.party_id = self.party["party_id"]
        self.tobin = published_pc(s, "Tobin")
        self.mira = published_pc(s, "Mira")
        first = add(s, self.party_id, self.tobin, self.t[ARRIVAL])
        assert first.status_code == 201, first.text
        ended = end(s, self.party_id, first.json()["party_membership_id"], self.t[MEETING])
        assert ended.status_code == 200, ended.text
        second = add(s, self.party_id, self.tobin, self.t[DESCENT])
        assert second.status_code == 201, second.text
        assert add(s, self.party_id, self.mira, self.t[ARRIVAL]).status_code == 201

        self.player2 = s.harness.new_actor("Player Two")
        add_member(self.connection, s.cid, self.player2.user_id, "player")
        self.player_membership_id = self._campaign_membership(s.player.user_id)
        owner_type = self.connection.execute(
            text(
                "SELECT character_relationship_type_id FROM security.character_relationship_types "
                "WHERE code = 'owner'"
            )
        ).scalar()
        make_membership_character_relationship(
            self.connection, self.player_membership_id, uuid.UUID(self.tobin), owner_type
        )

        # Knowledge: one party fact (reachable only through party L), one private item, one public.
        world = uuid.UUID(str(s.world_id))
        self.party_fact = make_knowledge_item(
            self.connection, world, statement="The lantern road is watched."
        )
        make_party_knowledge(
            self.connection,
            self.timeline_id,
            uuid.UUID(self.party_id),
            self.party_fact,
            awareness_level="aware",
        )
        self.private_item = make_knowledge_item(
            self.connection, world, statement="Tobin owes the ferryman."
        )
        make_entity_knowledge(
            self.connection,
            self.timeline_id,
            self.private_item,
            uuid.UUID(self.tobin),
            interpretation="I owe the ferryman a favour.",
        )
        self.public_item = make_knowledge_item(
            self.connection, world, statement="The market opens at dawn."
        )
        location = make_location(self.connection, world, name="Lantern Market")
        make_public_knowledge(self.connection, self.timeline_id, self.public_item, location)

    def _campaign_membership(self, user_id: uuid.UUID) -> uuid.UUID:
        value = self.connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": self.s.cid, "u": user_id},
        ).scalar()
        assert isinstance(value, uuid.UUID)
        return value

    def clock_at(self, year: int) -> None:
        set_clock(self.s, self.t[year])

    # --- request helpers ---------------------------------------------------------------------
    def knowledge(self, actor: Any, **params: str) -> Any:
        return actor.get(f"/campaigns/{self.s.cid}/knowledge", limit=100, **params)

    def pair(self) -> dict[str, str]:
        return {"character_id": self.tobin, "party_id": self.party_id}

    def character_only(self) -> dict[str, str]:
        return {"character_id": self.tobin}

    def parties_of_tobin(self, actor: Any) -> Any:
        return actor.get(f"/campaigns/{self.s.cid}/characters/{self.tobin}/parties")

    def roster(self, actor: Any) -> Any:
        return actor.get(parties_url(self.s, f"/{self.party_id}/roster"))

    def gm_members(self) -> Any:
        return self.s.gm.get(parties_url(self.s, f"/{self.party_id}/members"))

    def inventory(self) -> Any:
        return self.s.gm.get(parties_url(self.s, f"/{self.party_id}/inventory"))

    def bootstrap_parties(self) -> list[str]:
        bootstrap = get_session_bootstrap(self.connection, user_id=self.s.player.user_id)
        campaign = next(c for c in bootstrap.campaigns if str(c.campaign_id) == self.s.cid)
        return [
            str(p.party_id)
            for perspective in campaign.character_perspectives
            if str(perspective.character_id) == self.tobin
            for p in perspective.authorized_parties
        ]

    def item_ids(self, response: Any) -> set[str]:
        assert response.status_code == 200, response.text
        return {item["knowledge_item_id"] for item in response.json()["items"]}


@pytest.fixture
def scene(db_connection: Connection, harness: AuthoringHarness) -> Scene:
    return Scene(ContentSetup(harness, db_connection))


def _stripped(response: Any) -> dict[str, Any]:
    """A refusal body without its per-request correlation id."""
    body = response.json()
    body["error"] = {k: v for k, v in body["error"].items() if k != "correlation_id"}
    return body  # type: ignore[no-any-return]


# --- the pure rule -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end_key", "clock", "expected"),
    [
        (100, 200, 99, "not_started"),
        (100, 200, 100, "in_effect"),  # the join boundary is included
        (100, 200, 150, "in_effect"),
        (100, 200, 200, "ended"),  # the leave boundary is excluded
        (100, 200, 201, "ended"),
        (300, None, 250, "not_started"),  # a future open-ended join is not current
        (300, None, 300, "in_effect"),
        (300, None, 10_000, "in_effect"),
        (100, 200, None, "clock_unset"),  # no clock: undetermined, not ended and not upcoming
        (300, None, None, "clock_unset"),
    ],
)
def test_the_half_open_rule_and_the_undetermined_state(
    start: int, end_key: int | None, clock: int | None, expected: str
) -> None:
    assert (
        membership_period_status(start, end_key, MembershipClock(sort_key=clock, display=None))
        == expected
    )


# --- every surface agrees on every probe ----------------------------------------------------------


@pytest.mark.real_relationship_policy
@pytest.mark.parametrize("year", range(BEFORE, AFTER + 1))
def test_every_surface_agrees_at_every_clock_position(scene: Scene, year: int) -> None:
    scene.clock_at(year)
    tobin_in = year in TOBIN_IN_EFFECT
    mira_in = year in MIRA_IN_EFFECT
    s = scene.s

    # Bootstrap authorized_parties and the per-request guard.
    assert scene.bootstrap_parties() == ([scene.party_id] if tobin_in else [])
    guard = scene.knowledge(s.player, **scene.pair())
    assert guard.status_code == (200 if tobin_in else 404)
    if tobin_in:
        assert scene.party_fact in {uuid.UUID(i) for i in scene.item_ids(guard)}

    # Knowledge's implicit eligible-party path (character selected, no party chosen).
    implicit = scene.item_ids(scene.knowledge(s.player, **scene.character_only()))
    assert (str(scene.party_fact) in implicit) is tobin_in
    assert {str(scene.private_item), str(scene.public_item)} <= implicit

    # Character Parties list.
    parties = scene.parties_of_tobin(s.player)
    assert parties.status_code == 200
    body = parties.json()
    assert [i["party_id"] for i in body["items"]] == ([scene.party_id] if tobin_in else [])
    assert body["clock_unset"] is False and body["as_of"]

    # Read-only roster: members and count agree.
    # D4-C (P03-A A3b): the player controls Tobin, so the roster lists the current members only
    # while Tobin is one; a controller of a former or future member sees no more than discovery.
    names = sorted(n for n, on in (("Tobin", tobin_in), ("Mira", mira_in)) if on)
    roster = scene.roster(s.player).json()
    roster_names = sorted(m["character_name"] for m in roster["members"])
    assert roster_names == (names if tobin_in else [])
    assert roster["member_count"] == len(roster_names)
    assert roster["clock_unset"] is False

    # GM management rows: period status per row, is_current kept as `in_effect`.
    gm = scene.gm_members().json()
    assert gm["clock_unset"] is False
    rows = {(r["character_name"], r["left_at"] is None, r["joined_at"]): r for r in gm["members"]}
    statuses = sorted((r["character_name"], r["period_status"]) for r in rows.values())
    expected_tobin_first = (
        "not_started" if year < ARRIVAL else "in_effect" if year < MEETING else "ended"
    )
    expected_tobin_second = "not_started" if year < DESCENT else "in_effect"
    expected_mira = "not_started" if year < ARRIVAL else "in_effect"
    assert statuses == sorted(
        [
            ("Tobin", expected_tobin_first),
            ("Tobin", expected_tobin_second),
            ("Mira", expected_mira),
        ]
    )
    assert all(r["is_current"] is (r["period_status"] == "in_effect") for r in rows.values())

    # GM party inventory lists the same members as the roster.
    inventory = scene.inventory().json()
    assert inventory["clock_unset"] is False
    assert sorted(m["character_name"] for m in inventory["members"]) == names


@pytest.mark.real_relationship_policy
def test_a_finite_interval_containing_the_clock_is_current_and_a_future_open_one_is_not(
    scene: Scene,
) -> None:
    # Under-authorization direction: [ARRIVAL, MEETING) contains the clock though it ends later.
    scene.clock_at(BETWEEN)
    assert scene.knowledge(scene.s.player, **scene.pair()).status_code == 200
    assert "Tobin" in [m["character_name"] for m in scene.roster(scene.s.player).json()["members"]]
    # Over-authorization direction: [DESCENT, inf) has not started at MEETING.
    scene.clock_at(MEETING)
    assert scene.knowledge(scene.s.player, **scene.pair()).status_code == 404
    assert scene.parties_of_tobin(scene.s.player).json()["items"] == []
    upcoming = [
        r["period_status"]
        for r in scene.gm_members().json()["members"]
        if r["character_name"] == "Tobin" and r["left_at"] is None
    ]
    assert upcoming == ["not_started"]


# --- no effective clock: undetermined -------------------------------------------------------------


@pytest.mark.real_relationship_policy
def test_with_no_clock_membership_is_undetermined_and_grants_nothing(scene: Scene) -> None:
    s = scene.s
    assert s.gm.get(f"/campaigns/{s.cid}/clock").json()["current"] is None

    bootstrap = get_session_bootstrap(scene.connection, user_id=s.player.user_id)
    campaign = next(c for c in bootstrap.campaigns if str(c.campaign_id) == s.cid)
    assert campaign.current_time_set is False
    assert scene.bootstrap_parties() == []
    # The character stays selectable; only the party list is withheld.
    assert [str(p.character_id) for p in campaign.character_perspectives] == [scene.tobin]

    assert scene.knowledge(s.player, **scene.pair()).status_code == 404
    implicit = scene.item_ids(scene.knowledge(s.player, **scene.character_only()))
    # Independent access: the character's own knowledge and public knowledge remain.
    assert implicit == {str(scene.private_item), str(scene.public_item)}

    parties = scene.parties_of_tobin(s.player).json()
    assert parties["items"] == [] and parties["clock_unset"] is True and parties["as_of"] is None

    roster = scene.roster(s.player).json()
    assert roster["members"] == [] and roster["member_count"] == 0
    assert roster["clock_unset"] is True and roster["as_of"] is None

    gm = scene.gm_members().json()
    assert gm["clock_unset"] is True and gm["as_of"] is None
    assert len(gm["members"]) == 3  # the GM still sees every membership row
    assert {r["period_status"] for r in gm["members"]} == {"clock_unset"}
    assert {r["is_current"] for r in gm["members"]} == {False}

    inventory = scene.inventory().json()
    assert inventory["members"] == [] and inventory["clock_unset"] is True


@pytest.mark.real_relationship_policy
def test_with_no_clock_the_gm_keeps_canonical_views_and_can_still_manage_membership(
    scene: Scene,
) -> None:
    s = scene.s
    # Canonical (ground-truth) Knowledge needs no pair and is unchanged.
    canonical = scene.item_ids(scene.knowledge(s.gm))
    assert str(scene.party_fact) in canonical and str(scene.private_item) in canonical
    # The party directory and detail do not depend on membership.
    assert s.player.get(parties_url(s)).status_code == 200
    assert s.player.get(parties_url(s, f"/{scene.party_id}")).status_code == 200
    # GM management still works: add a member, read it back, end it.
    ada = published_pc(s, "Ada")
    joined = add(s, scene.party_id, ada, scene.t[ARRIVAL])
    assert joined.status_code == 201, joined.text
    assert (
        end(s, scene.party_id, joined.json()["party_membership_id"], scene.t[MEETING]).status_code
        == 200
    )
    ada_rows = [r for r in scene.gm_members().json()["members"] if r["character_name"] == "Ada"]
    assert [r["left_at"] is None for r in ada_rows] == [False]
    assert ada_rows[0]["period_status"] == "clock_unset"


@pytest.mark.real_relationship_policy
def test_a_character_targeted_allow_keeps_working_without_a_clock(scene: Scene) -> None:
    s = scene.s
    view_knowledge = scene.connection.execute(
        text(
            "SELECT capability_id FROM security.capabilities WHERE code = 'character.view_knowledge'"
        )
    ).scalar()
    # Player Two has no relationship to Tobin; an explicit allow grants the character's own view.
    assert scene.parties_of_tobin(scene.player2).status_code == 404
    make_resource_grant(
        scene.connection,
        uuid.UUID(s.cid),
        view_knowledge,
        grantee_campaign_membership_id=scene._campaign_membership(scene.player2.user_id),
        character_id=uuid.UUID(scene.tobin),
        effect="allow",
    )
    own = scene.item_ids(scene.knowledge(scene.player2, **scene.character_only()))
    assert str(scene.private_item) in own
    assert scene.parties_of_tobin(scene.player2).json()["clock_unset"] is True
    # But an allow on the character is not current membership: no party perspective, no party facts.
    assert scene.knowledge(scene.player2, **scene.pair()).status_code == 404
    assert str(scene.party_fact) not in own


# --- denies and non-disclosure --------------------------------------------------------------------


@pytest.mark.real_relationship_policy
def test_refusals_are_the_same_fixed_404_whatever_the_clock_or_the_cause(scene: Scene) -> None:
    s = scene.s
    scene.clock_at(MEETING)  # the pair is not in effect
    expired = scene.knowledge(s.player, **scene.pair())
    unknown_party = scene.knowledge(s.player, character_id=scene.tobin, party_id=str(uuid.uuid4()))
    no_relationship = scene.knowledge(scene.player2, **scene.pair())
    assert expired.status_code == unknown_party.status_code == no_relationship.status_code == 404
    assert _stripped(expired) == _stripped(unknown_party) == _stripped(no_relationship)
    for text_value in (expired.text, no_relationship.text):
        assert scene.party_id not in text_value and scene.tobin not in text_value

    # The Parties list: a caller without the character perspective gets the same 404 with and
    # without a clock, so the clock state is not learned from it.
    with_clock = scene.parties_of_tobin(scene.player2)
    scene.connection.execute(
        text("DELETE FROM campaign.timeline_clocks WHERE timeline_id = :t"),
        {"t": scene.timeline_id},
    )
    without_clock = scene.parties_of_tobin(scene.player2)
    assert with_clock.status_code == without_clock.status_code == 404
    assert _stripped(with_clock) == _stripped(without_clock)
    assert "clock" not in without_clock.text.lower()


@pytest.mark.real_relationship_policy
def test_an_entity_deny_keeps_a_member_in_effect_off_the_roster(scene: Scene) -> None:
    s = scene.s
    scene.clock_at(AFTER)
    view = scene.connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = 'campaign.view'")
    ).scalar()
    make_resource_grant(
        scene.connection,
        uuid.UUID(s.cid),
        view,
        grantee_campaign_membership_id=scene.player_membership_id,
        entity_id=uuid.UUID(scene.mira),
        effect="deny",
    )
    roster = scene.roster(s.player).json()
    assert [m["character_name"] for m in roster["members"]] == ["Tobin"]
    assert roster["member_count"] == 1 and scene.mira not in str(roster)
    assert scene.roster(s.gm).json()["member_count"] == 2


@pytest.mark.real_relationship_policy
def test_an_archived_party_is_not_found_for_a_viewer_before_any_clock_state(scene: Scene) -> None:
    s = scene.s
    archived = s.gm.post_raw(
        parties_url(s, f"/{scene.party_id}/archive"),
        {
            "expected_row_version": s.gm.get(parties_url(s, f"/{scene.party_id}")).json()[
                "row_version"
            ]
        },
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200, archived.text
    no_clock = scene.roster(s.player)
    scene.clock_at(AFTER)
    with_clock = scene.roster(s.player)
    assert no_clock.status_code == with_clock.status_code == 404
    assert _stripped(no_clock) == _stripped(with_clock)


# --- fresh requests -------------------------------------------------------------------------------


@pytest.mark.real_relationship_policy
def test_each_request_uses_the_clock_as_it_is_now(scene: Scene) -> None:
    s = scene.s
    scene.clock_at(BETWEEN)
    assert scene.bootstrap_parties() == [scene.party_id]
    assert scene.knowledge(s.player, **scene.pair()).status_code == 200
    # Advance through the real route to the (excluded) leave boundary: the very next requests no
    # longer see the stint.
    clock = s.gm.get(f"/campaigns/{s.cid}/clock").json()
    advanced = s.gm.post_raw(
        f"/campaigns/{s.cid}/clock/advance",
        {
            "world_time_id": scene.t[MEETING],
            "expected_row_version": clock["row_version"],
        },
        key=s.gm.fresh_key(),
    )
    assert advanced.status_code == 200, advanced.text
    assert scene.bootstrap_parties() == []
    assert scene.knowledge(s.player, **scene.pair()).status_code == 404
    assert scene.parties_of_tobin(s.player).json()["items"] == []
    # Moving the clock back restores it; nothing was cached.
    scene.clock_at(BETWEEN)
    assert scene.bootstrap_parties() == [scene.party_id]


@pytest.mark.real_relationship_policy
def test_one_request_resolves_the_effective_clock_once(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene.clock_at(AFTER)
    real = period_module.resolve_effective_clock
    calls: list[uuid.UUID] = []

    def counting(connection: Connection, *, timeline_id: uuid.UUID) -> Any:
        calls.append(timeline_id)
        return real(connection, timeline_id=timeline_id)

    monkeypatch.setattr(period_module, "resolve_effective_clock", counting)
    detail = f"/campaigns/{scene.s.cid}/knowledge/{scene.party_fact}"
    for actor in (scene.s.player, scene.s.gm):
        calls.clear()
        response = actor.get(detail, **scene.pair())
        assert response.status_code in (200, 404), response.text
        assert len(calls) <= 1, "a request must read the effective clock at most once"
    calls.clear()
    assert scene.knowledge(scene.s.player, **scene.pair()).status_code == 200
    assert len(calls) == 1


# --- timeline scope and inherited clocks ----------------------------------------------------------


@pytest.mark.real_relationship_policy
def test_a_branch_inherits_the_clock_not_the_membership(scene: Scene) -> None:
    s = scene.s
    # Parent clock after the branch point: the branch reads its branch point, not the parent time.
    # (A branch point needs a recorded event there, so the clock is advanced through the route.)
    assert _advance(s, scene.t[BETWEEN], 0).status_code == 200
    assert _advance(s, scene.t[AFTER], 1).status_code == 200
    branch_cid = _branch_campaign(s, scene.t[BETWEEN])
    branch_timeline = uuid.UUID(
        str(
            scene.connection.execute(
                text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
                {"c": branch_cid},
            ).scalar()
        )
    )
    between_key = scene.connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :w"),
        {"w": scene.t[BETWEEN]},
    ).scalar()
    clock = resolve_membership_clock(scene.connection, timeline_id=branch_timeline)
    assert clock.sort_key == between_key

    party = uuid.UUID(scene.party_id)
    parent_clock = resolve_membership_clock(scene.connection, timeline_id=scene.timeline_id)
    assert parent_clock.sort_key != clock.sort_key
    # The parent's memberships do not appear on the branch (timeline scope retained).
    assert (
        list_party_members(
            scene.connection, timeline_id=branch_timeline, party_id=party, membership_clock=clock
        )
        == []
    )
    # A membership written on the branch is judged against the inherited clock.
    make_campaign_party(scene.connection, uuid.UUID(branch_cid), party)
    make_party_membership(
        scene.connection,
        branch_timeline,
        party,
        uuid.UUID(scene.tobin),
        uuid.UUID(scene.t[BETWEEN]),
    )
    make_party_membership(
        scene.connection, branch_timeline, party, uuid.UUID(scene.mira), uuid.UUID(scene.t[LATER])
    )
    rows = list_party_members(
        scene.connection, timeline_id=branch_timeline, party_id=party, membership_clock=clock
    )
    assert {r.character_name: r.period_status for r in rows} == {
        "Tobin": "in_effect",  # joined at the branch point: the join boundary is included
        "Mira": "not_started",  # joined after the branch point
    }


@pytest.mark.real_relationship_policy
def test_a_branch_of_a_root_without_a_clock_is_never_undetermined(scene: Scene) -> None:
    s = scene.s
    assert _advance(s, scene.t[BETWEEN], 0).status_code == 200  # leaves the event a branch needs
    scene.connection.execute(
        text("DELETE FROM campaign.timeline_clocks WHERE timeline_id = :t"),
        {"t": scene.timeline_id},
    )
    assert (
        resolve_membership_clock(scene.connection, timeline_id=scene.timeline_id).sort_key is None
    )
    branch_cid = _branch_campaign(s, scene.t[BETWEEN])
    branch_timeline = scene.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": branch_cid}
    ).scalar()
    clock = resolve_membership_clock(scene.connection, timeline_id=branch_timeline)
    assert clock.is_set and clock.display
    # ...while the root itself stays undetermined.
    assert not resolve_membership_clock(scene.connection, timeline_id=scene.timeline_id).is_set


# --- history and the travel exception -------------------------------------------------------------


@pytest.mark.real_relationship_policy
def test_the_gm_rows_keep_every_stored_period_whatever_the_clock(scene: Scene) -> None:
    scene.clock_at(BEFORE)
    early = {
        (r["character_name"], r["joined_at"], r["left_at"])
        for r in scene.gm_members().json()["members"]
    }
    scene.clock_at(AFTER)
    late = {
        (r["character_name"], r["joined_at"], r["left_at"])
        for r in scene.gm_members().json()["members"]
    }
    assert early == late and len(late) == 3  # history is stored fact; only the label moves


@pytest.mark.real_relationship_policy
def test_the_travel_command_still_expands_open_ended_members_regardless_of_the_clock(
    scene: Scene,
) -> None:
    """Deferred (plan section 8, U1): the travel command keeps expanding a party to its open-ended
    memberships and is not routed through the Now predicate in this checkpoint, so Tobin's
    not-yet-started stint travels with the party at MEETING while his ended stint adds nothing."""
    from tests.database.test_api_routes_travel import place, travel

    s = scene.s
    scene.clock_at(MEETING)
    gm_rows = [
        (r["character_name"], r["period_status"], r["left_at"] is None)
        for r in scene.gm_members().json()["members"]
    ]
    # `left_at is None` is the stored open end, the fact the unchanged command moves. It is not
    # `period_status`/`is_current`; the portal Travel preview reads it (B1-DEF7b).
    assert ("Tobin", "not_started", True) in gm_rows
    town = place(s, "Lantern Market Town")
    result = travel(s, town, party_id=scene.party_id)
    assert result.status_code == 200, result.text
    assert set(result.json()["moved"]) == {scene.tobin, scene.mira}
