"""World relationship authoring (checkpoint 15.3A-2a, decision D-18, ADR 0017, migration 129)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.data_classification import replay_body
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


def npc(s: ContentSetup, name: str, *, publish: bool = True) -> str:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("npcs"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    if publish:
        s.publish(created["npc_id"], created["row_version"])
    return str(created["npc_id"])


def place(s: ContentSetup, name: str, category: str = "settlement", *, publish: bool = True) -> str:
    created = s.gm.post(
        s.url("locations"), {"category": category, "name": name}, key=s.gm.fresh_key()
    ).json()
    if publish:
        s.publish(created["location_id"], created["row_version"])
    return str(created["location_id"])


def organization(s: ContentSetup, name: str) -> str:
    created = s.gm.post(
        s.url("organizations"),
        {"kind": "organization", "organization_type": "guild", "name": name},
        key=s.gm.fresh_key(),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    entity = body.get("organization_id") or body.get("entity_id")
    s.publish(entity, body["row_version"])
    return str(entity)


def time_at(s: ContentSetup, year: int, times: Times | None = None) -> str:
    return (times or Times(s)).at(year)


def create(s: ContentSetup, kind: str, relationship_type: str, participants: list, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post(
        s.url("relationships"),
        {
            "kind": kind,
            "relationship_type": relationship_type,
            "participants": [{"entity_id": e, "role": r} for e, r in participants],
            **extra,
        },
        key=s.gm.fresh_key(),
    )


def view(s: ContentSetup, relationship_id: str, who: object = None) -> dict:
    actor = who or s.gm
    response = actor.get(s.url(f"relationships/{relationship_id}"))  # type: ignore[attr-defined]
    assert response.status_code == 200, response.text
    return response.json()


def act(s: ContentSetup, relationship: dict, action: str, body: dict | None = None):  # type: ignore[no-untyped-def]
    current = view(s, relationship["relationship_id"])
    return s.gm.post(
        s.url(f"relationships/{relationship['relationship_id']}/{action}"),
        {"expected_row_version": current["row_version"], **(body or {})},
        key=s.gm.fresh_key(),
    )


def test_each_kind_is_created_with_its_participants_and_typed_fields(s: ContentSetup) -> None:
    mira, tom, ann = npc(s, "Mira"), npc(s, "Tom"), npc(s, "Ann")
    guild = organization(s, "The Guild")
    year1 = time_at(s, 1)

    family = create(
        s,
        "family",
        "family",
        [(mira, "parent"), (tom, "child"), (ann, "child")],
        family_unit_name="House Vale",
        description="A close family.",
    )
    assert family.status_code == 201, family.text
    assert family.json()["typed"] == {"family_unit_name": "House Vale"}
    assert {p["role"] for p in family.json()["participants"]} == {"parent", "child"}

    job = create(
        s,
        "employment",
        "employment",
        [(guild, "employer"), (mira, "employee")],
        job_title="Quartermaster",
        started_world_time_id=year1,
    )
    assert job.status_code == 201, job.text
    assert job.json()["typed"] == {"job_title": "Quartermaster"}
    assert job.json()["started_world_time_id"] == year1

    stake = create(
        s,
        "ownership",
        "ownership",
        [(tom, "owner"), (guild, "property")],
        ownership_share=40,
        is_public=False,
    )
    assert stake.status_code == 201 and stake.json()["typed"]["is_public"] is False

    pact = create(
        s,
        "political",
        "alliance",
        [(guild, "ally"), (place(s, "Stonebridge"), "ally")],
        treaty_terms="Mutual defence.",
    )
    assert pact.status_code == 201 and pact.json()["typed"]["is_active"] is True

    plain = create(
        s, "general", "worship", [(mira, "subject"), (place(s, "Shrine", "building"), "object")]
    )
    assert plain.status_code == 201 and plain.json()["typed"] == {}
    [audit] = s.audit("create_relationship")[:1]
    assert audit.action == "created" and audit.entity_id is None
    assert "close family" not in str(audit.changed_fields)


def test_invalid_shapes_are_refused_and_nothing_is_written(s: ContentSetup) -> None:
    mira, tom = npc(s, "Mira"), npc(s, "Tom")
    draft = npc(s, "Unpublished", publish=False)
    before = s.count("world.relationships")
    cases = [
        create(s, "family", "alliance", [(mira, "parent"), (tom, "child")]),  # wrong type
        create(s, "family", "family", [(mira, "owner"), (tom, "child")]),  # wrong role
        create(s, "family", "family", [(mira, "parent")]),  # too few
        create(s, "employment", "employment", [(mira, "employer"), (mira, "employee")]),
        create(s, "employment", "employment", [(mira, "employer"), (tom, "employer")]),
        create(s, "mystery", "family", [(mira, "parent"), (tom, "child")]),
        create(s, "family", "family", [(mira, "parent"), (mira, "parent")]),
    ]
    for response in cases:
        assert response.status_code in (400, 422), response.text
    bad = create(s, "family", "family", [(mira, "parent"), (str(uuid.uuid4()), "child")])
    assert bad.status_code == 400 and code(bad) == "participant_invalid"
    non_entity = create(
        s, "family", "family", [(mira, "parent"), (tom, "child")], ownership_share=5
    )
    assert non_entity.status_code == 400 and code(non_entity) == "relationship_invalid"
    assert (
        create(
            s, "ownership", "ownership", [(mira, "owner"), (tom, "property")], ownership_share=101
        ).status_code
        == 422
    )
    foreign_time = create(
        s,
        "family",
        "family",
        [(mira, "parent"), (tom, "child")],
        started_world_time_id=str(uuid.uuid4()),
    )
    assert foreign_time.status_code == 400 and code(foreign_time) == "relationship_time_invalid"
    # A draft participant is allowed: the edge simply stays unseen until it is published.
    with_draft = create(s, "family", "family", [(mira, "parent"), (draft, "child")])
    assert with_draft.status_code == 201
    assert s.count("world.relationships") == before + 1


def test_update_changes_only_what_may_change_and_uses_the_version(s: ContentSetup) -> None:
    mira, tom = npc(s, "Mira"), npc(s, "Tom")
    created = create(
        s, "family", "family", [(mira, "parent"), (tom, "child")], family_unit_name="Old"
    ).json()
    updated = act(
        s, created, "update", {"description": "Now described.", "family_unit_name": "House New"}
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (
        body["description"] == "Now described." and body["typed"]["family_unit_name"] == "House New"
    )
    assert body["row_version"] == created["row_version"] + 1
    assert [p["entity_id"] for p in body["participants"]] == [
        p["entity_id"] for p in created["participants"]
    ]
    stale = s.gm.post(
        s.url(f"relationships/{created['relationship_id']}/update"),
        {"expected_row_version": created["row_version"], "description": "Late"},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and code(stale) == "stale_write"
    same = act(
        s, body, "update", {"description": "Now described.", "family_unit_name": "House New"}
    )
    assert same.status_code == 200 and same.json()["changed"] is False
    wrong = act(s, body, "update", {"job_title": "Cook"})
    assert wrong.status_code == 400 and code(wrong) == "relationship_invalid"
    forbidden = s.gm.post(
        s.url(f"relationships/{created['relationship_id']}/update"),
        {"expected_row_version": body["row_version"], "relationship_type": "war"},
        key=s.gm.fresh_key(),
    )
    assert forbidden.status_code == 422  # the type and participants are not editable
    assert "described" not in str(s.audit("update_relationship")[0].changed_fields)


def test_a_relationship_ends_once_and_only_after_it_started(s: ContentSetup) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    times = Times(s)
    year1, year5, year0 = times.at(1), times.at(5), times.at(0)
    job = create(
        s, "employment", "employment", [(guild, "employer"), (mira, "employee")], job_title="Cook"
    ).json()
    no_start = act(s, job, "end", {"ended_world_time_id": year5})
    assert no_start.status_code == 409 and code(no_start) == "relationship_start_required"
    started = act(s, job, "update", {"started_world_time_id": year1, "job_title": "Cook"}).json()
    early = act(s, started, "end", {"ended_world_time_id": year0})
    assert early.status_code == 400 and code(early) == "relationship_time_invalid"
    ended = act(s, started, "end", {"ended_world_time_id": year5})
    assert ended.status_code == 200 and ended.json()["ended_world_time_id"] == year5
    assert "end" not in ended.json()["available_actions"]
    again = act(s, ended.json(), "end", {"ended_world_time_id": year5})
    assert again.status_code == 409 and code(again) == "relationship_already_ended"
    effective_to = s.connection.execute(
        text(
            "SELECT effective_to_world_time_id FROM world.employment_relationships "
            "WHERE relationship_id = :r"
        ),
        {"r": job["relationship_id"]},
    ).scalar()
    assert str(effective_to) == year5


def test_a_political_relationship_becomes_inactive_when_it_ends(s: ContentSetup) -> None:
    guild, town = organization(s, "The Guild"), place(s, "Stonebridge")
    times = Times(s)
    pact = create(
        s,
        "political",
        "alliance",
        [(guild, "ally"), (town, "ally")],
        started_world_time_id=times.at(1),
    ).json()
    ended = act(s, pact, "end", {"ended_world_time_id": times.at(3)})
    assert ended.status_code == 200 and ended.json()["typed"]["is_active"] is False


def test_archive_hides_from_readers_and_restore_brings_it_back(s: ContentSetup) -> None:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    created = create(
        s, "general", "adjacency", [(north, "subject"), (south, "object")], description="Kin"
    ).json()
    rid = created["relationship_id"]
    listing = s.player.get(f"/campaigns/{s.cid}/world/relationships")
    assert [i["relationship_id"] for i in listing.json()["items"]] == [rid]
    assert s.player.get(f"/campaigns/{s.cid}/relationships/{rid}").status_code == 200
    archived = act(s, created, "archive")
    assert archived.status_code == 200 and archived.json()["lifecycle_status"] == "archived"
    assert archived.json()["available_actions"] == ["restore"]
    assert s.player.get(f"/campaigns/{s.cid}/world/relationships").json()["items"] == []
    assert s.player.get(f"/campaigns/{s.cid}/relationships/{rid}").status_code == 404
    assert s.gm.get(f"/campaigns/{s.cid}/relationships/{rid}").status_code == 200
    refused = act(s, archived.json(), "update", {"description": "x"})
    assert refused.status_code == 409 and code(refused) == "relationship_archived"
    again = act(s, archived.json(), "archive")
    assert again.status_code == 409 and code(again) == "relationship_archived"
    restored = act(s, archived.json(), "restore")
    assert restored.status_code == 200 and restored.json()["lifecycle_status"] == "active"
    assert s.player.get(f"/campaigns/{s.cid}/relationships/{rid}").status_code == 200
    not_archived = act(s, restored.json(), "restore")
    assert not_archived.status_code == 409 and code(not_archived) == "relationship_not_archived"


def test_a_private_ownership_edge_is_hidden_from_readers_only(s: ContentSetup) -> None:
    tom, guild = organization(s, "The Bank"), organization(s, "The Guild")
    secret = create(
        s, "ownership", "ownership", [(tom, "owner"), (guild, "property")], is_public=False
    ).json()
    public = create(
        s, "ownership", "ownership", [(tom, "owner"), (guild, "property")], is_public=True
    ).json()
    ids = {
        i["relationship_id"]
        for i in s.player.get(f"/campaigns/{s.cid}/world/relationships").json()["items"]
    }
    assert ids == {public["relationship_id"]}
    assert (
        s.player.get(f"/campaigns/{s.cid}/relationships/{secret['relationship_id']}").status_code
        == 404
    )
    gm_ids = {
        i["relationship_id"]
        for i in s.gm.get(f"/campaigns/{s.cid}/world/relationships").json()["items"]
    }
    assert gm_ids == {secret["relationship_id"], public["relationship_id"]}


def test_an_edge_to_an_unpublished_participant_is_hidden_until_it_is_published(
    s: ContentSetup,
) -> None:
    mira = place(s, "Stonebridge")
    hidden = place(s, "Hidden Keep", publish=False)
    edge = create(s, "general", "other", [(mira, "subject"), (hidden, "object")]).json()
    assert s.player.get(f"/campaigns/{s.cid}/world/relationships").json()["items"] == []
    assert (
        s.player.get(f"/campaigns/{s.cid}/relationships/{edge['relationship_id']}").status_code
        == 404
    )
    row = s.gm.get(s.url(f"locations/{hidden}")).json()
    s.publish(hidden, row["row_version"])
    assert len(s.player.get(f"/campaigns/{s.cid}/world/relationships").json()["items"]) == 1


def test_perspectives_belong_to_participants_and_are_gm_only(s: ContentSetup) -> None:
    mira, tom, ann = npc(s, "Mira"), npc(s, "Tom"), npc(s, "Ann")
    created = create(s, "family", "family", [(mira, "parent"), (tom, "child")]).json()
    set_one = act(
        s,
        created,
        "perspectives",
        {
            "holder_entity_id": mira,
            "affinity": 70,
            "trust": 50,
            "emotional_tone": "Proud",
            "private_interpretation": "Hides her worry.",
        },
    )
    assert set_one.status_code == 200, set_one.text
    [perspective] = set_one.json()["perspectives"]
    assert perspective["holder_name"] == "Mira" and perspective["affinity"] == 70
    revised = act(s, set_one.json(), "perspectives", {"holder_entity_id": mira, "affinity": 20})
    assert revised.status_code == 200 and revised.json()["perspectives"][0]["affinity"] == 20
    assert revised.json()["perspectives"][0]["emotional_tone"] is None  # a full replacement
    stranger = act(s, revised.json(), "perspectives", {"holder_entity_id": ann, "affinity": 1})
    assert stranger.status_code == 400 and code(stranger) == "perspective_holder_invalid"
    too_big = act(s, revised.json(), "perspectives", {"holder_entity_id": mira, "trust": 101})
    assert too_big.status_code == 422
    audit = s.audit("set_relationship_perspective")
    assert [a.action for a in audit] == ["created", "updated"]
    assert "worry" not in str([a.changed_fields for a in audit])


def test_archived_relationships_refuse_state_changes(s: ContentSetup) -> None:
    mira, tom = npc(s, "Mira"), npc(s, "Tom")
    created = create(s, "family", "family", [(mira, "parent"), (tom, "child")]).json()
    clock = Times(s).at(1)
    assert _advance(s, clock, 0).status_code == 200
    archived = act(s, created, "archive").json()
    refused = s.gm.post_raw(
        f"/campaigns/{s.cid}/relationships/{archived['relationship_id']}/evolve",
        {"world_time_id": clock, "new_status_code": "strained"},
        key=s.gm.fresh_key(),
    )
    assert refused.status_code == 409 and code(refused) == "relationship_archived"


def test_the_entity_list_includes_private_and_archived_for_editors(s: ContentSetup) -> None:
    mira, tom = npc(s, "Mira"), npc(s, "Tom")
    first = create(s, "family", "family", [(mira, "parent"), (tom, "child")]).json()
    second = create(s, "general", "other", [(mira, "subject"), (tom, "object")]).json()
    act(s, second, "archive")
    visible = s.gm.get(s.url("relationships"), entity_id=mira).json()["items"]
    assert [i["relationship_id"] for i in visible] == [first["relationship_id"]]
    everything = s.gm.get(s.url("relationships"), entity_id=mira, include_archived="true").json()[
        "items"
    ]
    assert {i["relationship_id"] for i in everything} == {
        first["relationship_id"],
        second["relationship_id"],
    }
    assert s.player.get(s.url("relationships"), entity_id=mira).status_code == 403


def test_authority_replay_and_other_worlds(s: ContentSetup) -> None:
    mira, tom = npc(s, "Mira"), npc(s, "Tom")
    denied = s.player.post(
        s.url("relationships"),
        {
            "kind": "family",
            "relationship_type": "family",
            "participants": [
                {"entity_id": mira, "role": "parent"},
                {"entity_id": tom, "role": "child"},
            ],
        },
        key=s.player.fresh_key(),
    )
    assert denied.status_code == 403
    key = s.gm.fresh_key()
    body = {
        "kind": "family",
        "relationship_type": "family",
        "participants": [
            {"entity_id": mira, "role": "parent"},
            {"entity_id": tom, "role": "child"},
        ],
    }
    first = s.gm.post(s.url("relationships"), body, key=key)
    replay = s.gm.post(s.url("relationships"), body, key=key)
    assert first.status_code == replay.status_code == 201 and replay.json() == replay_body(
        first.json()
    )
    assert len(s.audit("create_relationship")) == 1
    stranger_npc = npc(s, "Elsewhere")
    foreign = s.stranger.post(
        s.url("relationships", s.other_cid),
        {
            "kind": "family",
            "relationship_type": "family",
            "participants": [
                {"entity_id": mira, "role": "parent"},
                {"entity_id": stranger_npc, "role": "child"},
            ],
        },
        key=s.stranger.fresh_key(),
    )
    assert foreign.status_code == 400 and code(foreign) == "participant_invalid"
    assert (
        s.stranger.get(
            s.url(f"relationships/{first.json()['relationship_id']}", s.other_cid)
        ).status_code
        == 404
    )


# --- Participant compatibility (policy in domain/relationship_authoring.py) -------------------


def pc(s: ContentSetup, name: str) -> str:
    species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    response = s.gm.post(
        s.url("player-characters"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["player_character_id"])


def religion(s: ContentSetup, name: str) -> str:
    response = s.gm.post(
        s.url("religions"),
        {"name": name, "summary": None, "pantheon_structure": "One"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["religion_id"])


def world_search(s: ContentSetup, actor: object = None, **params: object):  # type: ignore[no-untyped-def]
    return (actor or s.gm).get(f"/campaigns/{s.cid}/world/search", **params)  # type: ignore[attr-defined]


_PERSON_SIDES = {
    "ownership": ("ownership", "ownership", "owner", "property"),
    "control": ("political", "control", "ruler", "object"),
    "worship": ("general", "worship", "subject", "object"),
}


def test_characters_take_either_side_of_ownership_control_and_worship(s: ContentSetup) -> None:
    people = {
        "npc-a": npc(s, "Alder"),
        "npc-b": npc(s, "Birch"),
        "pc-a": pc(s, "Cedar"),
        "pc-b": pc(s, "Dogwood"),
    }
    pairs = [("npc-a", "npc-b"), ("npc-a", "pc-a"), ("pc-a", "npc-a"), ("pc-a", "pc-b")]
    for kind, relationship_type, first_role, second_role in _PERSON_SIDES.values():
        for first, second in pairs:
            # Both directions, whichever record the form was opened on.
            for left, right in ((first, second), (second, first)):
                response = create(
                    s,
                    kind,
                    relationship_type,
                    [(people[left], first_role), (people[right], second_role)],
                )
                assert response.status_code == 201, (relationship_type, left, right, response.text)


def test_fictional_ownership_control_and_worship_grant_nothing(s: ContentSetup) -> None:
    owner, owned = pc(s, "Cedar"), npc(s, "Alder")
    tables = (
        "security.membership_character_relationships",
        "narrative.events",
        "campaign.relationship_state",
    )
    before = {t: s.count(t) for t in tables}
    for kind, relationship_type, first_role, second_role in _PERSON_SIDES.values():
        response = create(s, kind, relationship_type, [(owner, first_role), (owned, second_role)])
        assert response.status_code == 201, response.text
    assert {t: s.count(t) for t in tables} == before
    # A player with no character access still cannot read the editor's relationships.
    assert s.player.get(s.url("relationships"), entity_id=owned).status_code == 403


def test_incompatible_participants_are_refused_and_nothing_is_written(s: ContentSetup) -> None:
    mira, tom = npc(s, "Mira"), npc(s, "Tom")
    town, other_town = place(s, "Highmarch"), place(s, "Lowmarch")
    nation = place(s, "Vell", "nation")
    faith = religion(s, "The Light")
    before = s.count("world.relationships")
    incompatible = [
        # An NPC cannot be the capital or the governed place, adjoin, or be a parent.
        create(s, "general", "capital_of", [(mira, "subject"), (nation, "object")]),
        create(s, "general", "capital_of", [(town, "subject"), (mira, "object")]),
        create(s, "general", "adjacency", [(mira, "subject"), (tom, "object")]),
        create(s, "general", "parent_of", [(mira, "subject"), (tom, "object")]),
        # A nation is not a capital; a settlement is not a governed place.
        create(s, "general", "capital_of", [(nation, "subject"), (town, "object")]),
        create(s, "general", "capital_of", [(town, "subject"), (other_town, "object")]),
        # Both sides of parent_of are the same kind of record.
        create(s, "general", "parent_of", [(town, "subject"), (faith, "object")]),
        # A religion is not an employee; a place is not a family member.
        create(s, "employment", "employment", [(mira, "employer"), (faith, "employee")]),
        create(s, "family", "family", [(mira, "parent"), (town, "child")]),
        # A route keeps its original refusal.
        create(s, "route", "route", [(mira, "origin"), (town, "destination")]),
    ]
    for response in incompatible:
        assert response.status_code == 400, response.text
        assert code(response) in ("participant_incompatible", "participant_invalid"), response.text
    assert code(incompatible[0]) == "participant_incompatible"
    assert code(incompatible[-1]) == "participant_invalid"
    # A role that is not the type's, and missing required roles, are shape errors.
    wrong_role = create(s, "political", "alliance", [(town, "ruler"), (other_town, "territory")])
    assert wrong_role.status_code == 400 and code(wrong_role) == "relationship_invalid"
    no_object = create(s, "political", "war", [(town, "subject"), (other_town, "subject")])
    assert no_object.status_code == 400 and code(no_object) == "relationship_invalid"
    two_capitals = create(s, "general", "capital_of", [(town, "subject"), (other_town, "subject")])
    assert two_capitals.status_code == 400 and code(two_capitals) == "relationship_invalid"
    assert s.count("world.relationships") == before
    # A participant that does not exist is still indistinguishable from an unusable one.
    ghost = create(s, "general", "capital_of", [(town, "subject"), (str(uuid.uuid4()), "object")])
    assert ghost.status_code == 400 and code(ghost) == "participant_invalid"
    # The compatible shapes work, in either participant order.
    for participants in (
        [(town, "subject"), (nation, "object")],
        [(nation, "object"), (town, "subject")],
    ):
        assert create(s, "general", "capital_of", participants).status_code == 201
    assert (
        create(s, "general", "adjacency", [(town, "object"), (other_town, "subject")]).status_code
        == 201
    )


def test_an_inactive_type_is_not_offered_or_created_but_existing_records_stay_usable(
    s: ContentSetup, db_connection: Connection
) -> None:
    mira, tom = npc(s, "Mira"), npc(s, "Tom")
    existing = create(s, "general", "worship", [(mira, "subject"), (tom, "object")]).json()
    db_connection.execute(
        text("UPDATE world.relationship_types SET is_active = false WHERE code = 'worship'")
    )
    offered = s.gm.get(s.url("relationships/options"), entity_id=mira).json()
    assert "worship" not in {t["code"] for t in offered["relationship_types"]}
    assert "worship" not in {p["relationship_type"] for p in offered["for_entity"]["pairings"]}
    refused = create(s, "general", "worship", [(mira, "subject"), (tom, "object")])
    assert refused.status_code == 400 and code(refused) == "relationship_invalid"
    current = view(s, existing["relationship_id"])
    assert current["policy_conflicts"] == ["This type of relationship is no longer offered."]
    assert act(s, existing, "update", {"description": "Still correctable"}).status_code == 200


def test_existing_incompatible_records_stay_readable_and_correctable(
    s: ContentSetup, db_connection: Connection
) -> None:
    from tests.factories import make_relationship

    mira, town = npc(s, "Mira"), place(s, "Highmarch")
    relationship_id = make_relationship(
        db_connection, uuid.UUID(str(s.world_id)), relationship_type_code="capital_of"
    )
    for entity, role in ((mira, "subject"), (town, "object")):
        db_connection.execute(
            text("""
                INSERT INTO world.relationship_participants
                    (relationship_id, entity_id, participant_role_id)
                VALUES (:r, :e, (SELECT relationship_participant_role_id
                                 FROM world.relationship_participant_roles WHERE code = :role))
            """),
            {"r": relationship_id, "e": entity, "role": role},
        )
    current = view(s, str(relationship_id))
    assert any("Mira" in reason and "capital" in reason for reason in current["policy_conflicts"])
    listed = s.gm.get(s.url("relationships"), entity_id=mira).json()["items"]
    assert listed[0]["policy_conflicts"] == current["policy_conflicts"]
    # A compatible relationship reports no conflicts.
    fine = create(s, "general", "worship", [(mira, "subject"), (town, "object")]).json()
    assert fine["policy_conflicts"] == []
    # Correct, archive, restore and end all still work on the incompatible record.
    updated = act(s, current, "update", {"description": "Corrected"})
    assert updated.status_code == 200, updated.text
    archived = act(s, updated.json(), "archive")
    assert archived.status_code == 200, archived.text
    restored = act(s, archived.json(), "restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["policy_conflicts"] == current["policy_conflicts"]
    times = Times(s)
    started = act(s, restored.json(), "update", {"started_world_time_id": times.at(1)})
    assert started.status_code == 200, started.text
    ended = act(s, started.json(), "end", {"ended_world_time_id": times.at(2)})
    assert ended.status_code == 200, ended.text


def test_options_are_scoped_to_the_entity(s: ContentSetup) -> None:
    mira, town, nation = npc(s, "Mira"), place(s, "Highmarch"), place(s, "Vell", "nation")

    def pairings(entity: str, type_code: str) -> set[tuple[str, str]]:
        response = s.gm.get(s.url("relationships/options"), entity_id=entity)
        assert response.status_code == 200, response.text
        return {
            (p["my_role"], p["other_role"])
            for p in response.json()["for_entity"]["pairings"]
            if p["relationship_type"] == type_code
        }

    person = {
        p["relationship_type"]
        for p in s.gm.get(s.url("relationships/options"), entity_id=mira).json()["for_entity"][
            "pairings"
        ]
    }
    assert person >= {"family", "ownership", "control", "worship", "alliance", "other"}
    assert not person & {"adjacency", "capital_of", "parent_of", "route"}
    assert pairings(town, "capital_of") == {("subject", "object")}
    assert pairings(nation, "capital_of") == {("object", "subject")}
    assert pairings(mira, "control") == {
        ("ruler", "object"),
        ("ruler", "territory"),
        ("object", "ruler"),
    }
    # The portal's fixture is the metadata this endpoint serves.
    from tests.unit.relationship_policy_fixture import build

    served = s.gm.get(s.url("relationships/options"), entity_id=mira).json()
    assert served["relationship_types"] == build()["relationship_types"]
    assert served["for_entity"]["pairings"] == build()["pairings"]["npc"]
    # Without an entity the catalog is unchanged and nothing entity-specific is returned.
    plain = s.gm.get(s.url("relationships/options")).json()
    assert "for_entity" not in plain and plain["kinds"]
    assert {t["code"] for t in plain["relationship_types"]} >= {"capital_of", "worship"}
    # Missing and other-world entities are the same 404; a non-editor is refused as before.
    assert s.gm.get(s.url("relationships/options"), entity_id=str(uuid.uuid4())).status_code == 404
    foreign = s.stranger.get(s.url("relationships/options", s.other_cid), entity_id=mira)
    assert foreign.status_code == 404
    assert s.player.get(s.url("relationships/options"), entity_id=mira).status_code == 403


def test_world_search_entity_type_filter(s: ContentSetup) -> None:
    for index in range(3):
        place(s, f"A building {index}", "building")
    first = place(s, "Zed", "settlement")
    draft = place(s, "Zed draft", "settlement", publish=False)
    page = world_search(s, category="location", entity_type="settlement", limit=1)
    assert page.status_code == 200, page.text
    assert [i["entity_id"] for i in page.json()["items"]] == [first]
    assert page.json()["next_cursor"] is None
    two = world_search(s, category="location", entity_type=["settlement", "building"], limit=50)
    assert {i["entity_type_code"] for i in two.json()["items"]} == {"settlement", "building"}
    assert world_search(s, category="location", entity_type="npc").status_code == 422
    assert world_search(s, entity_type="npc").status_code == 200
    seen = world_search(s, s.player, category="location", entity_type="settlement")
    assert seen.status_code == 200
    assert draft not in {i["entity_id"] for i in seen.json()["items"]}
