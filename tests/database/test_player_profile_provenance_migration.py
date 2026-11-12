"""Migration 148 (P03-A A5b): the `player_profile` origin and its provenance columns, on throwaway
databases.

A populated upgrade from 147 (authored and legacy-copied rows are untouched: no `row_version` moves,
no audit row), the downgrade guard (it refuses, changing nothing, while any draft or release carries
player-profile provenance, tested for each), the clean downgrade that restores revision 142's origin
function, 143's paired CHECK and 144's watermark function exactly (compared by definition before and
after), a re-upgrade, and `alembic check` for drift between the migration and the metadata.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text

from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_timeline,
    make_user,
    make_world,
)
from tests.player_profile_support import (
    seed_player_profile,
    seed_player_profile_copy_in,
)

pytestmark = pytest.mark.database

PARENT = "147_character_player_profiles"
TARGET = "148_player_profile_provenance"
DRAFTS = "campaign.character_public_profiles"
RELEASES = "campaign.character_public_profile_releases"
_NEW_COLUMNS = tuple(
    f"public_{field}_origin_player_profile_{kind}_id"
    for field in ("appearance", "background")
    for kind in ("version", "field")
)
_FUNCTIONS = (
    "campaign.enforce_public_profile_field_origins()",
    "campaign.enforce_public_profile_restriction_watermarks()",
)
_PAIRED = (
    "ck_character_public_profiles_appearance_watermark_paired",
    "ck_character_public_profiles_background_watermark_paired",
)


def _revision(connection: Connection) -> str:
    return str(
        connection.execute(text("SELECT version_num FROM core.alembic_version")).scalar_one()
    )


def _columns(connection: Connection, table: str) -> set[str]:
    schema, name = table.split(".")
    return set(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = ANY(:n)"
            ),
            {"s": schema, "t": name, "n": list(_NEW_COLUMNS)},
        ).scalars()
    )


def _definitions(connection: Connection) -> dict[str, Any]:
    """What the downgrade must restore exactly: the two trigger functions (body and comment), the
    paired CHECKs, the origin lookup's codes and its table comment."""
    out: dict[str, Any] = {}
    for function in _FUNCTIONS:
        out[function] = connection.execute(
            text("SELECT pg_get_functiondef(CAST(:f AS regprocedure))"), {"f": function}
        ).scalar_one()
        out[function + " comment"] = connection.execute(
            text("SELECT obj_description(CAST(:f AS regprocedure), 'pg_proc')"), {"f": function}
        ).scalar_one()
    for name in _PAIRED:
        out[name] = connection.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
            {"n": name},
        ).scalar_one()
    out["origins"] = sorted(
        connection.execute(
            text("SELECT code, sort_order FROM campaign.public_profile_field_origins")
        ).all()
    )
    out["lookup comment"] = connection.execute(
        text("SELECT obj_description('campaign.public_profile_field_origins'::regclass)")
    ).scalar_one()
    out["watermark column comment"] = connection.execute(
        text(
            "SELECT col_description('campaign.character_public_profiles'::regclass, attnum) "
            "FROM pg_attribute WHERE attrelid = 'campaign.character_public_profiles'::regclass "
            "AND attname = 'public_appearance_restricted_row_version'"
        )
    ).scalar_one()
    return out


def _legacy_draft(
    connection: Connection, campaign: uuid.UUID, character: uuid.UUID, membership: uuid.UUID
) -> None:
    """A draft written as 142 to 144 allow: a legacy-copied appearance with its watermark."""
    connection.execute(
        text("""
            INSERT INTO campaign.character_public_profiles (
                campaign_id, character_id, public_appearance, public_appearance_origin_id,
                public_appearance_origin_entity_row_version,
                public_appearance_restricted_row_version, public_background,
                public_background_origin_id, created_by_membership_id, updated_by_membership_id)
            VALUES (:c, :ch, 'Legacy copied', (SELECT public_profile_field_origin_id
                        FROM campaign.public_profile_field_origins WHERE code = 'legacy_appearance'),
                    3, 1, 'Authored', (SELECT public_profile_field_origin_id
                        FROM campaign.public_profile_field_origins WHERE code = 'authored'),
                    :m, :m)
        """),
        {"c": campaign, "ch": character, "m": membership},
    )


def _state(connection: Connection) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in connection.execute(
            text(f"""
                SELECT character_id, row_version, public_appearance, public_background,
                       public_appearance_origin_entity_row_version,
                       public_appearance_restricted_row_version, updated_at
                FROM {DRAFTS} ORDER BY character_id
            """)  # noqa: S608
        )
    ]


