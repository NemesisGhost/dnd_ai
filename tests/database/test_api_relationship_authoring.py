"""World relationship authoring (checkpoint 15.3A-2a, decision D-18, ADR 0017, migration 129)."""

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
    assert first.status_code == replay.status_code == 201 and first.json() == replay.json()
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
