# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Copied player-profile text stays restricted until a release covers it (P03-A A5b, D16).

The A5c copy command does not exist, so a `player_profile` draft field is seeded by the one fixture
helper (`tests/player_profile_support.py`), exactly the write the copy will perform. Every read, save
and release then goes through the real HTTP routes. The A2b scenarios for legacy text run unchanged in
`test_character_public_profile_restrictions.py`; here the same guarantees are shown for the new origin,
and for a draft that mixes both.

Cast, on one NPC (a legacy source read needs role `canon.edit` plus the world capability
`world.canon.read_private`; the player-profile source read needs *effective* `canon.edit`, which a
`canon.edit` deny on the character removes):

- `gm` (delegated, world editor) and `o2` (world editor): pass both source rules;
- `o1` (no world role): fails the legacy rule, passes the player-profile rule;
- `ast` (world reader): fails the legacy rule, passes the player-profile rule;
- `o2` or `o1` once a `canon.edit` deny on the character exists: passes the legacy rule (role-only),
  fails the player-profile rule. Both owners keep reveal authority, so they still read the draft.
"""

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.domain.player_profiles import PLAYER_PROFILE_FIELDS
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (
    body,
    code,
    counts,
    error_code,
    read,
    release,
    release_rows,
    save,
    url,
)
from tests.database.test_character_public_profile_grant_denies import deny_via_route
from tests.database.test_character_public_profile_restrictions import (  # noqa: F401 - fixtures
    FULL,
    npc,
    seed_copy,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_player_profile_api import _text_of_tables
from tests.player_profile_support import (
    markers,
    seed_player_profile,
    seed_player_profile_copy,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

SUMMARY = "AUTHORED-SUMMARY-MARKER-5505"
EXCERPT = "PP-EXCERPT-MARKER-E-6606"
APPENDED = "PP-APPENDED-MARKER-X-7707"
AUTHORED_B = "AUTHORED-BACKGROUND-MARKER-8808"
PROVENANCE_KEYS = (
    "public_appearance_origin_player_profile_version",
    "public_appearance_origin_player_profile_field",
    "public_background_origin_player_profile_version",
    "public_background_origin_player_profile_field",
)


@pytest.fixture
def source(postgres_engine: Engine, g: Gate, npc: uuid.UUID) -> dict[str, str]:
    """A player profile of the NPC in the Gate's campaign, every field distinctly marked."""
    fields = markers("NPC")
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=npc,
        editor_membership_id=g.o1,
        fields=fields,
    )
    return fields


def copy_in(engine: Engine, g: Gate, npc: uuid.UUID, target: str, field: str) -> int:
    return seed_player_profile_copy(
        engine,
        campaign_id=g.campaign_id,
        character_id=npc,
        membership_id=g.o1,
        target_field=target,
        source_field=field,
    )


def draft_state(engine: Engine, g: Gate, character: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("""
                    SELECT d.row_version, d.public_appearance, d.public_background,
                           ao.code AS appearance_origin, bo.code AS background_origin,
                           d.public_appearance_origin_entity_row_version AS appearance_legacy,
                           d.public_background_origin_entity_row_version AS background_legacy,
                           d.public_appearance_origin_player_profile_version_id AS a_pp_version,
                           d.public_appearance_origin_player_profile_field_id AS a_pp_field,
                           d.public_background_origin_player_profile_version_id AS b_pp_version,
                           d.public_background_origin_player_profile_field_id AS b_pp_field,
                           d.public_appearance_restricted_row_version AS appearance_mark,
                           d.public_background_restricted_row_version AS background_mark
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
    return dict(row)


def release_provenance(engine: Engine, g: Gate, character: uuid.UUID) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT r.version_number, r.public_appearance, ao.code AS appearance_origin,
                       r.public_appearance_origin_player_profile_version_id AS a_version,
                       (SELECT code FROM campaign.player_profile_fields f
                         WHERE f.player_profile_field_id =
                               r.public_appearance_origin_player_profile_field_id) AS a_field
                FROM campaign.character_public_profile_releases r
                JOIN campaign.public_profile_field_origins ao
                  ON ao.public_profile_field_origin_id = r.public_appearance_origin_id
                WHERE r.campaign_id = :c AND r.character_id = :ch ORDER BY r.version_number
            """),
            {"c": g.campaign_id, "ch": character},
        ).mappings()
        return [dict(r) for r in rows]


