# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The legacy-copy route (P03-A A2b-2, plan section 9, decisions D7 and D8), end to end over HTTP.

`POST .../public-profile/draft/copy-legacy` copies one legacy description field of an NPC or player
character into the draft field of the same name. It is the only writer of a legacy origin, so the
excerpt regressions of A2b-1 are rerun here through it instead of through a seeded row.

Cast, on one NPC (its source read needs role `canon.edit` and the world capability
`world.canon.read_private`): *permitted* are the delegated GM (`gm`) and the second owner (`o2`),
both world editors; *restricted* are the first owner (`o1`, no world role) and the assistant GM
(`ast`, world reader). Markers: FULL is the NPC's background, SRC_APPEARANCE its appearance, NOTES
its GM notes (a source of nothing); EXCERPT and APPENDED are edits of the copy.
"""

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.npcs import update_npc
from dnd_ai.commands.world_memberships import end_world_membership
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    body,
    code,
    deny,
    error_code,
    make_one_character,
    make_outsider,
    read,
    release,
    release_rows,
    save,
    url,
)
from tests.database.test_character_public_profile_restrictions import (  # noqa: F401 - fixtures
    A_TEXT,
    APPENDED,
    EXCERPT,
    FULL,
    Seen,
    background,
    edit_background,
    npc,
    profile,
    row,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import make_character

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

SRC_APPEARANCE = "SOURCE-APPEARANCE-MARKER-6606"
NOTES = "SOURCE-NOTES-MARKER-7707"
NEW_SOURCE = "REWRITTEN-SOURCE-MARKER-8808"
COPY_COMMAND = "copy_legacy_text_to_public_profile_draft"


# --- fixtures and helpers --------------------------------------------------------------------------


def _describe(engine: Engine, character: uuid.UUID, **fields: str | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO character.character_descriptions (character_id, background, appearance, notes)
                VALUES (:c, :background, :appearance, :notes)
                ON CONFLICT (character_id) DO UPDATE SET background = EXCLUDED.background,
                    appearance = EXCLUDED.appearance, notes = EXCLUDED.notes
            """),
            {"c": character, "background": None, "appearance": None, "notes": None, **fields},
        )


@pytest.fixture
def source_npc(postgres_engine: Engine, npc: uuid.UUID) -> uuid.UUID:
    """The restricted-cast NPC, with legacy description text in all three fields."""
    _describe(postgres_engine, npc, background=FULL, appearance=SRC_APPEARANCE, notes=NOTES)
    return npc


@pytest.fixture
def pc(postgres_engine: Engine, g: Gate) -> uuid.UUID:
    with postgres_engine.begin() as connection:
        character = make_character(
            connection, g.world_id, name="Copied Hero", entity_type_code="player_character"
        )
        connection.execute(
            text("INSERT INTO character.player_characters (player_character_id) VALUES (:c)"),
            {"c": character},
        )
    _describe(postgres_engine, character, background=FULL, appearance=SRC_APPEARANCE, notes=NOTES)
    return character


def entity_version(engine: Engine, character: uuid.UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :c"), {"c": character}
            ).scalar_one()
        )


def copy(
    client_factory: Factory,
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    token: int | None,
    field: str,
    *,
    key: str | None = None,
    extra: dict[str, object] | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    payload: dict[str, object] = {"expected_row_version": token, "field": field, **(extra or {})}
    with client_factory(user) as client:
        return client.post(url(g, character, "/draft/copy-legacy"), json=payload, headers=headers)


def update_source(
    g: Gate, character: uuid.UUID, user: uuid.UUID, **overrides: str | None
) -> Callable[[Connection], Any]:
    """The real `update_npc` command with the NPC's current values and `overrides`."""

    def run(connection: Connection) -> Any:
        current = connection.execute(
            text("""
                SELECT e.canonical_name, e.summary, e.row_version, c.species_id, c.size_category,
                       c.origin_location_id, d.background, d.appearance, d.notes
                FROM core.entities e
                JOIN character.characters c ON c.character_id = e.entity_id
                LEFT JOIN character.character_descriptions d ON d.character_id = e.entity_id
                WHERE e.entity_id = :c
            """),
            {"c": character},
        ).one()
        values = {
            "background": current.background,
            "appearance": current.appearance,
            "notes": current.notes,
            **overrides,
        }
        return update_npc(
            connection,
            npc_id=character,
            campaign_id=g.campaign_id,
            actor_user_id=user,
            expected_row_version=int(current.row_version),
            name=current.canonical_name,
            summary=current.summary,
            species_id=current.species_id,
            size_category=current.size_category,
            origin_location_id=current.origin_location_id,
            **values,
        )

    return run


def audit_dump(engine: Engine, g: Gate) -> str:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT l.command_name, a.code, l.changed_fields, l.reason FROM audit.change_log l "
                "JOIN audit.change_actions a ON a.change_action_id = l.change_action_id "
                "WHERE l.world_id = :w ORDER BY l.change_log_id"
            ),
            {"w": g.world_id},
        ).all()
    return json.dumps([list(r) for r in rows], default=str)


