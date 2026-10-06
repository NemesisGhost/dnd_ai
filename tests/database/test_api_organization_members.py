"""Organization membership, offices and operational status (checkpoint 15.3A-2b, decision D-19)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def organization(s: ContentSetup, name: str, *, publish: bool = True) -> str:
    created = s.gm.post(
        s.url("organizations"),
        {"kind": "organization", "organization_type": "guild", "name": name},
        key=s.gm.fresh_key(),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    entity = str(body["organization_id"])
    if publish:
        s.publish(entity, body["row_version"])
    return entity


def npc(s: ContentSetup, name: str) -> str:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("npcs"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["npc_id"], created["row_version"])
    return str(created["npc_id"])


def place(s: ContentSetup, name: str) -> str:
    created = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": name}, key=s.gm.fresh_key()
    ).json()
    s.publish(created["location_id"], created["row_version"])
    return str(created["location_id"])


def join(s: ContentSetup, org: str, member: str, start: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post(
        s.url("relationships"),
        {
            "kind": "membership",
            "relationship_type": "membership",
            "participants": [
                {"entity_id": member, "role": "member"},
                {"entity_id": org, "role": "organization"},
            ],
            "started_world_time_id": start,
            **extra,
        },
        key=s.gm.fresh_key(),
    )


def members(s: ContentSetup, org: str, who: object = None) -> dict:
    actor = who or s.gm
    response = actor.get(f"/campaigns/{s.cid}/organizations/{org}/members")  # type: ignore[attr-defined]
    assert response.status_code == 200, response.text
    return response.json()


def act(s: ContentSetup, relationship: dict, action: str, body: dict | None = None):  # type: ignore[no-untyped-def]
    current = s.gm.get(s.url(f"relationships/{relationship['relationship_id']}")).json()
    return s.gm.post(
        s.url(f"relationships/{relationship['relationship_id']}/{action}"),
        {"expected_row_version": current["row_version"], **(body or {})},
        key=s.gm.fresh_key(),
    )


def test_a_member_joins_with_an_office_and_the_roster_shows_it(s: ContentSetup) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    start = Times(s).at(1)
    joined = join(s, guild, mira, start, role="Captain", rank="Senior", is_public=True)
    assert joined.status_code == 201, joined.text
    body = joined.json()
    assert body["kind"] == "membership" and body["typed"] == {
        "role": "Captain",
        "rank": "Senior",
        "is_public": True,
    }
    roster = members(s, guild)
    [row] = roster["members"]
    assert row["member_name"] == "Mira" and row["role"] == "Captain" and row["current"] is True
    assert roster["can_edit"] is True and roster["status"] is None
    assert {c["value"] for c in roster["status_choices"]} >= {"active", "dissolved"}
    [audit] = s.audit("create_relationship")
    assert audit.action == "created" and "Captain" not in str(audit.changed_fields)


def test_membership_shapes_are_checked(s: ContentSetup) -> None:
    guild, mira, town = organization(s, "The Guild"), npc(s, "Mira"), place(s, "Stonebridge")
    start = Times(s).at(1)
    before = s.count("world.organization_memberships")
    cases = [
        join(s, mira, guild, start),  # roles the wrong way round: the member is not an organization
        join(s, guild, town, start),  # a place cannot be a member
        join(s, guild, guild, start),  # an organization is not its own member
    ]
    for response in cases:
        assert response.status_code in (400,), response.text
    no_start = s.gm.post(
        s.url("relationships"),
        {
            "kind": "membership",
            "relationship_type": "membership",
            "participants": [
                {"entity_id": mira, "role": "member"},
                {"entity_id": guild, "role": "organization"},
            ],
        },
        key=s.gm.fresh_key(),
    )
    assert no_start.status_code == 400 and code(no_start) == "membership_start_required"
    wrong_field = join(s, guild, mira, start, job_title="Cook")
    assert wrong_field.status_code in (400, 422)
    assert s.count("world.organization_memberships") == before


def test_one_stint_at_a_time_but_a_rejoin_is_a_new_row(s: ContentSetup) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    times = Times(s)
    year1, year3, year5, year8 = times.at(1), times.at(3), times.at(5), times.at(8)
    first = join(s, guild, mira, year1, role="Initiate")
    assert first.status_code == 201
    overlap = join(s, guild, mira, year3)
    assert overlap.status_code == 409 and code(overlap) == "membership_overlap"
    ended = act(s, first.json(), "end", {"ended_world_time_id": year5})
    assert ended.status_code == 200 and ended.json()["ended"] is not None
    still = join(s, guild, mira, year3)
    assert still.status_code == 409 and code(still) == "membership_overlap"
    rejoin = join(s, guild, mira, year8, role="Captain")
    assert rejoin.status_code == 201
    assert rejoin.json()["relationship_id"] != first.json()["relationship_id"]
    rows = members(s, guild)["members"]
    assert [(r["role"], r["current"]) for r in rows] == [("Initiate", False), ("Captain", True)]
    # Another organization is a separate scope.
    other = organization(s, "The Order")
    assert join(s, other, mira, year3).status_code == 201


def test_an_office_is_edited_in_place(s: ContentSetup) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    joined = join(s, guild, mira, Times(s).at(1), role="Initiate").json()
    updated = act(
        s,
        joined,
        "update",
        {
            "started_world_time_id": joined["started_world_time_id"],
            "role": "Captain",
            "rank": "First",
            "is_public": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["typed"] == {"role": "Captain", "rank": "First", "is_public": False}
    [row] = members(s, guild)["members"]
    assert (row["role"], row["rank"], row["is_public"]) == ("Captain", "First", False)
    wrong = act(
        s,
        updated.json(),
        "update",
        {"started_world_time_id": joined["started_world_time_id"], "family_unit_name": "x"},
    )
    assert wrong.status_code == 400 and code(wrong) == "relationship_invalid"


def test_moving_a_start_cannot_create_an_overlap(s: ContentSetup) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    times = Times(s)
    year1, year3, year5, year8 = times.at(1), times.at(3), times.at(5), times.at(8)
    first = join(s, guild, mira, year1).json()
    act(s, first, "end", {"ended_world_time_id": year3})
    second = join(s, guild, mira, year5).json()
    moved = act(s, second, "update", {"started_world_time_id": year1})
    assert moved.status_code == 409 and code(moved) == "membership_overlap"
    fine = act(s, second, "update", {"started_world_time_id": year8})
    assert fine.status_code == 200


def test_readers_see_only_public_active_members_they_can_discover(s: ContentSetup) -> None:
    guild = organization(s, "The Guild")
    bank, order, secret = (
        organization(s, "The Bank"),
        organization(s, "The Order"),
        organization(s, "The Cabal"),
    )
    start = Times(s).at(1)
    join(s, guild, bank, start, role="Patron")
    join(s, guild, secret, start, role="Hidden hand", is_public=False)
    archived = join(s, guild, order, start, role="Observer").json()
    act(s, archived, "archive")
    reader = members(s, guild, s.player)
    assert [m["member_name"] for m in reader["members"]] == ["The Bank"]
    assert reader["can_edit"] is False and reader["status_choices"] == []
    everyone = members(s, guild)
    assert {m["member_name"] for m in everyone["members"]} == {"The Bank", "The Cabal", "The Order"}
    # A character the reader cannot discover is not listed even when the membership is public.
    mira = npc(s, "Mira")
    join(s, guild, mira, start, role="Quartermaster")
    assert "Mira" not in [m["member_name"] for m in members(s, guild, s.player)["members"]]
    assert "Mira" in [m["member_name"] for m in members(s, guild)["members"]]


def test_an_unpublished_organization_has_no_roster_for_readers(s: ContentSetup) -> None:
    draft = organization(s, "Unpublished", publish=False)
    assert s.player.get(f"/campaigns/{s.cid}/organizations/{draft}/members").status_code == 404
    assert s.gm.get(f"/campaigns/{s.cid}/organizations/{draft}/members").status_code == 200
    assert s.gm.get(f"/campaigns/{s.cid}/organizations/{uuid.uuid4()}/members").status_code == 404
    mira = npc(s, "Mira")
    assert s.gm.get(f"/campaigns/{s.cid}/organizations/{mira}/members").status_code == 404


def status(
    s: ContentSetup, org: str, new: str, expected: str | None, time_id: str, **extra: object
):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/organizations/{org}/status",
        {"world_time_id": time_id, "new_status_code": new, "expected_status": expected, **extra},
        key=s.gm.fresh_key(),
    )


def test_organization_status_is_hardened(s: ContentSetup) -> None:
    guild = organization(s, "The Guild")
    times = Times(s)
    year1 = times.at(1)
    assert _advance(s, year1, 0).status_code == 200
    first = status(s, guild, "dormant", None, year1)
    assert first.status_code == 200, first.text
    assert members(s, guild)["status"] == "dormant"
    stale = status(s, guild, "banned", None, year1)
    assert stale.status_code == 409 and code(stale) == "stale_write"
    same = status(s, guild, "dormant", "dormant", year1)
    assert same.status_code == 409 and code(same) == "organization_status_unchanged"
    moved = status(s, guild, "banned", "dormant", year1)
    assert moved.status_code == 200 and members(s, guild)["status"] == "banned"
    # An adapter that does not name the status it saw keeps working, but may not repeat one.
    legacy = s.gm.post_raw(
        f"/campaigns/{s.cid}/organizations/{guild}/status",
        {"world_time_id": year1, "new_status_code": "underground"},
        key=s.gm.fresh_key(),
    )
    assert legacy.status_code == 200
    again = s.gm.post_raw(
        f"/campaigns/{s.cid}/organizations/{guild}/status",
        {"world_time_id": year1, "new_status_code": "underground"},
        key=s.gm.fresh_key(),
    )
    assert again.status_code == 409 and code(again) == "organization_status_unchanged"


def test_an_organization_status_change_can_be_corrected(s: ContentSetup) -> None:
    guild = organization(s, "The Guild")
    year1 = Times(s).at(1)
    assert _advance(s, year1, 0).status_code == 200
    first = status(s, guild, "dormant", None, year1).json()
    second = status(s, guild, "banned", "dormant", year1).json()
    refused = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{first['event_id']}/void",
        {"reason": "Wrong"},
        key=s.gm.fresh_key(),
    )
    assert refused.status_code == 409 and code(refused) == "correction_not_reversible"
    undone = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{second['event_id']}/void",
        {"reason": "Not banned"},
        key=s.gm.fresh_key(),
    )
    assert undone.status_code == 200, undone.text
    assert members(s, guild)["status"] == "dormant"
    first_undone = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{first['event_id']}/void",
        {"reason": "Never happened"},
        key=s.gm.fresh_key(),
    )
    assert first_undone.status_code == 409  # the restoring event now wrote the row


def test_authority_and_replay(s: ContentSetup) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    start = Times(s).at(1)
    body = {
        "kind": "membership",
        "relationship_type": "membership",
        "participants": [
            {"entity_id": mira, "role": "member"},
            {"entity_id": guild, "role": "organization"},
        ],
        "started_world_time_id": start,
    }
    assert s.player.post(s.url("relationships"), body, key=s.player.fresh_key()).status_code == 403
    key = s.gm.fresh_key()
    first = s.gm.post(s.url("relationships"), body, key=key)
    replay = s.gm.post(s.url("relationships"), body, key=key)
    assert first.status_code == replay.status_code == 201 and first.json() == replay.json()
    assert s.count("world.organization_memberships") == 1
    row = s.connection.execute(
        text("SELECT upper_inf(membership_period) AS open FROM world.organization_memberships")
    ).one()
    assert row.open is True
