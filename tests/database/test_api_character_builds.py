"""Character builds, activation, and starting state (checkpoint 15.2B-2, migration 119)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.character_build_resolution import resolve_effective_character_build_id
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance, _branch_campaign

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def options(s: ContentSetup) -> dict:
    response = s.gm.get(f"/campaigns/{s.cid}/authoring/character-build-options")
    assert response.status_code == 200, response.text
    return response.json()


def pc(s: ContentSetup, name: str = "Aldric") -> str:
    species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    response = s.gm.post(
        s.url("player-characters"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()["player_character_id"]


def builds_url(s: ContentSetup, character_id: str, suffix: str = "") -> str:
    return s.url(f"characters/{character_id}/builds{suffix}")


def full_body(s: ContentSetup, label: str = "Level 1") -> dict:
    o = options(s)
    ability = o["abilities"][0]["id"]
    cls = o["classes"][0]
    return {
        "label": label,
        "ability_scores": [{"ability_id": o["abilities"][0]["id"], "score": 16}],
        "class_levels": [{"class_id": cls["id"], "subclass_id": None, "level": 1}],
        "proficiencies": [
            {
                "proficiency_type_id": next(
                    t["id"] for t in o["proficiency_types"] if t["target_kind"] == "skill"
                ),
                "skill_id": o["skills"][0]["id"],
            },
            {
                "proficiency_type_id": next(
                    t["id"] for t in o["proficiency_types"] if t["target_kind"] == "saving_throw"
                ),
                "saving_throw_ability_id": ability,
            },
        ],
        "feature_ids": [o["features"][0]["id"]],
        "spellcasting": [
            {
                "class_id": cls["id"],
                "spellcasting_ability_id": ability,
                "known_spell_ids": [o["spells"][0]["id"]],
                "prepared_spell_ids": [o["spells"][0]["id"]],
            }
        ],
    }


def create_build(s: ContentSetup, character_id: str, **overrides: object) -> dict:
    body = {**full_body(s), **overrides}
    response = s.gm.post_raw(builds_url(s, character_id), body, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def initialize(s: ContentSetup, character_id: str, maximum: int = 12, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        s.url(f"characters/{character_id}/state/initialize"),
        {"maximum_hit_points": maximum, **extra},
        key=s.gm.fresh_key(),
    )


def activate(s: ContentSetup, character_id: str, build_id: str, expected: str | None, cid=None):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        s.url(f"characters/{character_id}/builds/{build_id}/activate", cid),
        {"expected_active_build_id": expected},
        key=s.gm.fresh_key(),
    )


def state_row(s: ContentSetup, character_id: str):  # type: ignore[no-untyped-def]
    return s.connection.execute(
        text(
            "SELECT cs.character_build_id, cs.last_event_id, cs.current_hit_points, "
            "cs.maximum_hit_points FROM campaign.character_state cs "
            "JOIN campaign.campaigns c ON c.timeline_id = cs.timeline_id "
            "WHERE c.campaign_id = :c AND cs.character_id = :ch"
        ),
        {"c": s.cid, "ch": character_id},
    ).one_or_none()


# --- options ---------------------------------------------------------------------------------


def test_options_list_the_campaigns_canon_rules_including_spells(
    s: ContentSetup,
) -> None:
    o = options(s)
    assert len(o["abilities"]) >= 6 and o["classes"] and o["features"] and o["skills"]
    assert {t["target_kind"] for t in o["proficiency_types"]} >= {"skill", "saving_throw"}
    assert o["spells"] and o["unsupported"] == []
    assert s.player.get(f"/campaigns/{s.cid}/authoring/character-build-options").status_code == 403


# --- starting state -----------------------------------------------------------------------------


def test_initialize_creates_administrative_state_once(s: ContentSetup) -> None:
    character = pc(s)
    response = initialize(s, character, 20, current_hit_points=15)
    assert response.status_code == 201, response.text
    assert set(response.json()) >= {"character_id", "created"} and "event_id" not in response.json()
    row = state_row(s, character)
    assert (row.current_hit_points, row.maximum_hit_points, row.last_event_id) == (15, 20, None)
    assert row.character_build_id is None
    again = initialize(s, character, 30)
    assert again.status_code == 409 and again.json()["error"]["code"] == "character_state_exists"
    (audit,) = s.audit("initialize_character_state")
    assert audit.entity_id == uuid.UUID(character)


@pytest.mark.parametrize(
    "body", [{"maximum_hit_points": 0}, {"maximum_hit_points": 5, "current_hit_points": 6}]
)
def test_initialize_validates_hit_points(s: ContentSetup, body: dict) -> None:
    character = pc(s)
    response = s.gm.post_raw(
        s.url(f"characters/{character}/state/initialize"), body, key=s.gm.fresh_key()
    )
    assert response.status_code in (400, 422)
    assert state_row(s, character) is None


# --- build creation --------------------------------------------------------------------------------


def test_create_build_writes_the_whole_snapshot_atomically_without_events(s: ContentSetup) -> None:
    character = pc(s)
    events_before = s.count("narrative.events")
    receipt = create_build(s, character)
    build_id = receipt["character_build_id"]
    assert set(receipt) == {"character_id", "character_build_id", "created", "changed"}
    counts = {
        table: s.connection.execute(
            text(f"SELECT count(*) FROM character.{table} WHERE character_build_id = :b"),
            {"b": build_id},
        ).scalar()
        for table in (
            "character_ability_scores",
            "character_class_levels",
            "character_proficiencies",
            "character_features",
            "character_spellcasting_profiles",
        )
    }
    assert counts == {
        "character_ability_scores": 1,
        "character_class_levels": 1,
        "character_proficiencies": 2,
        "character_features": 1,
        "character_spellcasting_profiles": 1,
    }
    spells = s.connection.execute(
        text(
            "SELECT (SELECT count(*) FROM character.character_known_spells), "
            "(SELECT count(*) FROM character.character_prepared_spells)"
        )
    ).one()
    assert tuple(spells) == (1, 1)
    assert s.count("narrative.events") == events_before
    (audit,) = s.audit("create_character_build")
    assert audit.entity_id == uuid.UUID(character)
    assert "Level 1" not in str(audit.changed_fields)


def test_an_npc_can_have_a_build_but_a_bare_or_foreign_character_cannot(s: ContentSetup) -> None:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    npc = s.gm.post(
        s.url("npcs"),
        {"name": "Mira", "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()["npc_id"]
    create_build(s, npc)
    from tests.factories import make_character

    bare = make_character(s.connection, s.world_id, name="Bare")
    refused = s.gm.post_raw(builds_url(s, str(bare)), full_body(s), key=s.gm.fresh_key())
    assert (
        refused.status_code == 400 and refused.json()["error"]["code"] == "build_character_invalid"
    )
    assert s.gm.get(builds_url(s, str(bare))).status_code == 404
    assert s.gm.get(builds_url(s, str(uuid.uuid4()))).status_code == 404


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b, o: b["ability_scores"].append(dict(b["ability_scores"][0])),  # duplicate
        lambda b, o: b["ability_scores"][0].update(score=99),
        lambda b, o: b["class_levels"][0].update(level=0),
        lambda b, o: b["proficiencies"][0].update(skill_id=None),  # no target
        lambda b, o: b["feature_ids"].append(b["feature_ids"][0]),
    ],
)
def test_invalid_shapes_are_refused_and_write_nothing(s: ContentSetup, mutate) -> None:  # type: ignore[no-untyped-def]
    character = pc(s)
    body = full_body(s)
    mutate(body, options(s))
    before = s.count("character.character_builds")
    response = s.gm.post_raw(builds_url(s, character), body, key=s.gm.fresh_key())
    assert response.status_code in (400, 422), response.text
    assert s.count("character.character_builds") == before


def test_rules_options_must_exist_in_the_campaigns_ruleset_and_agree(s: ContentSetup) -> None:
    character = pc(s)
    o = options(s)
    bad_spell = full_body(s)
    bad_spell["spellcasting"][0]["known_spell_ids"] = [str(uuid.uuid4())]
    refused = s.gm.post_raw(builds_url(s, character), bad_spell, key=s.gm.fresh_key())
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "build_option_not_available"
    unknown = full_body(s)
    unknown["feature_ids"] = [str(uuid.uuid4())]
    response = s.gm.post_raw(builds_url(s, character), unknown, key=s.gm.fresh_key())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "build_option_not_available"

    # A proficiency whose target does not match its type's kind.
    mismatch = full_body(s)
    mismatch["proficiencies"] = [
        {
            "proficiency_type_id": next(
                t["id"] for t in o["proficiency_types"] if t["target_kind"] == "saving_throw"
            ),
            "skill_id": o["skills"][0]["id"],
        }
    ]
    response = s.gm.post_raw(builds_url(s, character), mismatch, key=s.gm.fresh_key())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "build_option_not_available"
    assert s.count("character.character_builds") == 0


def test_players_cannot_create_builds_and_replay_is_stable(s: ContentSetup) -> None:
    character = pc(s)
    body = full_body(s)
    assert (
        s.player.post_raw(builds_url(s, character), body, key=s.player.fresh_key()).status_code
        == 403
    )
    key = s.gm.fresh_key()
    first = s.gm.post_raw(builds_url(s, character), body, key=key)
    again = s.gm.post_raw(builds_url(s, character), body, key=key)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    assert s.count("character.character_builds") == 1
    changed = s.gm.post_raw(builds_url(s, character), {**body, "label": "Other"}, key=key)
    assert changed.status_code == 409


def test_the_build_list_shows_counts_state_and_the_active_build(s: ContentSetup) -> None:
    character = pc(s)
    first = create_build(s, character)["character_build_id"]
    before = s.gm.get(builds_url(s, character)).json()
    assert before["state"]["initialized"] is False and before["active_build_id"] is None
    assert before["builds"][0]["counts"]["features"] == 1
    initialize(s, character, 9)
    assert activate(s, character, first, None).status_code == 200
    after = s.gm.get(builds_url(s, character)).json()
    assert after["state"] == {"initialized": True, "current_hit_points": 9, "maximum_hit_points": 9}
    assert after["active_build_id"] == first and after["builds"][0]["is_active"] is True
    assert after["character"]["kind"] == "player_character"
    assert s.player.get(builds_url(s, character)).status_code == 403


# --- activation ---------------------------------------------------------------------------------------


def test_the_first_activation_is_administrative_later_ones_are_events(s: ContentSetup) -> None:
    character = pc(s)
    one = create_build(s, character)["character_build_id"]
    two = create_build(s, character, label="Level 2")["character_build_id"]
    # Activation needs starting state first.
    early = activate(s, character, one, None)
    assert early.status_code == 409 and early.json()["error"]["code"] == "character_state_missing"
    initialize(s, character)

    events_before = s.count("narrative.events")
    first = activate(s, character, one, None)
    assert first.status_code == 200 and "event_id" not in first.json()
    row = state_row(s, character)
    assert (row.character_build_id, row.last_event_id) == (uuid.UUID(one), None)
    assert s.count("narrative.events") == events_before

    # A later change records an event: the character must be published, and the
    # campaign needs a recorded time.
    unpublished = activate(s, character, two, one)
    assert unpublished.status_code == 409
    assert unpublished.json()["error"]["code"] == "character_not_published"
    s.publish(character, s.gm.get(s.url(f"player-characters/{character}")).json()["row_version"])
    needs_clock = activate(s, character, two, one)
    assert (
        needs_clock.status_code == 409 and needs_clock.json()["error"]["code"] == "clock_required"
    )
    assert _advance(s, Times(s).at(1), 0).status_code == 200

    second = activate(s, character, two, one)
    assert second.status_code == 200, second.text
    event_id = second.json()["event_id"]
    effect = s.connection.execute(
        text(
            "SELECT ev.target_component, ev.previous_value, ev.new_value, et.code AS type_code "
            "FROM narrative.event_effects ev JOIN narrative.events e ON e.event_id = ev.event_id "
            "JOIN narrative.event_types et ON et.event_type_id = e.event_type_id "
            "WHERE ev.event_id = :e"
        ),
        {"e": event_id},
    ).one()
    assert effect.type_code == "character_build_activated"
    assert (effect.target_component, effect.previous_value, effect.new_value) == (
        "character_build_id",
        one,
        two,
    )
    row = state_row(s, character)
    assert (row.character_build_id, str(row.last_event_id)) == (uuid.UUID(two), event_id)
    audits = s.audit("activate_character_build")
    assert len(audits) == 2 and audits[1].entity_id == uuid.UUID(character)


def test_a_stale_active_build_and_a_repeat_are_refused(s: ContentSetup) -> None:
    character = pc(s)
    one = create_build(s, character)["character_build_id"]
    two = create_build(s, character, label="Two")["character_build_id"]
    initialize(s, character)
    assert activate(s, character, one, None).status_code == 200
    stale = activate(s, character, two, None)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    repeat = activate(s, character, one, one)
    assert repeat.status_code == 409 and repeat.json()["error"]["code"] == "build_already_active"
    assert state_row(s, character).character_build_id == uuid.UUID(one)


def test_a_build_of_another_character_cannot_be_activated(s: ContentSetup) -> None:
    mine, other = pc(s, "Mine"), pc(s, "Other")
    foreign = create_build(s, other)["character_build_id"]
    initialize(s, mine)
    response = activate(s, mine, foreign, None)
    assert response.status_code == 404
    assert state_row(s, mine).character_build_id is None


# --- branches ---------------------------------------------------------------------------------------------


def test_a_branch_made_before_a_later_activation_keeps_the_build_active_at_the_branch_point(
    s: ContentSetup,
) -> None:
    character = pc(s)
    one = create_build(s, character)["character_build_id"]
    two = create_build(s, character, label="Two")["character_build_id"]
    initialize(s, character)
    assert activate(s, character, one, None).status_code == 200  # administrative baseline
    s.publish(character, s.gm.get(s.url(f"player-characters/{character}")).json()["row_version"])
    times = Times(s)
    year1, year5 = times.at(1), times.at(5)
    assert _advance(s, year1, 0).status_code == 200
    branch_cid = _branch_campaign(s, year1)  # branches while `one` is active
    assert _advance(s, year5, 1).status_code == 200  # parent moves on...
    assert activate(s, character, two, one).status_code == 200  # ...and switches to `two`

    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": branch_cid},
    ).scalar()
    parent_timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    char_uuid = uuid.UUID(character)
    assert resolve_effective_character_build_id(
        s.connection, character_id=char_uuid, timeline_id=parent_timeline
    ) == uuid.UUID(two)
    # The branch never sees the parent's later change.
    assert resolve_effective_character_build_id(
        s.connection, character_id=char_uuid, timeline_id=timeline
    ) == uuid.UUID(one)