def copy_audit(engine: Engine, g: Gate) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            dict(r)
            for r in connection.execute(
                text(
                    "SELECT l.changed_fields, a.code AS change_action_code FROM audit.change_log l "
                    "JOIN audit.change_actions a ON a.change_action_id = l.change_action_id "
                    "WHERE l.world_id = :w AND l.command_name = :n ORDER BY l.change_log_id"
                ),
                {"w": g.world_id, "n": COPY_COMMAND},
            ).mappings()
        ]


def state(engine: Engine, g: Gate, character: uuid.UUID) -> tuple[Any, ...]:
    """The draft, every release and every audit row: a refusal changes none of them."""
    with engine.connect() as connection:
        draft = connection.execute(
            text(
                "SELECT * FROM campaign.character_public_profiles "
                "WHERE campaign_id = :c AND character_id = :ch"
            ),
            {"c": g.campaign_id, "ch": character},
        ).all()
    return (tuple(map(tuple, draft)), release_rows(engine, g, character), audit_dump(engine, g))


# --- the copy itself ------------------------------------------------------------------------------------------


def test_a_permitted_gm_copies_a_legacy_field_into_a_new_draft_and_nothing_leaks(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    source_version = entity_version(postgres_engine, c)
    response = copy(client_factory, m.gm_user_id, g, c, None, "background")
    assert code(response) == 201, body(response)
    receipt = body(response)
    assert receipt["row_version"] == 1 and receipt["created"] is True and receipt["changed"] is True
    assert receipt["origin_entity_row_version"] == source_version
    assert FULL not in response.text and NOTES not in response.text  # no copied text in the receipt
    after = row(postgres_engine, g, c)
    assert after["public_background"] == FULL and after["background_origin"] == "legacy_background"
    assert after["background_source"] == source_version and after["background_watermark"] == 1
    assert after["public_appearance"] is None and after["appearance_origin"] == "authored"
    assert after["appearance_source"] is None and after["appearance_watermark"] is None
    # One audit row: the field, the origin and the versions; never the text.
    audit = copy_audit(postgres_engine, g)
    assert len(audit) == 1 and audit[0]["change_action_code"] == "created"
    assert audit[0]["changed_fields"] == {
        "source_field": "background",
        "origin": "legacy_background",
        "origin_entity_row_version": source_version,
        "row_version": 1,
    }
    assert FULL not in audit_dump(postgres_engine, g) and NOTES not in audit_dump(
        postgres_engine, g
    )
    # Restricted readers see that it is withheld, with its provenance, never the text.
    seen = Seen()
    for user in (g.o1_user_id, m.ast_user_id):
        view = body(seen.take(read(client_factory, user, g, c)))
        assert background(view) == (None, True)  # type: ignore[arg-type]
        assert view["draft"]["public_background_origin_entity_row_version"] == source_version  # type: ignore[index]
    seen.assert_none_of(FULL, SRC_APPEARANCE, NOTES)
    assert background(profile(client_factory, m.gm_user_id, g, c)) == (FULL, False)


def test_a_copy_over_an_existing_draft_keeps_the_other_field_and_bumps_the_version(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": A_TEXT})) == 201  # fmt: skip
    response = copy(client_factory, m.gm_user_id, g, c, 1, "background")
    assert code(response) == 200 and body(response)["row_version"] == 2
    assert body(response)["created"] is False
    after = row(postgres_engine, g, c)
    assert after["public_appearance"] == A_TEXT and after["appearance_origin"] == "authored"
    assert after["public_background"] == FULL and after["background_watermark"] == 2
    # Copying over authored text turns that field legacy and restricted.
    over = copy(client_factory, m.gm_user_id, g, c, 2, "appearance")
    assert code(over) == 200
    after = row(postgres_engine, g, c)
    assert after["public_appearance"] == SRC_APPEARANCE
    assert after["appearance_origin"] == "legacy_appearance" and after["appearance_watermark"] == 3
    assert after["background_watermark"] == 2  # the other field's watermark is untouched (I3)
    view = profile(client_factory, g.o1_user_id, g, c)
    assert view["draft"]["public_appearance_withheld"] is True and background(view) == (None, True)


def test_every_copy_starts_new_restricted_content_even_with_identical_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    assert code(copy(client_factory, m.gm_user_id, g, c, None, "background")) == 201
    assert code(release(client_factory, g.o2_user_id, g, c, 1)) == 201  # covers the copy
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (FULL, False)
    again = copy(client_factory, m.gm_user_id, g, c, 1, "background")  # the same source text
    assert code(again) == 200 and body(again)["changed"] is True and body(again)["row_version"] == 2
    assert row(postgres_engine, g, c)["background_watermark"] == 2
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (None, True)
    assert code(release(client_factory, g.o1_user_id, g, c, 2)) == 403
    assert code(release(client_factory, g.o2_user_id, g, c, 2)) == 201
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (FULL, False)


def test_a_copy_after_a_source_edit_records_the_new_source_version_and_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    assert code(copy(client_factory, m.gm_user_id, g, c, None, "background")) == 201
    first = row(postgres_engine, g, c)["background_source"]
    with postgres_engine.begin() as connection:
        update_source(g, c, m.gm_user_id, background=NEW_SOURCE)(connection)
    # The draft keeps the old copy and its source version until a new copy is made.
    assert row(postgres_engine, g, c)["public_background"] == FULL
    assert code(copy(client_factory, m.gm_user_id, g, c, 1, "background")) == 200
    after = row(postgres_engine, g, c)
    assert after["public_background"] == NEW_SOURCE
    assert after["background_source"] == entity_version(postgres_engine, c) > first


# --- the excerpt regressions, through the real copy route -------------------------------------------------------------------


def _copied_then_cut_and_released(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, c: uuid.UUID
) -> int:
    """Authored appearance (v1), a copy (v2), cut to an excerpt (v3), released by a permitted owner."""
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": A_TEXT})) == 201  # fmt: skip
    assert code(copy(client_factory, m.gm_user_id, g, c, 1, "background")) == 200
    assert code(edit_background(client_factory, m.gm_user_id, g, c, 2, EXCERPT)) == 200
    assert code(release(client_factory, g.o2_user_id, g, c, 3)) == 201
    return 3


def test_cutting_a_copy_releasing_the_excerpt_then_appending_source_text_is_withheld_again(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    seen = Seen()
    version = _copied_then_cut_and_released(client_factory, postgres_engine, g, m, c)
    view = body(seen.take(read(client_factory, g.o1_user_id, g, c)))
    assert background(view) == (EXCERPT, False)  # type: ignore[arg-type]
    appended = edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT + APPENDED)
    assert code(appended) == 200
    view = body(seen.take(read(client_factory, g.o1_user_id, g, c)))
    assert background(view) == (None, True)  # type: ignore[arg-type]
    assert view["latest_release"]["public_background"] == EXCERPT  # type: ignore[index]
    assert code(seen.take(release(client_factory, g.o1_user_id, g, c, version + 1))) == 403
    seen.assert_none_of(APPENDED, FULL)
    assert code(release(client_factory, g.o2_user_id, g, c, version + 1)) == 201
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (EXCERPT + APPENDED, False)


@pytest.mark.parametrize("restore", ["edit", "recopy"])
def test_restoring_the_full_text_after_an_excerpt_release_is_withheld_until_released(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    source_npc: uuid.UUID,
    restore: str,
) -> None:
    c = source_npc
    seen = Seen()
    version = _copied_then_cut_and_released(client_factory, postgres_engine, g, m, c)
    if restore == "edit":
        restored = edit_background(client_factory, m.gm_user_id, g, c, version, FULL)
    else:
        restored = copy(client_factory, m.gm_user_id, g, c, version, "background")
    assert code(restored) == 200
    assert background(body(seen.take(read(client_factory, g.o1_user_id, g, c)))) == (None, True)  # type: ignore[arg-type]
    assert code(seen.take(release(client_factory, g.o1_user_id, g, c, version + 1))) == 403
    seen.assert_none_of(FULL)
    assert code(release(client_factory, g.o2_user_id, g, c, version + 1)) == 201
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (FULL, False)


def test_editing_the_other_field_after_a_copy_release_never_restricts_the_released_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    assert code(copy(client_factory, m.gm_user_id, g, c, None, "background")) == 201
    assert code(release(client_factory, g.o2_user_id, g, c, 1)) == 201
    watermark = row(postgres_engine, g, c)["background_watermark"]
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": A_TEXT})) == 200  # fmt: skip
    assert row(postgres_engine, g, c)["background_watermark"] == watermark
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (FULL, False)


# --- who may copy what --------------------------------------------------------------------------------------------------------


def test_an_npc_copy_needs_the_world_capability_a_player_character_copy_does_not(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    source_npc: uuid.UUID,
    pc: uuid.UUID,
) -> None:
    before = state(postgres_engine, g, source_npc)
    for user in (g.o1_user_id, m.ast_user_id):  # campaign canon.edit, no world.canon.read_private
        refused = copy(client_factory, user, g, source_npc, None, "background")
        assert (code(refused), error_code(refused)) == (403, "world_authority_required")
        assert FULL not in refused.text
    assert state(postgres_engine, g, source_npc) == before
    for user in (g.player_user_id, g.manager_user_id):  # no role canon.edit
        assert code(copy(client_factory, user, g, source_npc, None, "background")) == 403
    assert code(copy(client_factory, make_outsider(postgres_engine), g, source_npc, None, "background")) == 404  # fmt: skip
    # A player character needs role canon.edit only: every GM role copies, and every reader sees it.
    for index, user in enumerate((g.o1_user_id, m.gm_user_id, m.ast_user_id)):
        character = make_pc_with_source(postgres_engine, g, f"Hero {index}")
        assert code(copy(client_factory, user, g, character, None, "background")) == 201
        for reader in (g.o1_user_id, m.gm_user_id, m.ast_user_id):
            assert background(profile(client_factory, reader, g, character)) == (FULL, False)
    assert code(copy(client_factory, m.gm_user_id, g, pc, None, "appearance")) == 201


def make_pc_with_source(engine: Engine, g: Gate, name: str) -> uuid.UUID:
    with engine.begin() as connection:
        character = make_character(
            connection, g.world_id, name=name, entity_type_code="player_character"
        )
        connection.execute(
            text("INSERT INTO character.player_characters (player_character_id) VALUES (:c)"),
            {"c": character},
        )
    _describe(engine, character, background=FULL, appearance=SRC_APPEARANCE, notes=NOTES)
    return character


def test_unsupported_kinds_fields_and_provenance_in_the_request_are_refused(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    plain = make_one_character(postgres_engine, g, "Plain Character")  # kind `character`
    _describe(postgres_engine, plain, background=FULL)
    before = state(postgres_engine, g, c)
    assert code(copy(client_factory, m.gm_user_id, g, plain, None, "background")) == 404
    assert code(copy(client_factory, m.gm_user_id, g, uuid.uuid4(), None, "background")) == 404
    for field in ("notes", "public_background", "", "Background"):
        assert code(copy(client_factory, m.gm_user_id, g, c, None, field)) == 422
    for extra in (
        {"origin": "authored"},
        {"origin_entity_row_version": 1},
        {"public_background": "typed"},
        {"restricted_row_version": 1},
        {"text": "typed"},
    ):
        assert code(copy(client_factory, m.gm_user_id, g, c, None, "background", extra=extra)) == 422  # fmt: skip
    assert state(postgres_engine, g, c) == before
    assert NOTES not in audit_dump(postgres_engine, g)


@pytest.mark.parametrize("blank", [None, "", "   \n "])
def test_an_empty_source_field_is_refused_and_writes_nothing(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    source_npc: uuid.UUID,
    blank: str | None,
) -> None:
    _describe(postgres_engine, source_npc, background=blank, appearance=SRC_APPEARANCE)
    before = state(postgres_engine, g, source_npc)
    refused = copy(client_factory, m.gm_user_id, g, source_npc, None, "background")
    assert (code(refused), error_code(refused)) == (409, "public_profile_legacy_text_missing")
    assert state(postgres_engine, g, source_npc) == before
    with postgres_engine.begin() as connection:  # a character with no description row at all
        connection.execute(
            text("DELETE FROM character.character_descriptions WHERE character_id = :c"),
            {"c": source_npc},
        )
    assert code(copy(client_factory, m.gm_user_id, g, source_npc, None, "appearance")) == 409


def test_denies_and_an_inactive_character_refuse_a_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    deny(postgres_engine, g, g.o2, "canon.edit", c)
    refused = copy(client_factory, g.o2_user_id, g, c, None, "background")
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")
    deny(postgres_engine, g, m.gm, "campaign.view", c)
    assert code(copy(client_factory, m.gm_user_id, g, c, None, "background")) == 404
    assert row_count(postgres_engine, g, c) == 0
    other = make_npc_with_source(postgres_engine, g, m, "Retired NPC")
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE entity_id = :c"
            ),
            {"c": other},
        )
    inactive = copy(client_factory, g.o2_user_id, g, other, None, "background")
    assert (code(inactive), error_code(inactive)) == (409, "public_profile_character_not_active")


def row_count(engine: Engine, g: Gate, character: uuid.UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM campaign.character_public_profiles "
                    "WHERE campaign_id = :c AND character_id = :ch"
                ),
                {"c": g.campaign_id, "ch": character},
            ).scalar_one()
        )


