# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The player-profile copy route (P03-A A5c, design sections 9.3 to 9.7), end to end over HTTP.

`POST .../public-profile/draft/copy-player-profile` copies one of nine eligible fields of the version
of a campaign player profile the caller read into a draft field, as restricted `player_profile` text.
The profile itself is written only by the fixture helper (`tests/player_profile_support.py`), the
stand-in for P03-B; nothing here writes a draft field except the real route (and the A2b legacy copy,
for the mixed-origin cases).

Cast, on one NPC: every caller below passes the player-profile read rule (effective `canon.edit`) unless
a `canon.edit` deny on the character removes it. `o1` and `o2` (owners), `gm` and `ast` copy; a player
cannot reach the route; `o2` with a deny is the *restricted* reader (still an owner with reveal
authority, so still allowed to read the draft and to release it).

New-behaviour tests: every test here (the route did not exist at the parent). The A2b regressions
(`test_character_public_profile_copy.py`) are untouched.
"""

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.domain.player_profiles import (
    COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS,
    PLAYER_PROFILE_FIELDS,
)
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (
    body,
    code,
    deny,
    error_code,
    make_one_character,
    read,
    release,
    release_rows,
    save,
    url,
)
from tests.database.test_character_public_profile_restrictions import (  # noqa: F401 - fixtures
    Seen,
    npc,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import rev  # noqa: F401 - fixture
from tests.database.test_character_revelations_discovery import people  # noqa: F401 - fixture
from tests.factories import make_character
from tests.player_profile_support import (
    edit_player_profile,
    markers,
    seed_player_profile,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

COPY_COMMAND = "copy_player_profile_field_to_public_profile_draft"
EXCERPT = "PP-EXCERPT-MARKER-3141"
APPENDED = "PP-APPENDED-MARKER-2718"
LEGACY_FULL = "LEGACY-FULL-MARKER-1618"


# --- fixtures and helpers --------------------------------------------------------------------------------


@pytest.fixture
def source(postgres_engine: Engine, g: Gate, npc: uuid.UUID) -> dict[str, str]:
    """A player profile of the NPC in the Gate's campaign (head version 1), every field marked."""
    fields = markers("COPY")
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=npc,
        editor_membership_id=g.o1,
        fields=fields,
    )
    return fields


def copy_pp(
    factory: Factory,
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    *,
    draft: int | None = None,
    token: int = 1,
    source_field: str = "personality",
    target: str = "public_background",
    key: str | None = None,
    extra: dict[str, object] | None = None,
    omit: tuple[str, ...] = (),
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    payload: dict[str, object] = {
        "expected_row_version": draft,
        "expected_player_profile_row_version": token,
        "source_field": source_field,
        "target_field": target,
        **(extra or {}),
    }
    for name in omit:
        payload.pop(name)
    with factory(user) as client:
        return client.post(
            url(g, character, "/draft/copy-player-profile"), json=payload, headers=headers
        )


def draft(engine: Engine, g: Gate, character: uuid.UUID) -> dict[str, Any] | None:
    """The draft row with its origins, provenance (as the cited profile *version number* and field
    code) and watermarks, or `None`."""
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("""
                    SELECT d.row_version, d.public_appearance, d.public_background,
                           d.public_summary,
                           ao.code AS appearance_origin, bo.code AS background_origin,
                           d.public_appearance_origin_entity_row_version AS appearance_legacy,
                           d.public_background_origin_entity_row_version AS background_legacy,
                           (SELECT v.profile_row_version FROM
                              campaign.character_player_profile_versions v WHERE
                              v.character_player_profile_version_id =
                              d.public_appearance_origin_player_profile_version_id) AS a_version,
                           (SELECT v.profile_row_version FROM
                              campaign.character_player_profile_versions v WHERE
                              v.character_player_profile_version_id =
                              d.public_background_origin_player_profile_version_id) AS b_version,
                           (SELECT f.code FROM campaign.player_profile_fields f WHERE
                              f.player_profile_field_id =
                              d.public_appearance_origin_player_profile_field_id) AS a_field,
                           (SELECT f.code FROM campaign.player_profile_fields f WHERE
                              f.player_profile_field_id =
                              d.public_background_origin_player_profile_field_id) AS b_field,
                           d.public_appearance_restricted_row_version AS a_mark,
                           d.public_background_restricted_row_version AS b_mark
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
            .one_or_none()
        )
    return None if row is None else dict(row)


def profile_state(engine: Engine, g: Gate, character: uuid.UUID) -> tuple[int, int] | None:
    """(head `row_version`, number of versions), or `None` without a profile: a copy never changes
    either."""
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT h.row_version, (SELECT count(*) FROM
                  campaign.character_player_profile_versions v
                  WHERE v.character_player_profile_id = h.character_player_profile_id)
                FROM campaign.character_player_profiles h
                WHERE h.campaign_id = :c AND h.character_id = :ch
            """),
            {"c": g.campaign_id, "ch": character},
        ).one_or_none()
    return None if row is None else (int(row[0]), int(row[1]))


def receipts(engine: Engine) -> int:
    """Stored idempotency receipts over every receipt table."""
    with engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_name LIKE '%idempot%' AND table_type = 'BASE TABLE'"
            )
        ).all()
        return sum(
            int(connection.execute(text(f"SELECT count(*) FROM {s}.{t}")).scalar_one())  # noqa: S608
            for s, t in tables
        )


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


