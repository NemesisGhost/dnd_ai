"""Temporal party membership endpoints (checkpoint 15.2C-2, migration 121)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.bootstrap import get_session_bootstrap
from dnd_ai.queries.party_members import list_party_members
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _branch_campaign
from tests.factories import make_character, make_membership_character_relationship

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def parties_url(s: ContentSetup, suffix: str = "") -> str:
    return f"/campaigns/{s.cid}/parties{suffix}"


def new_party(s: ContentSetup, name: str = "The Company") -> dict:
    response = s.gm.post_raw(parties_url(s), {"name": name}, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def published_pc(s: ContentSetup, name: str = "Aldric") -> str:
    species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("player-characters"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["player_character_id"], created["row_version"])
    return created["player_character_id"]


def party_version(s: ContentSetup, party_id: str) -> int:
    return int(s.gm.get(parties_url(s, f"/{party_id}")).json()["row_version"])


def add(s: ContentSetup, party_id: str, character: str, time_id: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        parties_url(s, f"/{party_id}/members"),
        {
            "character_id": character,
            "effective_from_world_time_id": time_id,
            "expected_party_row_version": party_version(s, party_id),
            **extra,
        },
        key=s.gm.fresh_key(),
    )


def end(s: ContentSetup, party_id: str, membership_id: str, time_id: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        parties_url(s, f"/{party_id}/members/{membership_id}/end"),
        {
            "effective_to_world_time_id": time_id,
            "expected_party_row_version": party_version(s, party_id),
            **extra,
        },
        key=s.gm.fresh_key(),
    )


def members(s: ContentSetup, party_id: str) -> dict:
    response = s.gm.get(parties_url(s, f"/{party_id}/members"))
    assert response.status_code == 200, response.text
    return response.json()


def event_of(s: ContentSetup, event_id: str) -> dict:
    row = s.connection.execute(
        text("""
            SELECT et.code AS event_type, e.timeline_id, e.campaign_id, e.world_time_id,
                   (SELECT count(*) FROM narrative.event_participants ep WHERE ep.event_id = e.event_id)
                       AS participants,
                   (SELECT string_agg(f.target_component || ':' || coalesce(f.previous_value::text, 'null')
                                      || '>' || coalesce(f.new_value::text, 'null'), ',')
                    FROM narrative.event_effects f WHERE f.event_id = e.event_id) AS effects
            FROM narrative.events e JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
            WHERE e.event_id = :e
        """),
        {"e": event_id},
    ).one()
    return dict(row._mapping)


def test_adding_a_member_records_an_event_an_effect_and_bumps_the_party(s: ContentSetup) -> None:
    times = Times(s)
    party, pc, y1 = new_party(s), published_pc(s), times.at(1)
    response = add(s, party["party_id"], pc, y1, reason="SECRET REASON")
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert set(receipt) == {
        "party_id",
        "party_membership_id",
        "row_version",
        "event_id",
        "created",
        "changed",
    }
    assert receipt["row_version"] == party["row_version"] + 1
    event = event_of(s, receipt["event_id"])
    assert event["event_type"] == "party_member_joined" and event["participants"] == 1
    assert str(event["world_time_id"]) == y1 and str(event["campaign_id"]) == s.cid
    assert event["effects"] == f'party_membership:null>"{party["party_id"]}"'
    listed = members(s, party["party_id"])
    (row,) = listed["members"]
    assert row["is_current"] is True and row["character_name"] == "Aldric"
    assert row["joined_at"].startswith("Year 1") and row["left_at"] is None
    (audit,) = s.audit("add_party_member")
    assert audit.entity_id == uuid.UUID(pc)
    assert "SECRET REASON" not in str(audit.changed_fields)


@pytest.mark.parametrize("kind", ["draft", "bare", "foreign"])
def test_only_published_active_characters_of_the_world_can_join(s: ContentSetup, kind: str) -> None:
    times = Times(s)
    party, y1 = new_party(s), times.at(1)
    if kind == "draft":
        species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
        character = s.gm.post(
            s.url("player-characters"),
            {"name": "Draft", "species_id": species, "size_category": "medium"},
            key=s.gm.fresh_key(),
        ).json()["player_character_id"]
    elif kind == "bare":
        character = str(make_character(s.connection, s.world_id, name="Bare"))
    else:
        character = str(make_character(s.connection, s.other_world_id, name="Elsewhere"))
    response = add(s, party["party_id"], character, y1)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "party_member_invalid"
    assert members(s, party["party_id"])["members"] == []


def test_times_and_the_party_version_and_state_are_checked(s: ContentSetup) -> None:
    times = Times(s)
    party, pc, y1 = new_party(s), published_pc(s), times.at(1)
    other_world_time = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars",
        {
            "name": "C",
            "description": None,
            "days_per_week": None,
            "epoch_label": None,
            "months": [{"name": "M", "day_count": 10}],
        },
        key=s.stranger.fresh_key(),
    ).json()["calendar_id"]
    foreign_time = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/world-times",
        {"calendar_id": other_world_time, "year": 1},
        key=s.stranger.fresh_key(),
    ).json()["world_time_id"]
    refused = add(s, party["party_id"], pc, foreign_time)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "world_time_id_invalid"

    stale = s.gm.post_raw(
        parties_url(s, f"/{party['party_id']}/members"),
        {"character_id": pc, "effective_from_world_time_id": y1, "expected_party_row_version": 99},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"

    archived = s.gm.post_raw(
        parties_url(s, f"/{party['party_id']}/archive"),
        {"expected_row_version": party["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200
    closed = add(s, party["party_id"], pc, y1)
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "party_not_active"
    assert members(s, party["party_id"])["members"] == []


def test_overlapping_memberships_are_a_clean_conflict_and_adjacent_ones_are_fine(
    s: ContentSetup,
) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s)
    y1, y3, y5, y7 = times.at(1), times.at(3), times.at(5), times.at(7)
    first = add(s, party["party_id"], pc, y1).json()
    again = add(s, party["party_id"], pc, y3)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "party_membership_overlap"

    assert end(s, party["party_id"], first["party_membership_id"], y5).status_code == 200
    # Starting inside the ended interval overlaps it; starting where it ended does not.
    inside = add(s, party["party_id"], pc, y3)
    assert (
        inside.status_code == 409 and inside.json()["error"]["code"] == "party_membership_overlap"
    )
    rejoin = add(s, party["party_id"], pc, y5)
    assert rejoin.status_code == 201, rejoin.text
    # Another party takes the same character at the same time.
    other = new_party(s, "The Second Company")
    assert add(s, other["party_id"], pc, y5).status_code == 201
    listed = members(s, party["party_id"])["members"]
    assert [m["is_current"] for m in listed] == [True, False]
    assert y7  # unused anchor keeps the times ordered for readers of the test


def test_ending_a_membership_records_a_leave_event_and_rules_out_bad_ends(
    s: ContentSetup,
) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s)
    y2, y4 = times.at(2), times.at(4)
    joined = add(s, party["party_id"], pc, y2).json()
    for bad in (y2, times.at(1)):  # at, and before, the start
        response = end(s, party["party_id"], joined["party_membership_id"], bad)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "party_membership_end_not_after_start"
    left = end(s, party["party_id"], joined["party_membership_id"], y4, reason="PRIVATE")
    assert left.status_code == 200, left.text
    event = event_of(s, left.json()["event_id"])
    assert event["event_type"] == "party_member_left"
    assert event["effects"] == f'party_membership:"{party["party_id"]}">null'
    row = members(s, party["party_id"])["members"][0]
    assert row["is_current"] is False and row["left_at"].startswith("Year 4")
    twice = end(s, party["party_id"], joined["party_membership_id"], times.at(6))
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "party_membership_not_open"
    (audit,) = s.audit("end_party_membership")
    assert "PRIVATE" not in str(audit.changed_fields)
    # Ending is still allowed once the party is archived (history stays correct).
    second = add(s, party["party_id"], published_pc(s, "Bryn"), times.at(7)).json()
    version = party_version(s, party["party_id"])
    assert (
        s.gm.post_raw(
            parties_url(s, f"/{party['party_id']}/archive"),
            {"expected_row_version": version},
            key=s.gm.fresh_key(),
        ).status_code
        == 200
    )
    assert end(s, party["party_id"], second["party_membership_id"], times.at(8)).status_code == 200


def test_foreign_parties_and_memberships_are_indistinguishable_from_missing(
    s: ContentSetup,
) -> None:
    times = Times(s)
    party, pc, y1 = new_party(s), published_pc(s), times.at(1)
    joined = add(s, party["party_id"], pc, y1).json()
    other = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/parties", {"name": "Elsewhere"}, key=s.stranger.fresh_key()
    ).json()
    responses = [
        s.gm.get(parties_url(s, f"/{other['party_id']}/members")),
        s.gm.get(parties_url(s, f"/{uuid.uuid4()}/members")),
        s.gm.post_raw(
            parties_url(s, f"/{other['party_id']}/members"),
            {
                "character_id": pc,
                "effective_from_world_time_id": y1,
                "expected_party_row_version": 1,
            },
            key=s.gm.fresh_key(),
        ),
        s.gm.post_raw(
            parties_url(s, f"/{other['party_id']}/members/{joined['party_membership_id']}/end"),
            {"effective_to_world_time_id": y1, "expected_party_row_version": 1},
            key=s.gm.fresh_key(),
        ),
        s.gm.post_raw(
            parties_url(s, f"/{party['party_id']}/members/{uuid.uuid4()}/end"),
            {
                "effective_to_world_time_id": times.at(3),
                "expected_party_row_version": party_version(s, party["party_id"]),
            },
            key=s.gm.fresh_key(),
        ),
    ]
    assert [r.status_code for r in responses] == [404] * 5
    assert len({(r.json()["error"]["code"], r.json()["error"]["message"]) for r in responses}) == 1


def test_players_cannot_read_or_write_membership(s: ContentSetup) -> None:
    times = Times(s)
    party, pc, y1 = new_party(s), published_pc(s), times.at(1)
    assert s.player.get(parties_url(s, f"/{party['party_id']}/members")).status_code == 403
    body = {"character_id": pc, "effective_from_world_time_id": y1, "expected_party_row_version": 1}
    assert (
        s.player.post_raw(
            parties_url(s, f"/{party['party_id']}/members"), body, key=s.player.fresh_key()
        ).status_code
        == 403
    )


def test_replay_returns_the_same_receipt_and_one_event(s: ContentSetup) -> None:
    times = Times(s)
    party, pc, y1 = new_party(s), published_pc(s), times.at(1)
    body = {
        "character_id": pc,
        "effective_from_world_time_id": y1,
        "expected_party_row_version": party["row_version"],
    }
    key = s.gm.fresh_key()
    first = s.gm.post_raw(parties_url(s, f"/{party['party_id']}/members"), body, key=key)
    again = s.gm.post_raw(parties_url(s, f"/{party['party_id']}/members"), body, key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    joined_events = s.connection.execute(
        text(
            "SELECT count(*) FROM narrative.events e JOIN narrative.event_types t "
            "ON t.event_type_id = e.event_type_id "
            "WHERE e.campaign_id = :c AND t.code = 'party_member_joined'"
        ),
        {"c": s.cid},
    ).scalar()
    assert joined_events == 1


def test_a_failure_while_writing_the_membership_leaves_no_event(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    times = Times(s)
    party, pc, y1 = new_party(s), published_pc(s), times.at(1)
    version = party_version(s, party["party_id"])
    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO campaign.party_memberships" in str(statement):
            raise RuntimeError("injected failure before the membership row")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = (
        "campaign.party_memberships",
        "narrative.events",
        "narrative.event_effects",
        "audit.change_log",
    )
    before = {t: s.count(t) for t in tables}
    monkeypatch.setattr(Conn, "execute", failing)
    response = s.gm.post_raw(
        parties_url(s, f"/{party['party_id']}/members"),
        {
            "character_id": pc,
            "effective_from_world_time_id": y1,
            "expected_party_row_version": version,
        },
        key=s.gm.fresh_key(),
    )
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}
    assert party_version(s, party["party_id"]) == version


def test_membership_belongs_to_one_timeline_and_a_branch_starts_without_it(
    s: ContentSetup,
) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s)
    y1 = times.at(1)
    assert add(s, party["party_id"], pc, y1).status_code == 201
    branch_cid = _branch_campaign(s, y1)
    parent_timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    branch_timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": branch_cid},
    ).scalar()
    party_id = uuid.UUID(party["party_id"])
    assert (
        len(list_party_members(s.connection, timeline_id=parent_timeline, party_id=party_id)) == 1
    )
    assert list_party_members(s.connection, timeline_id=branch_timeline, party_id=party_id) == []


@pytest.mark.real_relationship_policy
def test_the_party_perspective_appears_when_a_member_joins_and_goes_when_they_leave(
    s: ContentSetup,
) -> None:
    times = Times(s)
    party, pc = new_party(s), published_pc(s)
    y1, y3 = times.at(1), times.at(3)
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
    make_membership_character_relationship(s.connection, membership, uuid.UUID(pc), owner_type)

    def parties_for_player() -> list[str]:
        bootstrap = get_session_bootstrap(s.connection, user_id=s.player.user_id)
        campaign = next(c for c in bootstrap.campaigns if str(c.campaign_id) == s.cid)
        return [
            str(p.party_id)
            for perspective in campaign.character_perspectives
            for p in perspective.authorized_parties
        ]

    assert parties_for_player() == []
    joined = add(s, party["party_id"], pc, y1).json()
    assert parties_for_player() == [party["party_id"]]
    assert end(s, party["party_id"], joined["party_membership_id"], y3).status_code == 200
    assert parties_for_player() == []


def test_the_database_keeps_membership_events_on_the_memberships_own_timeline(
    s: ContentSetup,
) -> None:
    from sqlalchemy.exc import IntegrityError

    times = Times(s)
    party, pc, y1 = new_party(s), published_pc(s), times.at(1)
    joined = add(s, party["party_id"], pc, y1).json()
    # An event of another timeline cannot be cited, and a leave event needs an end.
    foreign_event = s.connection.execute(
        text(
            "SELECT e.event_id FROM narrative.events e WHERE e.timeline_id <> "
            "(SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c) LIMIT 1"
        ),
        {"c": s.cid},
    ).scalar()
    if foreign_event is not None:
        with (
            pytest.raises(IntegrityError, match="belongs to timeline"),
            s.connection.begin_nested(),
        ):
            s.connection.execute(
                text(
                    "UPDATE campaign.party_memberships SET joined_event_id = :e "
                    "WHERE party_membership_id = :m"
                ),
                {"e": foreign_event, "m": joined["party_membership_id"]},
            )
    with pytest.raises(IntegrityError), s.connection.begin_nested():
        s.connection.execute(
            text(
                "UPDATE campaign.party_memberships SET left_event_id = :e "
                "WHERE party_membership_id = :m"
            ),
            {"e": joined["event_id"], "m": joined["party_membership_id"]},
        )
