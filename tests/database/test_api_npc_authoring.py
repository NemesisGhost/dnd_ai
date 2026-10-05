"""HTTP contract and command behavior for NPC identity authoring (Phase 15.1)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import (
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_relationship_type_capability,
    make_ruleset_version,
    make_species,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def species(s: ContentSetup, code: str = "human") -> str:
    options = s.gm.get(s.url("npcs/options")).json()
    return next(o["species_id"] for o in options["species"] if o["name"].lower() == code)


def create(s: ContentSetup, name: str = "Mira", **extra: object) -> dict:
    body: dict[str, object] = {
        "name": name,
        "species_id": species(s),
        "size_category": "medium",
        **extra,
    }
    response = s.gm.post(s.url("npcs"), body, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def update(s: ContentSetup, npc: dict, **fields: object) -> object:
    body: dict[str, object] = {
        "expected_row_version": npc["row_version"],
        "name": npc["name"],
        "summary": npc["summary"],
        "species_id": npc["species"]["species_id"],
        "size_category": npc["size"]["code"],
        "origin_location_id": npc["origin"] and npc["origin"]["entity_id"],
        "background": npc["background"],
        "appearance": npc["appearance"],
        "notes": npc["notes"],
        **fields,
    }
    return s.gm.post(s.url(f"npcs/{npc['npc_id']}/update"), body, key=s.gm.fresh_key())


def location(s: ContentSetup, name: str = "Hearth") -> dict:
    response = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": name}, key=s.gm.fresh_key()
    )
    assert response.status_code == 201
    return response.json()


# --- options ----------------------------------------------------------------------------------


def test_options_offer_only_canon_species_of_the_worlds_rulesets_and_the_closed_sizes(
    s: ContentSetup,
) -> None:
    foreign_version = make_ruleset_version(s.connection)
    make_species(s.connection, foreign_version, code="alien")
    body = s.gm.get(s.url("npcs/options")).json()
    names = {o["name"].lower() for o in body["species"]}
    assert {"human", "elf"} <= names and "alien" not in names
    assert [z["code"] for z in body["sizes"]] == [
        "tiny",
        "small",
        "medium",
        "large",
        "huge",
        "gargantuan",
    ]
    assert body["can_create"] is True and body["limits"]["text_max_length"] == 4000


# --- create -----------------------------------------------------------------------------------


def test_create_makes_a_complete_draft_npc_with_provenance_and_one_audit_row(
    s: ContentSetup,
) -> None:
    place = location(s)
    view = create(
        s,
        "Mira",
        summary="A baker.",
        origin_location_id=place["location_id"],
        background="Raised in the hills.",
        appearance="Tall, flour-dusted.",
        notes="GM: secretly a spy.",
    )
    assert (view["canon_status"], view["lifecycle_status"], view["changed"]) == (
        "draft",
        "active",
        True,
    )
    assert view["species"]["name"].lower() == "human" and view["size"] == {
        "code": "medium",
        "label": "Medium",
    }
    assert view["origin"]["name"] == "Hearth" and view["notes"] == "GM: secretly a spy."
    row = s.connection.execute(
        text("""
            SELECT et.code, e.created_by_user_id, st.code AS source_type,
                   (SELECT count(*) FROM character.npcs WHERE npc_id = e.entity_id) AS npcs,
                   (SELECT count(*) FROM character.characters WHERE character_id = e.entity_id) AS chars,
                   (SELECT count(*) FROM character.character_descriptions
                    WHERE character_id = e.entity_id) AS descriptions,
                   (SELECT count(*) FROM character.player_characters
                    WHERE player_character_id = e.entity_id) AS pcs
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.sources src ON src.source_id = e.source_id
            JOIN core.source_types st ON st.source_type_id = src.source_type_id
            WHERE e.entity_id = :e
        """),
        {"e": view["npc_id"]},
    ).one()
    assert (row.code, row.source_type, row.npcs, row.chars, row.descriptions, row.pcs) == (
        "npc",
        "gm_entry",
        1,
        1,
        1,
        0,
    )
    assert row.created_by_user_id == s.gm.user_id
    audit = s.audit("create_npc")
    assert len(audit) == 1 and audit[0].action == "created"
    assert audit[0].changed_fields["size_category"] == "medium"


def test_create_writes_no_state_events_or_assignments(s: ContentSetup) -> None:
    tables = (
        "campaign.character_state",
        "narrative.events",
        "campaign.character_location_history",
        "security.membership_character_relationships",
    )
    before = {t: s.count(t) for t in tables}
    create(s, "Quiet")
    assert before == {t: s.count(t) for t in tables}


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "x" * 201},
        {"size_category": "colossal"},
        {"size_category": "Medium"},
        {"size_category": ""},
        {"background": "x" * 4001},
        {"notes": "x" * 4001},
        {"world_id": str(uuid.uuid4())},
        {"entity_type_code": "player_character"},
        {"player_user_id": str(uuid.uuid4())},
    ],
)
def test_invalid_bodies_are_refused_and_write_nothing(s: ContentSetup, body: dict) -> None:
    before = s.count("core.entities")
    full = {"name": "Mira", "species_id": species(s), "size_category": "medium", **body}
    response = s.gm.post(s.url("npcs"), full, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)
    assert s.count("core.entities") == before


def test_species_must_be_canon_and_from_an_allowed_ruleset(s: ContentSetup) -> None:
    foreign_version = make_ruleset_version(s.connection)
    foreign = make_species(s.connection, foreign_version, code="alien")
    draft_species = species(s, "elf")
    s.connection.execute(
        text(
            "UPDATE rules.species SET canon_status_id = "
            "(SELECT canon_status_id FROM core.canon_statuses WHERE code = 'draft') "
            "WHERE species_id = :s"
        ),
        {"s": draft_species},
    )
    seen = set()
    for candidate in (str(foreign), draft_species, str(uuid.uuid4())):
        response = s.gm.post(
            s.url("npcs"),
            {"name": "x", "species_id": candidate, "size_category": "medium"},
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 400
        seen.add(response.json()["error"]["code"])
    assert seen == {"species_not_available"}


def test_origin_references_share_one_code(s: ContentSetup) -> None:
    gone = location(s, "Gone")
    s.transition(gone["location_id"], "archive", gone["row_version"])
    foreign = s.stranger.post(
        s.url("locations", s.other_cid),
        {"category": "region", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    ).json()
    codes = set()
    for origin in (gone["location_id"], foreign["location_id"], str(uuid.uuid4())):
        response = s.gm.post(
            s.url("npcs"),
            {
                "name": "x",
                "species_id": species(s),
                "size_category": "medium",
                "origin_location_id": origin,
            },
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 400
        codes.add(response.json()["error"]["code"])
    assert codes == {"origin_location_invalid"}


def test_a_failure_after_the_character_row_leaves_nothing(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO character.character_descriptions" in str(statement):
            raise RuntimeError("injected failure before the descriptions row")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = (
        "core.entities",
        "core.sources",
        "character.characters",
        "character.npcs",
        "audit.change_log",
        "security.idempotent_requests",
    )
    before = {t: s.count(t) for t in tables}
    monkeypatch.setattr(Conn, "execute", failing)
    response = s.gm.post(
        s.url("npcs"),
        {"name": "Doomed", "species_id": species(s), "size_category": "small"},
        key=s.gm.fresh_key(),
    )
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}


# --- update ------------------------------------------------------------------------------------


def test_update_changes_identity_and_audits_a_bounded_diff(s: ContentSetup) -> None:
    npc = create(s, "Mira", notes="old note")
    place = location(s)
    view = update(
        s,
        npc,
        name="Mira Vale",
        species_id=species(s, "elf"),
        size_category="small",
        origin_location_id=place["location_id"],
        notes="new note",
    ).json()
    assert (view["name"], view["species"]["name"].lower(), view["size"]["code"]) == (
        "Mira Vale",
        "elf",
        "small",
    )
    assert view["origin"]["name"] == "Hearth" and view["notes"] == "new note"
    diff = s.audit("update_npc")[0].changed_fields
    assert diff["name"] == {"from": "Mira", "to": "Mira Vale"}
    assert diff["size_category"] == {"from": "medium", "to": "small"}
    assert diff["notes"] == {"from": "old note", "to": "new note"}


def test_no_op_stale_and_review_states(s: ContentSetup) -> None:
    npc = create(s, "Mira")
    again = update(s, npc).json()
    assert again["changed"] is False and again["row_version"] == npc["row_version"]
    assert s.audit("update_npc") == []
    assert update(s, npc, name="First").status_code == 200
    stale = update(s, npc, name="Second")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    s.set_status(npc["npc_id"], canon="approved")
    current = s.gm.get(s.url(f"npcs/{npc['npc_id']}")).json()
    locked = update(s, current, name="Third")
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "content_not_editable"


def test_descriptions_are_upserted_even_when_the_row_was_missing(s: ContentSetup) -> None:
    npc = create(s, "Mira")
    s.connection.execute(
        text("DELETE FROM character.character_descriptions WHERE character_id = :e"),
        {"e": npc["npc_id"]},
    )
    current = s.gm.get(s.url(f"npcs/{npc['npc_id']}")).json()
    assert update(s, current, background="Now written").json()["background"] == "Now written"


def test_a_player_character_or_bare_character_is_not_an_npc_route_target(s: ContentSetup) -> None:
    bare = make_character(s.connection, s.world_id, name="Bare")
    assert s.gm.get(s.url(f"npcs/{bare}")).status_code == 404
    body = {
        "expected_row_version": 1,
        "name": "x",
        "species_id": species(s),
        "size_category": "medium",
    }
    assert s.gm.post(s.url(f"npcs/{bare}/update"), body).status_code == 404


# --- lifecycle hooks ---------------------------------------------------------------------------------


def test_publishing_waits_for_a_published_origin(s: ContentSetup) -> None:
    place = location(s)
    npc = create(s, "Mira", origin_location_id=place["location_id"])
    version = npc["row_version"]
    for action in ("submit-for-review", "approve"):
        version = s.transition(npc["npc_id"], action, version)["row_version"]
    blocked = s.gm.post(
        s.lifecycle(npc["npc_id"], "/publish"),
        {"expected_row_version": version},
        key=s.gm.fresh_key(),
    )
    assert (
        blocked.status_code == 409 and blocked.json()["error"]["code"] == "reference_not_published"
    )
    view = s.gm.get(s.url(f"npcs/{npc['npc_id']}")).json()
    assert {"action": "publish", "reason": "reference_not_published"} in view["blocked_actions"]
    s.publish(place["location_id"], place["row_version"])
    assert s.transition(npc["npc_id"], "publish", version)["canon_status"] == "canon"


def test_an_npc_linked_to_a_user_cannot_be_archived(s: ContentSetup) -> None:
    npc = create(s, "Companion")
    membership = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": s.player.user_id},
    ).scalar()
    relationship = make_membership_character_relationship(
        s.connection,
        membership,
        uuid.UUID(npc["npc_id"]),
        make_character_relationship_type(s.connection),
    )
    view = s.gm.get(s.url(f"npcs/{npc['npc_id']}")).json()
    assert "archive" not in view["available_actions"]
    assert {"action": "archive", "reason": "character_has_user_relationships"} in view[
        "blocked_actions"
    ]
    lifecycle = s.gm.get(s.lifecycle(npc["npc_id"])).json()
    assert {"action": "archive", "reason": "character_has_user_relationships"} in lifecycle[
        "blocked_actions"
    ]
    refused = s.gm.post(
        s.lifecycle(npc["npc_id"], "/archive"),
        {"expected_row_version": view["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "character_has_user_relationships"

    s.connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship},
    )
    current = s.gm.get(s.url(f"npcs/{npc['npc_id']}")).json()
    assert (
        s.transition(npc["npc_id"], "archive", current["row_version"])["lifecycle_status"]
        == "archived"
    )


def test_a_draft_npc_with_no_references_can_be_deleted_with_its_identity_rows(
    s: ContentSetup,
) -> None:
    npc = create(s, "Mistake")
    response = s.gm.post(
        s.lifecycle(npc["npc_id"], "/delete-draft"),
        {"expected_row_version": npc["row_version"], "reason": "created by mistake"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 200 and response.json()["deleted"] is True
    for table, column in (
        ("character.characters", "character_id"),
        ("character.npcs", "npc_id"),
        ("character.character_descriptions", "character_id"),
    ):
        assert (
            s.connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :e"), {"e": npc["npc_id"]}
            ).scalar()
            == 0
        )


# --- read gating ----------------------------------------------------------------------------------------


def grant_player_sight(s: ContentSetup, npc_id: str) -> None:
    """Give the player a relationship to the NPC that grants discovery and the
    summary tier -- so only the lifecycle gate can still hide a draft."""
    membership = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": s.player.user_id},
    ).scalar()
    relationship_type = make_character_relationship_type(s.connection)
    for code in ("character.discover", "character.view_summary", "campaign.view"):
        capability = s.connection.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = :c"), {"c": code}
        ).scalar()
        make_relationship_type_capability(s.connection, relationship_type, capability)
    make_membership_character_relationship(
        s.connection, membership, uuid.UUID(npc_id), relationship_type
    )


def test_a_draft_npc_is_invisible_to_players_on_every_character_read(s: ContentSetup) -> None:
    npc = create(s, "Hidden Mira", notes="GM ONLY SECRET")
    grant_player_sight(s, npc["npc_id"])
    node = npc["npc_id"]
    for path in (
        f"/campaigns/{s.cid}/characters/{node}",
        f"/campaigns/{s.cid}/characters/{node}/sheet",
        f"/campaigns/{s.cid}/characters/{node}/inventory",
    ):
        assert s.player.get(path).status_code == 404, path
    search = s.player.get(f"/campaigns/{s.cid}/world/search", q="Hidden", category="character")
    assert all(item["name"] != "Hidden Mira" for item in search.json()["items"])
    assert s.player.get(f"/campaigns/{s.cid}/world/characters/{node}").status_code in (403, 404)
    gm_search = s.gm.get(
        f"/campaigns/{s.cid}/world/search",
        q="Hidden",
        category="character",
        include_noncanon="true",
    )
    assert any(item["name"] == "Hidden Mira" for item in gm_search.json()["items"])
    assert s.gm.get(f"/campaigns/{s.cid}/characters/{node}").status_code == 200


def test_a_published_npc_shows_players_identity_but_never_gm_notes(s: ContentSetup) -> None:
    npc = create(s, "Open Mira", summary="A baker.", notes="GM ONLY SECRET")
    grant_player_sight(s, npc["npc_id"])
    s.publish(npc["npc_id"], npc["row_version"])
    search = s.player.get(f"/campaigns/{s.cid}/world/search", q="Open Mira", category="character")
    assert [i["name"] for i in search.json()["items"]] == ["Open Mira"]
    detail = s.player.get(f"/campaigns/{s.cid}/characters/{npc['npc_id']}")
    assert detail.status_code == 200 and detail.json()["name"] == "Open Mira"
    assert "GM ONLY SECRET" not in search.text and "GM ONLY SECRET" not in detail.text
    assert s.gm.get(s.url(f"npcs/{npc['npc_id']}")).json()["notes"] == "GM ONLY SECRET"
    # An archived published NPC stays readable by editors (history is referenceable).
    s.connection.execute(
        text("UPDATE security.membership_character_relationships SET revoked_at = now()")
    )
    current = s.gm.get(s.url(f"npcs/{npc['npc_id']}")).json()
    s.transition(npc["npc_id"], "archive", current["row_version"])
    assert s.gm.get(f"/campaigns/{s.cid}/characters/{npc['npc_id']}").status_code == 200


def test_state_commands_refuse_a_draft_npc_but_accept_it_once_published(s: ContentSetup) -> None:
    from dnd_ai.commands._shared import EntityNotTargetableError
    from dnd_ai.commands.character_state import _adjust_hit_points_impl
    from dnd_ai.commands.encounters import _start_encounter_impl
    from tests.factories import make_world_time

    npc = create(s, "Guard")
    npc_id = uuid.UUID(npc["npc_id"])
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    when = make_world_time(s.connection, s.world_id, 500)

    def start() -> object:
        return _start_encounter_impl(
            s.connection,
            timeline_id=timeline,
            world_time_id=when,
            participant_entity_ids=(npc_id,),
            campaign_id=uuid.UUID(s.cid),
        )

    with pytest.raises(EntityNotTargetableError):
        start()
    with pytest.raises(EntityNotTargetableError):
        _adjust_hit_points_impl(
            s.connection,
            timeline_id=timeline,
            character_id=npc_id,
            delta=-1,
            world_time_id=when,
        )
    s.publish(npc["npc_id"], npc["row_version"])
    start()


def test_an_unpublished_npc_cannot_be_conversed_with(s: ContentSetup) -> None:
    """A draft NPC must not reach a player through the AI portrayal path: the
    turn is refused, before any context is assembled, like a nonexistent NPC."""
    from dnd_ai.commands._shared import EntityNotTargetableError
    from dnd_ai.commands.ai_npc import _AssignmentContext, _record_request_and_context
    from tests.factories import make_agent, make_agent_assignment

    npc = create(s, "Draft Innkeeper")
    agent = make_agent(s.connection)
    campaign = uuid.UUID(s.cid)
    assignment_id = make_agent_assignment(s.connection, agent, campaign, uuid.UUID(npc["npc_id"]))
    with pytest.raises(EntityNotTargetableError):
        _record_request_and_context(
            s.connection,
            agent_assignment_id=assignment_id,
            assignment=_AssignmentContext(
                agent_id=agent, campaign_id=campaign, npc_entity_id=uuid.UUID(npc["npc_id"])
            ),
            requesting_user_id=None,
            requesting_character_id=uuid.uuid4(),
            requesting_party_id=uuid.uuid4(),
            player_message="Hello",
            timeline_id=uuid.uuid4(),
            expected_world_id=s.world_id,
        )


# --- authorization -----------------------------------------------------------------------------------------


def test_players_strangers_and_cross_world_targets_are_refused(s: ContentSetup) -> None:
    npc = create(s, "Mira")
    foreign = s.stranger.post(
        s.url("npcs", s.other_cid),
        {
            "name": "Foreign",
            "species_id": s.stranger.get(s.url("npcs/options", s.other_cid)).json()["species"][0][
                "species_id"
            ],
            "size_category": "medium",
        },
        key=s.stranger.fresh_key(),
    ).json()
    paths = [
        ("get", s.url("npcs/options")),
        ("get", s.url(f"npcs/{npc['npc_id']}")),
        ("post", s.url("npcs")),
        ("post", s.url(f"npcs/{npc['npc_id']}/update")),
    ]
    body = {
        "name": "x",
        "species_id": species(s),
        "size_category": "medium",
        "expected_row_version": 1,
    }
    for actor, expected in ((s.player, 403), (s.stranger, 404)):
        for method, path in paths:
            call = getattr(actor, method)
            response = call(path) if method == "get" else call(path, body, key=actor.fresh_key())
            assert response.status_code == expected, (actor.name, path)
    assert s.gm.get(s.url(f"npcs/{foreign['npc_id']}")).status_code == 404
    assert s.gm.post(s.url(f"npcs/{foreign['npc_id']}/update"), body).status_code == 404
    assert s.gm.get(s.url(f"npcs/{npc['npc_id']}")).headers["cache-control"] == "no-store"


def test_replay_and_conflict(s: ContentSetup) -> None:
    body = {"name": "Once", "species_id": species(s), "size_category": "medium"}
    first = s.gm.post(s.url("npcs"), body, key="npc-1")
    second = s.gm.post(s.url("npcs"), body, key="npc-1")
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert len(s.audit("create_npc")) == 1
    other = s.gm.post(s.url("npcs"), {**body, "name": "Other"}, key="npc-1")
    assert other.status_code == 409
