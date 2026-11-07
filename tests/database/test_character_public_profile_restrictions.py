# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Copied text stays restricted until a release covers it (P03-A A2b-1, plan section 9, D7).

No copy route exists yet (A2b-2 adds it), so a copied field is seeded with `seed_copy`, the one
place these tests write a legacy-origin row directly. It writes exactly what the copy command will
(the legacy origin, the source version, and the watermark the database trigger demands); every
read, save and release in the scenarios then goes through the HTTP routes.

Cast, on one NPC (its source read needs role `canon.edit` and the world capability
`world.canon.read_private`):

- *permitted*: the delegated GM (`gm`, world editor) and the second owner (`o2`, world editor);
- *restricted*: the first owner (`o1`, no world role) and the assistant GM (`ast`, world reader).

Markers: F is the full source text, E an excerpt of it, X source text not in the excerpt.
"""

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.character_reveal import grant_character_reveal_delegation
from dnd_ai.commands.world_memberships import end_world_membership, set_world_role
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    body,
    code,
    counts,
    deny,
    draft_row,
    error_code,
    make_outsider,
    read,
    release,
    release_rows,
    save,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import make_character

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

A_TEXT = "AUTHORED-A-MARKER-1101"
FULL = "FULL-SOURCE-MARKER-F-2202"
EXCERPT = "EXCERPT-MARKER-E-3303"
APPENDED = "APPENDED-SOURCE-MARKER-X-4404"
MARKERS = (FULL, APPENDED)


# --- fixtures and helpers --------------------------------------------------------------------------


@pytest.fixture
def npc(postgres_engine: Engine, g: Gate, m: Members) -> uuid.UUID:
    """A canon, active NPC, with the world roles of the cast and a reveal delegation for `gm`."""
    with postgres_engine.begin() as connection:
        character = make_character(
            connection, g.world_id, name="Restricted NPC", entity_type_code="npc"
        )
        connection.execute(
            text("INSERT INTO character.npcs (npc_id) VALUES (:c)"), {"c": character}
        )
        for user, role in (
            (m.gm_user_id, "world_editor"),
            (g.o2_user_id, "world_editor"),
            (m.ast_user_id, "world_reader"),
        ):
            set_world_role(connection, world_id=g.world_id, user_id=user, role_code=role)
        grant_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Runs the reveals",
        )
    return character


def _origin(engine: Engine, code_: str) -> uuid.UUID:
    with engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT public_profile_field_origin_id FROM campaign.public_profile_field_origins "
                "WHERE code = :c"
            ),
            {"c": code_},
        ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def seed_copy(
    engine: Engine, g: Gate, character: uuid.UUID, field: str, text_value: str, *, source: int = 3
) -> None:
    """Writes copied (legacy-origin) text into one field of the existing draft, as the copy command
    will: the legacy origin, the source version, and a watermark equal to the new `row_version`."""
    origin = _origin(engine, f"legacy_{field}")
    with engine.begin() as connection:
        connection.execute(
            text(f"""
                UPDATE campaign.character_public_profiles SET
                    public_{field} = :t,
                    public_{field}_origin_id = :o,
                    public_{field}_origin_entity_row_version = :v,
                    public_{field}_restricted_row_version = row_version + 1
                WHERE campaign_id = :c AND character_id = :ch
            """),  # noqa: S608
            {"t": text_value, "o": origin, "v": source, "c": g.campaign_id, "ch": character},
        )


def row(engine: Engine, g: Gate, character: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as connection:
        found = (
            connection.execute(
                text("""
                SELECT d.row_version, d.public_appearance, d.public_background,
                       ao.code AS appearance_origin, bo.code AS background_origin,
                       d.public_appearance_origin_entity_row_version AS appearance_source,
                       d.public_background_origin_entity_row_version AS background_source,
                       d.public_appearance_restricted_row_version AS appearance_watermark,
                       d.public_background_restricted_row_version AS background_watermark
                FROM campaign.character_public_profiles d
                JOIN campaign.public_profile_field_origins ao
                  ON ao.public_profile_field_origin_id = d.public_appearance_origin_id
                JOIN campaign.public_profile_field_origins bo
                  ON bo.public_profile_field_origin_id = d.public_background_origin_id
                WHERE d.campaign_id = :c AND d.character_id = :ch
            """),
                {"c": g.campaign_id, "ch": character},
            )
            .mappings()
            .one()
        )
    return dict(found)


def started(
    client_factory: Factory, engine: Engine, g: Gate, character: uuid.UUID, copied: str = FULL
) -> int:
    """An authored appearance (version 1) and a copied background at version 2; returns 2."""
    assert code(save(client_factory, g.o1_user_id, g, character, {"expected_row_version": None, "public_appearance": A_TEXT})) == 201  # fmt: skip
    seed_copy(engine, g, character, "background", copied)
    return 2


class Seen:
    """Every body a restricted caller received, so a marker can be searched in all of them."""

    def __init__(self) -> None:
        self.bodies: list[str] = []

    def take(self, response: object) -> object:
        self.bodies.append(response.text)  # type: ignore[attr-defined]
        return response

    def assert_none_of(self, *markers: str) -> None:
        for marker in markers:
            assert not any(marker in b for b in self.bodies), marker


def profile(client_factory: Factory, user: uuid.UUID, g: Gate, c: uuid.UUID) -> dict[str, Any]:
    response = read(client_factory, user, g, c)
    assert code(response) == 200, body(response)
    return body(response)  # type: ignore[return-value]


def background(view: dict[str, Any]) -> tuple[str | None, bool]:
    draft = view["draft"]
    return draft["public_background"], draft["public_background_withheld"]


def edit_background(
    client_factory: Factory, user: uuid.UUID, g: Gate, c: uuid.UUID, version: int, value: str | None
) -> object:
    return save(client_factory, user, g, c, {"expected_row_version": version, "public_background": value})  # fmt: skip


# --- who is withheld what ---------------------------------------------------------------------------


def test_a_restricted_reader_sees_that_the_copy_is_withheld_never_the_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    version = started(client_factory, postgres_engine, g, npc)
    seen = Seen()
    for user in (g.o1_user_id, m.ast_user_id):  # restricted
        response = seen.take(read(client_factory, user, g, npc))
        view = body(response)
        assert view["draft"]["public_appearance"] == A_TEXT  # type: ignore[index]
        assert view["draft"]["public_appearance_withheld"] is False  # type: ignore[index]
        assert background(view) == (None, True)  # type: ignore[arg-type]
        assert view["draft"]["public_background_origin"] == "legacy_background"  # type: ignore[index]
        assert view["draft"]["public_background_origin_entity_row_version"] == 3  # type: ignore[index]
        assert view["draft"]["row_version"] == version  # type: ignore[index]
        assert view["can_release"] is False  # type: ignore[index]
    for user in (m.gm_user_id, g.o2_user_id):  # permitted
        view = profile(client_factory, user, g, npc)
        assert background(view) == (FULL, False)
        assert view["draft"]["public_background_origin"] == "legacy_background"
    # The reveal holder without a world role cannot release the uncovered copy.
    assert profile(client_factory, g.o1_user_id, g, npc)["can_release"] is False
    assert profile(client_factory, g.o2_user_id, g, npc)["can_release"] is True
    seen.assert_none_of(*MARKERS)
    # Others find nothing.
    for user in (g.player_user_id, make_outsider(postgres_engine)):
        assert code(read(client_factory, user, g, npc)) == 404


def test_a_player_character_copy_is_shown_to_every_reader_who_can_read_the_profile(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members
) -> None:
    with postgres_engine.begin() as connection:
        pc = make_character(
            connection, g.world_id, name="Hero", entity_type_code="player_character"
        )
        connection.execute(
            text("INSERT INTO character.player_characters (player_character_id) VALUES (:c)"),
            {"c": pc},
        )
        grant_character_reveal_delegation(
            connection, campaign_id=g.campaign_id, actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm, reason="r",
        )  # fmt: skip
    started(client_factory, postgres_engine, g, pc)
    for user in (g.o1_user_id, m.gm_user_id, m.ast_user_id):  # none holds a world role here
        assert background(profile(client_factory, user, g, pc)) == (FULL, False)


def test_a_reveal_holder_with_a_canon_edit_deny_and_the_world_role_reads_but_cannot_edit(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    version = started(client_factory, postgres_engine, g, npc)
    deny(postgres_engine, g, g.o2, "canon.edit", npc)
    view = profile(client_factory, g.o2_user_id, g, npc)
    assert background(view) == (FULL, False)  # a per-character deny does not enter the source rule
    assert view["can_edit"] is False and view["can_release"] is True
    refused = edit_background(client_factory, g.o2_user_id, g, npc, version, "new")
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")


# --- the excerpt regressions ---------------------------------------------------------------------------


def _release_by_permitted(client_factory: Factory, g: Gate, c: uuid.UUID, version: int) -> object:
    response = release(client_factory, g.o2_user_id, g, c, version)
    assert code(response) == 201, body(response)
    return response


def test_cutting_a_copy_to_an_excerpt_releasing_it_then_appending_source_text_restricts_it_again(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    seen = Seen()
    assert background(body(seen.take(read(client_factory, g.o1_user_id, g, c)))) == (None, True)  # type: ignore[arg-type]
    # 2. The permitted GM cuts the copy to an excerpt; still withheld from the restricted owner.
    cut = edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT)
    assert code(cut) == 200 and body(cut)["row_version"] == version + 1
    version += 1
    assert row(postgres_engine, g, c)["background_watermark"] == version
    assert background(body(seen.take(read(client_factory, g.o1_user_id, g, c)))) == (None, True)  # type: ignore[arg-type]
    # 3. A permitted release covers the excerpt: the restricted reader now sees it everywhere.
    _release_by_permitted(client_factory, g, c, version)
    view = body(seen.take(read(client_factory, g.o1_user_id, g, c)))
    assert background(view) == (EXCERPT, False)  # type: ignore[arg-type]
    assert view["latest_release"]["public_background"] == EXCERPT  # type: ignore[index]
    # 4. Append source text: withheld again, and the release still holds only the excerpt.
    appended = edit_background(
        client_factory, m.gm_user_id, g, c, version, EXCERPT + " " + APPENDED
    )
    assert code(appended) == 200
    version += 1
    view = body(seen.take(read(client_factory, g.o1_user_id, g, c)))
    assert background(view) == (None, True)  # type: ignore[arg-type]
    assert view["latest_release"]["public_background"] == EXCERPT  # type: ignore[index]
    assert (
        body(seen.take(read(client_factory, g.o1_user_id, g, c, "/releases/1")))[
            "public_background"
        ]
        == EXCERPT
    )  # type: ignore[index]  # noqa: E501
    # A restricted releaser cannot publish it; nothing is written.
    before = counts(postgres_engine, g)
    refused = seen.take(release(client_factory, g.o1_user_id, g, c, version))
    assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
    assert counts(postgres_engine, g) == before
    seen.assert_none_of(APPENDED, FULL)
    # After a permitted release the restricted reader sees the appended text.
    _release_by_permitted(client_factory, g, c, version)
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (
        EXCERPT + " " + APPENDED,
        False,
    )


def test_restoring_the_full_text_is_withheld_until_a_permitted_release(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT)) == 200
    version += 1
    _release_by_permitted(client_factory, g, c, version)
    seen = Seen()
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, FULL)) == 200
    version += 1
    assert background(body(seen.take(read(client_factory, g.o1_user_id, g, c)))) == (None, True)  # type: ignore[arg-type]
    assert code(seen.take(release(client_factory, g.o1_user_id, g, c, version))) == 403
    seen.assert_none_of(FULL)
    _release_by_permitted(client_factory, g, c, version)
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (FULL, False)


def test_editing_back_to_exactly_the_released_text_is_still_withheld_until_released_again(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT)) == 200
    version += 1
    _release_by_permitted(client_factory, g, c, version)
    assert (
        code(edit_background(client_factory, m.gm_user_id, g, c, version, "something else")) == 200
    )
    version += 1
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT)) == 200
    version += 1
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (
        None,
        True,
    )  # accepted over-restriction
    _release_by_permitted(client_factory, g, c, version)
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (EXCERPT, False)


# --- independent fields ----------------------------------------------------------------------------------------


def test_editing_the_other_field_never_restricts_a_released_one(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    _release_by_permitted(client_factory, g, c, version)
    watermark = row(postgres_engine, g, c)["background_watermark"]
    for user in (
        m.gm_user_id,
        g.o1_user_id,
    ):  # a permitted and a restricted GM each edit appearance
        response = save(client_factory, user, g, c, {"expected_row_version": version, "public_appearance": f"A{version}"})  # fmt: skip
        assert code(response) == 200, body(response)
        version += 1
        assert row(postgres_engine, g, c)["background_watermark"] == watermark  # I3
        assert background(profile(client_factory, g.o1_user_id, g, c)) == (FULL, False)
    # Then editing B restricts only B.
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, "changed")) == 200
    view = profile(client_factory, g.o1_user_id, g, c)
    assert background(view) == (None, True)
    assert view["draft"]["public_appearance_withheld"] is False
    assert view["draft"]["public_appearance"] == f"A{version - 1}"


def test_a_copied_appearance_and_a_copied_background_are_withheld_independently(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID
) -> None:
    c = npc
    started(client_factory, postgres_engine, g, c)
    seed_copy(postgres_engine, g, c, "appearance", "COPIED-APPEARANCE-MARKER-5505", source=4)
    view = profile(client_factory, g.o1_user_id, g, c)
    assert view["draft"]["public_appearance_withheld"] is True
    assert view["draft"]["public_background_withheld"] is True
    # A release covering both lifts both.
    _release_by_permitted(client_factory, g, c, view["draft"]["row_version"])
    view = profile(client_factory, g.o1_user_id, g, c)
    assert view["draft"]["public_appearance"] == "COPIED-APPEARANCE-MARKER-5505"
    assert background(view) == (FULL, False)


# --- saves: mixed refusal, clearing, stale tokens ---------------------------------------------------------------------


def test_a_save_that_puts_text_into_a_withheld_field_is_refused_whole_and_is_not_an_oracle(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    before_row, before_counts = row(postgres_engine, g, c), counts(postgres_engine, g)
    seen = Seen()
    for guess in ("some guess", FULL):  # a wrong guess and the stored text answer the same way
        refused = seen.take(
            save(
                client_factory,
                g.o1_user_id,
                g,
                c,
                {
                    "expected_row_version": version,
                    "public_appearance": "changed A",
                    "public_background": guess,
                },
            )  # fmt: skip
        )
        assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
        assert row(postgres_engine, g, c) == before_row  # nothing written, A included
        assert counts(postgres_engine, g) == before_counts
    seen.assert_none_of(FULL, "some guess")
    # The same caller saving A alone, with B left out, succeeds and leaves B alone.
    ok = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": version, "public_appearance": "changed A"})  # fmt: skip
    assert code(ok) == 200
    after = row(postgres_engine, g, c)
    assert (
        after["public_background"] == FULL
        and after["background_watermark"] == before_row["background_watermark"]
    )  # noqa: E501


def test_clearing_a_withheld_field_is_allowed_and_ends_its_lineage(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    cleared = edit_background(
        client_factory, g.o1_user_id, g, c, version, None
    )  # a restricted GM clears
    assert code(cleared) == 200, body(cleared)
    after = row(postgres_engine, g, c)
    assert after["public_background"] is None and after["background_origin"] == "authored"
    assert after["background_source"] is None and after["background_watermark"] is None
    assert after["public_appearance"] == A_TEXT  # untouched
    version += 1
    # Then the same GM writes new text: authored, and visible to everyone.
    typed = edit_background(client_factory, g.o1_user_id, g, c, version, "Brand new authored text")
    assert code(typed) == 200
    assert row(postgres_engine, g, c)["background_origin"] == "authored"
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (
        "Brand new authored text",
        False,
    )


def test_a_permitted_gm_who_clears_and_types_the_source_by_hand_writes_authored_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, None)) == 200
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version + 1, FULL)) == 200
    assert row(postgres_engine, g, c)["background_origin"] == "authored"  # D7-b, documented
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (FULL, False)


def test_a_stale_token_is_answered_before_the_withheld_refusal(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT)) == 200
    before = row(postgres_engine, g, c)
    stale = edit_background(
        client_factory, g.o1_user_id, g, c, version, "guess"
    )  # old token, text into B
    assert (code(stale), error_code(stale)) == (409, "stale_write")
    assert row(postgres_engine, g, c) == before


def test_a_release_of_a_version_whose_field_later_moved_is_stale_or_a_retry(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    assert code(edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT)) == 200
    version += 1
    _release_by_permitted(client_factory, g, c, version)
    assert (
        code(edit_background(client_factory, m.gm_user_id, g, c, version, EXCERPT + APPENDED))
        == 200
    )
    # A restricted releaser re-asking for the released version gets the existing release (200), and
    # nothing newer is covered.
    again = release(client_factory, g.o1_user_id, g, c, version)
    assert code(again) == 200 and body(again)["created"] is False
    assert background(profile(client_factory, g.o1_user_id, g, c)) == (None, True)
    # Naming a version that never existed is stale.
    stale = release(client_factory, g.o1_user_id, g, c, version + 5)
    assert (code(stale), error_code(stale)) == (409, "stale_write")
    assert len(release_rows(postgres_engine, g, c)) == 1


# --- keyed retries and permission changes ---------------------------------------------------------------------------------


def _lose_the_world_role(engine: Engine, g: Gate, user: uuid.UUID) -> None:
    with engine.begin() as connection:
        end_world_membership(connection, world_id=g.world_id, user_id=user)


def _regain_the_world_role(engine: Engine, g: Gate, user: uuid.UUID) -> None:
    with engine.begin() as connection:
        set_world_role(connection, world_id=g.world_id, user_id=user, role_code="world_editor")


def test_a_save_replay_survives_losing_the_source_read_but_not_the_d8_checks(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    key = f"save-{uuid.uuid4().hex[:8]}"
    first = edit_bg_keyed(client_factory, m.gm_user_id, g, c, version, EXCERPT, key)
    assert code(first) == 200
    _lose_the_world_role(postgres_engine, g, m.gm_user_id)
    before = row(postgres_engine, g, c)
    replay = edit_bg_keyed(client_factory, m.gm_user_id, g, c, version, EXCERPT, key)
    assert code(replay) == 200 and body(replay)["row_version"] == version + 1
    assert row(postgres_engine, g, c) == before  # nothing written
    assert EXCERPT not in replay.text  # type: ignore[attr-defined]  # a receipt holds no text
    # The D8 pre-check still runs first: a canon.edit deny refuses the replay.
    deny(postgres_engine, g, m.gm, "canon.edit", c)
    refused = edit_bg_keyed(client_factory, m.gm_user_id, g, c, version, EXCERPT, key)
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")


def edit_bg_keyed(
    client_factory: Factory,
    user: uuid.UUID,
    g: Gate,
    c: uuid.UUID,
    version: int,
    value: str,
    key: str,
) -> object:
    return save(client_factory, user, g, c, {"expected_row_version": version, "public_background": value}, key=key)  # fmt: skip


def test_a_refused_save_stores_nothing_so_its_key_runs_afresh_once_the_role_is_back(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    _lose_the_world_role(postgres_engine, g, g.o2_user_id)
    key = f"refused-{uuid.uuid4().hex[:8]}"
    refused = edit_bg_keyed(client_factory, g.o2_user_id, g, c, version, EXCERPT, key)
    assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
    _regain_the_world_role(postgres_engine, g, g.o2_user_id)
    again = edit_bg_keyed(client_factory, g.o2_user_id, g, c, version, EXCERPT, key)
    assert code(again) == 200 and body(again)["row_version"] == version + 1


def test_a_released_version_survives_losing_the_source_read_but_a_new_one_does_not(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    key = f"release-{uuid.uuid4().hex[:8]}"
    first = release(client_factory, g.o2_user_id, g, c, version, key=key)
    assert code(first) == 201
    _lose_the_world_role(postgres_engine, g, g.o2_user_id)
    before = counts(postgres_engine, g)
    replay = release(client_factory, g.o2_user_id, g, c, version, key=key)
    natural = release(client_factory, g.o2_user_id, g, c, version)
    assert code(replay) == 201 and code(natural) == 200 and body(natural)["created"] is False
    assert counts(postgres_engine, g) == before
    # A new version holding uncovered copied content is refused for the same releaser.
    assert (
        code(edit_background(client_factory, m.gm_user_id, g, c, version, "fresh copy text")) == 200
    )
    refused = release(client_factory, g.o2_user_id, g, c, version + 1)
    assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
    # D8 still precedes the replay: a whole-character deny makes the same keyed replay a 404.
    deny(postgres_engine, g, g.o2, "campaign.view", c)
    assert code(release(client_factory, g.o2_user_id, g, c, version, key=key)) == 404
    assert code(release(client_factory, g.o2_user_id, g, c, version)) == 404


# --- disclosure ---------------------------------------------------------------------------------------------------------------


def test_copied_text_is_in_no_error_receipt_or_audit_row(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = started(client_factory, postgres_engine, g, c)
    seen = Seen()
    seen.take(edit_background(client_factory, g.o1_user_id, g, c, version, "guess"))  # 403
    seen.take(release(client_factory, g.o1_user_id, g, c, version))  # 403
    seen.take(
        edit_background(client_factory, m.gm_user_id, g, c, version, FULL + APPENDED)
    )  # receipt
    seen.take(edit_background(client_factory, m.gm_user_id, g, c, version, "stale"))  # 409
    with postgres_engine.connect() as connection:
        audit = connection.execute(
            text(
                "SELECT command_name, changed_fields, reason FROM audit.change_log WHERE world_id = :w"
            ),
            {"w": g.world_id},
        ).all()
    dump = json.dumps([[r[0], r[1], r[2]] for r in audit], default=str)
    for marker in (FULL, APPENDED, "guess"):
        assert marker not in dump
        seen.assert_none_of(marker)
