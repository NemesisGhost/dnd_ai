# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The integrity rules of migration 142 (P03-A A2a): constraints, triggers and grants.

Each rule is exercised with the statement that would break it, on committed fixtures (the Gate:
two campaign owners, a custom manager, a player), because several of them are triggers that read
other tables. Releases are append-only to everyone, the draft is never deleted by the application,
and a character that has a profile cannot be physically deleted.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dnd_ai.commands.character_reveal import grant_character_reveal_delegation
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    g,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

DRAFTS = "campaign.character_public_profiles"
RELEASES = "campaign.character_public_profile_releases"


def _origin(connection: Any, code: str) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT public_profile_field_origin_id FROM campaign.public_profile_field_origins "
            "WHERE code = :c"
        ),
        {"c": code},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _draft(connection: Any, g: Gate, character: uuid.UUID, **overrides: object) -> uuid.UUID:
    authored = _origin(connection, "authored")
    values: dict[str, object] = {
        "campaign": g.campaign_id,
        "character": character,
        "appearance": "Tall.",
        "background": None,
        "a_origin": authored,
        "a_version": None,
        "b_origin": authored,
        "b_version": None,
        "a_mark": None,
        "b_mark": None,
        "created_by": g.o1,
    }
    values.update(overrides)
    value = connection.execute(
        text(f"""
            INSERT INTO {DRAFTS} (
                campaign_id, character_id, public_appearance, public_appearance_origin_id,
                public_appearance_origin_entity_row_version, public_background,
                public_background_origin_id, public_background_origin_entity_row_version,
                public_appearance_restricted_row_version, public_background_restricted_row_version,
                created_by_membership_id, updated_by_membership_id)
            VALUES (:campaign, :character, :appearance, :a_origin, :a_version, :background,
                    :b_origin, :b_version, :a_mark, :b_mark, :created_by, :created_by)
            RETURNING character_public_profile_id
        """),  # noqa: S608
        values,
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _release(
    connection: Any, g: Gate, profile: uuid.UUID, character: uuid.UUID, **overrides: object
) -> uuid.UUID:
    authored = _origin(connection, "authored")
    values: dict[str, object] = {
        "profile": profile,
        "campaign": g.campaign_id,
        "character": character,
        "version": 1,
        "from_version": 1,
        "appearance": "Tall.",
        "background": None,
        "a_origin": authored,
        "b_origin": authored,
        "source": "owner",
        "delegation": None,
        "by": g.o1,
    }
    values.update(overrides)
    value = connection.execute(
        text(f"""
            INSERT INTO {RELEASES} (
                character_public_profile_id, campaign_id, character_id, version_number,
                from_draft_row_version, public_appearance, public_appearance_origin_id,
                public_background, public_background_origin_id, authority_source_code,
                character_reveal_delegation_id, released_by_membership_id)
            VALUES (:profile, :campaign, :character, :version, :from_version, :appearance,
                    :a_origin, :background, :b_origin, :source, :delegation, :by)
            RETURNING character_public_profile_release_id
        """),  # noqa: S608
        values,
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


@pytest.fixture
def two(postgres_engine: Engine, g: Gate) -> tuple[uuid.UUID, uuid.UUID]:
    with postgres_engine.begin() as connection:
        return (
            make_character(connection, g.world_id, name="Schema One"),
            make_character(connection, g.world_id, name="Schema Two"),
        )


def _refused(engine: Engine, statement: Callable[[Any], object]) -> str:
    with pytest.raises(DBAPIError) as raised, engine.begin() as connection:
        statement(connection)
    return str(raised.value)


# --- releases are append-only ---------------------------------------------------------------------


def test_releases_refuse_update_delete_and_truncate_and_the_roles_hold_no_such_privilege(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    with postgres_engine.begin() as connection:
        profile = _draft(connection, g, character)
        release = _release(connection, g, profile, character)
    for statement in (
        f"UPDATE {RELEASES} SET release_note = 'edited' WHERE character_public_profile_release_id = :r",
        f"DELETE FROM {RELEASES} WHERE character_public_profile_release_id = :r",
    ):
        message = _refused(
            postgres_engine, lambda c, s=statement: c.execute(text(s), {"r": release})
        )
        assert "append-only" in message, statement
    assert "append-only" in _refused(
        postgres_engine, lambda c: c.execute(text(f"TRUNCATE {RELEASES}"))
    )
    with postgres_engine.connect() as connection:
        granted = {
            (table, role, privilege): bool(
                connection.execute(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": role, "table": table, "privilege": privilege},
                ).scalar()
            )
            for table in (DRAFTS, RELEASES)
            for role in ("app_read_write", "integration_worker", "app_read_only")
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }
    # The application role reads and appends releases and reads, creates and updates drafts.
    assert granted[(RELEASES, "app_read_write", "SELECT")]
    assert granted[(RELEASES, "app_read_write", "INSERT")]
    assert all(granted[(DRAFTS, "app_read_write", p)] for p in ("SELECT", "INSERT", "UPDATE"))
    # No application role can update or delete a release, or delete or truncate a draft. (The
    # integration worker holds no grants in the campaign schema at all.)
    for role in ("app_read_write", "integration_worker"):
        assert not any(granted[(RELEASES, role, p)] for p in ("UPDATE", "DELETE", "TRUNCATE"))
        assert not any(granted[(DRAFTS, role, p)] for p in ("DELETE", "TRUNCATE"))
    assert not any(
        granted[(table, "app_read_only", p)]
        for table in (DRAFTS, RELEASES)
        for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
    )


def test_version_numbers_and_draft_versions_are_unique_per_profile(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    with postgres_engine.begin() as connection:
        profile = _draft(connection, g, character)
        _release(connection, g, profile, character)
    duplicate_version = _refused(
        postgres_engine,
        lambda c: _release(c, g, profile, character, version=1, from_version=2),
    )
    assert "ux_character_public_profile_releases_version" in duplicate_version
    duplicate_draft = _refused(
        postgres_engine,
        lambda c: _release(c, g, profile, character, version=2, from_version=1),
    )
    assert "ux_character_public_profile_releases_draft_version" in duplicate_draft


def test_a_draft_is_unique_per_campaign_and_character(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    with postgres_engine.begin() as connection:
        _draft(connection, g, two[0])
    assert "ux_character_public_profiles_campaign_character" in _refused(
        postgres_engine, lambda c: _draft(c, g, two[0])
    )


# --- scope ----------------------------------------------------------------------------------------


def test_a_release_cannot_name_another_characters_or_campaigns_profile(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    one, other = two
    with postgres_engine.begin() as connection:
        profile = _draft(connection, g, one)
        other_campaign = make_campaign(connection, g.timeline_id, "Schema Campaign B")
        b_user = make_user(connection, "Schema B Owner")
        b_membership = make_campaign_membership(connection, other_campaign, b_user)
        make_membership_role(connection, b_membership, g.owner_role_id)
    try:
        wrong_character = _refused(postgres_engine, lambda c: _release(c, g, profile, other))
        assert "fk_character_public_profile_releases_profile" in wrong_character
        wrong_campaign = _refused(
            postgres_engine,
            lambda c: _release(c, g, profile, one, campaign=other_campaign, by=b_membership),
        )
        assert "fk_character_public_profile_releases_profile" in wrong_campaign
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                    "(SELECT campaign_membership_id FROM security.campaign_memberships "
                    "WHERE campaign_id = :c)"
                ),
                {"c": other_campaign},
            )
            connection.execute(
                text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
                {"c": other_campaign},
            )
            connection.execute(
                text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": other_campaign}
            )


def test_the_scope_triggers_refuse_a_foreign_character_foreign_memberships_and_a_wrong_delegation(
    postgres_engine: Engine, g: Gate, m: Members, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    with postgres_engine.begin() as connection:
        foreign_world = make_world(connection, slug=f"schema-foreign-{uuid.uuid4().hex[:8]}")
        foreign_character = make_character(connection, foreign_world, name="Schema Foreign")
        other_campaign = make_campaign(connection, g.timeline_id, "Schema Scope Campaign")
        foreign_user = make_user(connection, "Schema Foreign Member")
        foreign_membership = make_campaign_membership(connection, other_campaign, foreign_user)
        make_membership_role(connection, foreign_membership, g.owner_role_id)
        profile = _draft(connection, g, character)
        grant_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Schema delegation",
        )
        delegation = connection.execute(
            text(
                "SELECT character_reveal_delegation_id FROM security.character_reveal_delegations "
                "WHERE grantee_campaign_membership_id = :m"
            ),
            {"m": m.gm},
        ).scalar_one()
    try:
        assert "not in the world" in _refused(
            postgres_engine, lambda c: _draft(c, g, foreign_character)
        )
        assert "does not belong to campaign" in _refused(
            postgres_engine,
            lambda c: _draft(c, g, two[1], created_by=foreign_membership),
        )
        assert "does not belong to campaign" in _refused(
            postgres_engine, lambda c: _release(c, g, profile, character, by=foreign_membership)
        )
        # A delegation names its grantee: only that member may release under it.
        assert "is not a delegation" in _refused(
            postgres_engine,
            lambda c: _release(
                c, g, profile, character, source="delegation", delegation=delegation, by=g.o1
            ),
        )
        with postgres_engine.begin() as connection:  # the right pairing works
            _release(
                connection,
                g,
                profile,
                character,
                source="delegation",
                delegation=delegation,
                by=m.gm,
            )
        # The source and the delegation id must agree.
        assert "delegation_pairing" in _refused(
            postgres_engine,
            lambda c: _release(
                c,
                g,
                profile,
                character,
                version=2,
                from_version=2,
                source="owner",
                delegation=delegation,
                by=m.gm,
            ),  # fmt: skip
        )
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                    "(SELECT campaign_membership_id FROM security.campaign_memberships "
                    "WHERE campaign_id = :c)"
                ),
                {"c": other_campaign},
            )
            connection.execute(
                text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
                {"c": other_campaign},
            )
            connection.execute(
                text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": other_campaign}
            )
            connection.execute(
                text("DELETE FROM core.entities WHERE world_id = :w"), {"w": foreign_world}
            )
            connection.execute(
                text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": foreign_world}
            )


# --- origins --------------------------------------------------------------------------------------


def test_the_origin_rules_hold(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    with postgres_engine.connect() as connection:
        legacy_appearance = _origin(connection, "legacy_appearance")
        legacy_background = _origin(connection, "legacy_background")
    # A legacy origin needs the source row version, and only a legacy origin carries one.
    assert "needs the source row version" in _refused(
        postgres_engine, lambda c: _draft(c, g, character, a_origin=legacy_appearance)
    )
    assert "needs the source row version" in _refused(
        postgres_engine, lambda c: _draft(c, g, character, a_version=3)
    )
    # An origin that belongs to the other field cannot describe this one.
    assert "cannot describe the public appearance" in _refused(
        postgres_engine,
        lambda c: _draft(c, g, character, a_origin=legacy_background, a_version=3),
    )
    assert "cannot describe the public background" in _refused(
        postgres_engine,
        lambda c: _draft(c, g, character, b_origin=legacy_appearance, b_version=3),
    )
    # Empty text has the authored origin.
    assert "empty public appearance" in _refused(
        postgres_engine,
        lambda c: _draft(c, g, character, appearance=None, a_origin=legacy_appearance, a_version=3),
    )
    with postgres_engine.begin() as connection:  # a well-formed legacy origin is accepted
        # A migration-143 database also needs the watermark (equal to row_version on insert).
        _draft(connection, g, character, a_origin=legacy_appearance, a_version=3, a_mark=1)


# --- a character with a profile is never physically deleted --------------------------------------------


def test_a_character_with_a_draft_or_release_cannot_be_physically_deleted(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    with postgres_engine.begin() as connection:
        profile = _draft(connection, g, character)
    assert isinstance(
        _refused_exc(
            postgres_engine,
            lambda c: c.execute(
                text("DELETE FROM core.entities WHERE entity_id = :e"), {"e": character}
            ),
        ),  # noqa: E501
        IntegrityError,
    )
    with postgres_engine.begin() as connection:
        _release(connection, g, profile, character)
    assert isinstance(
        _refused_exc(
            postgres_engine,
            lambda c: c.execute(
                text("DELETE FROM core.entities WHERE entity_id = :e"), {"e": character}
            ),
        ),  # noqa: E501
        IntegrityError,
    )
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM core.entities WHERE entity_id = :e"), {"e": character}
            ).scalar_one()
            == 1
        )


def _refused_exc(engine: Engine, statement: Callable[[Any], object]) -> BaseException:
    with pytest.raises(DBAPIError) as raised, engine.begin() as connection:
        statement(connection)
    return raised.value
