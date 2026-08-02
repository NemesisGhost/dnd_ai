"""rules.rulesets, rules.ruleset_versions, rules.world_rulesets, and the
closed forward references (revisions 013, 016, 024, 027).

Covers: at most one current version per ruleset, a world's allowed-ruleset
allow-list, and the two forward references (core.worlds.default_ruleset_id,
campaign.campaigns.ruleset_version_id) both requiring the ruleset be allowed
for the relevant world via rules.world_rulesets. Since revision 027,
core.worlds.default_ruleset_id is the sole source of truth for a world's
default — rules.world_rulesets no longer has its own is_default flag.
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


def _current_version(connection: Connection, ruleset_id: uuid.UUID) -> uuid.UUID:
    return connection.execute(
        text(
            "SELECT ruleset_version_id FROM rules.ruleset_versions "
            "WHERE ruleset_id = :r AND is_current"
        ),
        {"r": ruleset_id},
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


def test_world_rulesets_has_no_default_flag_of_its_own(db_connection: Connection) -> None:
    """revision 027: core.worlds.default_ruleset_id is the sole source of
    truth for a world's default ruleset. rules.world_rulesets is a pure
    allow-list with no is_default column at all — two allowed rulesets for
    one world coexist with no uniqueness rule between them."""
    columns = {
        r[0]
        for r in db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'rules' AND table_name = 'world_rulesets'"
            )
        )
    }
    assert "is_default" not in columns


def test_removing_a_worlds_default_ruleset_association_is_rejected(
    db_connection: Connection,
) -> None:
    world = make_world(db_connection, slug="ruleset-remove-default")
    ruleset = make_ruleset_for_world(db_connection, world, code="ruleset_still_default")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("DELETE FROM rules.world_rulesets WHERE world_id = :w AND ruleset_id = :r"),
            {"w": world, "r": ruleset},
        )
    assert "is that world's default" in str(exc.value)


def test_removing_a_ruleset_a_campaign_depends_on_is_rejected(
    db_connection: Connection,
) -> None:
    world = make_world(db_connection, slug="ruleset-remove-in-use")
    timeline = make_timeline(db_connection, world, is_primary=True)
    # is_default=False so the campaign-dependency path (not the default path)
    # is what this test actually exercises.
    ruleset = make_ruleset_for_world(db_connection, world, code="ruleset_in_use", is_default=False)
    make_campaign(
        db_connection, timeline, ruleset_version_id=_current_version(db_connection, ruleset)
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("DELETE FROM rules.world_rulesets WHERE world_id = :w AND ruleset_id = :r"),
            {"w": world, "r": ruleset},
        )
    assert "still pinned to a version of it" in str(exc.value)


def test_removing_an_unused_allowed_ruleset_succeeds(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-remove-unused")
    ruleset = make_ruleset_for_world(db_connection, world, code="ruleset_unused", is_default=False)

    db_connection.execute(
        text("DELETE FROM rules.world_rulesets WHERE world_id = :w AND ruleset_id = :r"),
        {"w": world, "r": ruleset},
    )


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
# campaign.campaigns.ruleset_version_id
# ---------------------------------------------------------------------------


def test_campaign_ruleset_must_be_allowed_for_its_world(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-campaign-world")
    timeline = make_timeline(db_connection, world, is_primary=True)
    disallowed_ruleset = _make_ruleset(db_connection, "campaign_disallowed_ruleset")
    disallowed_version = _make_version(db_connection, disallowed_ruleset, "v1", is_current=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_campaign(db_connection, timeline, ruleset_version_id=disallowed_version)
    assert "not allowed for world" in str(exc.value)


def test_campaign_ruleset_succeeds_once_allowed(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="ruleset-campaign-ok-world")
    timeline = make_timeline(db_connection, world, is_primary=True)
    ruleset = make_ruleset_for_world(db_connection, world, code="campaign_allowed_ruleset")

    make_campaign(
        db_connection, timeline, ruleset_version_id=_current_version(db_connection, ruleset)
    )


def test_campaign_pins_a_specific_version_not_just_the_ruleset_family(
    db_connection: Connection,
) -> None:
    """revision 024: a campaign is reproducible because it is pinned to one
    ruleset_version, not merely to a ruleset family that might later gain a
    second, different, current version."""
    world = make_world(db_connection, slug="ruleset-campaign-pin-world")
    timeline = make_timeline(db_connection, world, is_primary=True)
    ruleset = make_ruleset_for_world(db_connection, world, code="ruleset_pin_family")
    old_version = _current_version(db_connection, ruleset)

    campaign_id = make_campaign(db_connection, timeline, ruleset_version_id=old_version)

    # A new version becomes current; the campaign's pin does not silently follow.
    db_connection.execute(
        text("UPDATE rules.ruleset_versions SET is_current = false WHERE ruleset_id = :r"),
        {"r": ruleset},
    )
    _make_version(db_connection, ruleset, "v2", is_current=True)

    pinned = db_connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    assert pinned == old_version
