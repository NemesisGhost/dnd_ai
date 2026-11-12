# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The integrity rules of migration 148 (P03-A A5b): origin, provenance and watermark guarantees.

Each rule is exercised with the statement that would break it, on committed fixtures (the Gate and
two campaigns sharing one world, timeline and character), because the origin and watermark rules are
triggers that read other tables and the campaign isolation is a composite foreign key. Valid
`player_profile` draft states are written by the one fixture helper (`tests/player_profile_support.py`);
the raw statements here are the refusals. The existing 143 and 144 tests run unchanged at head.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dnd_ai.domain.player_profiles import COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    g,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_user,
)
from tests.player_profile_support import (
    markers,
    seed_player_profile,
    seed_player_profile_copy,
    seed_player_profile_copy_in,
)

pytestmark = pytest.mark.database

DRAFTS = "campaign.character_public_profiles"
RELEASES = "campaign.character_public_profile_releases"
FIELDS = ("public_appearance", "public_background")
INELIGIBLE = ("boundaries", "profile_notes")


@pytest.fixture
def ctx(postgres_engine: Engine, g: Gate) -> dict[str, Any]:
    """Character K with a profile in campaign A (every field filled), and the same character with
    its own profile in a second campaign B of the same world and timeline."""
    with postgres_engine.begin() as connection:
        character = make_character(connection, g.world_id, name="Provenance Subject")
        other = make_character(connection, g.world_id, name="Provenance Other")
        campaign_b = make_campaign(
            connection, g.timeline_id, "Campaign B", lifecycle_status_code="active"
        )
        owner_b = make_user(connection, "Provenance B Owner")
        member_b = make_campaign_membership(connection, campaign_b, owner_b)
        make_membership_role(connection, member_b, g.owner_role_id)
    fields_a = markers("A")
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields=fields_a,
    )
    seed_player_profile(
        postgres_engine,
        campaign_id=campaign_b,
        character_id=character,
        editor_membership_id=member_b,
        fields=markers("B"),
    )
    return {
        "character": character,
        "other": other,
        "campaign_b": campaign_b,
        "member_b": member_b,
        "fields_a": fields_a,
    }


def _refused(engine: Engine, statement: Callable[[Connection], object]) -> str:
    with pytest.raises(DBAPIError) as raised, engine.begin() as connection:
        statement(connection)
    return str(raised.value)


def _origin(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT public_profile_field_origin_id FROM campaign.public_profile_field_origins "
            "WHERE code = :c"
        ),
        {"c": code},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _draft_row(engine: Engine, campaign: uuid.UUID, character: uuid.UUID) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(f"""
                    SELECT d.*, ao.code AS appearance_origin, bo.code AS background_origin
                    FROM {DRAFTS} d
                    JOIN campaign.public_profile_field_origins ao
                      ON ao.public_profile_field_origin_id = d.public_appearance_origin_id
                    JOIN campaign.public_profile_field_origins bo
                      ON bo.public_profile_field_origin_id = d.public_background_origin_id
                    WHERE d.campaign_id = :c AND d.character_id = :ch
                """),  # noqa: S608
                {"c": campaign, "ch": character},
            )
            .mappings()
            .one_or_none()
        )
    return None if row is None else dict(row)


def _cols(field: str) -> dict[str, str]:
    return {
        "text": field,
        "origin": f"{field}_origin_id",
        "legacy": f"{field}_origin_entity_row_version",
        "pp_version": f"{field}_origin_player_profile_version_id",
        "pp_field": f"{field}_origin_player_profile_field_id",
        "mark": f"{field}_restricted_row_version",
    }


def _pp_ids(
    connection: Connection, campaign: uuid.UUID, character: uuid.UUID, code: str
) -> tuple[uuid.UUID, uuid.UUID]:
    version = connection.execute(
        text("""
            SELECT v.character_player_profile_version_id
            FROM campaign.character_player_profiles h
            JOIN campaign.character_player_profile_versions v
              ON v.character_player_profile_id = h.character_player_profile_id
             AND v.profile_row_version = h.row_version
            WHERE h.campaign_id = :c AND h.character_id = :ch
        """),
        {"c": campaign, "ch": character},
    ).scalar_one()
    field = connection.execute(
        text("SELECT player_profile_field_id FROM campaign.player_profile_fields WHERE code = :c"),
        {"c": code},
    ).scalar_one()
    return version, field