def test_populated_upgrade_guarded_downgrade_exact_restoration_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            world = make_world(connection, slug=f"pp-prov-{uuid.uuid4().hex[:8]}")
            timeline = make_timeline(connection, world, is_primary=True)
            campaign = make_campaign(
                connection, timeline, "Provenance Migration", lifecycle_status_code="active"
            )
            legacy_character = make_character(connection, world, name="Legacy Copied")
            authored_character = make_character(connection, world, name="Authored Only")
            profiled = make_character(connection, world, name="Profiled")
            user = make_user(connection, "Provenance Migration Editor")
            membership = make_campaign_membership(connection, campaign, user)
            owner_role = connection.execute(
                text(
                    "SELECT role_id FROM security.roles WHERE code = 'campaign_owner' "
                    "AND campaign_id IS NULL"
                )
            ).scalar_one()
            make_membership_role(connection, membership, owner_role)
            _legacy_draft(connection, campaign, legacy_character, membership)
            connection.execute(
                text(f"""
                    INSERT INTO {DRAFTS} (campaign_id, character_id, public_appearance,
                        public_appearance_origin_id, public_background_origin_id)
                    SELECT :c, :ch, 'Plainly authored', o.public_profile_field_origin_id,
                           o.public_profile_field_origin_id
                    FROM campaign.public_profile_field_origins o WHERE o.code = 'authored'
                """),  # noqa: S608
                {"c": campaign, "ch": authored_character},
            )
        seed_player_profile(
            engine,
            campaign_id=campaign,
            character_id=profiled,
            editor_membership_id=membership,
            fields={"personality": "Copy me", "boundaries": "Never copy"},
        )
        with engine.connect() as connection:
            before_state = _state(connection)
            before_audit = connection.execute(
                text("SELECT count(*) FROM audit.change_log")
            ).scalar_one()
            before_definitions = _definitions(connection)
            assert _columns(connection, DRAFTS) == set() == _columns(connection, RELEASES)
            assert "player_profile" not in {o[0] for o in before_definitions["origins"]}

        _alembic_upgrade(test_url, TARGET)
        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            assert _columns(connection, DRAFTS) == set(_NEW_COLUMNS)
            assert _columns(connection, RELEASES) == set(_NEW_COLUMNS)
            # Existing rows are untouched: same row_version, text, origin, watermark and timestamp,
            # and no audit row was written.
            assert _state(connection) == before_state
            assert (
                connection.execute(text("SELECT count(*) FROM audit.change_log")).scalar_one()
                == before_audit
            )
            after_up = _definitions(connection)
            assert "player_profile" in {o[0] for o in after_up["origins"]}
            assert after_up != before_definitions

        # A5b: a draft field from a copy-eligible source field is accepted, one from boundaries
        # never is, and the guard refuses the downgrade while it exists.
        with engine.begin() as connection:
            seed_player_profile_copy_in(
                connection,
                campaign_id=campaign,
                character_id=profiled,
                membership_id=membership,
                target_field="public_background",
                source_field="personality",
            )
        refused = _alembic(test_url, "downgrade", PARENT)
        assert refused.returncode != 0
        assert "Copy me" not in refused.stdout + refused.stderr
        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            assert _columns(connection, DRAFTS) == set(_NEW_COLUMNS)
            assert _definitions(connection) == after_up

        # The guard also refuses on a release row alone (a release is immutable, so the draft is
        # cleared first and the release remains).
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(f"""
                    INSERT INTO {RELEASES} (character_public_profile_id, campaign_id, character_id,
                        version_number, from_draft_row_version, public_background,
                        public_appearance_origin_id, public_background_origin_id,
                        public_background_origin_player_profile_version_id,
                        public_background_origin_player_profile_field_id,
                        authority_source_code, released_by_membership_id)
                    SELECT d.character_public_profile_id, d.campaign_id, d.character_id, 1, 1,
                           d.public_background, d.public_appearance_origin_id,
                           d.public_background_origin_id,
                           d.public_background_origin_player_profile_version_id,
                           d.public_background_origin_player_profile_field_id, 'owner', :m
                    FROM {DRAFTS} d WHERE d.character_id = :ch
                """),  # noqa: S608
                {"m": membership, "ch": profiled},
            )
            connection.execute(
                text(f"""
                    UPDATE {DRAFTS} SET public_background = NULL,
                        public_background_origin_id = (SELECT public_profile_field_origin_id
                            FROM campaign.public_profile_field_origins WHERE code = 'authored'),
                        public_background_origin_player_profile_version_id = NULL,
                        public_background_origin_player_profile_field_id = NULL,
                        public_background_restricted_row_version = NULL
                    WHERE character_id = :ch
                """),  # noqa: S608
                {"ch": profiled},
            )
        still_refused = _alembic(test_url, "downgrade", PARENT)
        assert still_refused.returncode != 0
        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            assert _columns(connection, RELEASES) == set(_NEW_COLUMNS)

        # With no player-profile provenance anywhere the downgrade is clean, and restores 142's
        # origin function, 143's paired CHECK and 144's watermark function exactly.
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(text(f"DELETE FROM {RELEASES}"))  # noqa: S608
        downgraded = _alembic(test_url, "downgrade", PARENT)
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _revision(connection) == PARENT
            assert _columns(connection, DRAFTS) == set() == _columns(connection, RELEASES)
            restored = _definitions(connection)
            for key, value in before_definitions.items():
                assert restored[key] == value, key
            # Authored and legacy drafts survive the whole round trip untouched.
            assert [
                r for r in _state(connection) if r[0] in {legacy_character, authored_character}
            ] == before_state

        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_fresh_database_upgrades_to_head_with_no_drift() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "head")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            assert _columns(connection, DRAFTS) == set(_NEW_COLUMNS)
            codes = set(
                connection.execute(
                    text("SELECT code FROM campaign.public_profile_field_origins")
                ).scalars()
            )
            assert codes == {
                "authored",
                "legacy_appearance",
                "legacy_background",
                "player_profile",
            }
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
