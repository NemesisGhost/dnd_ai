# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Migration 143 and its database rules (P03-A A2b-1): per-field restriction watermarks.

Two parts. First, the CHECKs and the trigger on a head database: they refuse a draft write that
would lift a restriction (invariants I1 and I2, plan section 9.2), and accept the writes that must
stay possible (I3). Second, the migration itself on disposable PostgreSQL databases: it preserves
authored drafts and immutable releases, and its preflight and its downgrade guard each refuse
*atomically*, leaving the database, its revision and every row exactly as they were.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    g,
)
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import make_character, make_user

pytestmark = pytest.mark.database

DRAFTS = "campaign.character_public_profiles"
RELEASES = "campaign.character_public_profile_releases"
REVISION = "143_profile_watermarks"
PARENT = "142_character_public_profiles"


# --- the CHECKs and the trigger, on a head database -----------------------------------------------------


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


def _insert_draft(
    connection: Connection,
    g: Gate,
    character: uuid.UUID,
    *,
    legacy_background: bool = False,
    watermark: int | None = None,
    source_version: int | None = None,
) -> uuid.UUID:
    authored = _origin(connection, "authored")
    legacy = _origin(connection, "legacy_background") if legacy_background else authored
    value = connection.execute(
        text(f"""
            INSERT INTO {DRAFTS} (
                campaign_id, character_id, public_appearance, public_appearance_origin_id,
                public_background, public_background_origin_id,
                public_background_origin_entity_row_version,
                public_background_restricted_row_version)
            VALUES (:c, :ch, 'authored text', :authored, 'copied text', :legacy, :source, :mark)
            RETURNING character_public_profile_id
        """),  # noqa: S608
        {
            "c": g.campaign_id,
            "ch": character,
            "authored": authored,
            "legacy": legacy,
            "source": source_version,
            "mark": watermark,
        },
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _refused(engine: Engine, statement: Any, *, replica: bool = False) -> str:
    with pytest.raises(DBAPIError) as raised, engine.begin() as connection:
        if replica:  # disables triggers so a CHECK constraint is exercised on its own
            connection.execute(text("SET LOCAL session_replication_role = replica"))
        statement(connection)
    return str(raised.value)


@pytest.fixture
def character(postgres_engine: Engine, g: Gate) -> uuid.UUID:
    with postgres_engine.begin() as connection:
        return make_character(connection, g.world_id, name="Watermark Character")


def test_the_checks_refuse_a_watermark_that_is_unpaired_unbounded_or_below_one(
    postgres_engine: Engine, g: Gate, character: uuid.UUID
) -> None:
    # A watermark on an authored field, and a legacy field without one (the pairing CHECK).
    assert "watermark_paired" in _refused(
        postgres_engine,
        lambda c: _insert_draft(c, g, character, legacy_background=False, watermark=1),
        replica=True,
    )
    assert "watermark_paired" in _refused(
        postgres_engine,
        lambda c: _insert_draft(c, g, character, legacy_background=True, source_version=3),
        replica=True,
    )
    # Above row_version (a new draft is at version 1) and below one.
    assert "watermark_bounded" in _refused(
        postgres_engine,
        lambda c: _insert_draft(
            c, g, character, legacy_background=True, source_version=3, watermark=2
        ),
        replica=True,
    )
    assert "watermark_positive" in _refused(
        postgres_engine,
        lambda c: _insert_draft(
            c, g, character, legacy_background=True, source_version=3, watermark=0
        ),
        replica=True,
    )


def test_the_trigger_enforces_that_a_legacy_field_carries_the_version_of_its_last_change(
    postgres_engine: Engine, g: Gate, character: uuid.UUID
) -> None:
    # A legacy-origin INSERT must carry watermark = row_version (1).
    assert "needs its watermark" in _refused(
        postgres_engine,
        lambda c: _insert_draft(
            c, g, character, legacy_background=True, source_version=3, watermark=2
        ),
    )
    with postgres_engine.begin() as connection:
        profile = _insert_draft(
            connection, g, character, legacy_background=True, source_version=3, watermark=1
        )

    def change(set_clause: str) -> Any:
        return lambda c: c.execute(
            text(f"UPDATE {DRAFTS} SET {set_clause} WHERE character_public_profile_id = :p"),  # noqa: S608
            {"p": profile},
        )

    # Changing the copied text without advancing the watermark (or advancing it wrongly) is refused.
    assert "must advance its watermark" in _refused(
        postgres_engine, change("public_background = 'edited'")
    )
    assert "must advance its watermark" in _refused(
        postgres_engine,
        change("public_background = 'edited', public_background_restricted_row_version = 3"),
    )
    # So is changing only the source version, or the origin, without the watermark.
    assert "must advance its watermark" in _refused(
        postgres_engine, change("public_background_origin_entity_row_version = 9")
    )
    # Advancing it to OLD.row_version + 1 is accepted.
    with postgres_engine.begin() as connection:
        change("public_background = 'edited', public_background_restricted_row_version = 2")(
            connection
        )
    # An update of the OTHER field leaves this watermark alone (I3), and cannot lower it.
    with postgres_engine.begin() as connection:
        change("public_appearance = 'another authored edit'")(connection)
    assert "never decreases" in _refused(
        postgres_engine,
        change("public_appearance = 'x', public_background_restricted_row_version = 1"),
    )
    with postgres_engine.connect() as connection:
        marks = connection.execute(
            text(
                f"SELECT row_version, public_background_restricted_row_version FROM {DRAFTS} "  # noqa: S608
                "WHERE character_public_profile_id = :p"
            ),
            {"p": profile},
        ).one()
    assert tuple(marks) == (3, 2)  # two edits; the watermark moved only with the background


def test_clearing_a_legacy_field_resets_its_lineage_in_one_write(
    postgres_engine: Engine, g: Gate, character: uuid.UUID
) -> None:
    with postgres_engine.begin() as connection:
        profile = _insert_draft(
            connection, g, character, legacy_background=True, source_version=3, watermark=1
        )
        authored = _origin(connection, "authored")
        connection.execute(
            text(f"""
                UPDATE {DRAFTS} SET public_background = NULL, public_background_origin_id = :a,
                    public_background_origin_entity_row_version = NULL,
                    public_background_restricted_row_version = NULL
                WHERE character_public_profile_id = :p
            """),  # noqa: S608
            {"a": authored, "p": profile},
        )


# --- the migration on disposable databases ------------------------------------------------------------------------


def _seed_142(engine: Engine, *, legacy: str | None = None) -> dict[str, Any]:
    """A campaign, a character, an authored draft and an authored release on a database at 142.
    `legacy` ("draft" or "release") also writes one legacy-origin row, which 143 must refuse."""
    with engine.begin() as connection:
        owner = make_user(connection, "Watermark Migration Owner")
        world = make_authored_world(connection, owner_user_id=owner, name="Watermark World")
        campaign = make_authored_campaign(connection, world, name="Watermark Campaign")
        membership = connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c LIMIT 1"
            ),
            {"c": campaign},
        ).scalar_one()
        authored = _origin(connection, "authored")
        legacy_origin = _origin(connection, "legacy_background")
        characters = [
            make_character(connection, world.world_id, name=f"Seed {n}") for n in range(2)
        ]
        profiles = []
        for index, character in enumerate(characters):
            is_legacy_draft = legacy == "draft" and index == 1
            profiles.append(
                connection.execute(
                    text(f"""
                        INSERT INTO {DRAFTS} (
                            campaign_id, character_id, public_appearance, public_appearance_origin_id,
                            public_background, public_background_origin_id,
                            public_background_origin_entity_row_version)
                        VALUES (:c, :ch, :appearance, :authored, :background, :bo, :source)
                        RETURNING character_public_profile_id
                    """),  # noqa: S608
                    {
                        "c": campaign,
                        "ch": character,
                        "appearance": f"authored appearance {index}",
                        "authored": authored,
                        "background": f"background {index}",
                        "bo": legacy_origin if is_legacy_draft else authored,
                        "source": 3 if is_legacy_draft else None,
                    },
                ).scalar_one()
            )
        release_origin = legacy_origin if legacy == "release" else authored
        connection.execute(
            text(f"""
                INSERT INTO {RELEASES} (
                    character_public_profile_id, campaign_id, character_id, version_number,
                    from_draft_row_version, public_appearance, public_appearance_origin_id,
                    public_background, public_background_origin_id,
                    public_background_origin_entity_row_version, authority_source_code,
                    released_by_membership_id)
                VALUES (:p, :c, :ch, 1, 1, 'released appearance', :authored, 'released background',
                        :bo, :source, 'owner', :m)
            """),  # noqa: S608
            {
                "p": profiles[0],
                "c": campaign,
                "ch": characters[0],
                "authored": authored,
                "bo": release_origin,
                "source": 3 if legacy == "release" else None,
                "m": membership,
            },
        )
    return {"campaign": campaign, "characters": characters, "profiles": profiles}


