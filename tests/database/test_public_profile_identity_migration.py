"""Migration 146 (P03-A A4a): publishable species and size on public-profile drafts and releases.

Runs on throwaway databases: a populated upgrade from 145 (drafts read false, releases carry null
identity, no `row_version` moves, an existing release still returns from the GM read), every CHECK
and the insert trigger, the downgrade guard that refuses atomically while a profile holds two
releases of one draft version, the lossy downgrade, a re-upgrade, and `alembic check`.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from dnd_ai.domain.access import resolve_access_context
from dnd_ai.queries.character_public_profile import read_character_public_profile
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import make_character, make_user

pytestmark = pytest.mark.database

PARENT = "145_character_revelations"
TARGET = "146_public_profile_identity"
_RELEASE_COLUMNS = (
    "released_species_id",
    "released_species_code",
    "released_species_display_name",
    "released_size_category",
    "identity_entity_row_version",
)
_DRAFT_COLUMNS = ("should_publish_species", "should_publish_size")
_TRIGGER = "tr_character_public_profile_releases_enforce_identity"


def _columns(connection: Connection, table: str, names: tuple[str, ...]) -> int:
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'campaign' "
                "AND table_name = :t AND column_name = ANY(:n)"
            ),
            {"t": table, "n": list(names)},
        ).scalar_one()
    )


def _revision(connection: Connection) -> str:
    return str(
        connection.execute(text("SELECT version_num FROM core.alembic_version")).scalar_one()
    )


def _constraint(connection: Connection, name: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conname = :n"), {"n": name}
        ).scalar()
    )


def _trigger(connection: Connection) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM pg_trigger WHERE tgname = :n"), {"n": _TRIGGER}
        ).scalar()
    )


def _insert_release(
    connection: Connection,
    *,
    profile: uuid.UUID,
    campaign: uuid.UUID,
    character: uuid.UUID,
    membership: uuid.UUID,
    version: int,
    from_version: int,
    extra: dict[str, Any] | None = None,
) -> None:
    origin = connection.execute(
        text(
            "SELECT public_profile_field_origin_id FROM campaign.public_profile_field_origins "
            "WHERE code = 'authored'"
        )
    ).scalar_one()
    columns = {
        "character_public_profile_id": profile,
        "campaign_id": campaign,
        "character_id": character,
        "version_number": version,
        "from_draft_row_version": from_version,
        "public_appearance": "Tall.",
        "public_appearance_origin_id": origin,
        "public_background_origin_id": origin,
        "authority_source_code": "owner",
        "released_by_membership_id": membership,
        **(extra or {}),
    }
    names = ", ".join(columns)
    binds = ", ".join(f":{name}" for name in columns)
    connection.execute(
        text(f"INSERT INTO campaign.character_public_profile_releases ({names}) VALUES ({binds})"),  # noqa: S608
        columns,
    )


def _refused(connection: Connection, *, triggers_off: bool = False, **kwargs: Any) -> str:
    """The error text of an insert that must fail, rolled back to a savepoint. BEFORE triggers run
    ahead of CHECK constraints, so the CHECK tests switch triggers off for the statement
    (`session_replication_role = replica` reverts with the savepoint)."""
    with pytest.raises(DBAPIError) as raised, connection.begin_nested():
        if triggers_off:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
        _insert_release(connection, **kwargs)
    return str(raised.value)


def test_populated_upgrade_checks_guarded_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            assert _columns(connection, "character_public_profiles", _DRAFT_COLUMNS) == 0
            assert _columns(connection, "character_public_profile_releases", _RELEASE_COLUMNS) == 0
            owner = make_user(connection, "Identity Migration Owner")
            world = make_authored_world(connection, owner_user_id=owner, name="Identity World")
            campaign = make_authored_campaign(connection, world, name="Identity Campaign")
            character = make_character(connection, world.world_id, name="Identity Character")
            membership = connection.execute(
                text("SELECT campaign_membership_id FROM security.campaign_memberships LIMIT 1")
            ).scalar_one()
            origin = connection.execute(
                text(
                    "SELECT public_profile_field_origin_id "
                    "FROM campaign.public_profile_field_origins WHERE code = 'authored'"
                )
            ).scalar_one()
            profile = connection.execute(
                text("""
                    INSERT INTO campaign.character_public_profiles (
                        campaign_id, character_id, public_appearance,
                        public_appearance_origin_id, public_background_origin_id,
                        created_by_membership_id, updated_by_membership_id)
                    VALUES (:c, :ch, 'Tall.', :o, :o, :m, :m)
                    RETURNING character_public_profile_id
                """),
                {"c": campaign, "ch": character, "o": origin, "m": membership},
            ).scalar_one()
            _insert_release(
                connection,
                profile=profile,
                campaign=campaign,
                character=character,
                membership=membership,
                version=1,
                from_version=1,
            )
            draft_version = connection.execute(
                text("SELECT row_version FROM campaign.character_public_profiles")
            ).scalar_one()
            entity_version = connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :e"),
                {"e": character},
            ).scalar_one()

        _alembic_upgrade(test_url, TARGET)
        with engine.begin() as connection:
            assert _revision(connection) == TARGET
            assert _columns(connection, "character_public_profiles", _DRAFT_COLUMNS) == 2
            assert _columns(connection, "character_public_profile_releases", _RELEASE_COLUMNS) == 5
            flags = connection.execute(
                text(
                    "SELECT should_publish_species, should_publish_size FROM campaign.character_public_profiles"
                )
            ).one()
            assert tuple(flags) == (False, False)
            release = connection.execute(
                text(
                    "SELECT released_species_id, released_species_code, "
                    "released_species_display_name, released_size_category, "
                    "identity_entity_row_version "
                    "FROM campaign.character_public_profile_releases"
                )
            ).one()
            assert tuple(release) == (None, None, None, None, None)
            # No row_version moved: the flag defaults fire no row trigger.
            assert (
                connection.execute(
                    text("SELECT row_version FROM campaign.character_public_profiles")
                ).scalar_one()
                == draft_version
            )
            assert (
                connection.execute(
                    text("SELECT row_version FROM core.entities WHERE entity_id = :e"),
                    {"e": character},
                ).scalar_one()
                == entity_version
            )
            assert _constraint(connection, "ux_character_public_profile_releases_draft_identity")
            assert not _constraint(connection, "ux_character_public_profile_releases_draft_version")
            assert _trigger(connection)

            # --- every CHECK, and the insert trigger -------------------------------------------
            species, size = connection.execute(
                text(
                    "SELECT species_id, size_category FROM character.characters WHERE character_id = :c"
                ),
                {"c": character},
            ).one()
            code, display = connection.execute(
                text("SELECT code, display_name FROM rules.species WHERE species_id = :s"),
                {"s": species},
            ).one()
            base: dict[str, Any] = {
                "profile": profile,
                "campaign": campaign,
                "character": character,
                "membership": membership,
                "version": 2,
                "from_version": 1,
            }
            valid = {
                "released_species_id": species,
                "released_species_code": code,
                "released_species_display_name": display,
                "released_size_category": size,
                "identity_entity_row_version": entity_version,
            }
            # Species columns: all null or all set.
            assert "species_snapshot" in _refused(
                connection,
                triggers_off=True,
                **base,
                extra={
                    **valid,
                    "released_species_code": None,
                    "identity_entity_row_version": entity_version,
                },
            )
            assert "species_snapshot" in _refused(
                connection,
                triggers_off=True,
                **base,
                extra={**valid, "released_species_display_name": None},
            )
            # Size: one of the six codes.
            assert "size_category" in _refused(
                connection,
                triggers_off=True,
                **base,
                extra={**valid, "released_size_category": "colossal"},
            )
            # The entity version is set exactly when species or size is, and is at least 1.
            assert "identity_version" in _refused(
                connection,
                triggers_off=True,
                **base,
                extra={"identity_entity_row_version": entity_version},
            )
            assert "identity_version" in _refused(
                connection,
                triggers_off=True,
                **base,
                extra={**valid, "identity_entity_row_version": None},
            )
            assert "identity_version" in _refused(
                connection,
                triggers_off=True,
                **base,
                extra={**valid, "identity_entity_row_version": 0},
            )
            # The trigger: published values must equal the live definition.
            assert "actual species" in _refused(
                connection, **base, extra={**valid, "released_species_display_name": "Disguise"}
            )
            assert "actual size" in _refused(
                connection, **base, extra={**valid, "released_size_category": "tiny"}
            )
            assert "row_version" in _refused(
                connection,
                **base,
                extra={**valid, "identity_entity_row_version": entity_version + 1},
            )
            # The live values are accepted (this one stays: version 2 of the profile).
            _insert_release(connection, **base, extra=valid)

        # The downgrade refuses, and changes nothing, while a profile holds two releases of one
        # draft version (version 1 has no identity, version 2 carries one: legal after 146).
        refused = _alembic(test_url, "downgrade", PARENT)
        assert refused.returncode != 0
        assert "Refusing to downgrade 146_public_profile_identity" in (
            refused.stderr + refused.stdout
        )
        with engine.begin() as connection:
            assert _revision(connection) == TARGET
            assert _columns(connection, "character_public_profile_releases", _RELEASE_COLUMNS) == 5
            assert _columns(connection, "character_public_profiles", _DRAFT_COLUMNS) == 2
            assert _trigger(connection)
            assert _constraint(connection, "ux_character_public_profile_releases_draft_identity")
            assert not _constraint(connection, "ux_character_public_profile_releases_draft_version")
            # Make the downgrade possible again: remove the second release of draft version 1.
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "DELETE FROM campaign.character_public_profile_releases WHERE version_number = 2"
                )
            )

        downgraded = _alembic(test_url, "downgrade", PARENT)
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.begin() as connection:
            assert _revision(connection) == PARENT
            assert _columns(connection, "character_public_profiles", _DRAFT_COLUMNS) == 0
            assert _columns(connection, "character_public_profile_releases", _RELEASE_COLUMNS) == 0
            assert not _trigger(connection)
            assert _constraint(connection, "ux_character_public_profile_releases_draft_version")
            assert not _constraint(
                connection, "ux_character_public_profile_releases_draft_identity"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_proc WHERE proname = 'enforce_public_profile_release_identity'"
                    )
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM campaign.character_public_profile_releases")
                ).scalar_one()
                == 1
            )
        _alembic_upgrade(test_url, "head")
        # An existing release still returns from the GM read. (A5b: the current read selects the
        # player-profile provenance columns migration 148 adds, so this assertion, which ran at 146,
        # now runs after upgrading to head; the data it reads is the same pre-existing release.)
        with engine.begin() as connection:
            access = resolve_access_context(connection, user_id=owner, campaign_id=campaign)
            assert access is not None
            view = read_character_public_profile(connection, access=access, character_id=character)
            assert view is not None
            assert view["latest_release"]["version_number"] == 1
            assert view["draft"]["row_version"] == draft_version
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