def _raw_insert(
    connection: Connection,
    g: Gate,
    character: uuid.UUID,
    field: str,
    **overrides: Any,
) -> None:
    """A raw draft INSERT with one field set to `overrides` (the refusal probes)."""
    c = _cols(field)
    other = "public_background" if field == "public_appearance" else "public_appearance"
    values: dict[str, Any] = {
        "campaign": g.campaign_id,
        "character": character,
        "text": "copied text",
        "origin": _origin(connection, "authored"),
        "other": _origin(connection, "authored"),
        "legacy": None,
        "pp_version": None,
        "pp_field": None,
        "mark": None,
    }
    values.update(overrides)
    connection.execute(
        text(f"""
            INSERT INTO {DRAFTS} (campaign_id, character_id, {c["text"]}, {c["origin"]},
                {c["legacy"]}, {c["pp_version"]}, {c["pp_field"]}, {c["mark"]},
                {other}_origin_id)
            VALUES (:campaign, :character, :text, :origin, :legacy, :pp_version, :pp_field, :mark,
                    :other)
        """),  # noqa: S608
        values,
    )


# --- the origin and its lookup ------------------------------------------------------------------------


def test_the_player_profile_origin_exists_after_the_three_existing_ones(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT code, display_name, sort_order FROM campaign.public_profile_field_origins ORDER BY sort_order"
            )
        ).all()
    assert [r.code for r in rows] == [
        "authored",
        "legacy_appearance",
        "legacy_background",
        "player_profile",
    ]
    assert rows[-1].sort_order == 40 and rows[-1].display_name == "Copied from the player profile"


# --- acceptance: every eligible source field, both targets ------------------------------------------------


@pytest.mark.parametrize("target", FIELDS)
@pytest.mark.parametrize("source", COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS)
def test_every_copy_eligible_field_is_accepted_for_both_targets(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], target: str, source: str
) -> None:
    version = seed_player_profile_copy(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=ctx["character"],
        membership_id=g.o1,
        target_field=target,
        source_field=source,
    )
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None and version == 1
    c = _cols(target)
    assert row[c["text"]] == ctx["fields_a"][source]
    assert row[f"{target.removeprefix('public_')}_origin"] == "player_profile"
    assert row[c["legacy"]] is None and row[c["mark"]] == row["row_version"] == 1
    assert row[c["pp_version"]] is not None and row[c["pp_field"]] is not None


@pytest.mark.parametrize("target", FIELDS)
@pytest.mark.parametrize("source", INELIGIBLE)
def test_boundaries_and_profile_notes_can_never_be_the_origin_of_a_public_field(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], target: str, source: str
) -> None:
    """Refused by the database whatever the helper, the text or the watermark: a raw INSERT naming the
    ineligible source field fails, and so does an UPDATE of an existing draft to cite it."""
    message = _refused(
        postgres_engine,
        lambda c: seed_player_profile_copy_in(
            c,
            campaign_id=g.campaign_id,
            character_id=ctx["character"],
            membership_id=g.o1,
            target_field=target,
            source_field=source,
        ),
    )
    assert "cannot be the origin of a public field" in message
    assert _draft_row(postgres_engine, g.campaign_id, ctx["character"]) is None
    # An existing authored draft is not turned into a copy of the ineligible field either.
    with postgres_engine.begin() as connection:
        _raw_insert(connection, g, ctx["character"], target, text="authored")
    message = _refused(
        postgres_engine,
        lambda c: seed_player_profile_copy_in(
            c,
            campaign_id=g.campaign_id,
            character_id=ctx["character"],
            membership_id=g.o1,
            target_field=target,
            source_field=source,
        ),
    )
    assert "cannot be the origin of a public field" in message
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None and row[target] == "authored" and row["row_version"] == 1