def _snapshot(engine: Engine) -> dict[str, list[Any]]:
    with engine.connect() as connection:
        drafts = connection.execute(
            text(
                "SELECT character_public_profile_id, row_version, public_appearance, "  # noqa: S608
                "public_background, public_appearance_origin_id, public_background_origin_id, "
                "public_background_origin_entity_row_version "
                f"FROM {DRAFTS} ORDER BY character_public_profile_id"
            )
        ).all()
        releases = connection.execute(
            text(
                "SELECT character_public_profile_release_id, version_number, "  # noqa: S608
                "from_draft_row_version, public_appearance, public_background, "
                "public_background_origin_id, public_background_origin_entity_row_version "
                f"FROM {RELEASES} ORDER BY character_public_profile_release_id"
            )
        ).all()
        audit = connection.execute(text("SELECT count(*) FROM audit.change_log")).scalar_one()
    return {
        "drafts": [tuple(r) for r in drafts],
        "releases": [tuple(r) for r in releases],
        "audit": [audit],
    }  # noqa: E501


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(text("SELECT version_num FROM core.alembic_version")).scalar_one()
        )


def _watermark_columns(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'campaign' AND table_name = 'character_public_profiles' "
                    "AND column_name LIKE '%restricted_row_version'"
                )
            ).scalar_one()
        )


