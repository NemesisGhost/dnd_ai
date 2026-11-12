# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The integrity rules of migration 147 (P03-A A5a): constraints, triggers, grants and comments.

Each rule is exercised with the statement that would break it, on committed fixtures (the Gate: two
campaign owners, a custom manager, a player), because several rules are triggers that read other
tables. The raw statements in this file probe the schema's own refusals; the tests that need a
*valid* profile use the one fixture writer (`tests/player_profile_support.py`). The application
roles write none of the profile tables (decision D18): `app_read_write` holds SELECT only, and
`integration_worker` and `app_read_only` hold no access; checked both from the catalog and by
attempting the statements as the real runtime roles.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dnd_ai.domain.player_profiles import (
    COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS,
    PLAYER_PROFILE_FIELD_LABELS,
    PLAYER_PROFILE_FIELDS,
)
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_user,
    make_world,
)
from tests.player_profile_support import (
    edit_player_profile,
    edit_player_profile_in,
    seed_player_profile,
    seed_player_profile_in,
)

pytestmark = pytest.mark.database

LOOKUP = "campaign.player_profile_fields"
HEAD = "campaign.character_player_profiles"
VERSIONS = "campaign.character_player_profile_versions"
TABLES = (LOOKUP, HEAD, VERSIONS)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
ROLES = ("app_read_write", "integration_worker", "app_read_only")


@pytest.fixture
def two(postgres_engine: Engine, g: Gate) -> tuple[uuid.UUID, uuid.UUID]:
    with postgres_engine.begin() as connection:
        return (
            make_character(connection, g.world_id, name="Player Profile One"),
            make_character(connection, g.world_id, name="Player Profile Two"),
        )


def _profile_state(engine: Engine, head: uuid.UUID) -> tuple[int, int, str | None]:
    """(head row_version, number of versions, the `bonds` text of the newest version)."""
    with engine.connect() as connection:
        row = connection.execute(
            text(f"""
                SELECT h.row_version,
                       (SELECT count(*) FROM {VERSIONS} v
                         WHERE v.character_player_profile_id = h.character_player_profile_id),
                       (SELECT v.bonds FROM {VERSIONS} v
                         WHERE v.character_player_profile_id = h.character_player_profile_id
                         ORDER BY v.profile_row_version DESC LIMIT 1)
                FROM {HEAD} h WHERE h.character_player_profile_id = :h
            """),  # noqa: S608
            {"h": head},
        ).one()
    return (int(row[0]), int(row[1]), row[2])


def _refused(engine: Engine, statement: Callable[[Any], object]) -> str:
    with pytest.raises(DBAPIError) as raised, engine.begin() as connection:
        statement(connection)
    return str(raised.value)


def _refused_exc(engine: Engine, statement: Callable[[Any], object]) -> BaseException:
    with pytest.raises(DBAPIError) as raised, engine.begin() as connection:
        statement(connection)
    return raised.value