# --- provenance consistency ------------------------------------------------------------------------------


def test_the_provenance_pair_is_set_together_and_only_with_the_player_profile_origin(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any]
) -> None:
    with postgres_engine.connect() as connection:
        version, field = _pp_ids(connection, g.campaign_id, ctx["character"], "personality")
        pp_origin = _origin(connection, "player_profile")
        legacy = _origin(connection, "legacy_appearance")
        authored = _origin(connection, "authored")
    pair = "needs its source version and field, and only it does"
    pair_check = "ck_character_public_profiles_appearance_pp_pair"
    cases = {
        "origin without a version": ({"origin": pp_origin, "pp_field": field, "mark": 1}, (pair,)),
        "origin without a field": (
            {"origin": pp_origin, "pp_version": version, "mark": 1},
            (pair,),
        ),
        "origin without either": ({"origin": pp_origin, "mark": 1}, (pair,)),
        "pair without the origin (authored)": (
            {"origin": authored, "pp_version": version, "pp_field": field, "mark": 1},
            (pair,),
        ),
        "version alone": ({"origin": authored, "pp_version": version}, (pair, pair_check)),
        "field alone": ({"origin": authored, "pp_field": field}, (pair, pair_check)),
        "legacy origin carrying the pair": (
            {"origin": legacy, "legacy": 3, "pp_version": version, "pp_field": field, "mark": 1},
            (pair, "provenance_exclusive"),
        ),
        "both provenances on a player-profile origin": (
            {"origin": pp_origin, "legacy": 3, "pp_version": version, "pp_field": field, "mark": 1},
            ("needs the source row version, and only it does", "provenance_exclusive"),
        ),
        "empty text with the origin": (
            {
                "origin": pp_origin,
                "pp_version": version,
                "pp_field": field,
                "mark": 1,
                "text": None,
            },
            ("has the authored origin",),
        ),
    }
    for name, (overrides, expected) in cases.items():
        message = _refused(
            postgres_engine,
            lambda c, o=overrides: _raw_insert(c, g, ctx["character"], "public_appearance", **o),
        )
        assert any(fragment in message for fragment in expected), (name, message[:300])
    assert _draft_row(postgres_engine, g.campaign_id, ctx["character"]) is None


def test_a_draft_or_release_can_cite_only_its_own_campaigns_profile_of_the_same_character(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any]
) -> None:
    with postgres_engine.connect() as connection:
        b_version, field = _pp_ids(connection, ctx["campaign_b"], ctx["character"], "personality")
        pp_origin = _origin(connection, "player_profile")
    # Campaign A's draft citing campaign B's version of the same character: the composite key refuses.
    error = None
    with pytest.raises(IntegrityError) as raised, postgres_engine.begin() as connection:
        _raw_insert(
            connection, g, ctx["character"], "public_appearance",
            origin=pp_origin, pp_version=b_version, pp_field=field, mark=1,
        )  # fmt: skip
    error = str(raised.value)
    assert "fk_character_public_profiles_appearance_pp_version" in error
    # The same through a different character in campaign A (A has no profile for it at all).
    with postgres_engine.connect() as connection:
        a_version, _ = _pp_ids(connection, g.campaign_id, ctx["character"], "personality")
    with pytest.raises(IntegrityError) as raised, postgres_engine.begin() as connection:
        _raw_insert(
            connection, g, ctx["other"], "public_background",
            origin=pp_origin, pp_version=a_version, pp_field=field, mark=1,
        )  # fmt: skip
    assert "fk_character_public_profiles_background_pp_version" in str(raised.value)
    # A release is held to the same rule.
    seed_player_profile_copy(
        postgres_engine, campaign_id=g.campaign_id, character_id=ctx["character"],
        membership_id=g.o1, target_field="public_appearance", source_field="personality",
    )  # fmt: skip

    def raw_release(connection: Connection, version: uuid.UUID) -> None:
        connection.execute(
            text(f"""
                INSERT INTO {RELEASES} (character_public_profile_id, campaign_id, character_id,
                    version_number, from_draft_row_version, public_appearance,
                    public_appearance_origin_id, public_background_origin_id,
                    public_appearance_origin_player_profile_version_id,
                    public_appearance_origin_player_profile_field_id,
                    authority_source_code, released_by_membership_id)
                SELECT d.character_public_profile_id, d.campaign_id, d.character_id, 1, 1,
                       'x', :origin, d.public_background_origin_id, :version, :field, 'owner', :m
                FROM {DRAFTS} d WHERE d.campaign_id = :c AND d.character_id = :ch
            """),  # noqa: S608
            {"origin": pp_origin, "version": version, "field": field, "m": g.o1,
             "c": g.campaign_id, "ch": ctx["character"]},
        )  # fmt: skip

    with pytest.raises(IntegrityError) as raised, postgres_engine.begin() as connection:
        raw_release(connection, b_version)
    assert "fk_character_public_profile_releases_appearance_pp_version" in str(raised.value)
    with postgres_engine.begin() as connection:
        raw_release(connection, a_version)  # its own campaign's version is accepted


