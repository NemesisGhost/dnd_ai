"""P15-C11-S01-T01: migration 150 on a populated database (D17-D20).

Upgrade 149 -> 150 is additive: every pre-existing row keeps every pre-existing column byte for byte,
gains its membership's campaign, and is not an assignment. The downgrade restores the exact previous
index, trigger body and columns, and refuses while an assignment row exists. Throwaway databases only.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text

from dnd_ai.domain.access import (
    BUILTIN_RELATIONSHIP_CAPABILITIES,
    AccessContext,
    resolve_access_context,
)
from tests.access_reference import reference_resolve_access_context
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
    make_control_assignment,
    make_membership_character_relationship,
    make_membership_role,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    relationship_type_id,
)

pytestmark = pytest.mark.database

PARENT = "149_reservation_fk_deferrable"
TARGET = "150_control_assignments"

_TABLE = "security.membership_character_relationships"
_LEGACY_COLUMNS = (
    "membership_character_relationship_id, campaign_membership_id, character_id, "
    "character_relationship_type_id, timeline_id, effective_from_world_time_id, "
    "effective_to_world_time_id, effective_period::text AS effective_period, "
    "granted_by_membership_id, granted_at, expires_at, revoked_at, notes"
)
_NEW_COLUMNS = (
    "campaign_id",
    "is_control_assignment",
    "is_primary",
    "assignment_period_kind",
    "revoked_by_membership_id",
    "revocation_reason",
)


def _revision(connection: Connection) -> str:
    return str(
        connection.execute(text("SELECT version_num FROM core.alembic_version")).scalar_one()
    )


def _shape(connection: Connection) -> dict[str, Any]:
    """Everything the downgrade must restore: columns, indexes, constraints, trigger function."""
    columns = connection.execute(
        text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'security' AND table_name = 'membership_character_relationships'
            ORDER BY ordinal_position
        """)
    ).all()
    indexes = connection.execute(
        text("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = 'security' AND tablename = 'membership_character_relationships'
            ORDER BY indexname
        """)
    ).all()
    constraints = connection.execute(
        text("""
            SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = 'security.membership_character_relationships'::regclass
            ORDER BY conname
        """)
    ).all()
    triggers = connection.execute(
        text("""
            SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger
            WHERE tgrelid = 'security.membership_character_relationships'::regclass
              AND NOT tgisinternal ORDER BY tgname
        """)
    ).all()
    function = connection.execute(
        text(
            "SELECT pg_get_functiondef('security.enforce_membership_character_relationship_scope()"
            "'::regprocedure)"
        )
    ).scalar_one()
    comments = connection.execute(
        text("""
            SELECT a.attname, col_description(a.attrelid, a.attnum)
            FROM pg_attribute a
            WHERE a.attrelid = 'security.membership_character_relationships'::regclass
              AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attname
        """)
    ).all()
    return {
        "columns": [tuple(r) for r in columns],
        "indexes": [tuple(r) for r in indexes],
        "constraints": [tuple(r) for r in constraints],
        "triggers": [tuple(r) for r in triggers],
        "function": function,
        "comments": [tuple(r) for r in comments],
    }


def _legacy_rows(connection: Connection) -> dict[uuid.UUID, dict[str, Any]]:
    rows = connection.execute(
        text(
            f"SELECT {_LEGACY_COLUMNS} FROM {_TABLE} ORDER BY membership_character_relationship_id"
        )
    ).mappings()
    return {r["membership_character_relationship_id"]: dict(r) for r in rows}


class Populated:
    def __init__(self, connection: Connection) -> None:
        c = connection
        self.world_id = make_world(c, slug=f"migration-150-{uuid.uuid4().hex[:8]}")
        self.timeline_id = make_timeline(c, self.world_id, "Primary", is_primary=True)
        self.campaign_id = make_campaign(c, self.timeline_id, "One")
        self.other_campaign_id = make_campaign(c, self.timeline_id, "Two")
        self.t10 = make_world_time(c, self.world_id, 10)
        self.t20 = make_world_time(c, self.world_id, 20)
        self.users: dict[str, uuid.UUID] = {}
        self.memberships: dict[str, uuid.UUID] = {}
        for name, campaign in (
            ("owner", self.campaign_id),
            ("gm_player", self.campaign_id),
            ("other", self.other_campaign_id),
        ):
            self.users[name] = make_user(c, name)
            self.memberships[name] = make_campaign_membership(c, campaign, self.users[name])
        owner_role = c.execute(
            text(
                "SELECT role_id FROM security.roles WHERE code = 'campaign_owner' "
                "AND campaign_id IS NULL"
            )
        ).scalar_one()
        # committed campaigns must keep an access manager (the deferred retention trigger)
        make_membership_role(c, self.memberships["owner"], owner_role)
        make_membership_role(c, self.memberships["other"], owner_role)
        self.ids: dict[str, uuid.UUID] = {}
        self._legacy(c, "live", "primary_controller", self.memberships["owner"])
        self._legacy(c, "live_other_campaign", "co_controller", self.memberships["other"])
        self._legacy(c, "revoked", "owner", self.memberships["owner"], revoked=True)
        self._legacy(c, "dated", "viewer", self.memberships["owner"], from_time=self.t10)
        self._legacy(
            c,
            "closed",
            "portrayer",
            self.memberships["owner"],
            from_time=self.t10,
            to_time=self.t20,
        )
        self._legacy(
            c, "timeline", "co_controller", self.memberships["gm_player"], timeline=self.timeline_id
        )
        expired = self._legacy(c, "expired", "former_controller", self.memberships["gm_player"])
        c.execute(
            text(f"""
                UPDATE {_TABLE}
                SET granted_at = now() - interval '2 days', expires_at = now() - interval '1 day'
                WHERE membership_character_relationship_id = :id
            """),
            {"id": expired},
        )
        c.execute(
            text(
                f"UPDATE {_TABLE} SET notes = 'kept' WHERE membership_character_relationship_id = :id"
            ),
            {"id": self.ids["live"]},
        )

    def _legacy(
        self,
        connection: Connection,
        label: str,
        role: str,
        membership: uuid.UUID,
        *,
        revoked: bool = False,
        from_time: uuid.UUID | None = None,
        to_time: uuid.UUID | None = None,
        timeline: uuid.UUID | None = None,
    ) -> uuid.UUID:
        character = make_character(connection, self.world_id, name=f"char-{label}")
        rid = make_membership_character_relationship(
            connection,
            membership,
            character,
            relationship_type_id(connection, role),
            revoked=revoked,
            effective_from_world_time_id=from_time,
            effective_to_world_time_id=to_time,
            timeline_id=timeline,
        )
        self.ids[label] = rid
        return rid


_CAMPAIGN_OF = {
    "owner": "campaign_id",
    "gm_player": "campaign_id",
    "other": "other_campaign_id",
}


def _legacy_fields(ctx: AccessContext | None) -> dict[str, object] | None:
    """The legacy access fields, compared explicitly (never the additive control fields)."""
    if ctx is None:
        return None
    return {
        "user_id": ctx.user_id,
        "campaign_id": ctx.campaign_id,
        "campaign_membership_id": ctx.campaign_membership_id,
        "timeline_id": ctx.timeline_id,
        "role_capabilities": ctx.role_capabilities,
        "character_capabilities": ctx.character_capabilities,
        "grant_effects": ctx.grant_effects,
        "campaign_lifecycle_status": ctx.campaign_lifecycle_status,
        "revelations": ctx.revelations,
    }


def _contexts_before(connection: Connection, p: Populated) -> dict[str, AccessContext | None]:
    """Revision-149 side. The production resolver reads revision-150 columns, which do not exist yet, so the
    frozen pre-assignment reference resolver (`tests/access_reference.py`) reads the database state instead; it
    shares no SQL with the production statement."""
    return {
        name: reference_resolve_access_context(
            connection, user_id=p.users[name], campaign_id=getattr(p, attr)
        )
        for name, attr in _CAMPAIGN_OF.items()
    }


def _contexts_after(connection: Connection, p: Populated) -> dict[str, AccessContext | None]:
    """Post-upgrade side: the production resolver."""
    return {
        name: resolve_access_context(
            connection, user_id=p.users[name], campaign_id=getattr(p, attr)
        )
        for name, attr in _CAMPAIGN_OF.items()
    }


def _character_of(connection: Connection, relationship_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text(f"SELECT character_id FROM {_TABLE} WHERE membership_character_relationship_id = :r"),
        {"r": relationship_id},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _expected_character_capabilities(
    connection: Connection, p: Populated
) -> dict[str, dict[uuid.UUID, frozenset[str]]]:
    """What the legacy semantics grant each fixture user: live rows confer their type's built-in set; revoked,
    expired and closed-period rows confer nothing; an open-ended dated row and a timeline row of the campaign's own
    timeline confer; another campaign's row never reaches this campaign."""
    cap = BUILTIN_RELATIONSHIP_CAPABILITIES
    return {
        "owner": {
            _character_of(connection, p.ids["live"]): cap["primary_controller"],
            _character_of(connection, p.ids["dated"]): cap["viewer"],
        },
        "gm_player": {_character_of(connection, p.ids["timeline"]): cap["co_controller"]},
        "other": {_character_of(connection, p.ids["live_other_campaign"]): cap["co_controller"]},
    }


@pytest.mark.real_relationship_policy
def test_d17_d18_upgrade_preserves_legacy_rows_and_access_contexts() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            populated = Populated(connection)
        with engine.connect() as connection:
            before_rows = _legacy_rows(connection)
            before_contexts = _contexts_before(connection, populated)
            expected = _expected_character_capabilities(connection, populated)
            # the revision-149 contexts are meaningful, not empty: each user holds the legacy capabilities
            for name, ctx in before_contexts.items():
                assert ctx is not None, name
                assert ctx.character_capabilities == expected[name], name
            assert before_contexts["owner"].role_capabilities  # type: ignore[union-attr]
            # and refusals: a member of campaign Two has no access to campaign One, and nobody to a stranger
            assert (
                reference_resolve_access_context(
                    connection, user_id=populated.users["other"], campaign_id=populated.campaign_id
                )
                is None
            )
        assert len(before_rows) == 7

        _alembic_upgrade(test_url, TARGET)
        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            after_rows = _legacy_rows(connection)
            assert after_rows == before_rows  # D17: every pre-existing column byte-identical
            new = connection.execute(
                text(
                    f"SELECT membership_character_relationship_id, {', '.join(_NEW_COLUMNS)}, "
                    f"(SELECT cm.campaign_id FROM security.campaign_memberships cm "
                    f"  WHERE cm.campaign_membership_id = r.campaign_membership_id) AS membership_campaign, "
                    f"(SELECT t.code FROM security.character_relationship_types t "
                    f"  WHERE t.character_relationship_type_id = r.character_relationship_type_id) AS type_code "
                    f"FROM {_TABLE} r"
                )
            ).mappings()
            seen = 0
            for r in new:
                seen += 1
                assert r["campaign_id"] == r["membership_campaign"]
                assert r["is_control_assignment"] is False
                assert r["assignment_period_kind"] is None
                assert r["revoked_by_membership_id"] is None and r["revocation_reason"] is None
                # is_primary is derived from the type for every row, legacy rows included
                assert r["is_primary"] is (r["type_code"] == "primary_controller")
            assert seen == 7
            # D18: the resolver's view of each fixture user is unchanged
            after_contexts = _contexts_after(connection, populated)
            assert {n: _legacy_fields(c) for n, c in after_contexts.items()} == {
                n: _legacy_fields(c) for n, c in before_contexts.items()
            }
            for name, ctx in after_contexts.items():
                assert ctx is not None, name
                assert ctx.character_capabilities == expected[name], name
                # the additive control fields are empty: no assignment row exists
                assert ctx.control_assignments == {} and ctx.control_clock_key is None, name
            assert (
                resolve_access_context(
                    connection, user_id=populated.users["other"], campaign_id=populated.campaign_id
                )
                is None
            )
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_d19_downgrade_without_assignments_restores_the_exact_previous_shape() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            before = _shape(connection)
        with engine.begin() as connection:
            populated = Populated(connection)
        with engine.connect() as connection:
            rows_before = _legacy_rows(connection)

        _alembic_upgrade(test_url, TARGET)
        with engine.connect() as connection:
            during = _shape(connection)
        assert during != before
        assert any(
            i[0] == "ux_membership_character_relationships_live_primary" for i in during["indexes"]
        )
        assert any(
            i[0] == "ux_membership_character_relationships_live_assignment"
            for i in during["indexes"]
        )
        assert any(
            i[0] == "ux_membership_character_relationships_active_type" for i in during["indexes"]
        )

        downgraded = _alembic(test_url, "downgrade", PARENT)
        assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
        with engine.connect() as connection:
            assert _revision(connection) == PARENT
            assert _shape(connection) == before  # index definition, trigger body, columns
            assert _legacy_rows(connection) == rows_before
            assert populated.ids  # data survived
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_d20_downgrade_with_an_assignment_row_refuses_and_changes_nothing() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, TARGET)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            populated = Populated(connection)
            character = make_character(connection, populated.world_id, name="assigned")
            assignment = make_control_assignment(
                connection,
                populated.memberships["owner"],
                character,
                "primary_controller",
                "ongoing",
            )
        with engine.connect() as connection:
            shape_before = _shape(connection)
            rows_before = connection.execute(
                text(f"SELECT * FROM {_TABLE} ORDER BY membership_character_relationship_id")
            ).all()

        refused = _alembic(test_url, "downgrade", PARENT)
        assert refused.returncode != 0
        assert "control assignment" in (refused.stdout + refused.stderr).lower()

        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            assert _shape(connection) == shape_before
            assert (
                connection.execute(
                    text(f"SELECT * FROM {_TABLE} ORDER BY membership_character_relationship_id")
                ).all()
                == rows_before
            )
            assert (
                connection.execute(
                    text(
                        f"SELECT is_control_assignment FROM {_TABLE} "
                        "WHERE membership_character_relationship_id = :id"
                    ),
                    {"id": assignment},
                ).scalar_one()
                is True
            )
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


_CREATED_CONSTRAINTS = (
    "membership_character_relationships_campaign_id_fkey",
    "membership_character_relationships_revoked_by_fkey",
    "ck_membership_character_relationships_assignment_kind_values",
    "ck_membership_character_relationships_assignment_kind_present",
    "ck_membership_character_relationships_ongoing_has_no_period",
    "ck_membership_character_relationships_dated_has_start",
    "ck_membership_character_relationships_assignment_unscoped",
    "ck_membership_character_relationships_revocation_only_revoked",
    "ck_membership_character_relationships_revocation_reason_length",
)
_CREATED_INDEXES = (
    "ux_membership_character_relationships_active_type",
    "ux_membership_character_relationships_live_primary",
    "ux_membership_character_relationships_live_assignment",
    "ix_membership_character_relationships_campaign_id",
    "ix_membership_character_relationships_revoked_by",
)
_CREATED_TRIGGERS = ("tr_membership_character_relationships_enforce_immutable",)


def test_d21_every_name_revision_150_creates_exists_exactly_as_written() -> None:
    """PostgreSQL truncates an identifier longer than 63 bytes without error; a truncated name would make a
    later DROP or a declaration that names it fail. Every created name is checked in pg_catalog."""
    for name in (*_CREATED_CONSTRAINTS, *_CREATED_INDEXES, *_CREATED_TRIGGERS):
        assert len(name.encode()) <= 63, name
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, TARGET)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            constraints = {
                r[0]
                for r in connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'security.membership_character_relationships'::regclass"
                    )
                )
            }
            indexes = {
                r[0]
                for r in connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = 'security' "
                        "AND tablename = 'membership_character_relationships'"
                    )
                )
            }
            triggers = {
                r[0]
                for r in connection.execute(
                    text(
                        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                        "AND tgrelid = 'security.membership_character_relationships'::regclass"
                    )
                )
            }
        engine.dispose()
        assert set(_CREATED_CONSTRAINTS) <= constraints
        assert set(_CREATED_INDEXES) <= indexes
        assert set(_CREATED_TRIGGERS) <= triggers
    finally:
        _drop_database(admin_url, test_url)
