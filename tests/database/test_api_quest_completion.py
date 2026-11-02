"""Quest dependencies, participants, outcomes, rewards and GM notes (checkpoint 15.2E-2a)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import make_quest_state

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def qurl(s: ContentSetup, quest: dict, suffix: str = "") -> str:
    return s.url(f"quests/{quest['quest_id']}{suffix}")


def post(s: ContentSetup, quest: dict, suffix: str, body: dict):  # type: ignore[no-untyped-def]
    return s.gm.post(
        qurl(s, quest, suffix),
        {"expected_row_version": quest["row_version"], **body},
        key=s.gm.fresh_key(),
    )


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def objective(**extra: object) -> dict:
    return {
        "name": "Reach the ruin",
        "description": None,
        "objective_type": "reach_location",
        "requirement_level": "required",
        "completion_mode": "automatic",
        "visibility_policy": "visible",
        "quantity_required": None,
        "target_entity_id": None,
        **extra,
    }


def quest_with_objectives(s: ContentSetup, count: int = 3) -> dict:
    quest = s.gm.post(
        s.url("quests"), {"name": "The Lost Amulet", "summary": "Find it."}, key=s.gm.fresh_key()
    ).json()
    stage = post(
        s, quest, "/stages", {"name": "Stage", "description": None, "stage_type": "sequential"}
    )
    quest = stage.json()
    for index in range(count):
        quest = post(
            s,
            quest,
            f"/stages/{quest['stages'][0]['quest_stage_id']}/objectives",
            objective(name=f"Objective {index + 1}"),
        ).json()
    return quest


def ids(quest: dict) -> list[str]:
    return [o["quest_objective_id"] for o in quest["stages"][0]["objectives"]]


def npc(s: ContentSetup, name: str = "Mira") -> dict:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    response = s.gm.post(
        s.url("npcs"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- dependencies --------------------------------------------------------------------------------


def test_a_dependency_links_two_objectives_and_is_removed_by_id(s: ContentSetup) -> None:
    quest = quest_with_objectives(s)
    a, b, _ = ids(quest)
    response = post(
        s,
        quest,
        "/dependencies",
        {"objective_id": b, "depends_on_objective_id": a, "dependency_type": "prerequisite"},
    )
    assert response.status_code == 200, response.text
    quest = response.json()
    assert quest["dependencies"] == [
        {
            "objective_dependency_id": quest["dependencies"][0]["objective_dependency_id"],
            "objective_id": b,
            "depends_on_objective_id": a,
            "dependency_type": "prerequisite",
        }
    ]
    assert quest["has_progress"] is False  # a dependency is definition, not progress
    removed = post(
        s, quest, f"/dependencies/{quest['dependencies'][0]['objective_dependency_id']}/remove", {}
    )
    assert removed.status_code == 200 and removed.json()["dependencies"] == []
    assert [a.action for a in s.audit("add_objective_dependency")] == ["created"]


def test_prerequisite_loops_are_refused_but_other_kinds_may_pair(s: ContentSetup) -> None:
    quest = quest_with_objectives(s)
    a, b, c = ids(quest)

    def add(q: dict, objective_id: str, depends_on: str, kind: str = "prerequisite"):  # type: ignore[no-untyped-def]
        return post(
            s,
            q,
            "/dependencies",
            {
                "objective_id": objective_id,
                "depends_on_objective_id": depends_on,
                "dependency_type": kind,
            },
        )

    quest = add(quest, b, a).json()
    quest = add(quest, c, b).json()
    loop = add(quest, a, c)
    assert loop.status_code == 409 and code(loop) == "objective_dependency_cycle"
    direct = add(quest, a, b)
    assert direct.status_code == 409 and code(direct) == "objective_dependency_cycle"
    # Exclusions and blocks are not orderings, so a mutual pair is fine.
    quest = add(quest, a, b, "exclusion").json()
    quest = add(quest, b, a, "exclusion").json()
    assert len(quest["dependencies"]) == 4
    duplicate = add(quest, a, b, "exclusion")
    assert duplicate.status_code == 409 and code(duplicate) == "objective_dependency_exists"


def test_a_dependency_needs_two_different_objectives_of_this_quest(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 2)
    other = quest_with_objectives(s, 1)
    a, _ = ids(quest)
    for payload in (
        {"objective_id": a, "depends_on_objective_id": a},
        {"objective_id": a, "depends_on_objective_id": ids(other)[0]},
        {"objective_id": a, "depends_on_objective_id": str(uuid.uuid4())},
    ):
        response = post(s, quest, "/dependencies", {"dependency_type": "prerequisite", **payload})
        assert response.status_code == 400 and code(response) == "objective_dependency_invalid"
    bad_type = post(
        s,
        quest,
        "/dependencies",
        {
            "objective_id": a,
            "depends_on_objective_id": ids(quest)[1],
            "dependency_type": "sideways",
        },
    )
    assert bad_type.status_code in (400, 422)
    assert s.gm.get(qurl(s, quest)).json()["dependencies"] == []


def test_dependencies_freeze_once_the_quest_has_progress(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 2)
    a, b = ids(quest)
    quest = post(
        s,
        quest,
        "/dependencies",
        {"objective_id": b, "depends_on_objective_id": a, "dependency_type": "prerequisite"},
    ).json()
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    make_quest_state(s.connection, timeline, uuid.UUID(quest["quest_id"]))
    view = s.gm.get(qurl(s, quest)).json()
    assert view["has_progress"] is True
    blocked = {b["action"]: b["reason"] for b in view["blocked_actions"]}
    assert blocked["add_dependency"] == blocked["remove_dependency"] == "quest_has_progress"
    adding = post(
        s,
        view,
        "/dependencies",
        {"objective_id": a, "depends_on_objective_id": b, "dependency_type": "blocking"},
    )
    assert adding.status_code == 409 and code(adding) == "quest_has_progress"
    removing = post(
        s, view, f"/dependencies/{quest['dependencies'][0]['objective_dependency_id']}/remove", {}
    )
    assert removing.status_code == 409 and code(removing) == "quest_has_progress"
    assert len(s.gm.get(qurl(s, view)).json()["dependencies"]) == 1


# --- participants --------------------------------------------------------------------------------


def test_participants_are_people_or_organizations_with_a_role(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 1)
    giver = npc(s)
    quest = post(
        s,
        quest,
        "/participants",
        {"participant_entity_id": giver["npc_id"], "participant_role": "quest_giver"},
    ).json()
    assert [(p["participant"]["name"], p["participant_role"]) for p in quest["participants"]] == [
        ("Mira", "quest_giver")
    ]
    duplicate = post(
        s,
        quest,
        "/participants",
        {"participant_entity_id": giver["npc_id"], "participant_role": "quest_giver"},
    )
    assert duplicate.status_code == 409 and code(duplicate) == "quest_participant_exists"
    quest = post(
        s,
        quest,
        "/participants",
        {"participant_entity_id": giver["npc_id"], "participant_role": "ally"},
    ).json()
    place = s.gm.post(
        s.url("locations"), {"category": "region", "name": "Ruin"}, key=s.gm.fresh_key()
    ).json()
    refused = post(
        s,
        quest,
        "/participants",
        {"participant_entity_id": place["location_id"], "participant_role": "involved"},
    )
    assert refused.status_code == 400 and code(refused) == "quest_participant_invalid"
    missing = post(
        s,
        quest,
        "/participants",
        {"participant_entity_id": str(uuid.uuid4()), "participant_role": "involved"},
    )
    assert missing.status_code == 400 and code(missing) == "quest_participant_invalid"
    bad_role = post(
        s,
        quest,
        "/participants",
        {"participant_entity_id": giver["npc_id"], "participant_role": "bystander"},
    )
    assert bad_role.status_code in (400, 422)
    first = quest["participants"][0]["quest_participant_id"]
    removed = post(s, quest, f"/participants/{first}/remove", {})
    assert removed.status_code == 200 and len(removed.json()["participants"]) == 1


def test_participants_stay_editable_after_progress(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 1)
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    make_quest_state(s.connection, timeline, uuid.UUID(quest["quest_id"]))
    view = s.gm.get(qurl(s, quest)).json()
    assert (
        post(
            s,
            view,
            "/participants",
            {"participant_entity_id": npc(s)["npc_id"], "participant_role": "ally"},
        ).status_code
        == 200
    )


# --- outcomes and rewards -------------------------------------------------------------------------


def test_outcomes_have_a_permanent_code_and_rewards_belong_to_them(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 1)
    quest = post(
        s,
        quest,
        "/outcomes",
        {
            "code": "saved_the_village",
            "name": "The village is saved",
            "description": "Hooray",
            "outcome_category": "success",
        },
    ).json()
    outcome = quest["outcomes"][0]
    assert (outcome["code"], outcome["outcome_category"], outcome["rewards"]) == (
        "saved_the_village",
        "success",
        [],
    )
    again = post(
        s,
        quest,
        "/outcomes",
        {"code": "saved_the_village", "name": "Duplicate", "outcome_category": "neutral"},
    )
    assert again.status_code == 409 and code(again) == "quest_outcome_code_exists"
    for bad in ("Saved The Village", "1st", "", "x" * 80):
        refused = post(
            s, quest, "/outcomes", {"code": bad, "name": "x", "outcome_category": "neutral"}
        )
        assert refused.status_code in (400, 422), bad
    updated = post(
        s,
        quest,
        f"/outcomes/{outcome['quest_outcome_id']}/update",
        {
            "name": "The village survives",
            "description": None,
            "outcome_category": "partial_success",
        },
    ).json()
    assert updated["outcomes"][0]["name"] == "The village survives"
    assert updated["outcomes"][0]["code"] == "saved_the_village"  # the code never changes
    same = post(
        s,
        updated,
        f"/outcomes/{outcome['quest_outcome_id']}/update",
        {
            "name": "The village survives",
            "description": None,
            "outcome_category": "partial_success",
        },
    )
    assert same.status_code == 200 and same.json()["row_version"] == updated["row_version"]

    rewarded = post(
        s,
        updated,
        f"/outcomes/{outcome['quest_outcome_id']}/rewards",
        {
            "reward_type": "currency",
            "description": "50 gold, SECRET LOOT",
            "reward_knowledge_item_id": None,
        },
    ).json()
    reward = rewarded["outcomes"][0]["rewards"][0]
    assert (reward["reward_type"], reward["description"]) == ("currency", "50 gold, SECRET LOOT")
    (audit,) = s.audit("add_quest_reward")
    assert "SECRET LOOT" not in str(audit.changed_fields)
    removed_reward = post(s, rewarded, f"/rewards/{reward['quest_reward_id']}/remove", {}).json()
    assert removed_reward["outcomes"][0]["rewards"] == []
    with_reward = post(
        s,
        removed_reward,
        f"/outcomes/{outcome['quest_outcome_id']}/rewards",
        {"reward_type": "other", "description": "Gratitude", "reward_knowledge_item_id": None},
    ).json()
    gone = post(s, with_reward, f"/outcomes/{outcome['quest_outcome_id']}/remove", {}).json()
    assert gone["outcomes"] == []
    leftover = s.connection.execute(text("SELECT count(*) FROM narrative.quest_rewards")).scalar()
    assert leftover == 0


def test_a_knowledge_reward_names_a_usable_knowledge_item(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 1)
    quest = post(
        s,
        quest,
        "/outcomes",
        {"code": "found_it", "name": "Found it", "outcome_category": "success"},
    ).json()
    oid = quest["outcomes"][0]["quest_outcome_id"]
    claim = s.gm.post(
        s.url("knowledge"),
        {
            "statement": "The amulet is in the well.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
        key=s.gm.fresh_key(),
    )
    assert claim.status_code == 201, claim.text
    item = claim.json()["knowledge_item_id"]
    ok = post(
        s,
        quest,
        f"/outcomes/{oid}/rewards",
        {
            "reward_type": "knowledge",
            "description": "Learn where it is",
            "reward_knowledge_item_id": item,
        },
    )
    assert ok.status_code == 200, ok.text
    quest = ok.json()
    assert quest["outcomes"][0]["rewards"][0]["knowledge"]["entity_id"] == item
    mismatched = [
        {"reward_type": "knowledge", "description": "x", "reward_knowledge_item_id": None},
        {"reward_type": "currency", "description": "x", "reward_knowledge_item_id": item},
        {
            "reward_type": "knowledge",
            "description": "x",
            "reward_knowledge_item_id": str(uuid.uuid4()),
        },
    ]
    for body in mismatched:
        refused = post(s, quest, f"/outcomes/{oid}/rewards", body)
        assert refused.status_code == 400 and code(refused) == "reward_knowledge_invalid", body
    missing = post(
        s, quest, f"/outcomes/{uuid.uuid4()}/rewards", {"reward_type": "other", "description": "x"}
    )
    assert missing.status_code == 404


# --- GM notes ---------------------------------------------------------------------------------------


def test_gm_notes_are_gm_only_kept_when_omitted_and_cleared_when_empty(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 1)
    body = {"name": quest["name"], "summary": quest["summary"]}
    noted = post(s, quest, "/update", {**body, "gm_notes": "The amulet is cursed."}).json()
    assert noted["gm_notes"] == "The amulet is cursed."
    kept = post(
        s, noted, "/update", {**body, "summary": "Find it, quickly."}
    ).json()  # no gm_notes sent
    assert kept["gm_notes"] == "The amulet is cursed." and kept["summary"] == "Find it, quickly."
    cleared = post(
        s, kept, "/update", {**body, "summary": "Find it, quickly.", "gm_notes": ""}
    ).json()
    assert cleared["gm_notes"] is None
    audits = s.audit("update_quest")
    assert all("cursed" not in str(a.changed_fields) for a in audits)
    too_long = post(s, cleared, "/update", {**body, "gm_notes": "x" * 5000})
    assert too_long.status_code in (400, 422)
    # Revision history holds the notes through the GM-only authoring view.
    snapshot = s.connection.execute(
        text(
            "SELECT snapshot FROM core.entity_revisions WHERE entity_id = :e "
            "ORDER BY row_version DESC LIMIT 1"
        ),
        {"e": quest["quest_id"]},
    ).scalar()
    assert "gm_notes" in snapshot


def test_players_never_see_notes_or_the_new_authoring_data(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 1)
    body = {"name": quest["name"], "summary": quest["summary"], "gm_notes": "TOP SECRET PLAN"}
    quest = post(s, quest, "/update", body).json()
    quest = post(
        s,
        quest,
        "/participants",
        {"participant_entity_id": npc(s)["npc_id"], "participant_role": "quest_giver"},
    ).json()
    quest = post(
        s,
        quest,
        "/outcomes",
        {
            "code": "done",
            "name": "Done",
            "description": "SECRET OUTCOME",
            "outcome_category": "success",
        },
    ).json()
    assert s.player.get(qurl(s, quest)).status_code == 403
    s.publish(quest["quest_id"], quest["row_version"])
    for path in (f"/campaigns/{s.cid}/quests", f"/campaigns/{s.cid}/quests/{quest['quest_id']}"):
        response = s.player.get(path)
        assert "TOP SECRET PLAN" not in response.text and "SECRET OUTCOME" not in response.text, (
            path
        )
    preview = s.gm.get(f"/campaigns/{s.cid}/quests/{quest['quest_id']}")
    assert "TOP SECRET PLAN" not in preview.text


def test_foreign_and_stale_writes_are_refused(s: ContentSetup) -> None:
    quest = quest_with_objectives(s, 1)
    stale = s.gm.post(
        qurl(s, quest, "/outcomes"),
        {"expected_row_version": 99, "code": "x", "name": "x", "outcome_category": "neutral"},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and code(stale) == "stale_write"
    foreign = s.stranger.post(
        qurl(s, quest, "/outcomes"),
        {"expected_row_version": 1, "code": "x", "name": "x", "outcome_category": "neutral"},
        key=s.stranger.fresh_key(),
    )
    assert foreign.status_code in (403, 404)
    assert (
        s.player.post(
            qurl(s, quest, "/participants"),
            {
                "expected_row_version": 1,
                "participant_entity_id": str(uuid.uuid4()),
                "participant_role": "ally",
            },
            key=s.player.fresh_key(),
        ).status_code
        == 403
    )