def make_npc_with_source(engine: Engine, g: Gate, m: Members, name: str) -> uuid.UUID:
    with engine.begin() as connection:
        character = make_character(connection, g.world_id, name=name, entity_type_code="npc")
        connection.execute(
            text("INSERT INTO character.npcs (npc_id) VALUES (:c)"), {"c": character}
        )
    _describe(engine, character, background=FULL)
    return character


# --- the profile read advertises what can be copied ----------------------------------------------------------------------------------


def test_the_profile_read_reports_copyable_fields_only_to_a_caller_who_may_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    _describe(postgres_engine, c, background=FULL, appearance=None, notes=NOTES)
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": A_TEXT})) == 201  # fmt: skip
    for user in (m.gm_user_id, g.o2_user_id):
        assert profile(client_factory, user, g, c)["legacy_copy"] == {
            "appearance": False,
            "background": True,
        }
    for user in (g.o1_user_id, m.ast_user_id):  # the source read fails
        assert profile(client_factory, user, g, c)["legacy_copy"] is None
    deny(postgres_engine, g, g.o2, "canon.edit", c)  # can read, cannot edit
    assert profile(client_factory, g.o2_user_id, g, c)["legacy_copy"] is None
    assert NOTES not in json.dumps(profile(client_factory, m.gm_user_id, g, c))


