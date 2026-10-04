"""HTTP contract and command behavior for Quest definition authoring (Phase 15.1)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import (
    make_organization,
    make_quest_state,
    make_world,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def quest_url(s: ContentSetup, quest: dict, suffix: str = "") -> str:
    return s.url(f"quests/{quest['quest_id']}{suffix}")


def create_quest(s: ContentSetup, name: str = "The Lost Amulet") -> dict:
    response = s.gm.post(
        s.url("quests"), {"name": name, "summary": "Find it."}, key=s.gm.fresh_key()
    )
    assert response.status_code == 201, response.text
    return response.json()


def post(s: ContentSetup, quest: dict, suffix: str, body: dict) -> object:
    return s.gm.post(
        quest_url(s, quest, suffix),
        {"expected_row_version": quest["row_version"], **body},
        key=s.gm.fresh_key(),
    )


def add_stage(s: ContentSetup, quest: dict, name: str = "Stage", **extra: object) -> dict:
    response = post(
        s,
        quest,
        "/stages",
        {"name": name, "description": None, "stage_type": "sequential", **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def objective_body(**extra: object) -> dict:
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


def add_objective(s: ContentSetup, quest: dict, stage_index: int = 0, **extra: object) -> dict:
    stage_id = quest["stages"][stage_index]["quest_stage_id"]
    response = post(s, quest, f"/stages/{stage_id}/objectives", objective_body(**extra))
    assert response.status_code == 200, response.text
    return response.json()


def full_quest(s: ContentSetup, **objective: object) -> dict:
    quest = create_quest(s)
    quest = add_stage(s, quest)
    return add_objective(s, quest, **objective)


def place(s: ContentSetup, name: str = "Ruin") -> dict:
    response = s.gm.post(
        s.url("locations"), {"category": "region", "name": name}, key=s.gm.fresh_key()
    )
    assert response.status_code == 201
    return response.json()


# --- catalogs ------------------------------------------------------------------------------------


def test_the_options_catalog_is_server_driven(s: ContentSetup) -> None:
    body = s.gm.get(s.url("quests/options")).json()
    assert {o["value"] for o in body["objective_types"]} >= {
        "reach_location",
        "defeat_entity",
        "other",
    }
    assert [o["value"] for o in body["stage_types"]] == [
        "sequential",
        "optional",
        "conditional",
        "mutually_exclusive",
    ]
    assert [o["value"] for o in body["requirement_levels"]] == ["required", "optional", "hidden"]
    assert [o["value"] for o in body["completion_modes"]] == ["automatic", "gm_confirmed"]
    assert [o["value"] for o in body["visibility_policies"]] == [
        "visible",
        "hidden_until_active",
        "hidden_until_discovered",
        "gm_only",
    ]
    assert body["limits"]["max_stages"] == 100


def test_target_options_list_only_eligible_in_world_targets(s: ContentSetup) -> None:
    ruin = place(s, "Ruin")
    gone = place(s, "Gone")
    s.transition(gone["location_id"], "archive", gone["row_version"])
    s.stranger.post(
        s.url("locations", s.other_cid),
        {"category": "region", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    )
    quest = create_quest(s)
    items = s.gm.get(s.url("quests/target-options")).json()["items"]
    names = [i["name"] for i in items]
    assert names == ["Ruin"] and items[0]["kind"] == "region"
    assert quest["quest_id"] not in {i["entity_id"] for i in items}  # a quest is not a target
    assert items[0]["entity_id"] == ruin["location_id"]


# --- the quest root ------------------------------------------------------------------------------


def test_create_and_update_a_draft_quest_with_one_audit_row_each(s: ContentSetup) -> None:
    states = {
        t: s.count(t)
        for t in ("campaign.quest_state", "campaign.objective_state", "narrative.events")
    }
    quest = create_quest(s)
    assert (quest["canon_status"], quest["stages"], quest["has_progress"]) == ("draft", [], False)
    assert {"update", "add_stage"} <= set(quest["available_actions"])
    assert len(s.audit("create_quest")) == 1
    renamed = s.gm.post(
        quest_url(s, quest, "/update"),
        {"expected_row_version": quest["row_version"], "name": "The Found Amulet", "summary": None},
        key=s.gm.fresh_key(),
    ).json()
    assert renamed["name"] == "The Found Amulet" and renamed["changed"] is True
    assert s.audit("update_quest")[0].changed_fields["name"] == {
        "from": "The Lost Amulet",
        "to": "The Found Amulet",
    }
    assert states == {t: s.count(t) for t in states}


def test_an_identical_update_is_a_no_op(s: ContentSetup) -> None:
    quest = create_quest(s)
    same = s.gm.post(
        quest_url(s, quest, "/update"),
        {
            "expected_row_version": quest["row_version"],
            "name": quest["name"],
            "summary": quest["summary"],
        },
        key=s.gm.fresh_key(),
    ).json()
    assert same["changed"] is False and same["row_version"] == quest["row_version"]
    assert s.audit("update_quest") == []


# --- stages ---------------------------------------------------------------------------------------


def test_stages_are_numbered_by_the_server_in_order(s: ContentSetup) -> None:
    quest = create_quest(s)
    quest = add_stage(s, quest, "First")
    quest = add_stage(s, quest, "Second", stage_type="optional")
    assert [(st["name"], st["sequence_number"], st["stage_type"]) for st in quest["stages"]] == [
        ("First", 1, "sequential"),
        ("Second", 2, "optional"),
    ]
    assert s.audit("add_quest_stage")[1].changed_fields["sequence_number"] == 2


def test_a_client_cannot_choose_a_sequence_number_or_an_unknown_stage_type(s: ContentSetup) -> None:
    quest = create_quest(s)
    assert (
        post(
            s, quest, "/stages", {"name": "x", "stage_type": "sequential", "sequence_number": 7}
        ).status_code
        == 422
    )
    assert post(s, quest, "/stages", {"name": "x", "stage_type": "boss_fight"}).status_code == 400
    assert post(s, quest, "/stages", {"name": "", "stage_type": "sequential"}).status_code == 422


def test_every_child_command_moves_the_quest_version(s: ContentSetup) -> None:
    quest = create_quest(s)
    versions = [quest["row_version"]]
    quest = add_stage(s, quest)
    versions.append(quest["row_version"])
    quest = add_objective(s, quest)
    versions.append(quest["row_version"])
    stage_id = quest["stages"][0]["quest_stage_id"]
    updated = post(
        s,
        quest,
        f"/stages/{stage_id}/update",
        {"name": "Renamed", "description": None, "stage_type": "sequential"},
    ).json()
    versions.append(updated["row_version"])
    assert versions == sorted(set(versions)) and len(versions) == 4


def test_update_stage_wording_and_stale_writes(s: ContentSetup) -> None:
    quest = add_stage(s, create_quest(s))
    stage_id = quest["stages"][0]["quest_stage_id"]
    body = {"name": "Better name", "description": "Why", "stage_type": "sequential"}
    ok = post(s, quest, f"/stages/{stage_id}/update", body)
    assert ok.status_code == 200 and ok.json()["stages"][0]["name"] == "Better name"
    stale = post(s, quest, f"/stages/{stage_id}/update", {**body, "name": "Again"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    assert len(s.audit("update_quest_stage")) == 1


def test_reorder_requires_every_stage_exactly_once(s: ContentSetup) -> None:
    quest = create_quest(s)
    for name in ("A", "B", "C"):
        quest = add_stage(s, quest, name)
    ids = [st["quest_stage_id"] for st in quest["stages"]]
    for bad in (
        [ids[0], ids[1]],
        [ids[0], ids[0], ids[1]],
        [*ids, str(uuid.uuid4())],
        [str(uuid.uuid4())] * 3,
    ):
        response = post(s, quest, "/stages/reorder", {"stage_ids": bad})
        assert response.status_code == 400, bad
    reordered = post(s, quest, "/stages/reorder", {"stage_ids": [ids[2], ids[0], ids[1]]}).json()
    assert [st["name"] for st in reordered["stages"]] == ["C", "A", "B"]
    assert [st["sequence_number"] for st in reordered["stages"]] == [1, 2, 3]
    same_order = post(
        s, reordered, "/stages/reorder", {"stage_ids": [ids[2], ids[0], ids[1]]}
    ).json()
    assert same_order["changed"] is False


def test_remove_stage_deletes_its_objectives_and_audits_once(s: ContentSetup) -> None:
    quest = full_quest(s)
    stage_id = quest["stages"][0]["quest_stage_id"]
    removed = post(s, quest, f"/stages/{stage_id}/remove", {}).json()
    assert removed["stages"] == []
    assert s.quest_objective_count() == 0
    row = s.audit("remove_quest_stage")[0]
    assert row.action == "deleted" and row.changed_fields["objectives_removed"] == 1


# --- objectives -----------------------------------------------------------------------------------


def test_add_update_and_remove_an_objective(s: ContentSetup) -> None:
    ruin = place(s)
    quest = add_stage(s, create_quest(s))
    stage_id = quest["stages"][0]["quest_stage_id"]
    quest = post(
        s,
        quest,
        f"/stages/{stage_id}/objectives",
        objective_body(target_entity_id=ruin["location_id"], quantity_required=2),
    ).json()
    objective = quest["stages"][0]["objectives"][0]
    assert objective["target"]["name"] == "Ruin" and objective["target_kind"] == "region"
    assert (objective["objective_type"], objective["quantity_required"]) == ("reach_location", 2)
    updated = post(
        s,
        quest,
        f"/stages/{stage_id}/objectives/{objective['quest_objective_id']}/update",
        objective_body(
            name="Reach the old ruin",
            visibility_policy="gm_only",
            target_entity_id=ruin["location_id"],
            quantity_required=2,
        ),
    ).json()
    assert updated["stages"][0]["objectives"][0]["name"] == "Reach the old ruin"
    diff = s.audit("update_quest_objective")[0].changed_fields
    assert set(diff) == {"name", "visibility_policy"}
    removed = post(
        s, updated, f"/stages/{stage_id}/objectives/{objective['quest_objective_id']}/remove", {}
    ).json()
    assert removed["stages"][0]["objectives"] == []
    assert s.audit("remove_quest_objective")[0].action == "deleted"


@pytest.mark.parametrize(
    "extra",
    [
        {"objective_type": "teleport"},
        {"requirement_level": "mandatory"},
        {"completion_mode": "magic"},
        {"visibility_policy": "secret"},
        {"quantity_required": 0},
        {"quantity_required": 1_000_001},
        {"name": ""},
        {"completion_rule": {"any": []}},
        {"target_area_hazard_id": str(uuid.uuid4())},
    ],
)
def test_invalid_objective_bodies_write_nothing(s: ContentSetup, extra: dict) -> None:
    quest = add_stage(s, create_quest(s))
    stage_id = quest["stages"][0]["quest_stage_id"]
    before = s.quest_objective_count()
    response = post(s, quest, f"/stages/{stage_id}/objectives", objective_body(**extra))
    assert response.status_code in (400, 422)
    assert s.quest_objective_count() == before


def test_unusable_targets_share_one_code(s: ContentSetup) -> None:
    quest = add_stage(s, create_quest(s))
    stage_id = quest["stages"][0]["quest_stage_id"]
    gone = place(s, "Gone")
    s.transition(gone["location_id"], "archive", gone["row_version"])
    rejected = place(s, "Rejected")
    s.set_status(rejected["location_id"], canon="rejected")
    another_quest = create_quest(s, "Another")
    foreign_org = str(make_organization(s.connection, make_world(s.connection, "quest-foreign")))
    codes = set()
    for target in (
        gone["location_id"],
        rejected["location_id"],
        another_quest["quest_id"],
        foreign_org,
        str(uuid.uuid4()),
    ):
        response = post(
            s, quest, f"/stages/{stage_id}/objectives", objective_body(target_entity_id=target)
        )
        assert response.status_code == 400, target
        codes.add(response.json()["error"]["code"])
    assert codes == {"objective_target_invalid"}


def test_a_stage_or_objective_of_another_quest_is_a_404(s: ContentSetup) -> None:
    first = full_quest(s)
    second = add_stage(s, create_quest(s, "Second"))
    foreign_stage = first["stages"][0]["quest_stage_id"]
    foreign_objective = first["stages"][0]["objectives"][0]["quest_objective_id"]
    own_stage = second["stages"][0]["quest_stage_id"]
    body = {"name": "x", "description": None, "stage_type": "sequential"}
    assert post(s, second, f"/stages/{foreign_stage}/update", body).status_code == 404
    assert post(s, second, f"/stages/{foreign_stage}/remove", {}).status_code == 404
    assert (
        post(s, second, f"/stages/{foreign_stage}/objectives", objective_body()).status_code == 404
    )
    assert (
        post(
            s,
            second,
            f"/stages/{own_stage}/objectives/{foreign_objective}/update",
            objective_body(),
        ).status_code
        == 404
    )
    assert (
        post(
            s, second, f"/stages/{own_stage}/objectives/{foreign_objective}/remove", {}
        ).status_code
        == 404
    )


# --- progress freeze ------------------------------------------------------------------------------


def with_progress(s: ContentSetup) -> dict:
    quest = full_quest(s)
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    make_quest_state(s.connection, timeline, uuid.UUID(quest["quest_id"]))
    return s.gm.get(quest_url(s, quest)).json()


def test_progress_freezes_structure_but_not_wording(s: ContentSetup) -> None:
    quest = with_progress(s)
    assert quest["has_progress"] is True and quest["field_locks"] == ["structure"]
    blocked = {b["action"]: b["reason"] for b in quest["blocked_actions"]}
    assert (
        blocked["reorder_stages"]
        == blocked["remove_stage"]
        == blocked["remove_objective"]
        == "quest_has_progress"
    )
    assert {"add_stage", "update_stage", "add_objective", "update_objective"} <= set(
        quest["available_actions"]
    )

    stage = quest["stages"][0]
    objective = stage["objectives"][0]
    stage_path = f"/stages/{stage['quest_stage_id']}"
    objective_path = f"{stage_path}/objectives/{objective['quest_objective_id']}"
    base = objective_body(name=objective["name"])

    def code(response: object) -> str | None:
        return response.json().get("error", {}).get("code")  # type: ignore[attr-defined]

    assert code(post(s, quest, f"{stage_path}/remove", {})) == "quest_has_progress"
    assert code(post(s, quest, f"{objective_path}/remove", {})) == "quest_has_progress"
    assert (
        code(
            post(
                s,
                quest,
                "/stages/reorder",
                {"stage_ids": [stage["quest_stage_id"], stage["quest_stage_id"]]},
            )
        )
        == "validation_failed"
    )
    for structural in (
        {"objective_type": "defeat_entity"},
        {"requirement_level": "optional"},
        {"completion_mode": "gm_confirmed"},
        {"quantity_required": 3},
    ):
        response = post(s, quest, f"{objective_path}/update", {**base, **structural})
        assert code(response) == "quest_has_progress", structural
    assert (
        code(
            post(
                s,
                quest,
                f"{stage_path}/update",
                {"name": stage["name"], "description": None, "stage_type": "optional"},
            )
        )
        == "quest_has_progress"
    )

    # Wording, visibility, and additions are still allowed.
    renamed = post(
        s,
        quest,
        f"{objective_path}/update",
        {**base, "name": "Reworded", "visibility_policy": "gm_only"},
    )
    assert renamed.status_code == 200
    again = renamed.json()
    assert (
        post(
            s,
            again,
            f"{stage_path}/update",
            {"name": "Reworded stage", "description": "d", "stage_type": "sequential"},
        ).status_code
        == 200
    )
    again = s.gm.get(quest_url(s, quest)).json()
    assert (
        add_stage(s, again, "Added after progress")["stages"][-1]["name"] == "Added after progress"
    )


def test_a_single_stage_reorder_with_progress_is_a_harmless_no_op(s: ContentSetup) -> None:
    quest = with_progress(s)
    ids = [quest["stages"][0]["quest_stage_id"]]
    assert post(s, quest, "/stages/reorder", {"stage_ids": ids}).json()["changed"] is False


# --- lifecycle ----------------------------------------------------------------------------------------


def test_child_commands_refuse_a_quest_under_review_or_archived(s: ContentSetup) -> None:
    quest = full_quest(s)
    stage_id = quest["stages"][0]["quest_stage_id"]
    s.set_status(quest["quest_id"], canon="proposed")
    quest = s.gm.get(quest_url(s, quest)).json()
    assert "add_stage" not in quest["available_actions"]
    for path, body in (
        ("/stages", {"name": "x", "description": None, "stage_type": "sequential"}),
        (f"/stages/{stage_id}/objectives", objective_body()),
        (f"/stages/{stage_id}/remove", {}),
    ):
        response = post(s, quest, path, body)
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "content_not_editable"
        ), path


def test_publishing_needs_an_objective_then_published_targets(s: ContentSetup) -> None:
    ruin = place(s)
    quest = create_quest(s)

    def attempt(version: int) -> tuple[int, str | None]:
        response = s.gm.post(
            s.lifecycle(quest["quest_id"], "/publish"),
            {"expected_row_version": version},
            key=s.gm.fresh_key(),
        )
        return response.status_code, response.json().get("error", {}).get("code")

    version = quest["row_version"]
    for action in ("submit-for-review", "approve"):
        version = s.transition(quest["quest_id"], action, version)["row_version"]
    assert attempt(version) == (409, "quest_definition_incomplete")
    view = s.gm.get(quest_url(s, quest)).json()
    assert {"action": "publish", "reason": "quest_definition_incomplete"} in view["blocked_actions"]

    s.transition(quest["quest_id"], "return-to-draft", version)
    quest = add_stage(s, s.gm.get(quest_url(s, quest)).json())
    quest = add_objective(s, quest, target_entity_id=ruin["location_id"])
    version = quest["row_version"]
    for action in ("submit-for-review", "approve"):
        version = s.transition(quest["quest_id"], action, version)["row_version"]
    assert attempt(version) == (409, "reference_not_published")
    s.publish(ruin["location_id"], ruin["row_version"])
    assert attempt(version) == (200, None)


def test_a_draft_quest_deletes_with_its_definition_but_not_once_tracked(s: ContentSetup) -> None:
    quest = full_quest(s)
    deleted = s.gm.post(
        s.lifecycle(quest["quest_id"], "/delete-draft"),
        {"expected_row_version": quest["row_version"], "reason": "mistake"},
        key=s.gm.fresh_key(),
    )
    assert deleted.status_code == 200
    assert s.quest_stage_count() == 0 and s.quest_objective_count() == 0
    tracked = with_progress(s)
    blocked = s.gm.post(
        s.lifecycle(tracked["quest_id"], "/delete-draft"),
        {"expected_row_version": tracked["row_version"], "reason": "mistake"},
        key=s.gm.fresh_key(),
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "entity_referenced"


# --- read gating ----------------------------------------------------------------------------------------


def test_drafts_reach_editors_but_never_players_through_quest_reads(s: ContentSetup) -> None:
    quest = full_quest(s)
    qid = quest["quest_id"]
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    list_path = f"/campaigns/{s.cid}/quests"
    detail_path = f"/campaigns/{s.cid}/quests/{qid}"
    gm_items = {i["quest_id"]: i for i in s.gm.get(list_path).json()}
    assert gm_items[qid]["tracked"] is False and gm_items[qid]["canon_status"] == "draft"
    assert s.player.get(list_path).json() == []
    # Tracked but still a draft (e.g. loaded by a script): hidden from players.
    make_quest_state(s.connection, timeline, uuid.UUID(qid))
    assert qid not in {i["quest_id"] for i in s.player.get(list_path).json()}
    assert s.player.get(detail_path).status_code == 404
    s.publish(qid, s.gm.get(quest_url(s, quest)).json()["row_version"])
    assert qid in {i["quest_id"] for i in s.player.get(list_path).json()}
    assert s.player.get(detail_path).status_code == 200
    s.transition(qid, "archive", s.gm.get(quest_url(s, quest)).json()["row_version"])
    assert qid not in {i["quest_id"] for i in s.player.get(list_path).json()}
    assert qid not in {i["quest_id"] for i in s.gm.get(list_path).json()}
    assert s.player.get(detail_path).status_code == 200  # history stays referenceable


def test_objective_targets_and_completion_rules_never_reach_player_reads(s: ContentSetup) -> None:
    ruin = place(s, "Secret ruin")
    s.publish(ruin["location_id"], ruin["row_version"])
    quest = full_quest(s, target_entity_id=ruin["location_id"])
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    make_quest_state(s.connection, timeline, uuid.UUID(quest["quest_id"]))
    s.publish(quest["quest_id"], s.gm.get(quest_url(s, quest)).json()["row_version"])
    body = s.player.get(f"/campaigns/{s.cid}/quests/{quest['quest_id']}")
    assert body.status_code == 200
    assert ruin["location_id"] not in body.text and "target" not in body.text


def test_a_draft_quest_cannot_be_advanced(s: ContentSetup) -> None:
    from dnd_ai.commands._shared import EntityNotTargetableError
    from dnd_ai.commands.quests import _advance_objective_impl
    from tests.factories import make_world_time

    quest = full_quest(s)
    objective = quest["stages"][0]["objectives"][0]["quest_objective_id"]
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    when = make_world_time(s.connection, s.world_id, 700)
    with pytest.raises(EntityNotTargetableError):
        _advance_objective_impl(
            s.connection,
            quest_objective_id=uuid.UUID(objective),
            timeline_id=timeline,
            world_time_id=when,
            new_status_code="completed",
            campaign_id=uuid.UUID(s.cid),
        )


# --- atomicity, idempotency, authorization -----------------------------------------------------------------


def test_a_failure_after_a_child_insert_leaves_the_quest_unchanged(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dnd_ai.commands.quest_definitions as definitions

    quest = add_stage(s, create_quest(s))
    stage_id = quest["stages"][0]["quest_stage_id"]
    monkeypatch.setattr(
        definitions, "_bump", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    tables = ("narrative.quest_objectives", "audit.change_log", "security.idempotent_requests")
    before = {t: s.count(t) for t in tables}
    response = post(s, quest, f"/stages/{stage_id}/objectives", objective_body())
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}
    assert s.gm.get(quest_url(s, quest)).json()["row_version"] == quest["row_version"]


def test_replay_returns_the_stored_response_and_a_changed_body_conflicts(s: ContentSetup) -> None:
    quest = create_quest(s)
    body = {
        "expected_row_version": quest["row_version"],
        "name": "S",
        "description": None,
        "stage_type": "sequential",
    }
    first = s.gm.post(quest_url(s, quest, "/stages"), body, key="stage-1")
    replay = s.gm.post(quest_url(s, quest, "/stages"), body, key="stage-1")
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    assert len(s.audit("add_quest_stage")) == 1 and s.quest_stage_count() == 1
    conflict = s.gm.post(quest_url(s, quest, "/stages"), {**body, "name": "Other"}, key="stage-1")
    assert conflict.status_code == 409


def test_players_strangers_and_cross_world_quests_are_refused(s: ContentSetup) -> None:
    quest = full_quest(s)
    foreign = s.stranger.post(
        s.url("quests", s.other_cid), {"name": "Foreign"}, key=s.stranger.fresh_key()
    ).json()
    paths = [
        ("get", s.url("quests/options")),
        ("get", s.url("quests/target-options")),
        ("get", quest_url(s, quest)),
        ("post", s.url("quests")),
        ("post", quest_url(s, quest, "/update")),
        ("post", quest_url(s, quest, "/stages")),
        ("post", quest_url(s, quest, "/stages/reorder")),
    ]
    body = {
        "name": "x",
        "expected_row_version": 1,
        "stage_type": "sequential",
        "stage_ids": [str(uuid.uuid4())],
    }
    for actor, expected in ((s.player, 403), (s.stranger, 404)):
        for method, path in paths:
            call = getattr(actor, method)
            response = call(path) if method == "get" else call(path, body, key=actor.fresh_key())
            assert response.status_code == expected, (actor.name, path)
    assert s.gm.get(quest_url(s, foreign)).status_code == 404
    assert post(s, foreign, "/stages", {"name": "x", "stage_type": "sequential"}).status_code == 404
    assert s.gm.get(quest_url(s, quest)).headers["cache-control"] == "no-store"