def test_a_release_cannot_cite_an_ineligible_source_field_either(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any]
) -> None:
    seed_player_profile_copy(
        postgres_engine, campaign_id=g.campaign_id, character_id=ctx["character"],
        membership_id=g.o1, target_field="public_appearance", source_field="personality",
    )  # fmt: skip
    with postgres_engine.connect() as connection:
        version, boundaries = _pp_ids(connection, g.campaign_id, ctx["character"], "boundaries")
        pp_origin = _origin(connection, "player_profile")
    message = _refused(
        postgres_engine,
        lambda c: c.execute(
            text(f"""
                INSERT INTO {RELEASES} (character_public_profile_id, campaign_id, character_id,
                    version_number, from_draft_row_version, public_appearance,
                    public_appearance_origin_id, public_background_origin_id,
                    public_appearance_origin_player_profile_version_id,
                    public_appearance_origin_player_profile_field_id,
                    authority_source_code, released_by_membership_id)
                SELECT d.character_public_profile_id, d.campaign_id, d.character_id, 1, 1,
                       'x', :origin, d.public_background_origin_id, :version, :field, 'owner', :m
                FROM {DRAFTS} d WHERE d.campaign_id = :c AND d.character_id = :ch
            """),  # noqa: S608
            {"origin": pp_origin, "version": version, "field": boundaries, "m": g.o1,
             "c": g.campaign_id, "ch": ctx["character"]},
        ),
    )  # fmt: skip
    assert "cannot be the origin of a public field" in message


def test_the_legacy_origin_still_means_the_character_row_version_and_nothing_else(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any]
) -> None:
    """A player-profile field never stores a source in `origin_entity_row_version`: the helper's row
    has it NULL, and the origin trigger refuses a legacy origin without it (142, unchanged)."""
    seed_player_profile_copy(
        postgres_engine, campaign_id=g.campaign_id, character_id=ctx["character"],
        membership_id=g.o1, target_field="public_appearance", source_field="goals",
    )  # fmt: skip
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None and row["public_appearance_origin_entity_row_version"] is None
    with postgres_engine.connect() as connection:
        legacy = _origin(connection, "legacy_background")
    message = _refused(
        postgres_engine,
        lambda c: _raw_insert(c, g, ctx["other"], "public_background", origin=legacy, mark=1),
    )
    assert "needs the source row version" in message


# --- watermark and relabel rules (the 143/144 rules, generalized) -------------------------------------------


def _seeded(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], target: str = "public_appearance"
) -> int:
    return seed_player_profile_copy(
        postgres_engine, campaign_id=g.campaign_id, character_id=ctx["character"],
        membership_id=g.o1, target_field=target, source_field="personality",
    )  # fmt: skip