def test_the_upgrade_keeps_authored_drafts_and_immutable_releases_and_the_downgrade_restores_them() -> (
    None
):
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        _seed_142(engine)
        before = _snapshot(engine)
        assert _watermark_columns(engine) == 0
        _alembic_upgrade(test_url, REVISION)
        assert _revision(engine) == REVISION and _watermark_columns(engine) == 2
        after = _snapshot(engine)
        assert after == before  # row_version, text, origins untouched; no audit row written
        with engine.connect() as connection:
            watermarks = connection.execute(
                text(
                    "SELECT count(*) FROM campaign.character_public_profiles WHERE "
                    "public_appearance_restricted_row_version IS NOT NULL OR "
                    "public_background_restricted_row_version IS NOT NULL"
                )
            ).scalar_one()
        assert watermarks == 0  # every existing draft is authored: NULL watermarks
        downgraded = _alembic(test_url, "downgrade", PARENT)
        assert downgraded.returncode == 0, downgraded.stderr
        assert _revision(engine) == PARENT and _watermark_columns(engine) == 0
        assert _snapshot(engine) == before
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


@pytest.mark.parametrize("legacy", ["draft", "release"])
def test_the_upgrade_refuses_a_legacy_origin_row_atomically(legacy: str) -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        _seed_142(engine, legacy=legacy)
        before = _snapshot(engine)
        refused = _alembic(test_url, "upgrade", REVISION)
        assert refused.returncode != 0
        assert "Refusing 143_profile_watermarks" in refused.stdout + refused.stderr
        # Nothing changed: the revision, the schema and every row (the authored ones included).
        assert _revision(engine) == PARENT
        assert _watermark_columns(engine) == 0
        assert _snapshot(engine) == before
        with engine.connect() as connection:
            triggers = connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname = 'tr_character_public_profiles_enforce_watermarks'"
                )
            ).scalar_one()
        assert triggers == 0
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


@pytest.mark.parametrize("legacy", ["draft", "release"])
def test_the_downgrade_refuses_while_a_legacy_origin_row_exists_atomically(legacy: str) -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, REVISION)
        engine = create_engine(test_url, connect_args=_connect_args())
        seeded = _seed_143(engine, legacy=legacy)
        before = _snapshot(engine)
        assert seeded
        refused = _alembic(test_url, "downgrade", PARENT)
        assert refused.returncode != 0
        assert "Refusing to downgrade 143_profile_watermarks" in refused.stdout + refused.stderr
        assert _revision(engine) == REVISION
        assert _watermark_columns(engine) == 2
        assert _snapshot(engine) == before
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def _seed_143(engine: Engine, *, legacy: str) -> bool:
    """The 142 seed on a database already at 143, with one legacy-origin row written the way the
    copy command will (a draft needs its watermark; a release needs none)."""
    with engine.begin() as connection:
        owner = make_user(connection, "Watermark Downgrade Owner")
        world = make_authored_world(connection, owner_user_id=owner, name="Downgrade World")
        campaign = make_authored_campaign(connection, world, name="Downgrade Campaign")
        membership = connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c LIMIT 1"
            ),
            {"c": campaign},
        ).scalar_one()
        authored = _origin(connection, "authored")
        legacy_origin = _origin(connection, "legacy_background")
        character = make_character(connection, world.world_id, name="Downgrade Character")
        legacy_draft = legacy == "draft"
        profile = connection.execute(
            text(f"""
                INSERT INTO {DRAFTS} (
                    campaign_id, character_id, public_appearance, public_appearance_origin_id,
                    public_background, public_background_origin_id,
                    public_background_origin_entity_row_version,
                    public_background_restricted_row_version)
                VALUES (:c, :ch, 'authored appearance', :authored, 'background', :bo, :source, :mark)
                RETURNING character_public_profile_id
            """),  # noqa: S608
            {
                "c": campaign,
                "ch": character,
                "authored": authored,
                "bo": legacy_origin if legacy_draft else authored,
                "source": 3 if legacy_draft else None,
                "mark": 1 if legacy_draft else None,
            },
        ).scalar_one()
        connection.execute(
            text(f"""
                INSERT INTO {RELEASES} (
                    character_public_profile_id, campaign_id, character_id, version_number,
                    from_draft_row_version, public_appearance, public_appearance_origin_id,
                    public_background, public_background_origin_id,
                    public_background_origin_entity_row_version, authority_source_code,
                    released_by_membership_id)
                VALUES (:p, :c, :ch, 1, 1, 'released', :authored, 'released background', :bo,
                        :source, 'owner', :m)
            """),  # noqa: S608
            {
                "p": profile,
                "c": campaign,
                "ch": character,
                "authored": authored,
                "bo": legacy_origin if legacy == "release" else authored,
                "source": 3 if legacy == "release" else None,
                "m": membership,
            },
        )
    return True