# --- stale tokens, keyed retries, permission loss, atomicity -----------------------------------------------------------------------


def test_stale_and_missing_tokens_are_conflicts_that_write_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    missing = copy(client_factory, m.gm_user_id, g, c, 3, "background")  # a token, but no draft
    assert (code(missing), error_code(missing)) == (409, "public_profile_draft_missing")
    assert code(copy(client_factory, m.gm_user_id, g, c, None, "background")) == 201
    before = state(postgres_engine, g, c)
    for token in (None, 2, 5):
        stale = copy(client_factory, m.gm_user_id, g, c, token, "appearance")
        assert (code(stale), error_code(stale)) == (409, "stale_write"), token
    assert state(postgres_engine, g, c) == before
    # A copy and a save with one token: the first wins, the second is stale.
    assert code(copy(client_factory, m.gm_user_id, g, c, 1, "appearance")) == 200
    late = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "late"})  # fmt: skip
    assert (code(late), error_code(late)) == (409, "stale_write")


def test_a_copy_replay_returns_the_receipt_but_a_caller_who_lost_the_source_read_gets_403(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    key = f"copy-{uuid.uuid4().hex[:8]}"
    first = copy(client_factory, m.gm_user_id, g, c, None, "background", key=key)
    assert code(first) == 201
    before = state(postgres_engine, g, c)
    replay = copy(client_factory, m.gm_user_id, g, c, None, "background", key=key)
    assert code(replay) == 201 and body(replay)["row_version"] == 1
    assert FULL not in replay.text  # the stored receipt holds no text
    assert state(postgres_engine, g, c) == before
    # The same key for another field or another character is the idempotency conflict, not a replay.
    other_field = copy(client_factory, m.gm_user_id, g, c, None, "appearance", key=key)
    assert code(other_field) == 409 and error_code(other_field) != "stale_write"
    other = make_npc_with_source(postgres_engine, g, m, "Another NPC")
    different = copy(client_factory, m.gm_user_id, g, other, None, "background", key=key)
    assert code(different) == 409 and error_code(different) != "stale_write"
    assert row_count(postgres_engine, g, other) == 0
    # Losing the source read (here the world role) refuses the replay: the read is the authority.
    with postgres_engine.begin() as connection:
        end_world_membership(connection, world_id=g.world_id, user_id=m.gm_user_id)
    lost = copy(client_factory, m.gm_user_id, g, c, None, "background", key=key)
    assert (code(lost), error_code(lost)) == (403, "world_authority_required")
    assert FULL not in lost.text
    assert state(postgres_engine, g, c) == before


def test_a_copy_that_fails_after_its_write_leaves_no_draft_no_audit_and_a_reusable_key(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    source_npc: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dnd_ai.api.character_public_profile as api

    c = source_npc
    key = f"atomic-{uuid.uuid4().hex[:8]}"
    real = api.record_change_log

    def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(api, "record_change_log", failing)
    failed = copy(client_factory, m.gm_user_id, g, c, None, "background", key=key)
    assert code(failed) == 500  # the transaction is rolled back with the request
    monkeypatch.setattr(api, "record_change_log", real)
    assert row_count(postgres_engine, g, c) == 0 and copy_audit(postgres_engine, g) == []
    retry = copy(client_factory, m.gm_user_id, g, c, None, "background", key=key)
    assert code(retry) == 201 and len(copy_audit(postgres_engine, g)) == 1


# --- mixed origins, clearing and recopying ---------------------------------------------------------------------------------------------


def test_mixed_origins_clear_and_recopy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    assert code(copy(client_factory, m.gm_user_id, g, c, None, "background")) == 201
    assert code(copy(client_factory, m.gm_user_id, g, c, 1, "appearance")) == 200
    seen = Seen()
    view = body(seen.take(read(client_factory, g.o1_user_id, g, c)))
    assert view["draft"]["public_appearance_withheld"] is True  # type: ignore[index]
    assert view["draft"]["public_background_withheld"] is True  # type: ignore[index]
    seen.assert_none_of(FULL, SRC_APPEARANCE)
    # A restricted GM may clear the copied background (D7-a) but not replace it; the appearance stays.
    mixed = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 2, "public_background": "typed", "public_appearance": None})  # fmt: skip
    assert (code(mixed), error_code(mixed)) == (403, "public_profile_field_withheld")
    cleared = edit_background(client_factory, g.o1_user_id, g, c, 2, None)
    assert code(cleared) == 200
    after = row(postgres_engine, g, c)
    assert after["public_background"] is None and after["background_origin"] == "authored"
    assert after["background_source"] is None and after["background_watermark"] is None
    assert after["appearance_origin"] == "legacy_appearance" and after["appearance_watermark"] == 2
    # A permitted GM copies it again: a new lineage and a new watermark.
    assert code(copy(client_factory, m.gm_user_id, g, c, 3, "background")) == 200
    after = row(postgres_engine, g, c)
    assert after["background_origin"] == "legacy_background" and after["background_watermark"] == 4
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (None, True)
    # One release by a permitted owner covers both copied fields.
    assert code(release(client_factory, g.o2_user_id, g, c, 4)) == 201
    view = profile(client_factory, g.o1_user_id, g, c)
    assert (view["draft"]["public_appearance"], background(view)) == (SRC_APPEARANCE, (FULL, False))