@pytest.mark.parametrize("target", FIELDS)
def test_a_new_copy_needs_its_watermark_equal_to_row_version(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], target: str
) -> None:
    with postgres_engine.connect() as connection:
        version, field = _pp_ids(connection, g.campaign_id, ctx["character"], "ideals")
        pp_origin = _origin(connection, "player_profile")
    for mark in (None, 2, 5):
        message = _refused(
            postgres_engine,
            lambda c, mark=mark: _raw_insert(
                c, g, ctx["character"], target,
                origin=pp_origin, pp_version=version, pp_field=field, mark=mark,
            ),
        )  # fmt: skip
        assert "watermark" in message, (mark, message[:200])
    assert _draft_row(postgres_engine, g.campaign_id, ctx["character"]) is None


@pytest.mark.parametrize("target", FIELDS)
def test_every_content_change_advances_the_watermark_and_nothing_else_may(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], target: str
) -> None:
    _seeded(postgres_engine, g, ctx, target)
    c = _cols(target)
    where = "campaign_id = :c AND character_id = :ch"
    params = {"c": g.campaign_id, "ch": ctx["character"]}
    # Changing the text without advancing the watermark is refused (and so is any other value).
    for mark in (None, 1, 5):
        mark_sql = "NULL" if mark is None else str(mark)
        message = _refused(
            postgres_engine,
            lambda conn, m=mark_sql: conn.execute(
                text(
                    f"UPDATE {DRAFTS} SET {c['text']} = 'edited', {c['mark']} = {m} WHERE {where}"
                ),  # noqa: S608
                params,
            ),
        )
        assert "watermark" in message, (mark, message[:200])
    # Advancing it to the new row_version (old + 1) is accepted.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(f"UPDATE {DRAFTS} SET {c['text']} = 'edited', {c['mark']} = 2 WHERE {where}"),  # noqa: S608
            params,
        )
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None and row["row_version"] == 2 and row[c["mark"]] == 2
    # Changing the provenance (the cited field) with identical text is a content change too.
    with postgres_engine.connect() as connection:
        _, other_field = _pp_ids(connection, g.campaign_id, ctx["character"], "bonds")
    message = _refused(
        postgres_engine,
        lambda conn: conn.execute(
            text(f"UPDATE {DRAFTS} SET {c['pp_field']} = :f WHERE {where}"),  # noqa: S608
            {**params, "f": other_field},
        ),
    )
    assert "must advance its watermark" in message
    with postgres_engine.begin() as connection:
        connection.execute(
            text(f"UPDATE {DRAFTS} SET {c['pp_field']} = :f, {c['mark']} = 3 WHERE {where}"),  # noqa: S608
            {**params, "f": other_field},
        )
    # An update that leaves the content alone keeps the watermark; lowering it is refused.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(f"UPDATE {DRAFTS} SET should_publish_size = true WHERE {where}"), params
        )  # noqa: S608
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None and row[c["mark"]] == 3 and row["row_version"] == 4
    message = _refused(
        postgres_engine,
        lambda conn: conn.execute(
            text(f"UPDATE {DRAFTS} SET {c['mark']} = 2 WHERE {where}"),
            params,  # noqa: S608
        ),
    )
    assert "never decreases" in message or "violates check constraint" in message


@pytest.mark.parametrize("target", FIELDS)
def test_the_other_field_is_left_alone_by_a_copy_and_by_its_edits(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], target: str
) -> None:
    other = "public_background" if target == "public_appearance" else "public_appearance"
    with postgres_engine.begin() as connection:
        _raw_insert(connection, g, ctx["character"], other, text="authored other")
    seed_player_profile_copy(
        postgres_engine, campaign_id=g.campaign_id, character_id=ctx["character"],
        membership_id=g.o1, target_field=target, source_field="fears",
    )  # fmt: skip
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None
    assert row[other] == "authored other" and row[_cols(other)["mark"]] is None
    assert row[_cols(other)["pp_version"]] is None and row[_cols(target)["mark"]] == 2


