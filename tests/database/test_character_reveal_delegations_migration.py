"""Migration 141 (P03-A A1): `character.reveal` and `security.character_reveal_delegations`.

Runs on throwaway databases: a populated upgrade (existing roles, memberships and grants are
untouched and nobody holds a delegation), the documented lossy downgrade, a re-upgrade, and
`alembic check` for drift between the migration and the SQLAlchemy metadata.
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

_TABLE = "security.character_reveal_delegations"
_TRIGGER_FUNCTIONS = (
    "enforce_character_reveal_delegation_scope",
    "reject_character_reveal_capability_row",
)


def _table_present(connection: Connection) -> bool:
    return connection.execute(text("SELECT to_regclass(:t)"), {"t": _TABLE}).scalar() is not None


def _capability_present(connection: Connection) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM security.capabilities WHERE code = 'character.reveal'")
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
            text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'tr_%_reject_reveal'")
        ).scalar()
        or 0
    )


def test_populated_upgrade_and_documented_downgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "140_clock_advance_details")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            assert not _table_present(connection)
            assert not _capability_present(connection)
            owner = make_user(connection, "Reveal Migration Owner")
            world = make_authored_world(connection, owner_user_id=owner, name="Reveal World")
            campaign_id = make_authored_campaign(connection, world, name="Reveal Campaign")
            gm_user = make_user(connection, "Reveal Migration GM")
            membership = make_campaign_membership(connection, campaign_id, gm_user)
            gm_role = connection.execute(
                text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
            ).scalar_one()
            assignment = make_membership_role(connection, membership, gm_role)
        _alembic_upgrade(test_url, "141_character_reveal_delegations")
        with engine.begin() as connection:
            assert _table_present(connection) and _capability_present(connection)
            assert _function_count(connection) == 2 and _guard_trigger_count(connection) == 3
            # Populated upgrade: the existing assignment is untouched and nobody holds a delegation.
            assert (
                connection.execute(
                    text(
                        "SELECT revoked_at IS NULL FROM security.membership_roles "
                        "WHERE membership_role_id = :r"
                    ),
                    {"r": assignment},
                ).scalar_one()
                is True
            )
            assert (
                connection.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar_one() == 0  # noqa: S608
            )
        downgraded = _alembic(test_url, "downgrade", "140_clock_advance_details")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.begin() as connection:
            assert not _table_present(connection) and not _capability_present(connection)
            assert _function_count(connection) == 0 and _guard_trigger_count(connection) == 0
            # Nothing else is lost: the assignment the delegation would have been bound to stays.
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM security.membership_roles WHERE membership_role_id = :r"
                    ),
                    {"r": assignment},
                ).scalar_one()
                == 1
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
                    "AND table_name = 'character_reveal_delegations'"
                )
            ).scalars()
            assert set(columns) == {
                "character_reveal_delegation_id",
                "campaign_id",
                "grantee_campaign_membership_id",
                "gm_membership_role_id",
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
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