def test_no_response_receipt_error_or_audit_row_carries_the_copied_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    seen = Seen()
    seen.take(copy(client_factory, g.o1_user_id, g, c, None, "background"))  # 403
    seen.take(copy(client_factory, m.gm_user_id, g, c, None, "background", key="k-1"))  # 201
    seen.take(copy(client_factory, m.gm_user_id, g, c, None, "background", key="k-1"))  # replay
    seen.take(copy(client_factory, m.gm_user_id, g, c, None, "appearance"))  # 409 stale
    seen.take(copy(client_factory, m.gm_user_id, g, c, 1, "notes"))  # 422
    seen.take(copy(client_factory, m.gm_user_id, g, c, 1, "appearance"))  # 200
    for user in (g.o1_user_id, m.ast_user_id, g.player_user_id):
        seen.take(read(client_factory, user, g, c))
        seen.take(read(client_factory, user, g, c, "/releases/1"))
        seen.take(release(client_factory, user, g, c, 2))
    seen.assert_none_of(FULL, SRC_APPEARANCE, NOTES)
    dump = audit_dump(postgres_engine, g)
    with postgres_engine.connect() as connection:
        stored = json.dumps(
            [
                [r[0], r[1]]
                for r in connection.execute(
                    text(
                        "SELECT response_body, request_fingerprint FROM security.idempotent_requests WHERE campaign_id = :c"
                    ),
                    {"c": g.campaign_id},
                )
            ],
            default=str,
        )
    for marker in (FULL, SRC_APPEARANCE, NOTES):
        assert marker not in dump and marker not in stored
