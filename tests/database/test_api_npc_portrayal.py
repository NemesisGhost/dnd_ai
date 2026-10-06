"""NPC detail level and portrayal profiles (checkpoint 15.3A-3, decision D-21, migration 131)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database

SOURCE = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def npc(s: ContentSetup, name: str = "Mira", *, publish: bool = False) -> dict:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("npcs"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    if publish:
        s.publish(created["npc_id"], created["row_version"])
    return created


def portrayal_url(s: ContentSetup, npc_id: str, suffix: str = "") -> str:
    return s.url(f"npcs/{npc_id}/portrayal{suffix}")


def save(s: ContentSetup, npc_id: str, expected: int, **fields: object):  # type: ignore[no-untyped-def]
    return s.gm.post(
        portrayal_url(s, npc_id),
        {"expected_version": expected, **fields},
        key=s.gm.fresh_key(),
    )


def test_a_new_npc_has_no_profile_and_a_standard_detail_level(s: ContentSetup) -> None:
    created = npc(s)
    view = s.gm.get(portrayal_url(s, created["npc_id"])).json()
    assert view["current_version"] == 0 and view["shown_version"] == 0
    assert view["detail_level"] == "standard" and view["can_edit"] is True
    assert set(view["fields"].values()) == {None} and view["versions"] == []
    assert [f["name"] for f in view["field_labels"]][:2] == ["voice", "speech_style"]


def test_each_save_appends_a_version_against_the_version_seen(s: ContentSetup) -> None:
    created = npc(s)
    first = save(
        s,
        created["npc_id"],
        0,
        voice="  Low and gravelly  ",
        topics_avoided="Her brother",
        change_note="First pass",
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["current_version"] == 1 and body["fields"]["voice"] == "Low and gravelly"
    assert body["changed"] is True
    second = save(s, created["npc_id"], 1, voice="Low and gravelly", mannerisms="Taps the table")
    assert second.status_code == 200 and second.json()["current_version"] == 2
    assert second.json()["fields"]["topics_avoided"] is None  # a full replacement
    same = save(s, created["npc_id"], 2, voice="Low and gravelly", mannerisms="Taps the table")
    assert same.status_code == 200 and same.json()["changed"] is False
    assert same.json()["current_version"] == 2
    stale = save(s, created["npc_id"], 1, voice="Late")
    assert stale.status_code == 409 and code(stale) == "stale_write"
    versions = s.gm.get(portrayal_url(s, created["npc_id"])).json()["versions"]
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[1]["change_note"] == "First pass"
    old = s.gm.get(portrayal_url(s, created["npc_id"]), version=1).json()
    assert old["shown_version"] == 1 and old["fields"]["topics_avoided"] == "Her brother"
    assert old["current_version"] == 2
    missing = s.gm.get(portrayal_url(s, created["npc_id"]), version=9)
    assert missing.status_code == 404 and code(missing) == "portrayal_version_not_found"


def test_invalid_saves_write_nothing(s: ContentSetup) -> None:
    created = npc(s)
    too_long = save(s, created["npc_id"], 0, voice="x" * 4001)
    assert too_long.status_code == 422
    unknown = s.gm.post(
        portrayal_url(s, created["npc_id"]),
        {"expected_version": 0, "personality": "friendly"},
        key=s.gm.fresh_key(),
    )
    assert unknown.status_code == 422
    assert save(s, created["npc_id"], -1).status_code == 422
    assert s.gm.get(portrayal_url(s, created["npc_id"])).json()["versions"] == []
    # A first save with every field empty still records version 1, which is a deliberate blank.
    blank = save(s, created["npc_id"], 0)
    assert blank.status_code == 200 and blank.json()["current_version"] == 1


def test_versions_cannot_be_changed_or_deleted(s: ContentSetup) -> None:
    created = npc(s)
    save(s, created["npc_id"], 0, voice="Soft")
    for statement in (
        "UPDATE character.npc_portrayal_profiles SET voice = 'Loud' WHERE npc_id = :n",
        "DELETE FROM character.npc_portrayal_profiles WHERE npc_id = :n",
    ):
        savepoint = s.connection.begin_nested()
        with pytest.raises(DBAPIError):
            s.connection.execute(text(statement), {"n": created["npc_id"]})
        savepoint.rollback()
    assert (
        s.connection.execute(
            text("SELECT voice FROM character.npc_portrayal_profiles WHERE npc_id = :n"),
            {"n": created["npc_id"]},
        ).scalar()
        == "Soft"
    )


def test_deleting_a_draft_npc_removes_its_profile(s: ContentSetup) -> None:
    created = npc(s)
    save(s, created["npc_id"], 0, voice="Soft")
    deleted = s.gm.post(
        s.lifecycle(created["npc_id"], "/delete-draft"),
        {"expected_row_version": created["row_version"], "reason": "typo"},
        key=s.gm.fresh_key(),
    )
    assert deleted.status_code == 200, deleted.text
    assert s.count("character.npc_portrayal_profiles") == 0 or (
        s.connection.execute(
            text("SELECT count(*) FROM character.npc_portrayal_profiles WHERE npc_id = :n"),
            {"n": created["npc_id"]},
        ).scalar()
        == 0
    )


def test_the_detail_level_changes_with_the_npc_version(s: ContentSetup) -> None:
    created = npc(s)
    url = s.url(f"npcs/{created['npc_id']}/detail-level")
    changed = s.gm.post(
        url,
        {"expected_row_version": created["row_version"], "detail_level": "major"},
        key=s.gm.fresh_key(),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["detail_level"] == "major"
    assert changed.json()["row_version"] == created["row_version"] + 1
    same = s.gm.post(
        url,
        {"expected_row_version": changed.json()["row_version"], "detail_level": "major"},
        key=s.gm.fresh_key(),
    )
    assert same.status_code == 200 and same.json()["changed"] is False
    stale = s.gm.post(
        url,
        {"expected_row_version": created["row_version"], "detail_level": "minimal"},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and code(stale) == "stale_write"
    bad = s.gm.post(
        url,
        {"expected_row_version": changed.json()["row_version"], "detail_level": "epic"},
        key=s.gm.fresh_key(),
    )
    assert bad.status_code == 422
    assert [a.action for a in s.audit("update_npc_detail_level")] == ["updated"]


def test_an_archived_npc_takes_no_portrayal_or_level_changes(s: ContentSetup) -> None:
    created = npc(s, publish=True)
    current = s.gm.get(s.url(f"npcs/{created['npc_id']}")).json()
    archived = s.gm.post(
        s.lifecycle(created["npc_id"], "/archive"),
        {"expected_row_version": current["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200, archived.text
    refused = save(s, created["npc_id"], 0, voice="Quiet")
    assert refused.status_code == 409
    level = s.gm.post(
        s.url(f"npcs/{created['npc_id']}/detail-level"),
        {"expected_row_version": archived.json()["row_version"], "detail_level": "major"},
        key=s.gm.fresh_key(),
    )
    assert level.status_code == 409


def test_the_profile_is_never_part_of_a_player_or_character_read(s: ContentSetup) -> None:
    created = npc(s, publish=True)
    secret = "Secretly afraid of the sea"
    assert save(s, created["npc_id"], 0, emotional_baseline=secret).status_code == 200
    assert s.player.get(portrayal_url(s, created["npc_id"])).status_code == 403
    assert (
        s.player.post(
            portrayal_url(s, created["npc_id"]), {"expected_version": 1}, key=s.player.fresh_key()
        ).status_code
        == 403
    )
    for actor in (s.gm, s.player):
        for path in (
            f"/campaigns/{s.cid}/characters/{created['npc_id']}",
            f"/campaigns/{s.cid}/world/characters/{created['npc_id']}",
            f"/campaigns/{s.cid}/world/search",
            s.url(f"npcs/{created['npc_id']}"),
        ):
            response = actor.get(path)
            assert secret not in response.text, path
    audit = s.audit("save_npc_portrayal_profile")
    assert [a.action for a in audit] == ["created"]
    assert secret not in str(audit[0].changed_fields)


def test_the_ai_context_builders_do_not_read_the_profile() -> None:
    """Phase 20 decides how portrayal reaches a model; until then nothing may."""
    for relative in ("domain/context_assembly.py", "commands/ai_npc.py", "domain/ai_provider.py"):
        assert "npc_portrayal_profiles" not in (SOURCE / relative).read_text(encoding="utf-8")


def test_runtime_options_list_the_rules_conditions_and_resources(s: ContentSetup) -> None:
    options = s.gm.get(s.url("npc-runtime-options"))
    assert options.status_code == 200, options.text
    body = options.json()
    assert body["conditions"] and {"value", "label"} <= set(body["conditions"][0])
    assert "resources" in body
    assert s.player.get(s.url("npc-runtime-options")).status_code == 403


def test_replay_and_other_worlds(s: ContentSetup) -> None:
    created = npc(s)
    key = s.gm.fresh_key()
    body = {"expected_version": 0, "voice": "Soft"}
    first = s.gm.post(portrayal_url(s, created["npc_id"]), body, key=key)
    replay = s.gm.post(portrayal_url(s, created["npc_id"]), body, key=key)
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    assert s.gm.get(portrayal_url(s, created["npc_id"])).json()["current_version"] == 1
    foreign = s.stranger.get(s.url(f"npcs/{created['npc_id']}/portrayal", s.other_cid))
    assert foreign.status_code == 404
    assert (
        s.stranger.post(
            s.url(f"npcs/{created['npc_id']}/portrayal", s.other_cid),
            body,
            key=s.stranger.fresh_key(),
        ).status_code
        == 404
    )
