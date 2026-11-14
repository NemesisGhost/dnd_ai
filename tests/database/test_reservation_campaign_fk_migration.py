"""Migration 149 (R01 S5-C): the reservation's campaign foreign key becomes deferrable.

Upgrade 148 -> 149 changes exactly one constraint (`idempotent_requests_campaign_id_fkey`) to
`DEFERRABLE INITIALLY IMMEDIATE`; the account foreign key, both referential actions and the immediate
default are untouched. Downgrade restores NOT DEFERRABLE. `alembic check` on the migrated database
shows no drift against the metadata. Throwaway databases only.
"""

import pytest
from sqlalchemy import Connection, create_engine, text

from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)

pytestmark = pytest.mark.database

PARENT = "148_player_profile_provenance"
TARGET = "149_reservation_fk_deferrable"

_CAMPAIGN_FK = "idempotent_requests_campaign_id_fkey"
_ACCOUNT_FK = "idempotent_requests_actor_user_id_fkey"


def _constraints(connection: Connection) -> dict[str, tuple[bool, bool, str, str, str]]:
    rows = connection.execute(
        text("""
            SELECT conname, condeferrable, condeferred, confdeltype::text, confupdtype::text,
                   confmatchtype::text
            FROM pg_constraint
            WHERE conrelid = 'security.idempotent_requests'::regclass AND contype = 'f'
        """)
    ).all()
    return {
        r.conname: (r.condeferrable, r.condeferred, r.confdeltype, r.confupdtype, r.confmatchtype)
        for r in rows
    }


def _ri_triggers(connection: Connection) -> set[tuple[str, bool, bool]]:
    """The internal RI triggers on both sides of the campaign FK: (name function, deferrable, deferred)."""
    rows = connection.execute(
        text("""
            SELECT p.proname, t.tgdeferrable, t.tginitdeferred
            FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
            JOIN pg_constraint c ON c.oid = t.tgconstraint
            WHERE c.conname = :name AND c.conrelid = 'security.idempotent_requests'::regclass
        """),
        {"name": _CAMPAIGN_FK},
    ).all()
    return {(r.proname, r.tgdeferrable, r.tginitdeferred) for r in rows}


def _revision(connection: Connection) -> str:
    return str(
        connection.execute(text("SELECT version_num FROM core.alembic_version")).scalar_one()
    )


def test_upgrade_changes_only_the_campaign_fk_and_downgrade_restores_it() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            before = _constraints(connection)
            before_triggers = _ri_triggers(connection)
        assert before[_CAMPAIGN_FK][:2] == (False, False)
        assert before[_ACCOUNT_FK][:2] == (False, False)
        assert {t[1:] for t in before_triggers} == {(False, False)}
        assert {t[0] for t in before_triggers} >= {"RI_FKey_check_ins", "RI_FKey_check_upd"}

        _alembic_upgrade(test_url, TARGET)
        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            after = _constraints(connection)
            after_triggers = _ri_triggers(connection)
        # deferrable, initially immediate; referential actions and match type unchanged
        assert after[_CAMPAIGN_FK] == (True, False, *before[_CAMPAIGN_FK][2:])
        assert after[_ACCOUNT_FK] == before[_ACCOUNT_FK]
        assert after[_CAMPAIGN_FK][2] == "c"  # ON DELETE CASCADE
        # the referencing side's checks become deferrable, none is initially deferred, and the
        # referenced side's ON DELETE CASCADE action trigger stays immediate
        assert {t[0] for t in after_triggers} == {t[0] for t in before_triggers}
        assert all(deferred is False for _, _, deferred in after_triggers)
        by_function = {function: deferrable for function, deferrable, _ in after_triggers}
        assert by_function["RI_FKey_check_ins"] is True
        assert by_function["RI_FKey_check_upd"] is True
        assert by_function["RI_FKey_cascade_del"] is False
        assert set(after) == set(before)

        downgraded = _alembic(test_url, "downgrade", PARENT)
        assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
        with engine.connect() as connection:
            assert _revision(connection) == PARENT
            assert _constraints(connection) == before
            assert _ri_triggers(connection) == before_triggers

        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        with engine.connect() as connection:
            assert _constraints(connection)[_CAMPAIGN_FK][:2] == (True, False)
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_fresh_database_has_the_deferrable_immediate_campaign_fk_and_no_drift() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "head")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            constraints = _constraints(connection)
        assert constraints[_CAMPAIGN_FK][:2] == (True, False)
        assert constraints[_ACCOUNT_FK][:2] == (False, False)
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