@pytest.mark.parametrize("target", FIELDS)
def test_player_profile_text_cannot_be_relabelled_authored_while_text_remains(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], target: str
) -> None:
    _seeded(postgres_engine, g, ctx, target)
    c = _cols(target)
    where, params = (
        "campaign_id = :c AND character_id = :ch",
        {"c": g.campaign_id, "ch": ctx["character"]},
    )
    with postgres_engine.connect() as connection:
        authored = _origin(connection, "authored")
    relabels = {
        "authored origin, provenance and watermark cleared, text kept": (
            f"{c['origin']} = :a, {c['pp_version']} = NULL, {c['pp_field']} = NULL, {c['mark']} = NULL"
        ),
        "the same with replacement text": (
            f"{c['text']} = 'rewritten', {c['origin']} = :a, {c['pp_version']} = NULL, "
            f"{c['pp_field']} = NULL, {c['mark']} = NULL"
        ),
        "the same advancing the old watermark": (
            f"{c['origin']} = :a, {c['pp_version']} = NULL, {c['pp_field']} = NULL, {c['mark']} = 2"
        ),
    }
    for name, assignment in relabels.items():
        message = _refused(
            postgres_engine,
            lambda conn, a=assignment: conn.execute(
                text(f"UPDATE {DRAFTS} SET {a} WHERE {where}"),
                {**params, "a": authored},  # noqa: S608
            ),
        )
        assert "cannot be relabelled authored" in message, (name, message[:200])
    # Clearing the text clears the lineage in the one permitted write.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {DRAFTS} SET {c['text']} = NULL, {c['origin']} = :a, {c['pp_version']} = NULL, "  # noqa: S608
                f"{c['pp_field']} = NULL, {c['mark']} = NULL WHERE {where}"
            ),
            {**params, "a": authored},
        )
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None and row[c["text"]] is None and row[c["mark"]] is None
    assert row[c["pp_version"]] is None and row[c["pp_field"]] is None


def test_legacy_provenance_is_still_protected_by_the_generalized_relabel_guard(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any]
) -> None:
    with postgres_engine.connect() as connection:
        legacy, authored = _origin(connection, "legacy_appearance"), _origin(connection, "authored")
    with postgres_engine.begin() as connection:
        _raw_insert(
            connection, g, ctx["character"], "public_appearance", origin=legacy, legacy=3, mark=1
        )
    where, params = (
        "campaign_id = :c AND character_id = :ch",
        {"c": g.campaign_id, "ch": ctx["character"]},
    )
    message = _refused(
        postgres_engine,
        lambda conn: conn.execute(
            text(
                f"UPDATE {DRAFTS} SET public_appearance_origin_id = :a, "  # noqa: S608
                "public_appearance_origin_entity_row_version = NULL, "
                f"public_appearance_restricted_row_version = NULL WHERE {where}"
            ),
            {**params, "a": authored},
        ),
    )
    assert "cannot be relabelled authored" in message


@pytest.mark.parametrize(
    ("from_origin", "to_origin"), [("legacy", "player_profile"), ("player_profile", "legacy")]
)
def test_switching_provenance_between_legacy_and_player_profile_must_advance_the_watermark(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any], from_origin: str, to_origin: str
) -> None:
    c = _cols("public_appearance")
    where, params = (
        "campaign_id = :c AND character_id = :ch",
        {"c": g.campaign_id, "ch": ctx["character"]},
    )
    with postgres_engine.connect() as connection:
        version, field = _pp_ids(connection, g.campaign_id, ctx["character"], "loyalties")
        legacy, pp = _origin(connection, "legacy_appearance"), _origin(connection, "player_profile")
    if from_origin == "legacy":
        with postgres_engine.begin() as connection:
            _raw_insert(
                connection,
                g,
                ctx["character"],
                "public_appearance",
                origin=legacy,
                legacy=3,
                mark=1,
            )
        switch = f"{c['origin']} = :pp, {c['legacy']} = NULL, {c['pp_version']} = :v, {c['pp_field']} = :f"
    else:
        _seeded(postgres_engine, g, ctx)
        switch = f"{c['origin']} = :legacy, {c['legacy']} = 4, {c['pp_version']} = NULL, {c['pp_field']} = NULL"
    values = {**params, "pp": pp, "legacy": legacy, "v": version, "f": field}
    message = _refused(
        postgres_engine,
        lambda conn: conn.execute(text(f"UPDATE {DRAFTS} SET {switch} WHERE {where}"), values),  # noqa: S608
    )
    assert "must advance its watermark" in message or "check constraint" in message
    with postgres_engine.begin() as connection:  # advancing it to row_version + 1 is accepted
        old = connection.execute(
            text(f"SELECT row_version FROM {DRAFTS} WHERE {where}"), params
        ).scalar_one()  # noqa: S608
        connection.execute(
            text(f"UPDATE {DRAFTS} SET {switch}, {c['mark']} = :m WHERE {where}"),  # noqa: S608
            {**values, "m": int(old) + 1},
        )
    row = _draft_row(postgres_engine, g.campaign_id, ctx["character"])
    assert row is not None and row["appearance_origin"] != from_origin.replace(
        "legacy", "legacy_appearance"
    )


