"""rules.rulesets, rules.ruleset_versions, rules.world_rulesets, and the
closed forward references (revisions 013, 016).

Covers: at most one current version per ruleset, at most one default ruleset
per world, and the two forward references (core.worlds.default_ruleset_id,
campaign.campaigns.ruleset_id) both requiring the ruleset be allowed for the
relevant world via rules.world_rulesets.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import make_campaign, make_ruleset_for_world, make_timeline, make_world

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _make_ruleset(connection: Connection, code: str) -> uuid.UUID:
    return connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()


def _make_version(
    connection: Connection, ruleset_id: uuid.UUID, label: str, *, is_current: bool = False
) -> uuid.UUID:
    return connection.execute(
        text("""
            INSERT INTO rules.ruleset_versions (ruleset_id, version_label, is_current)
            VALUES (:r, :l, :c)
            RETURNING ruleset_version_id
        """),
        {"r": ruleset_id, "l": label, "c": is_current},
    ).scalar()


# ---------------------------------------------------------------------------
# rules.ruleset_versions
# ---------------------------------------------------------------------------


def test_a_ruleset_may_have_several_versions(db_connection: Connection) -> None:
    ruleset = _make_ruleset(db_connection, "test_versions")
    _make_version(db_connection, ruleset, "2014")
    _make_version(db_connection, ruleset, "2024")

    count = db_connection.execute(
        text("SELECT count(*) FROM rules.ruleset_versions WHERE ruleset_id = :r"), {"r": ruleset}
    ).scalar()
    assert count == 2


def test_a_ruleset_cannot_have_two_current_versions(db_connection: Connection) -> None:
    ruleset = _make_ruleset(db_connection, "test_two_current")
    _make_version(db_connection, ruleset, "2014", is_current=True)

    with pytest.raises(IntegrityError) as exc:
        _make_version(db_connection, ruleset, "2024", is_current=True)
    assert "ux_ruleset_versions_one_current_per_ruleset" in str(exc.value)


def test_two_rulesets_may_each_have_a_current_version(db_connection: Connection) -> None:
    first = _make_ruleset(db_connection, "test_current_a")
    second = _make_ruleset(db_connection, "test_current_b")
    _make_version(db_connection, first, "v1", is_current=True)
    _make_version(db_connection, second, "v1", is_current=True)


# ---------------------------------------------------------------------------
# rules.world_rulesets
# ---------------------------------------------------------------------------


def test_a_world_may_allow_more_than_one_ruleset(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-world")
    make_ruleset_for_world(db_connection, world, code="ruleset_a")
    make_ruleset_for_world(db_connection, world, code="ruleset_b")

    count = db_connection.execute(
        text("SELECT count(*) FROM rules.world_rulesets WHERE world_id = :w"), {"w": world}
    ).scalar()
    assert count == 2


def test_a_world_cannot_have_two_default_rulesets(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-two-defaults")
    make_ruleset_for_world(db_connection, world, code="ruleset_default_a")

    other_ruleset = _make_ruleset(db_connection, "ruleset_default_b")
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO rules.world_rulesets (world_id, ruleset_id, is_default)
                VALUES (:w, :r, true)
            """),
            {"w": world, "r": other_ruleset},
        )
    assert "ux_world_rulesets_one_default_per_world" in str(exc.value)


# ---------------------------------------------------------------------------
# core.worlds.default_ruleset_id
# ---------------------------------------------------------------------------


def test_world_default_ruleset_must_be_allowed(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-default-world")
    ruleset = _make_ruleset(db_connection, "not_allowed_ruleset")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.worlds SET default_ruleset_id = :r WHERE world_id = :w"),
            {"r": ruleset, "w": world},
        )
    assert "not an allowed ruleset" in str(exc.value)


def test_world_default_ruleset_succeeds_once_allowed(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-default-ok-world")
    ruleset = make_ruleset_for_world(db_connection, world, code="allowed_ruleset")

    db_connection.execute(
        text("UPDATE core.worlds SET default_ruleset_id = :r WHERE world_id = :w"),
        {"r": ruleset, "w": world},
    )


# ---------------------------------------------------------------------------
# campaign.campaigns.ruleset_id
# ---------------------------------------------------------------------------


def test_campaign_ruleset_must_be_allowed_for_its_world(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-campaign-world")
    timeline = make_timeline(db_connection, world, is_primary=True)
    disallowed_ruleset = _make_ruleset(db_connection, "campaign_disallowed_ruleset")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_campaign(db_connection, timeline, ruleset_id=disallowed_ruleset)
    assert "not an allowed ruleset" in str(exc.value)


def test_campaign_ruleset_succeeds_once_allowed(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-campaign-ok-world")
    timeline = make_timeline(db_connection, world, is_primary=True)
    ruleset = make_ruleset_for_world(db_connection, world, code="campaign_allowed_ruleset")

    make_campaign(db_connection, timeline, ruleset_id=ruleset)
