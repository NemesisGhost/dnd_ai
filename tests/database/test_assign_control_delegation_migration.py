"""Migration 151 (P15-C11-S02-T02, H22): `character.assign_control` and `security.character_assign_control_delegations`.

Runs on throwaway databases: a populated upgrade (existing rows are untouched, no delegation is created, the reveal
delegations are not disturbed), the documented lossy downgrade (the table, the guard and the capability row go; the
reveal delegations stay), a re-upgrade, and `alembic check` for drift between the migration and the SQLAlchemy metadata.
"""

import pytest
from sqlalchemy import Connection, create_engine, text

from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import make_campaign_membership, make_membership_role, make_user

pytestmark = pytest.mark.database

_TABLE = "security.character_assign_control_delegations"
_PREVIOUS = "150_control_assignments"
_REVISION = "151_assign_control_delegations"
_CAPABILITY = "character.assign_control"
_TRIGGER_FUNCTIONS = (
    "enforce_character_assign_control_delegation_scope",
    "reject_character_assign_control_capability_row",
)


def _table_present(connection: Connection) -> bool:
    return connection.execute(text("SELECT to_regclass(:t)"), {"t": _TABLE}).scalar() is not None


def _capability_present(connection: Connection) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM security.capabilities WHERE code = :c"), {"c": _CAPABILITY}
        ).scalar()
    )


def _function_count(connection: Connection) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = ANY(:names)"),
            {"names": list(_TRIGGER_FUNCTIONS)},
        ).scalar()
        or 0
    )


def _guard_trigger_count(connection: Connection) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'tr_%_reject_assign_control'")
        ).scalar()
        or 0
    )


def _reveal_state(connection: Connection) -> tuple[int, bool]:
    rows = connection.execute(
        text("SELECT count(*) FROM security.character_reveal_delegations")
    ).scalar_one()
    capability = bool(
        connection.execute(
            text("SELECT count(*) FROM security.capabilities WHERE code = 'character.reveal'")
        ).scalar()
    )
    return int(rows), capability


def test_populated_upgrade_and_documented_downgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, _PREVIOUS)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            assert not _table_present(connection)
            assert not _capability_present(connection)
            owner = make_user(connection, "Assign Migration Owner")
            world = make_authored_world(connection, owner_user_id=owner, name="Assign World")
            campaign_id = make_authored_campaign(connection, world, name="Assign Campaign")
            gm_user = make_user(connection, "Assign Migration GM")
            membership = make_campaign_membership(connection, campaign_id, gm_user)
            gm_role = connection.execute(
                text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
            ).scalar_one()
            assistant_role = connection.execute(
                text(
                    "SELECT role_id FROM security.roles "
                    "WHERE code = 'assistant_gm' AND campaign_id IS NULL"
                )
            ).scalar_one()
            assistant_user = make_user(connection, "Assign Migration Assistant")
            assistant_membership = make_campaign_membership(connection, campaign_id, assistant_user)
            assignment = make_membership_role(connection, membership, gm_role)
            assistant_assignment = make_membership_role(
                connection, assistant_membership, assistant_role
            )
            owner_membership = connection.execute(
                text(
                    "SELECT campaign_membership_id FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id = :u"
                ),
                {"c": campaign_id, "u": owner},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO security.character_reveal_delegations "
                    "(campaign_id, grantee_campaign_membership_id, gm_membership_role_id, "
                    "granted_by_membership_id, reason) VALUES (:c, :g, :r, :by, 'pre-existing')"
                ),
                {"c": campaign_id, "g": membership, "r": assignment, "by": owner_membership},
            )
            reveal_before = _reveal_state(connection)
            assert reveal_before == (1, True)
        _alembic_upgrade(test_url, _REVISION)
        with engine.begin() as connection:
            assert _table_present(connection) and _capability_present(connection)
            assert _function_count(connection) == 2 and _guard_trigger_count(connection) == 3
            # Populated upgrade: existing assignments are untouched and nobody holds a delegation.
            for row_id in (assignment, assistant_assignment):
                assert (
                    connection.execute(
                        text(
                            "SELECT revoked_at IS NULL FROM security.membership_roles "
                            "WHERE membership_role_id = :r"
                        ),
                        {"r": row_id},
                    ).scalar_one()
                    is True
                )
            assert (
                connection.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar_one() == 0  # noqa: S608
            )
            assert _reveal_state(connection) == reveal_before
            # no role, relationship type or grant carries the new vocabulary row
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM security.role_capabilities rc "
                        "JOIN security.capabilities c ON c.capability_id = rc.capability_id "
                        "WHERE c.code = :c"
                    ),
                    {"c": _CAPABILITY},
                ).scalar_one()
                == 0
            )
        downgraded = _alembic(test_url, "downgrade", _PREVIOUS)
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.begin() as connection:
            assert not _table_present(connection) and not _capability_present(connection)
            assert _function_count(connection) == 0 and _guard_trigger_count(connection) == 0
            # Nothing else is lost: the assignment the delegation would have been bound to stays, and the reveal
            # delegation, its table, its guard triggers and its capability are untouched.
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM security.membership_roles WHERE membership_role_id = :r"
                    ),
                    {"r": assistant_assignment},
                ).scalar_one()
                == 1
            )
            assert _reveal_state(connection) == reveal_before
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'tr_%_reject_reveal'")
                ).scalar_one()
                == 3
            )
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_fresh_database_upgrades_to_head_with_the_table_and_no_drift() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "head")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _table_present(connection) and _capability_present(connection)
            columns = connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'security' "
                    "AND table_name = 'character_assign_control_delegations'"
                )
            ).scalars()
            assert set(columns) == {
                "character_assign_control_delegation_id",
                "campaign_id",
                "grantee_campaign_membership_id",
                "assistant_gm_membership_role_id",
                "granted_by_membership_id",
                "granted_at",
                "reason",
                "revoked_at",
                "revoked_by_membership_id",
                "revocation_reason",
                "end_reason",
                "created_at",
                "updated_at",
            }
            sort_order = connection.execute(
                text("SELECT sort_order FROM security.capabilities WHERE code = :c"),
                {"c": _CAPABILITY},
            ).scalar_one()
            reveal_order = connection.execute(
                text("SELECT sort_order FROM security.capabilities WHERE code = 'character.reveal'")
            ).scalar_one()
            assert sort_order > reveal_order
            heads = _alembic(test_url, "heads")
            assert _REVISION in heads.stdout
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