def test_the_watermark_is_set_exactly_when_either_provenance_is(
    postgres_engine: Engine, g: Gate, ctx: dict[str, Any]
) -> None:
    _seeded(postgres_engine, g, ctx)
    where, params = (
        "campaign_id = :c AND character_id = :ch",
        {"c": g.campaign_id, "ch": ctx["character"]},
    )
    # A watermark without provenance (authored text) is refused by the paired CHECK.
    with postgres_engine.begin() as connection:
        _raw_insert(connection, g, ctx["other"], "public_background", text="authored")
    message = _refused(
        postgres_engine,
        lambda conn: conn.execute(
            text(
                f"UPDATE {DRAFTS} SET public_background_restricted_row_version = 1 "  # noqa: S608
                "WHERE campaign_id = :c AND character_id = :ch"
            ),
            {"c": g.campaign_id, "ch": ctx["other"]},
        ),
    )
    assert "ck_character_public_profiles_background_watermark_paired" in message
    # Provenance without a watermark is refused too (the paired CHECK or the trigger).
    message = _refused(
        postgres_engine,
        lambda conn: conn.execute(
            text(
                f"UPDATE {DRAFTS} SET public_appearance_restricted_row_version = NULL WHERE {where}"
            ),  # noqa: S608
            params,
        ),
    )
    assert "watermark" in message, message[:200]


# --- structure of the change --------------------------------------------------------------------------


def test_the_new_columns_are_commented_indexed_and_the_grants_are_unchanged(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        for table in ("character_public_profiles", "character_public_profile_releases"):
            rows = connection.execute(
                text("""
                    SELECT a.attname, col_description(c.oid, a.attnum) AS comment
                    FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'campaign' AND c.relname = :t
                      AND a.attname LIKE '%origin_player_profile%' AND NOT a.attisdropped
                """),
                {"t": table},
            ).all()
            assert len(rows) == 4 and all(r.comment for r in rows), table
            indexes = connection.execute(
                text(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname = 'campaign' AND tablename = :t "
                    "AND indexdef LIKE '%origin_player_profile%' AND indexdef LIKE '%WHERE%'"
                ),
                {"t": table},
            ).scalar_one()
            assert indexes == 4, table

        # No privilege was widened: the application role still cannot write the source tables, and the
        # draft and release privileges are what 142 left them.
        def has(role: str, table: str, privilege: str) -> bool:
            return bool(
                connection.execute(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": role, "t": table, "p": privilege},
                ).scalar()
            )

        for table in (
            "campaign.character_player_profiles",
            "campaign.character_player_profile_versions",
            "campaign.player_profile_fields",
        ):
            assert not any(
                has("app_read_write", table, p) for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
            )
            assert not any(
                has(role, table, "SELECT") for role in ("integration_worker", "app_read_only")
            )
        assert not any(has("app_read_write", RELEASES, p) for p in ("UPDATE", "DELETE", "TRUNCATE"))
        assert not any(has("app_read_write", DRAFTS, p) for p in ("DELETE", "TRUNCATE"))