def _head(
    connection: Connection, g: Gate, character: uuid.UUID, campaign: uuid.UUID | None = None
) -> uuid.UUID:
    value = connection.execute(
        text(f"""
            INSERT INTO {HEAD} (campaign_id, character_id) VALUES (:c, :ch)
            RETURNING character_player_profile_id
        """),  # noqa: S608
        {"c": campaign or g.campaign_id, "ch": character},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _version(
    connection: Connection,
    g: Gate,
    head: uuid.UUID,
    character: uuid.UUID,
    *,
    row_version: int = 1,
    campaign: uuid.UUID | None = None,
    editor: uuid.UUID | None = None,
    **fields: str | None,
) -> None:
    columns = ", ".join(fields)
    values = "".join(f", :f_{name}" for name in fields)
    connection.execute(
        text(f"""
            INSERT INTO {VERSIONS} (
                character_player_profile_id, campaign_id, character_id, profile_row_version,
                edited_by_campaign_membership_id{", " + columns if columns else ""})
            VALUES (:h, :c, :ch, :rv, :ed{values})
        """),  # noqa: S608
        {
            "h": head,
            "c": campaign or g.campaign_id,
            "ch": character,
            "rv": row_version,
            "ed": editor or g.o1,
            **{f"f_{name}": value for name, value in fields.items()},
        },
    )


# --- grants: the application reads the profile and writes none of it (D18) ---------------------


def test_the_catalog_grants_the_application_roles_select_only_and_the_reporting_role_nothing(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        granted = {
            (table, role, privilege): bool(
                connection.execute(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": role, "table": table, "privilege": privilege},
                ).scalar()
            )
            for table in TABLES
            for role in ROLES
            for privilege in PRIVILEGES
        }
    for table in TABLES:
        for role in ("app_read_write", "integration_worker"):
            assert not any(granted[(table, role, p)] for p in PRIVILEGES[1:]), (table, role)
    for table in (HEAD, VERSIONS):
        assert granted[(table, "app_read_write", "SELECT")], table
        assert not any(granted[(table, "app_read_only", p)] for p in PRIVILEGES), table
    assert granted[(LOOKUP, "app_read_write", "SELECT")]
    # The narrower grants are the contract: no access at all for these two roles (not even SELECT).
    for table in TABLES:
        for role in ("integration_worker", "app_read_only"):
            assert not any(granted[(table, role, p)] for p in PRIVILEGES), (table, role)


def test_the_runtime_roles_can_read_the_profile_and_every_write_is_refused_by_the_database(
    postgres_engine: Engine,
    app_read_write_engine: Engine,
    g: Gate,
    two: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Actual `app_read_write` session (a login as that role) and `SET ROLE integration_worker`:
    each profile table is readable by the first and no INSERT, UPDATE, DELETE or TRUNCATE succeeds
    for either, whatever the row."""
    character = two[0]
    head = seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={"personality": "x"},
    )
    statements = (
        f"INSERT INTO {HEAD} (campaign_id, character_id) VALUES ('{g.campaign_id}', '{two[1]}')",
        f"UPDATE {HEAD} SET updated_at = now()",
        f"DELETE FROM {HEAD}",
        f"TRUNCATE {HEAD}",
        f"INSERT INTO {VERSIONS} (character_player_profile_id, campaign_id, character_id, "
        f"profile_row_version, edited_by_campaign_membership_id) "
        f"VALUES ('{head}', '{g.campaign_id}', '{character}', 2, '{g.o1}')",
        f"UPDATE {VERSIONS} SET personality = 'y'",
        f"DELETE FROM {VERSIONS}",
        f"TRUNCATE {VERSIONS}",
        f"UPDATE {LOOKUP} SET is_copy_eligible = true",
        f"INSERT INTO {LOOKUP} (code, display_name, is_copy_eligible) VALUES ('x', 'x', true)",
        f"DELETE FROM {LOOKUP}",
        f"TRUNCATE {LOOKUP}",
    )
    with app_read_write_engine.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {HEAD}")).scalar_one() >= 1  # noqa: S608
        assert connection.execute(text(f"SELECT count(*) FROM {VERSIONS}")).scalar_one() >= 1  # noqa: S608
        assert connection.execute(text(f"SELECT count(*) FROM {LOOKUP}")).scalar_one() == 11  # noqa: S608
        connection.rollback()
        for statement in statements:
            with pytest.raises(DBAPIError, match="permission denied"):
                connection.execute(text(statement))
            connection.rollback()
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET LOCAL ROLE integration_worker"))
            for statement in statements:
                nested = connection.begin_nested()
                with pytest.raises(DBAPIError, match="permission denied"):
                    connection.execute(text(statement))
                nested.rollback()
        finally:
            transaction.rollback()
    # Nothing changed.
    with postgres_engine.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {VERSIONS}")).scalar_one() == 1  # noqa: S608


# --- the lookup -------------------------------------------------------------------------------------


def test_the_lookup_holds_the_eleven_d13_fields_in_order_with_the_right_eligibility(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT code, display_name, is_copy_eligible, sort_order FROM {LOOKUP} "  # noqa: S608
                "ORDER BY sort_order"
            )
        ).all()
    assert [r.code for r in rows] == list(PLAYER_PROFILE_FIELDS)
    assert [r.sort_order for r in rows] == sorted(r.sort_order for r in rows)
    assert {r.code: r.display_name for r in rows} == PLAYER_PROFILE_FIELD_LABELS
    assert {r.code for r in rows if r.is_copy_eligible} == set(COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS)
    assert {r.code for r in rows if not r.is_copy_eligible} == {"boundaries", "profile_notes"}
    assert "player_notes" not in {r.code for r in rows}


# --- the head and its versions ------------------------------------------------------------------------


def test_a_profile_is_a_head_and_a_version_and_each_edit_adds_one_of_each_row_version(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    head = seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={"personality": "first"},
    )
    assert (
        edit_player_profile(
            postgres_engine,
            campaign_id=g.campaign_id,
            character_id=character,
            editor_membership_id=g.o2,
            fields={"personality": "second", "bonds": "b"},
        )
        == 2
    )
    with postgres_engine.connect() as connection:
        row_version = connection.execute(
            text(f"SELECT row_version FROM {HEAD} WHERE character_player_profile_id = :h"),  # noqa: S608
            {"h": head},
        ).scalar_one()
        versions = connection.execute(
            text(
                f"SELECT profile_row_version, personality, bonds, edited_by_campaign_membership_id "  # noqa: S608
                f"FROM {VERSIONS} WHERE character_player_profile_id = :h ORDER BY 1"
            ),
            {"h": head},
        ).all()
    assert row_version == 2
    assert [tuple(v) for v in versions] == [(1, "first", None, g.o1), (2, "second", "b", g.o2)]


def test_a_head_without_the_version_it_made_current_fails_at_commit(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    # A new head with no version.
    message = _refused(postgres_engine, lambda c: _head(c, g, character))
    assert "has no version at row_version 1" in message
    # A bumped head with no version for the new row_version.
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={"personality": "x"},
    )
    bumped = _refused(
        postgres_engine,
        lambda c: c.execute(
            text(f"UPDATE {HEAD} SET updated_at = now() WHERE character_id = :c"), {"c": character}
        ),  # noqa: S608
    )
    assert "has no version at row_version 2" in bumped
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT row_version FROM {HEAD} WHERE character_id = :c"),  # noqa: S608
                {"c": character},
            ).scalar_one()
            == 1
        )


def test_the_deferred_check_runs_at_commit_not_per_statement(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Inside one transaction the head may exist before its version; only COMMIT checks."""
    character = two[0]
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        head = _head(connection, g, character)
        assert connection.execute(text(f"SELECT count(*) FROM {HEAD}")).scalar_one() >= 1  # noqa: S608
        _version(connection, g, head, character, personality="ok")
        transaction.commit()


def test_a_version_must_carry_the_heads_current_row_version(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    head = seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={"personality": "x"},
    )
    for wrong in (2, 3, 7):
        message = _refused(
            postgres_engine,
            lambda c, wrong=wrong: _version(
                c, g, head, character, row_version=wrong, personality="y"
            ),
        )
        assert "must carry its head's current row_version" in message, wrong
    duplicate = _refused_exc(
        postgres_engine, lambda c: _version(c, g, head, character, row_version=1, personality="y")
    )
    assert isinstance(duplicate, IntegrityError)
    assert "ux_character_player_profile_versions_row_version" in str(duplicate)


def test_a_head_is_unique_per_campaign_and_character_and_its_identity_columns_are_immutable(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={},
    )
    # The fixture writer's ON CONFLICT race finds the existing head and reports it ...
    with (
        pytest.raises(ValueError, match="already has a player profile"),
        postgres_engine.begin() as connection,
    ):
        seed_player_profile_in(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            editor_membership_id=g.o1,
            fields={},
        )
    # ... and the unique key itself refuses a plain second insert.
    duplicate = _refused_exc(postgres_engine, lambda c: _head(c, g, character))
    assert isinstance(duplicate, IntegrityError)
    assert "ux_character_player_profiles_campaign_character" in str(duplicate)
    for column, value in (("character_id", two[1]), ("campaign_id", uuid.uuid4())):
        message = _refused(
            postgres_engine,
            lambda c, column=column, value=value: c.execute(
                text(f"UPDATE {HEAD} SET {column} = :v WHERE character_id = :c"),  # noqa: S608
                {"v": value, "c": character},
            ),
        )
        assert column in message
    message = _refused(
        postgres_engine,
        lambda c: c.execute(
            text(f"UPDATE {HEAD} SET row_version = 0 WHERE character_id = :c"),
            {"c": character},  # noqa: S608
        ),
    )
    # The bump trigger overrides a supplied value, so this is the missing-version refusal.
    assert "no version" in message


def test_scope_the_character_must_be_in_the_campaigns_world_and_the_editor_in_its_campaign(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    with postgres_engine.begin() as connection:
        foreign_world = make_world(connection, slug=f"pp-schema-{uuid.uuid4().hex[:8]}")
        foreign = make_character(connection, foreign_world, name="Foreign")
        other_campaign = make_campaign(
            connection, g.timeline_id, "Other", lifecycle_status_code="active"
        )
        outsider = make_user(connection, "Schema Outsider")
        other_member = make_campaign_membership(connection, other_campaign, outsider)
        make_membership_role(connection, other_member, g.owner_role_id)
    try:
        wrong_world = _refused(postgres_engine, lambda c: _head(c, g, foreign))
        assert "is not in the world of campaign" in wrong_world
        head = seed_player_profile(
            postgres_engine,
            campaign_id=g.campaign_id,
            character_id=character,
            editor_membership_id=g.o1,
            fields={},
        )

        def bump_then(connection: Connection, head_id: uuid.UUID, **version: Any) -> None:
            connection.execute(
                text(
                    f"UPDATE {HEAD} SET updated_at = now() WHERE character_player_profile_id = :h"  # noqa: S608
                ),
                {"h": head_id},
            )
            _version(connection, g, head_id, character, row_version=2, **version)

        # A fresh row_version (2, after bumping the head in the same transaction) so that neither
        # the duplicate-version key nor the head-match trigger can be what refuses it: only the
        # scope trigger's editor-campaign rule can. The whole transaction rolls back.
        before = _profile_state(postgres_engine, head)
        editor = _refused(
            postgres_engine, lambda c: bump_then(c, head, editor=other_member, bonds="b")
        )
        assert "Editing membership" in editor and "does not belong to campaign" in editor
        assert "ux_character_player_profile_versions" not in editor
        assert _profile_state(postgres_engine, head) == before == (1, 1, None)

        # A version in another campaign naming this head fails the composite foreign key. The head
        # is bumped first so that the row_version triggers and the unique key pass and only the
        # composite key can refuse.
        composite = _refused_exc(
            postgres_engine,
            lambda c: bump_then(c, head, campaign=other_campaign, editor=other_member),
        )
        assert isinstance(composite, IntegrityError)
        assert "fk_character_player_profile_versions_profile" in str(composite)
        # The same character in the second campaign gets its own head; a version of that head
        # cannot be filed under campaign A.
        with postgres_engine.begin() as connection:
            second_head = seed_player_profile_in(
                connection,
                campaign_id=other_campaign,
                character_id=character,
                editor_membership_id=other_member,
                fields={"personality": "B"},
            )
        crossed = _refused_exc(
            postgres_engine, lambda c: bump_then(c, second_head, campaign=g.campaign_id)
        )
        assert isinstance(crossed, IntegrityError)
        assert "fk_character_player_profile_versions_profile" in str(crossed)
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            for table in (VERSIONS, HEAD):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE campaign_id = :c"),
                    {"c": other_campaign},  # noqa: S608
                )
            connection.execute(
                text("DELETE FROM security.membership_roles WHERE campaign_membership_id = :m"),
                {"m": other_member},
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


# --- field checks ------------------------------------------------------------------------------------


@pytest.mark.parametrize("code", PLAYER_PROFILE_FIELDS)
def test_every_field_accepts_4000_characters_and_refuses_more_or_blank_text(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID], code: str
) -> None:
    character = two[0]
    for bad in ("x" * 4001, "   ", "\n\t ", ""):
        message = _refused(
            postgres_engine,
            lambda c, bad=bad: seed_player_profile_in(
                c,
                campaign_id=g.campaign_id,
                character_id=character,
                editor_membership_id=g.o1,
                fields={code: bad},
            ),
        )
        assert f"ck_character_player_profile_versions_{code}_text" in message, repr(bad[:5])
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={code: "y" * 4000},
    )
    with postgres_engine.connect() as connection:
        stored = connection.execute(
            text(f"SELECT char_length({code}) FROM {VERSIONS} WHERE character_id = :c"),  # noqa: S608
            {"c": character},
        ).scalar_one()
    assert stored == 4000


def test_a_version_needs_an_editor_and_the_row_version_is_positive(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        head = _head(connection, g, character)
        transaction.rollback()
    message = _refused(
        postgres_engine,
        lambda c: c.execute(
            text(f"""
                INSERT INTO {VERSIONS} (character_player_profile_id, campaign_id, character_id,
                    profile_row_version) VALUES (:h, :c, :ch, 1)
            """),  # noqa: S608
            {"h": head, "c": g.campaign_id, "ch": character},
        ),
    )
    # The scope trigger (BEFORE INSERT) sees the missing editor first; the NOT NULL is the backstop.
    assert "Editing membership" in message or "edited_by_campaign_membership_id" in message
    zero = _refused(
        postgres_engine,
        lambda c: c.execute(
            text(
                f"INSERT INTO {HEAD} (campaign_id, character_id, row_version) VALUES (:c, :ch, 0)"
            ),  # noqa: S608
            {"c": g.campaign_id, "ch": character},
        ),
    )
    assert "ck_character_player_profiles_row_version_positive" in zero


# --- versions are append-only -------------------------------------------------------------------------


def test_versions_refuse_update_delete_and_truncate(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={"personality": "keep"},
    )
    for statement in (
        f"UPDATE {VERSIONS} SET personality = 'changed' WHERE character_id = :c",
        f"DELETE FROM {VERSIONS} WHERE character_id = :c",
    ):
        message = _refused(
            postgres_engine, lambda c, s=statement: c.execute(text(s), {"c": character})
        )
        assert "append-only" in message, statement
    assert "append-only" in _refused(
        postgres_engine, lambda c: c.execute(text(f"TRUNCATE {VERSIONS}"))
    )
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT personality FROM {VERSIONS} WHERE character_id = :c"),  # noqa: S608
                {"c": character},
            ).scalar_one()
            == "keep"
        )


def test_a_second_edit_in_one_transaction_is_one_head_bump_per_version(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={},
    )
    with postgres_engine.begin() as connection:
        first = edit_player_profile_in(
            connection, campaign_id=g.campaign_id, character_id=character,
            editor_membership_id=g.o1, fields={"bonds": "one"},
        )  # fmt: skip
        second = edit_player_profile_in(
            connection, campaign_id=g.campaign_id, character_id=character,
            editor_membership_id=g.o1, fields={"bonds": "two"},
        )  # fmt: skip
    assert (first, second) == (2, 3)


# --- lifecycle, comments, indexes and ownership --------------------------------------------------------


def test_a_character_or_campaign_with_a_profile_cannot_be_physically_deleted(
    postgres_engine: Engine, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    character = two[0]
    seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={"personality": "x"},
    )
    assert isinstance(
        _refused_exc(
            postgres_engine,
            lambda c: c.execute(
                text("DELETE FROM core.entities WHERE entity_id = :e"), {"e": character}
            ),
        ),
        IntegrityError,
    )
    assert isinstance(
        _refused_exc(
            postgres_engine,
            lambda c: c.execute(
                text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": g.campaign_id}
            ),
        ),
        IntegrityError,
    )


def test_every_table_column_and_function_is_commented_the_editor_fk_is_indexed_and_the_owner_owns(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        tables = connection.execute(
            text("""
                SELECT c.relname, obj_description(c.oid, 'pg_class') AS comment,
                       pg_get_userbyid(c.relowner) AS owner
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'campaign' AND c.relname IN (
                    'player_profile_fields', 'character_player_profiles',
                    'character_player_profile_versions')
            """)
        ).all()
        assert len(tables) == 3
        for table in tables:
            assert table.comment, table.relname
            assert table.owner == "migration_owner", table.relname
        uncommented = connection.execute(
            text("""
                SELECT c.relname, a.attname
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'campaign' AND a.attnum > 0 AND NOT a.attisdropped
                  AND c.relname IN ('player_profile_fields', 'character_player_profiles',
                                    'character_player_profile_versions')
                  AND col_description(c.oid, a.attnum) IS NULL
                  AND a.attname NOT IN ('player_profile_field_id', 'character_player_profile_id',
                       'character_player_profile_version_id', 'campaign_id', 'character_id',
                       'description', 'display_name', 'sort_order', 'is_active', 'created_at',
                       'updated_at')
            """)
        ).all()
        assert uncommented == []
        version_columns = {
            row.attname
            for row in connection.execute(
                text("""
                    SELECT a.attname FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'campaign' AND c.relname = 'character_player_profile_versions'
                      AND a.attnum > 0 AND NOT a.attisdropped
                      AND col_description(c.oid, a.attnum) IS NOT NULL
                """)
            )
        }
        assert set(PLAYER_PROFILE_FIELDS) <= version_columns
        functions = connection.execute(
            text("""
                SELECT p.proname, obj_description(p.oid, 'pg_proc') AS comment
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'campaign' AND p.proname LIKE 'enforce_player_profile_%'
            """)
        ).all()
        assert len(functions) == 4 and all(f.comment for f in functions)
        indexed = connection.execute(
            text("""
                SELECT count(*) FROM pg_indexes
                WHERE schemaname = 'campaign' AND tablename = 'character_player_profile_versions'
                  AND indexdef LIKE '%(edited_by_campaign_membership_id)%'
            """)
        ).scalar_one()
        assert indexed == 1
        comment = connection.execute(
            text(
                "SELECT col_description('campaign.character_player_profile_versions'::regclass, "
                "(SELECT attnum FROM pg_attribute WHERE attrelid = "
                "'campaign.character_player_profile_versions'::regclass AND attname = 'profile_notes'))"
            )
        ).scalar_one()
        assert "not a private notebook" in comment


def test_no_controller_profile_capability_exists_yet(postgres_engine: Engine) -> None:
    """A5 adds no `character.view_player_profile` / `character.edit_player_profile` vocabulary: the
    controller read and edit capabilities, the matrix entries and the grant paths are P03-B's."""
    with postgres_engine.connect() as connection:
        codes = (
            connection.execute(
                text("SELECT code FROM security.capabilities WHERE code LIKE '%player_profile%'")
            )
            .scalars()
            .all()
        )
    assert codes == []


def test_a_stored_version_at_the_top_of_the_bigint_domain_is_readable_over_http(
    postgres_engine: Engine, client_factory: Any, g: Gate, two: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """The version route's bound is the column's (BIGINT), not something tighter: a version stored at
    the largest value is read, and the next value up names nothing."""
    character = two[0]
    bigint_max = 9_223_372_036_854_775_807
    head = seed_player_profile(
        postgres_engine,
        campaign_id=g.campaign_id,
        character_id=character,
        editor_membership_id=g.o1,
        fields={"personality": "top"},
    )
    with postgres_engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                f"UPDATE {VERSIONS} SET profile_row_version = :v WHERE character_player_profile_id = :h"
            ),  # noqa: S608
            {"v": bigint_max, "h": head},
        )
        connection.execute(
            text(f"UPDATE {HEAD} SET row_version = :v WHERE character_player_profile_id = :h"),  # noqa: S608
            {"v": bigint_max, "h": head},
        )
    base = f"/campaigns/{g.campaign_id}/characters/{character}/player-profile"
    with client_factory(g.o1_user_id) as client:
        top = client.get(f"{base}/versions/{bigint_max}")
        assert top.status_code == 200 and top.json()["profile_row_version"] == bigint_max
        assert top.json()["fields"]["personality"] == "top"
        assert client.get(base).json()["profile"]["row_version"] == bigint_max
        assert client.get(f"{base}/versions/{bigint_max + 1}").status_code == 404