def state(engine: Engine, g: Gate, character: uuid.UUID) -> tuple[Any, ...]:
    """Everything a refusal must leave alone: the draft, the releases, the audit rows, the receipts
    and the player profile."""
    return (
        draft(engine, g, character),
        release_rows(engine, g, character),
        audit_dump(engine, g),
        receipts(engine),
        profile_state(engine, g, character),
    )


def legacy_copy(
    factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID, draft: int | None,
    field: str = "background",
) -> Any:  # fmt: skip
    """The real A2b legacy copy route (the NPC's description is the source)."""
    with factory(user) as client:
        return client.post(
            url(g, character, "/draft/copy-legacy"),
            json={"expected_row_version": draft, "field": field},
        )


def describe(engine: Engine, character: uuid.UUID, **fields: str | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO character.character_descriptions (character_id, background, appearance)
                VALUES (:c, :background, :appearance)
                ON CONFLICT (character_id) DO UPDATE SET background = EXCLUDED.background,
                    appearance = EXCLUDED.appearance
            """),
            {"c": character, "background": None, "appearance": None, **fields},
        )


def view(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> dict[str, Any]:
    response = read(factory, user, g, character)
    assert code(response) == 200, body(response)
    return body(response)  # type: ignore[return-value]


# --- the copy itself -------------------------------------------------------------------------------------


def test_a_gm_copies_a_field_into_a_new_draft_and_nothing_leaks(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    profile_before = profile_state(postgres_engine, g, npc)
    response = copy_pp(client_factory, g.o1_user_id, g, npc, key="k-new")
    assert code(response) == 201, body(response)
    payload = body(response)
    assert set(payload) == {
        "character_public_profile_id",
        "character_id",
        "row_version",
        "created",
        "changed",
        "player_profile_row_version",
        "source_field",
        "target_field",
    }
    assert payload["row_version"] == 1 and payload["created"] is True and payload["changed"] is True
    assert payload["player_profile_row_version"] == 1
    assert (payload["source_field"], payload["target_field"]) == (
        "personality",
        "public_background",
    )
    assert source["personality"] not in response.text
    row = draft(postgres_engine, g, npc)
    assert row is not None
    assert row["public_background"] == source["personality"]
    assert (row["background_origin"], row["b_version"], row["b_field"]) == (
        "player_profile",
        1,
        "personality",
    )
    assert row["b_mark"] == 1 and row["background_legacy"] is None
    # The other field and the summary are untouched; nothing is published.
    assert (row["appearance_origin"], row["public_appearance"], row["public_summary"]) == (
        "authored",
        None,
        None,
    )
    assert release_rows(postgres_engine, g, npc) == []
    assert profile_state(postgres_engine, g, npc) == profile_before  # the profile is never written
    audit = copy_audit(postgres_engine, g)
    assert [a["change_action_code"] for a in audit] == ["created"]
    assert audit[0]["changed_fields"] == {
        "source_field": "personality",
        "target_field": "public_background",
        "origin": "player_profile",
        "player_profile_row_version": 1,
        "row_version": 1,
    }
    assert source["personality"] not in audit_dump(postgres_engine, g)


def test_a_copy_over_an_existing_draft_keeps_the_other_field_and_bumps_the_version(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    created = save(
        client_factory,
        g.o1_user_id,
        g,
        npc,
        {"expected_row_version": None, "public_appearance": "authored face", "public_summary": "S"},
    )
    assert code(created) == 201
    response = copy_pp(client_factory, g.o1_user_id, g, npc, draft=1, target="public_background")
    assert code(response) == 200 and body(response)["created"] is False
    assert body(response)["row_version"] == 2
    row = draft(postgres_engine, g, npc)
    assert row is not None
    assert (row["public_appearance"], row["appearance_origin"], row["a_mark"]) == (
        "authored face",
        "authored",
        None,
    )
    assert row["public_summary"] == "S" and row["public_background"] == source["personality"]
    assert (row["background_origin"], row["b_mark"], row["row_version"]) == ("player_profile", 2, 2)


@pytest.mark.parametrize("source_field", COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS)
def test_each_of_the_nine_eligible_fields_copies_to_either_target(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID,
    source: dict[str, str], source_field: str,
) -> None:  # fmt: skip
    response = copy_pp(client_factory, g.o1_user_id, g, npc, source_field=source_field)
    assert code(response) == 201, body(response)
    response = copy_pp(
        client_factory, g.o1_user_id, g, npc, draft=1, source_field=source_field, target="public_appearance"
    )  # fmt: skip
    assert code(response) == 200, body(response)
    row = draft(postgres_engine, g, npc)
    assert row is not None
    assert row["public_background"] == row["public_appearance"] == source[source_field]
    assert (row["a_field"], row["b_field"]) == (source_field, source_field)
    assert (row["a_version"], row["b_version"]) == (1, 1)
    assert (row["a_mark"], row["b_mark"]) == (2, 1)


def test_every_copy_starts_new_restricted_content_even_with_identical_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    assert code(release(client_factory, g.o2_user_id, g, npc, 1)) == 201
    again = copy_pp(client_factory, g.o1_user_id, g, npc, draft=1)
    assert code(again) == 200 and body(again)["row_version"] == 2
    row = draft(postgres_engine, g, npc)
    assert (
        row is not None and row["b_mark"] == 2 and row["public_background"] == source["personality"]
    )


def test_a_copy_cites_the_version_the_caller_read_not_a_newer_one_and_flags_the_change(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    new = {**source, "personality": "PP-NEW-PERSONALITY-5959"}
    assert (
        edit_player_profile(
            postgres_engine, campaign_id=g.campaign_id, character_id=npc,
            editor_membership_id=g.o1, fields=new,
        )
        == 2
    )  # fmt: skip
    stale = copy_pp(client_factory, g.o1_user_id, g, npc, token=1)
    assert (code(stale), error_code(stale)) == (409, "player_profile_source_changed")
    assert draft(postgres_engine, g, npc) is None
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc, token=2)) == 201
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["public_background"] == "PP-NEW-PERSONALITY-5959"
    assert row["b_version"] == 2


# --- validation and refusals -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "omit"),
    [
        pytest.param({"source_field": "boundaries"}, (), id="boundaries"),
        pytest.param({"source_field": "profile_notes"}, (), id="profile_notes"),
        pytest.param({"source_field": "backstory"}, (), id="unknown-source"),
        pytest.param({"source_field": None}, (), id="null-source"),
        pytest.param({"target_field": "public_summary"}, (), id="summary-target"),
        pytest.param({"target_field": "appearance"}, (), id="unknown-target"),
        pytest.param({"expected_player_profile_row_version": 0}, (), id="zero-token"),
        pytest.param({"expected_row_version": 0}, (), id="zero-draft-token"),
        pytest.param({}, ("expected_player_profile_row_version",), id="missing-source-token"),
        pytest.param({}, ("expected_row_version",), id="missing-draft-token"),
        pytest.param({"text": "typed"}, (), id="extra-text"),
        pytest.param({"origin": "authored"}, (), id="extra-origin"),
        pytest.param({"public_background_restricted_row_version": 9}, (), id="extra-watermark"),
        pytest.param({"field": "personality"}, (), id="legacy-field-name"),
    ],
)
def test_invalid_selections_are_422_and_write_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID,
    source: dict[str, str], overrides: dict[str, object], omit: tuple[str, ...],
) -> None:  # fmt: skip
    before = state(postgres_engine, g, npc)
    seen = Seen()
    response = seen.take(copy_pp(client_factory, g.o1_user_id, g, npc, extra=overrides, omit=omit))
    assert code(response) == 422, body(response)
    seen.assert_none_of(*source.values())
    assert state(postgres_engine, g, npc) == before


def test_the_nine_request_codes_are_exactly_the_copy_eligible_fields() -> None:
    from dnd_ai.api.character_public_profile import CopyPlayerProfileFieldRequest

    literal = CopyPlayerProfileFieldRequest.model_fields["source_field"].annotation
    assert set(literal.__args__) == set(COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS)  # type: ignore[union-attr]
    assert set(PLAYER_PROFILE_FIELDS) - set(COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS) == {
        "boundaries",
        "profile_notes",
    }


def test_conflicts_write_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    # No draft yet, but a draft token: 409 public_profile_draft_missing.
    before = state(postgres_engine, g, npc)
    missing = copy_pp(client_factory, g.o1_user_id, g, npc, draft=1)
    assert (code(missing), error_code(missing)) == (409, "public_profile_draft_missing")
    assert state(postgres_engine, g, npc) == before
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    # A draft already exists but the caller said "none": a lost first-save race, 409 stale_write.
    before = state(postgres_engine, g, npc)
    lost = copy_pp(client_factory, g.o1_user_id, g, npc, draft=None)
    assert (code(lost), error_code(lost)) == (409, "stale_write")
    # A stale draft token (stale write) is a stale_write, never a source change.
    stale = copy_pp(client_factory, g.o1_user_id, g, npc, draft=7)
    assert (code(stale), error_code(stale)) == (409, "stale_write")
    assert state(postgres_engine, g, npc) == before


def test_a_missing_profile_and_an_empty_field_are_conflicts_that_write_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID
) -> None:  # fmt: skip
    before = state(postgres_engine, g, npc)
    none = copy_pp(client_factory, g.o1_user_id, g, npc)
    assert (code(none), error_code(none)) == (409, "player_profile_missing")
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=npc,
        editor_membership_id=g.o1,
        fields={"personality": "only this one"},
    )
    before = state(postgres_engine, g, npc)
    for empty in ("goals", "fears", "bonds"):  # never-set fields
        refused = copy_pp(client_factory, g.o1_user_id, g, npc, source_field=empty)
        assert (code(refused), error_code(refused)) == (409, "player_profile_field_empty")
    assert state(postgres_engine, g, npc) == before
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201


# --- who may copy ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["o1", "o2", "gm", "ast"])
def test_owners_gms_and_assistant_gms_may_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str], who: str,
) -> None:  # fmt: skip
    users = {"o1": g.o1_user_id, "o2": g.o2_user_id, "gm": m.gm_user_id, "ast": m.ast_user_id}
    response = copy_pp(client_factory, users[who], g, npc)
    assert code(response) == 201, body(response)
    assert source["personality"] not in response.text


def test_a_player_an_outsider_and_other_campaigns_are_refused_and_write_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    before = state(postgres_engine, g, npc)
    seen = Seen()
    for user in (g.player_user_id, uuid.uuid4()):
        refused = seen.take(copy_pp(client_factory, user, g, npc))
        assert code(refused) in (403, 404), refused.text
    seen.assert_none_of(*source.values())
    assert state(postgres_engine, g, npc) == before


def test_denies_and_an_inactive_character_refuse_a_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    before = state(postgres_engine, g, npc)
    deny(postgres_engine, g, g.o2, "canon.edit", npc)
    refused = copy_pp(client_factory, g.o2_user_id, g, npc)
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")
    deny(postgres_engine, g, m.gm, "campaign.view", npc)
    assert code(copy_pp(client_factory, m.gm_user_id, g, npc)) == 404
    assert state(postgres_engine, g, npc) == before
    other = make_one_character(postgres_engine, g, "Retired Subject")
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=other,
        editor_membership_id=g.o1,
        fields=markers("OLD"),
    )
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE entity_id = :c"
            ),
            {"c": other},
        )
    inactive = copy_pp(client_factory, g.o1_user_id, g, other)
    assert (code(inactive), error_code(inactive)) == (409, "public_profile_character_not_active")
    assert draft(postgres_engine, g, other) is None


def test_the_copy_behaves_the_same_for_every_character_kind(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID
) -> None:
    with postgres_engine.begin() as connection:
        pc = make_character(
            connection, g.world_id, name="Copied Hero", entity_type_code="player_character"
        )
        connection.execute(
            text("INSERT INTO character.player_characters (player_character_id) VALUES (:c)"),
            {"c": pc},
        )
    plain = make_one_character(postgres_engine, g, "Plain Subject")
    for kind, character in (("npc", npc), ("player_character", pc), ("character", plain)):
        fields = markers(kind)
        seed_player_profile(
            postgres_engine,
            campaign_id=g.campaign_id,
            character_id=character,
            editor_membership_id=g.o1,
            fields=fields,
        )
        response = copy_pp(client_factory, g.o1_user_id, g, character, source_field="goals")
        assert code(response) == 201, (kind, body(response))
        row = draft(postgres_engine, g, character)
        assert row is not None and row["public_background"] == fields["goals"], kind
        assert (row["background_origin"], row["b_field"]) == ("player_profile", "goals"), kind


def test_a_second_campaign_has_its_own_profile_and_cannot_reach_this_one(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str], rev: Any, people: Any,
) -> None:  # fmt: skip
    """Campaign B shares the world and timeline and holds its own profile of the same character. The
    source is selected by (route campaign, character): A's copy cites A's version and text, B's copy
    cites B's, neither draft ever holds the other's text, and A's staff cannot reach B's route."""
    campaign_b = people.campaign_b
    b_fields = markers("B")
    seed_player_profile(
        postgres_engine, campaign_id=campaign_b, character_id=npc,
        editor_membership_id=people.b_owner.membership, fields=b_fields,
    )  # fmt: skip

    def copy_b(user: uuid.UUID, **extra: object) -> Any:
        with client_factory(user) as client:
            return client.post(
                f"/campaigns/{campaign_b}/characters/{npc}/public-profile/draft/copy-player-profile",
                json={
                    "expected_row_version": None,
                    "expected_player_profile_row_version": 1,
                    "source_field": "personality",
                    "target_field": "public_background",
                    **extra,
                },
            )

    seen = Seen()
    # A's staff cannot reach B's route (not members there); no draft appears and no text leaks.
    for user in (g.o1_user_id, m.gm_user_id):
        refused = seen.take(copy_b(user))
        assert code(refused) in (403, 404), refused.text
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM campaign.character_public_profiles WHERE campaign_id = :c"
                ),
                {"c": campaign_b},
            ).scalar_one()
            == 0
        )
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    created = seen.take(copy_b(people.b_owner.user))
    assert code(created) == 201, created.text
    seen.assert_none_of(*source.values(), *b_fields.values())
    with postgres_engine.connect() as connection:
        rows = {
            row.campaign_id: row
            for row in connection.execute(
                text("""
                    SELECT d.campaign_id, d.public_background, v.campaign_id AS cited_campaign,
                           v.personality AS cited_text
                    FROM campaign.character_public_profiles d
                    JOIN campaign.character_player_profile_versions v
                      ON v.character_player_profile_version_id =
                         d.public_background_origin_player_profile_version_id
                    WHERE d.character_id = :ch
                """),
                {"ch": npc},
            )
        }
    assert rows[g.campaign_id].public_background == source["personality"]
    assert rows[campaign_b].public_background == b_fields["personality"]
    for campaign_id, row in rows.items():
        assert row.cited_campaign == campaign_id  # each draft cites its own campaign's version
    # B's later profile edit does not touch A's draft or its source_changed flag.
    edit_player_profile(
        postgres_engine, campaign_id=campaign_b, character_id=npc,
        editor_membership_id=people.b_owner.membership,
        fields={**b_fields, "personality": "B-REWRITTEN-6161"},
    )  # fmt: skip
    flagged = view(client_factory, g.o1_user_id, g, npc)["draft"]
    assert flagged["public_background_player_profile_source_changed"] is False
    assert profile_state(postgres_engine, g, npc) == (1, 1)


# --- retries ---------------------------------------------------------------------------------------------


def test_a_keyed_copy_replays_and_a_caller_who_lost_the_source_read_gets_a_refusal(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    key = f"copy-{uuid.uuid4().hex[:8]}"
    first = copy_pp(client_factory, g.o2_user_id, g, npc, key=key)
    assert code(first) == 201
    before = state(postgres_engine, g, npc)
    replay = copy_pp(client_factory, g.o2_user_id, g, npc, key=key)
    assert code(replay) == 201 and body(replay) == body(first)
    assert source["personality"] not in replay.text
    assert state(postgres_engine, g, npc) == before
    # The same key for another selection or another character is the idempotency conflict.
    other_field = copy_pp(client_factory, g.o2_user_id, g, npc, key=key, source_field="goals")
    assert code(other_field) == 409 and error_code(other_field) != "stale_write"
    other = make_one_character(postgres_engine, g, "Another Subject")
    seed_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=other,
        editor_membership_id=g.o1, fields=markers("OTH"),
    )  # fmt: skip
    different = copy_pp(client_factory, g.o2_user_id, g, other, key=key)
    assert code(different) == 409 and error_code(different) != "stale_write"
    assert draft(postgres_engine, g, other) is None
    assert state(postgres_engine, g, npc) == before
    # Losing the edit rule (a `canon.edit` deny) refuses the replay before the lookup: the source
    # read is the copy's own authority.
    deny(postgres_engine, g, g.o2, "canon.edit", npc)
    lost = copy_pp(client_factory, g.o2_user_id, g, npc, key=key)
    assert (code(lost), error_code(lost)) == (403, "public_profile_edit_denied")
    assert source["personality"] not in lost.text
    assert state(postgres_engine, g, npc) == before


def test_an_unkeyed_retry_runs_afresh_and_a_refused_keyed_copy_stores_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    retry = copy_pp(client_factory, g.o1_user_id, g, npc)  # old draft token (None)
    assert (code(retry), error_code(retry)) == (409, "stale_write")
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc, draft=1)) == 200
    # A refusal stores no receipt: the same key then succeeds with a correct token.
    key = f"refused-{uuid.uuid4().hex[:8]}"
    before = receipts(postgres_engine)
    refused = copy_pp(client_factory, g.o1_user_id, g, npc, draft=1, key=key)
    assert (code(refused), error_code(refused)) == (409, "stale_write")
    assert receipts(postgres_engine) == before
    ok = copy_pp(client_factory, g.o1_user_id, g, npc, draft=2, key=key)
    assert code(ok) == 200 and receipts(postgres_engine) == before + 1


def test_a_copy_that_fails_after_its_write_leaves_no_draft_no_audit_and_a_reusable_key(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID,
    source: dict[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    import dnd_ai.api.character_public_profile as api

    key = f"atomic-{uuid.uuid4().hex[:8]}"
    real = api.record_change_log
    before = state(postgres_engine, g, npc)

    def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(api, "record_change_log", failing)
    failed = copy_pp(client_factory, g.o1_user_id, g, npc, key=key)
    assert code(failed) == 500  # the transaction is rolled back with the request
    assert source["personality"] not in failed.text
    monkeypatch.setattr(api, "record_change_log", real)
    assert state(postgres_engine, g, npc) == before
    retry = copy_pp(client_factory, g.o1_user_id, g, npc, key=key)
    assert code(retry) == 201 and len(copy_audit(postgres_engine, g)) == 1


# --- restriction, edit, clear, recopy and the excerpt regressions ------------------------------------------


def background(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> tuple[Any, Any]:
    d = view(factory, user, g, character)["draft"]
    return d["public_background"], d["public_background_withheld"]


def _restricted_owner(engine: Engine, g: Gate, npc: uuid.UUID) -> None:
    """`o2` keeps reveal authority and the right to read the draft, but a `canon.edit` deny on the
    character removes the player-profile read rule, so `o2` is the restricted releaser."""
    deny(engine, g, g.o2, "canon.edit", npc)


def test_a_copied_field_is_withheld_from_a_caller_who_fails_the_source_rule_until_released(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    _restricted_owner(postgres_engine, g, npc)
    seen = Seen()
    restricted = view(client_factory, g.o2_user_id, g, npc)
    seen.take(read(client_factory, g.o2_user_id, g, npc))
    d = restricted["draft"]
    assert d["public_background"] is None and d["public_background_withheld"] is True
    assert d["public_background_origin"] == "player_profile"
    assert d["public_background_origin_player_profile_version"] == 1
    assert d["public_background_origin_player_profile_field"] == "personality"
    assert d["public_background_player_profile_source_changed"] is None  # never for withheld text
    assert restricted["can_release"] is False and restricted["player_profile_copy"] is None
    refused = release(client_factory, g.o2_user_id, g, npc, 1)
    assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
    seen.assert_none_of(*source.values())
    # A permitted GM reads it and releases it; the restricted owner then reads the covered field.
    assert background(client_factory, g.o1_user_id, g, npc) == (source["personality"], False)
    assert code(release(client_factory, g.o1_user_id, g, npc, 1)) == 201
    assert background(client_factory, g.o2_user_id, g, npc) == (source["personality"], False)


def _copied_cut_and_released(factory: Factory, engine: Engine, g: Gate, npc: uuid.UUID) -> int:
    """Copy `personality`, cut it to an excerpt, release the excerpt. Returns the draft version."""
    assert code(copy_pp(factory, g.o1_user_id, g, npc)) == 201
    assert code(save(factory, g.o1_user_id, g, npc, {"expected_row_version": 1, "public_background": EXCERPT})) == 200  # fmt: skip
    row = draft(engine, g, npc)
    assert row is not None and row["background_origin"] == "player_profile" and row["b_mark"] == 2
    assert code(release(factory, g.o1_user_id, g, npc, 2)) == 201
    return 2


def test_cutting_a_copy_releasing_the_excerpt_then_appending_source_text_is_withheld_again(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    version = _copied_cut_and_released(client_factory, postgres_engine, g, npc)
    _restricted_owner(postgres_engine, g, npc)
    seen = Seen()
    assert background(client_factory, g.o2_user_id, g, npc) == (EXCERPT, False)
    appended = save(client_factory, g.o1_user_id, g, npc, {"expected_row_version": version, "public_background": EXCERPT + APPENDED})  # fmt: skip
    assert code(appended) == 200
    view_ = body(seen.take(read(client_factory, g.o2_user_id, g, npc)))
    assert (view_["draft"]["public_background"], view_["draft"]["public_background_withheld"]) == (
        None,
        True,
    )  # type: ignore[index]
    assert view_["latest_release"]["public_background"] == EXCERPT  # type: ignore[index]
    assert code(seen.take(release(client_factory, g.o2_user_id, g, npc, version + 1))) == 403
    seen.assert_none_of(APPENDED, source["personality"])
    assert code(release(client_factory, g.o1_user_id, g, npc, version + 1)) == 201
    assert background(client_factory, g.o2_user_id, g, npc) == (EXCERPT + APPENDED, False)


@pytest.mark.parametrize("restore", ["edit", "recopy"])
def test_restoring_the_full_text_after_an_excerpt_release_is_withheld_until_released(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID,
    source: dict[str, str], restore: str,
) -> None:  # fmt: skip
    version = _copied_cut_and_released(client_factory, postgres_engine, g, npc)
    if restore == "edit":
        restored = save(client_factory, g.o1_user_id, g, npc, {"expected_row_version": version, "public_background": source["personality"]})  # fmt: skip
    else:
        restored = copy_pp(client_factory, g.o1_user_id, g, npc, draft=version)
    assert code(restored) == 200
    _restricted_owner(postgres_engine, g, npc)
    assert background(client_factory, g.o2_user_id, g, npc) == (None, True)
    assert code(release(client_factory, g.o2_user_id, g, npc, version + 1)) == 403
    assert code(release(client_factory, g.o1_user_id, g, npc, version + 1)) == 201
    assert background(client_factory, g.o2_user_id, g, npc) == (source["personality"], False)


def test_editing_the_other_field_after_a_copy_release_never_restricts_the_released_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    assert code(release(client_factory, g.o1_user_id, g, npc, 1)) == 201
    row = draft(postgres_engine, g, npc)
    assert row is not None
    mark = row["b_mark"]
    assert code(save(client_factory, g.o1_user_id, g, npc, {"expected_row_version": 1, "public_appearance": "face"})) == 200  # fmt: skip
    after = draft(postgres_engine, g, npc)
    assert after is not None and after["b_mark"] == mark
    _restricted_owner(postgres_engine, g, npc)
    assert background(client_factory, g.o2_user_id, g, npc) == (source["personality"], False)


def test_clear_ends_the_lineage_and_a_legacy_copy_switches_the_origin(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    cleared = save(client_factory, g.o1_user_id, g, npc, {"expected_row_version": 1, "public_background": None})  # fmt: skip
    assert code(cleared) == 200
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["public_background"] is None
    assert (row["background_origin"], row["b_version"], row["b_field"], row["b_mark"]) == (
        "authored",
        None,
        None,
        None,
    )
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc, draft=2, source_field="goals")) == 200
    row = draft(postgres_engine, g, npc)
    assert row is not None and (row["b_field"], row["b_mark"]) == ("goals", 3)
    # A legacy copy over a player-profile field switches the origin and clears the pair.
    describe(postgres_engine, npc, background=LEGACY_FULL)
    row = draft(postgres_engine, g, npc)
    assert row is not None
    swapped = legacy_copy(client_factory, m.gm_user_id, g, npc, row["row_version"])
    assert code(swapped) == 200, body(swapped)
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["background_origin"] == "legacy_background"
    assert (row["b_version"], row["b_field"]) == (None, None)
    # ...and a player-profile copy over a legacy field switches it back, clearing the legacy version.
    again = copy_pp(client_factory, g.o1_user_id, g, npc, draft=row["row_version"], source_field="bonds")  # fmt: skip
    assert code(again) == 200
    row = draft(postgres_engine, g, npc)
    assert row is not None
    assert (row["background_origin"], row["background_legacy"], row["b_field"]) == (
        "player_profile",
        None,
        "bonds",
    )
    assert row["b_mark"] == row["row_version"]


def test_a_mixed_draft_is_judged_per_field(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    """Appearance copied from the player profile (needs effective canon.edit), background from the
    legacy NPC description (needs world.canon.read_private): `o1` (no world role) passes the first and
    fails the second, `o2` with a canon.edit deny the reverse."""
    describe(postgres_engine, npc, background=LEGACY_FULL)
    legacy = legacy_copy(client_factory, m.gm_user_id, g, npc, None)
    assert code(legacy) == 201, body(legacy)
    pp = copy_pp(client_factory, g.o1_user_id, g, npc, draft=1, target="public_appearance")
    assert code(pp) == 200, body(pp)
    o1 = view(client_factory, g.o1_user_id, g, npc)["draft"]
    assert (o1["public_appearance"], o1["public_appearance_withheld"]) == (
        source["personality"],
        False,
    )
    assert (o1["public_background"], o1["public_background_withheld"]) == (None, True)
    _restricted_owner(postgres_engine, g, npc)
    o2 = view(client_factory, g.o2_user_id, g, npc)["draft"]
    assert (o2["public_appearance"], o2["public_appearance_withheld"]) == (None, True)
    assert (o2["public_background"], o2["public_background_withheld"]) == (LEGACY_FULL, False)


# --- the GM read: player_profile_copy and source_changed --------------------------------------------------------


def test_the_gm_read_advertises_the_copyable_fields_as_booleans_only_to_a_caller_who_may_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:  # fmt: skip
    # No profile: nothing to copy.
    assert view(client_factory, g.o1_user_id, g, npc)["player_profile_copy"] is None
    fields = markers("ADV")
    fields["fears"] = None  # type: ignore[assignment]
    fields["goals"] = None  # type: ignore[assignment]
    seed_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=npc,
        editor_membership_id=g.o1, fields=fields,
    )  # fmt: skip
    seen = Seen()
    for user in (g.o1_user_id, m.gm_user_id, m.ast_user_id):
        response = seen.take(read(client_factory, user, g, npc))
        advert = body(response)["player_profile_copy"]
        assert set(advert) == {"player_profile_row_version", "fields"}  # type: ignore[arg-type]
        assert advert["player_profile_row_version"] == 1  # type: ignore[index]
        flags = advert["fields"]  # type: ignore[index]
        assert set(flags) == set(COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS)
        assert {k for k, v in flags.items() if not v} == {"fears", "goals"}
        assert all(isinstance(v, bool) for v in flags.values())
    seen.assert_none_of(*[v for v in fields.values() if v])
    # A caller without the edit rule gets no advertisement; an archived character neither.
    deny(postgres_engine, g, g.o2, "canon.edit", npc)
    assert view(client_factory, g.o2_user_id, g, npc)["player_profile_copy"] is None
    other = make_one_character(postgres_engine, g, "Shelved Subject")
    seed_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=other,
        editor_membership_id=g.o1, fields=markers("SHL"),
    )  # fmt: skip
    assert view(client_factory, g.o1_user_id, g, other)["player_profile_copy"] is not None
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE entity_id = :c"
            ),
            {"c": other},
        )
    assert view(client_factory, g.o1_user_id, g, other)["player_profile_copy"] is None


def test_the_token_advertised_by_the_read_is_the_one_the_copy_accepts(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    edit_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=npc,
        editor_membership_id=g.o1, fields={**source, "ideals": "newer ideals"},
    )  # fmt: skip
    advert = view(client_factory, g.o1_user_id, g, npc)["player_profile_copy"]
    assert advert["player_profile_row_version"] == 2
    response = copy_pp(
        client_factory, g.o1_user_id, g, npc, token=advert["player_profile_row_version"],
        source_field="ideals",
    )  # fmt: skip
    assert code(response) == 201
    assert draft(postgres_engine, g, npc)["public_background"] == "newer ideals"  # type: ignore[index]


def test_source_changed_is_informative_only_for_an_unchanged_or_changed_source(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    d = view(client_factory, g.o1_user_id, g, npc)["draft"]
    assert d["public_background_player_profile_source_changed"] is False
    assert d["public_appearance_player_profile_source_changed"] is None  # not a copied field
    # A change to another field of the profile does not touch this field's flag.
    edit_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=npc,
        editor_membership_id=g.o1, fields={**source, "ideals": "elsewhere"},
    )  # fmt: skip
    d = view(client_factory, g.o1_user_id, g, npc)["draft"]
    assert d["public_background_player_profile_source_changed"] is False
    # A change to the copied field flips it; so does a clear. A later release is not blocked.
    edit_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=npc,
        editor_membership_id=g.o1, fields={**source, "personality": "rewritten"},
    )  # fmt: skip
    seen = Seen()
    response = seen.take(read(client_factory, g.o1_user_id, g, npc))
    d = body(response)["draft"]
    assert d["public_background_player_profile_source_changed"] is True  # type: ignore[index]
    assert d["public_background_origin_player_profile_version"] == 1  # type: ignore[index]
    seen.assert_none_of("rewritten")
    assert body(response)["can_release"] is True
    assert code(release(client_factory, g.o1_user_id, g, npc, 1)) == 201
    # Editing the draft text to something else keeps the citation and the flag.
    assert code(save(client_factory, g.o1_user_id, g, npc, {"expected_row_version": 1, "public_background": "edited"})) == 200  # fmt: skip
    assert (
        view(client_factory, g.o1_user_id, g, npc)["draft"][
            "public_background_player_profile_source_changed"
        ]
        is True
    )
    # Releases never carry the flag.
    latest = view(client_factory, g.o1_user_id, g, npc)["latest_release"]
    assert not any(k.endswith("source_changed") for k in latest)
    # Copying again from the new version resets it.
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc, draft=2, token=3)) == 200
    assert (
        view(client_factory, g.o1_user_id, g, npc)["draft"][
            "public_background_player_profile_source_changed"
        ]
        is False
    )


def test_a_cleared_source_field_counts_as_changed(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    edit_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=npc,
        editor_membership_id=g.o1, fields={**source, "personality": None},
    )  # fmt: skip
    d = view(client_factory, g.o1_user_id, g, npc)["draft"]
    assert d["public_background_player_profile_source_changed"] is True


# --- T82: the player-profile clause, end to end -------------------------------------------------------------


def test_t82_a_copied_excerpt_reaches_only_the_revealed_audience_of_its_own_campaign(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:  # fmt: skip
    from tests.database.test_character_public_tier import get
    from tests.database.test_character_revelations import campaign_body, create

    fields = markers("T82")
    seed_player_profile(
        postgres_engine, campaign_id=g.campaign_id, character_id=npc,
        editor_membership_id=g.o1, fields=fields,
    )  # fmt: skip
    assert code(copy_pp(client_factory, g.o1_user_id, g, npc, source_field="personality")) == 201
    assert code(save(client_factory, g.o1_user_id, g, npc, {"expected_row_version": 1, "public_background": EXCERPT})) == 200  # fmt: skip
    assert code(release(client_factory, g.o1_user_id, g, npc, 2)) == 201
    # Before a revelation, a player sees nothing of the profile.
    before = get(client_factory, g.player_user_id, g, npc)
    assert EXCERPT not in before.text
    created = create(client_factory, g.o1_user_id, g, npc, campaign_body("campaign_current"))
    assert code(created) == 201, created.text
    seen = Seen()
    player = seen.take(get(client_factory, g.player_user_id, g, npc))
    assert code(player) == 200, player.text
    assert player.json()["public_profile"]["background"] == EXCERPT
    seen.assert_none_of(*fields.values())
    # A later joiner (outside the revealed audience) and another campaign's member see nothing.
    from tests.database.test_character_revelations_discovery import join_late

    late = join_late(postgres_engine, g)
    nothing = Seen()
    later = nothing.take(get(client_factory, late.user, g, npc))
    assert code(later) == 404 or later.json().get("public_profile") is None
    outsider = nothing.take(get(client_factory, uuid.uuid4(), g, npc))
    assert code(outsider) in (403, 404)
    nothing.assert_none_of(EXCERPT, *fields.values())


# --- disclosure ---------------------------------------------------------------------------------------------


def test_no_response_receipt_error_log_or_audit_row_carries_profile_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str], caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    caplog.set_level(logging.DEBUG)
    seen = Seen()
    seen.take(copy_pp(client_factory, g.player_user_id, g, npc))  # refused
    seen.take(copy_pp(client_factory, g.o1_user_id, g, npc, key="k-1"))  # 201
    seen.take(copy_pp(client_factory, g.o1_user_id, g, npc, key="k-1"))  # replay
    seen.take(copy_pp(client_factory, g.o1_user_id, g, npc))  # 409 stale
    seen.take(copy_pp(client_factory, g.o1_user_id, g, npc, source_field="boundaries"))  # 422
    seen.take(copy_pp(client_factory, g.o1_user_id, g, npc, draft=1, token=9))  # 409 source changed
    seen.take(copy_pp(client_factory, g.o1_user_id, g, npc, draft=1, source_field="bonds"))  # 200
    _restricted_owner(postgres_engine, g, npc)
    # `ast` passes the player-profile rule and may legitimately read the text, so it is not a
    # restricted reader; `o2` (denied) and the player are.
    for user in (g.o2_user_id, g.player_user_id):
        seen.take(read(client_factory, user, g, npc))
        seen.take(read(client_factory, user, g, npc, "/releases/1"))
        seen.take(release(client_factory, user, g, npc, 2))
    seen.assert_none_of(*source.values())
    dump = audit_dump(postgres_engine, g)
    for marker in source.values():
        assert marker not in dump
    assert not any(marker in caplog.text for marker in source.values())
    with postgres_engine.connect() as connection:
        receipt_text = " ".join(
            str(row)
            for schema, table in connection.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_name LIKE '%idempot%' AND table_type = 'BASE TABLE'"
                )
            ).all()
            for row in connection.execute(text(f"SELECT * FROM {schema}.{table}")).all()  # noqa: S608
        )
    assert not any(marker in receipt_text for marker in source.values())


def test_the_copy_adds_no_new_audience_surface(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    """The audience projection and SQL are untouched by A5c: pinned by the structure test; here the
    behaviour: a release of a copied field shows exactly the same audience shape as authored text."""
    from dnd_ai.queries.character_public_profile import read_released_profile

    assert code(copy_pp(client_factory, g.o1_user_id, g, npc)) == 201
    assert code(release(client_factory, g.o1_user_id, g, npc, 1)) == 201
    with postgres_engine.connect() as connection:
        released = read_released_profile(connection, campaign_id=g.campaign_id, character_id=npc)
    assert released is not None
    assert released.background == source["personality"]
    assert set(vars(released)) == {"summary", "appearance", "background", "species", "size"}