def started_mixed(
    factory: Factory, engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:
    """Draft version 3: an authored summary (1), a legacy-copied background (2) and a
    player-profile-copied appearance (3)."""
    created = save(
        factory, g.o1_user_id, g, npc, {"expected_row_version": None, "public_summary": SUMMARY}
    )
    assert code(created) == 201, body(created)
    seed_copy(engine, g, npc, "background", FULL)
    assert copy_in(engine, g, npc, "public_appearance", "personality") == 3


# --- withholding is per field and per origin -----------------------------------------------------------


def test_a_mixed_draft_is_judged_per_field_by_each_fields_own_source_rule(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    started_mixed(client_factory, postgres_engine, g, npc, source)
    pp_text, pp_marker_keys = source["personality"], PLAYER_PROFILE_FIELDS
    # (user, appearance [player profile] visible, background [legacy] visible)
    expectations = [
        ("gm: passes both rules", m.gm_user_id, True, True),
        ("o1: no world role fails the legacy rule only", g.o1_user_id, True, False),
        ("ast: world reader fails the legacy rule only", m.ast_user_id, True, False),
    ]

    def check(name: str, user: uuid.UUID, pp_visible: bool, legacy_visible: bool) -> None:
        response = read(client_factory, user, g, npc)
        assert code(response) == 200, (name, body(response))
        view = body(response)
        draft = view["draft"]
        assert (draft["public_appearance"] == pp_text) is pp_visible, name
        assert draft["public_appearance_withheld"] is (not pp_visible), name
        assert (draft["public_background"] == FULL) is legacy_visible, name
        assert draft["public_background_withheld"] is (not legacy_visible), name
        # The origin code and the citation are disclosed even when the text is not (D7-f).
        assert draft["public_appearance_origin"] == "player_profile"
        assert draft["public_appearance_origin_player_profile_version"] == 1
        assert draft["public_appearance_origin_player_profile_field"] == "personality"
        assert draft["public_background_origin"] == "legacy_background"
        assert draft["public_background_origin_player_profile_version"] is None
        assert draft["public_background_origin_player_profile_field"] is None
        assert draft["public_summary"] == SUMMARY  # authored text is never withheld
        assert view["can_release"] is (pp_visible and legacy_visible), name
        if not pp_visible:
            assert pp_text not in response.text, name
        if not legacy_visible:
            assert FULL not in response.text, name
        # Neither the profile's other fields nor its identifiers are in any body.
        for code_, marker in source.items():
            if code_ != "personality" or not pp_visible:
                assert marker not in response.text, (name, code_)

    for name, user, pp_visible, legacy_visible in expectations:
        check(name, user, pp_visible, legacy_visible)

    # A canon.edit deny on the character (through the real grant route) removes the player-profile
    # rule but not the role-only legacy rule: o2, a world editor, now sees the opposite of o1.
    deny_via_route(client_factory, g, "canon.edit", npc, member=g.o2)
    check(
        "o2 with a canon.edit deny: passes legacy, fails player profile", g.o2_user_id, False, True
    )
    # And a caller who fails both sees neither.
    deny_via_route(client_factory, g, "canon.edit", npc, member=g.o1)
    check("o1 with a canon.edit deny: fails both", g.o1_user_id, False, False)
    assert len(pp_marker_keys) == 11


def test_a_save_in_a_mixed_draft_refuses_only_text_for_a_field_withheld_by_its_own_rule(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    """`o1` cannot read the legacy background but can read the player-profile appearance."""
    started_mixed(client_factory, postgres_engine, g, npc, source)
    before_state, before_counts = draft_state(postgres_engine, g, npc), counts(postgres_engine, g)
    # Text for the legacy-withheld field refuses the WHOLE request, including the readable field.
    refused = save(
        client_factory, g.o1_user_id, g, npc,
        {"expected_row_version": 3, "public_appearance": EXCERPT, "public_background": "typed"},
    )  # fmt: skip
    assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
    for marker in (FULL, source["personality"], EXCERPT, "typed"):
        assert marker not in refused.text
    assert draft_state(postgres_engine, g, npc) == before_state
    assert counts(postgres_engine, g) == before_counts
    # Text for the readable player-profile field is accepted: origin and provenance are kept and the
    # watermark advances to the new row_version (I2).
    edited = save(
        client_factory,
        g.o1_user_id,
        g,
        npc,
        {"expected_row_version": 3, "public_appearance": EXCERPT},
    )
    assert code(edited) == 200 and body(edited)["row_version"] == 4, body(edited)
    after = draft_state(postgres_engine, g, npc)
    assert after["appearance_origin"] == "player_profile" and after["public_appearance"] == EXCERPT
    assert after["a_pp_version"] == before_state["a_pp_version"]
    assert after["a_pp_field"] == before_state["a_pp_field"] and after["appearance_mark"] == 4
    assert after["appearance_legacy"] is None
    # The legacy field keeps its own provenance and watermark (I3).
    assert after["background_origin"] == "legacy_background" and after["background_mark"] == 2
    assert after["background_legacy"] == before_state["background_legacy"]
    # A clear of the withheld legacy field is allowed (D7-a) and ends only its own lineage (I6).
    cleared = save(
        client_factory, g.o1_user_id, g, npc, {"expected_row_version": 4, "public_background": None}
    )
    assert code(cleared) == 200, body(cleared)
    after = draft_state(postgres_engine, g, npc)
    assert after["public_background"] is None and after["background_origin"] == "authored"
    assert after["background_legacy"] is None and after["background_mark"] is None
    assert after["appearance_origin"] == "player_profile" and after["appearance_mark"] == 4


# --- edit, release coverage, no-op, clear, recopy (design section 9.5) ------------------------------------


def test_edit_release_coverage_noop_clear_and_recopy_of_player_profile_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    pp_text = source["personality"]
    assert copy_in(postgres_engine, g, npc, "public_appearance", "personality") == 1
    # o1, the restricted releaser, keeps reveal authority but loses the player-profile rule.
    deny_via_route(client_factory, g, "canon.edit", npc, member=g.o1)

    def o1_view() -> dict[str, Any]:
        return body(read(client_factory, g.o1_user_id, g, npc))  # type: ignore[no-any-return]

    view = o1_view()
    assert (
        view["draft"]["public_appearance"] is None and view["draft"]["public_appearance_withheld"]
    )
    assert view["can_release"] is False
    before = counts(postgres_engine, g)
    refused = release(client_factory, g.o1_user_id, g, npc, 1)
    assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
    assert pp_text not in refused.text and counts(postgres_engine, g) == before
    assert release_rows(postgres_engine, g, npc) == []

    # o2 (permitted) edits the copy down to an excerpt: origin and provenance kept, watermark advanced.
    edited = save(
        client_factory,
        g.o2_user_id,
        g,
        npc,
        {"expected_row_version": 1, "public_appearance": EXCERPT},
    )
    assert code(edited) == 200 and body(edited)["row_version"] == 2
    state = draft_state(postgres_engine, g, npc)
    assert state["appearance_origin"] == "player_profile" and state["appearance_mark"] == 2
    assert state["a_pp_version"] is not None and state["a_pp_field"] is not None
    # Released by the permitted owner: release 1 covers the excerpt and carries the provenance.
    created = release(client_factory, g.o2_user_id, g, npc, 2)
    assert code(created) == 201, body(created)
    snapshot = release_provenance(postgres_engine, g, npc)
    assert snapshot == [
        {
            "version_number": 1,
            "public_appearance": EXCERPT,
            "appearance_origin": "player_profile",
            "a_version": state["a_pp_version"],
            "a_field": "personality",
        }
    ]
    # The covered excerpt is no longer restricted: o1 reads it and may release.
    view = o1_view()
    assert view["draft"]["public_appearance"] == EXCERPT
    assert view["draft"]["public_appearance_withheld"] is False and view["can_release"] is True

    # Source text is appended to the excerpt: restricted again; the release still shows the excerpt.
    appended = save(
        client_factory, g.o2_user_id, g, npc,
        {"expected_row_version": 2, "public_appearance": EXCERPT + " " + APPENDED},
    )  # fmt: skip
    assert code(appended) == 200 and body(appended)["row_version"] == 3
    assert draft_state(postgres_engine, g, npc)["appearance_mark"] == 3
    view = o1_view()
    assert view["draft"]["public_appearance"] is None and view["can_release"] is False
    assert APPENDED not in json.dumps(view)
    # ... a release of the new version by the restricted releaser is refused, the old one is a retry.
    before = counts(postgres_engine, g)
    refused = release(client_factory, g.o1_user_id, g, npc, 3)
    assert (code(refused), error_code(refused)) == (403, "public_profile_field_withheld")
    assert counts(postgres_engine, g) == before
    retry = release(client_factory, g.o1_user_id, g, npc, 2)  # D7-d: a retry needs no source check
    assert code(retry) == 200 and body(retry)["created"] is False
    assert [r["public_appearance"] for r in release_rows(postgres_engine, g, npc)] == [EXCERPT]

    # A no-op save writes nothing, whoever sends it: no bump, no audit row, the watermark stays.
    audited, state = counts(postgres_engine, g), draft_state(postgres_engine, g, npc)
    noop = save(
        client_factory, g.o2_user_id, g, npc,
        {"expected_row_version": 3, "public_appearance": EXCERPT + " " + APPENDED},
    )  # fmt: skip
    assert code(noop) == 200 and body(noop)["changed"] is False and body(noop)["row_version"] == 3
    assert counts(postgres_engine, g) == audited and draft_state(postgres_engine, g, npc) == state

    # Edited back to exactly the released excerpt: still restricted until it is released again.
    back = save(
        client_factory,
        g.o2_user_id,
        g,
        npc,
        {"expected_row_version": 3, "public_appearance": EXCERPT},
    )
    assert code(back) == 200 and body(back)["row_version"] == 4
    assert draft_state(postgres_engine, g, npc)["appearance_mark"] == 4
    assert o1_view()["draft"]["public_appearance"] is None

    # Editing the OTHER field leaves this field's watermark alone (I3).
    other = save(
        client_factory,
        g.o2_user_id,
        g,
        npc,
        {"expected_row_version": 4, "public_background": AUTHORED_B},
    )
    assert code(other) == 200
    after = draft_state(postgres_engine, g, npc)
    assert after["appearance_mark"] == 4 and after["background_origin"] == "authored"
    assert after["background_mark"] is None and after["row_version"] == 5

    # A permitted GM clears the field: the lineage ends (I6), nothing is left to restrict or disclose.
    cleared = save(
        client_factory, m.gm_user_id, g, npc, {"expected_row_version": 5, "public_appearance": None}
    )
    assert code(cleared) == 200, body(cleared)
    after = draft_state(postgres_engine, g, npc)
    assert after["public_appearance"] is None and after["appearance_origin"] == "authored"
    assert after["a_pp_version"] is None and after["a_pp_field"] is None
    assert after["appearance_mark"] is None
    view = o1_view()
    assert view["draft"]["public_appearance_withheld"] is False
    assert view["draft"]["public_appearance_origin_player_profile_version"] is None
    assert view["draft"]["public_appearance_origin_player_profile_field"] is None

    # A copy again, from the same source after a covering release, is new restricted content.
    assert copy_in(postgres_engine, g, npc, "public_appearance", "personality") == 7
    state = draft_state(postgres_engine, g, npc)
    assert state["appearance_mark"] == 7 and state["row_version"] == 7
    assert o1_view()["draft"]["public_appearance_withheld"] is True


# --- the audience tier and the releases ------------------------------------------------------------------


def _key_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        out: set[str] = set()
        for key, inner in value.items():
            out |= {f"{prefix}/{key}", *_key_paths(inner, f"{prefix}/{key}")}
        return out
    if isinstance(value, list):
        out = set()
        for inner in value:
            out |= _key_paths(inner, prefix + "[]")
        return out
    return set()


def test_audiences_see_only_the_released_text_and_the_response_shape_is_unchanged(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    """After copy, release and revelation a player reads exactly the released excerpt, in the same
    response shape as a character whose release was entirely authored: no origin, provenance, version,
    profile id or source field reaches the audience tier, and the withheld source fields never do."""
    assert copy_in(postgres_engine, g, npc, "public_appearance", "personality") == 1
    edited = save(
        client_factory,
        g.o2_user_id,
        g,
        npc,
        {"expected_row_version": 1, "public_appearance": EXCERPT},
    )
    assert code(edited) == 200
    assert code(release(client_factory, g.o2_user_id, g, npc, 2)) == 201
    revealed = {"audience_kind": "member", "target_campaign_membership_id": str(g.player),
                "reason": "The table meets them"}  # fmt: skip
    base = f"/campaigns/{g.campaign_id}/characters"
    with client_factory(g.o1_user_id) as client:
        assert client.post(f"{base}/{npc}/revelations", json=revealed).status_code == 201
    with client_factory(g.player_user_id) as client:
        response = client.get(f"{base}/{npc}")
        assert response.status_code == 200, response.text
        audience = response.json()
        browse = client.get(
            f"/campaigns/{g.campaign_id}/world/search/counts", params={"q": "Restricted"}
        ).text
        found = client.get(
            f"/campaigns/{g.campaign_id}/world/search", params={"q": "Restricted"}
        ).text

    flat = json.dumps(audience)
    assert EXCERPT in flat
    for name, marker in source.items():
        assert marker not in flat + browse + found, name
    forbidden = ("player_profile", "provenance", "watermark", "origin", str(npc) + "x")
    for word in forbidden[:-1]:
        assert word not in flat + browse + found, word
    # Same shape as an entirely authored release of another NPC in the same campaign.
    from tests.factories import make_character

    with postgres_engine.begin() as connection:
        plain = make_character(connection, g.world_id, name="Plain NPC", entity_type_code="npc")
        connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:c)"), {"c": plain})
    assert code(save(client_factory, g.o2_user_id, g, plain, {"expected_row_version": None, "public_appearance": EXCERPT})) == 201  # fmt: skip
    assert code(release(client_factory, g.o2_user_id, g, plain, 1)) == 201
    with client_factory(g.o1_user_id) as client:
        assert client.post(f"{base}/{plain}/revelations", json=revealed).status_code == 201
    with client_factory(g.player_user_id) as client:
        authored = client.get(f"{base}/{plain}").json()
    paths = _key_paths(audience)
    assert paths == _key_paths(authored)


def test_the_gm_read_of_releases_carries_provenance_as_numbers_and_codes_only(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str],
) -> None:  # fmt: skip
    assert copy_in(postgres_engine, g, npc, "public_background", "goals") == 1
    assert code(release(client_factory, g.o2_user_id, g, npc, 1)) == 201
    view = body(read(client_factory, g.o2_user_id, g, npc))
    latest = view["latest_release"]
    assert latest["public_background"] == source["goals"]
    assert latest["public_background_origin"] == "player_profile"
    assert latest["public_background_origin_player_profile_version"] == 1
    assert latest["public_background_origin_player_profile_field"] == "goals"
    assert latest["public_appearance_origin_player_profile_version"] is None
    assert latest["public_appearance_origin_player_profile_field"] is None
    # The summaries in `releases` carry no text and no provenance; the one-release route does.
    assert all("public_background" not in r for r in view["releases"])
    detail = body(read(client_factory, g.o2_user_id, g, npc, "/releases/1"))
    assert detail["public_background_origin_player_profile_version"] == 1
    # Neither UUID of the cited version or its profile is exposed anywhere in the GM read.
    with postgres_engine.connect() as connection:
        ids = connection.execute(
            text("""
                SELECT v.character_player_profile_version_id::text, v.character_player_profile_id::text
                FROM campaign.character_player_profile_versions v
                WHERE v.campaign_id = :c AND v.character_id = :ch
            """),
            {"c": g.campaign_id, "ch": npc},
        ).one()
    for identifier in ids:
        assert identifier not in json.dumps(view) + json.dumps(detail)
    for key in PROVENANCE_KEYS:
        assert key in view["draft"]


# --- disclosure sweep -------------------------------------------------------------------------------------------


def test_ineligible_fields_and_withheld_text_reach_no_body_log_receipt_or_audit_row(
    client_factory: Factory, postgres_engine: Engine, caplog: pytest.LogCaptureFixture, g: Gate,
    m: Members, npc: uuid.UUID, source: dict[str, str],
) -> None:  # fmt: skip
    """Runs the save, release and read flows over a draft holding copied text, for authorized and
    withheld callers, and sweeps every body, the receipts, the audit rows and DEBUG logs. The
    `boundaries` and `profile_notes` markers can appear nowhere: no structured path reads them into a
    public-profile table. The copied field's marker appears only to callers who may read it."""
    caplog.set_level(logging.DEBUG)
    started_mixed(client_factory, postgres_engine, g, npc, source)
    deny_via_route(client_factory, g, "canon.edit", npc, member=g.o1)
    never = (source["boundaries"], source["profile_notes"])
    copied = source["personality"]
    bodies: list[tuple[str, str]] = []

    def take(who: str, response: Any) -> Any:
        bodies.append((who, response.text))
        return response

    for who, user in (
        ("o1 (withheld)", g.o1_user_id),
        ("ast", m.ast_user_id),
        ("gm", m.gm_user_id),
    ):
        take(who, read(client_factory, user, g, npc))
        take(who, read(client_factory, user, g, npc, "/releases/1"))
    take("o1 save", save(client_factory, g.o1_user_id, g, npc, {"expected_row_version": 3, "public_appearance": "x"}))  # fmt: skip
    take("o1 release", release(client_factory, g.o1_user_id, g, npc, 3, key="sweep-1"))
    take("gm save", save(client_factory, m.gm_user_id, g, npc, {"expected_row_version": 3, "public_appearance": EXCERPT}, key="sweep-2"))  # fmt: skip
    take("o2 release", release(client_factory, g.o2_user_id, g, npc, 4, key="sweep-3"))
    take("player", client_factory(g.player_user_id).get(url(g, npc)))

    receipts = _text_of_tables(postgres_engine, "%idempot%")
    audit = _text_of_tables(postgres_engine, "audit", world=g.world_id)
    stored = _text_of_tables(postgres_engine, "character_public_profile%")
    logs = "\n".join(f"{r.name} {r.getMessage()}" for r in caplog.records)
    for surface, content in (
        ("responses", "\n".join(b for _w, b in bodies)),
        ("receipts", receipts),
        ("audit", audit),
        ("public-profile rows", stored),
        ("logs", logs),
    ):
        for marker in never:
            assert marker not in content, (surface, marker)
    # Copied text: never in what a withheld caller received, a receipt, the audit log or a log.
    for who, content in bodies:
        if who.startswith("o1") or who == "player":
            assert copied not in content, who
    for surface, content in (("receipts", receipts), ("audit", audit), ("logs", logs)):
        assert copied not in content and EXCERPT not in content, surface
    assert "sweep-2" in receipts or "release_character_public_profile" in receipts  # not vacuous
