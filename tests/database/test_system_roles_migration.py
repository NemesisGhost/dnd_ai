"""Revisions 137 (system roles) and 138 (world roles and use grants) on a populated database.

Each test provisions its own throwaway database, migrates it to the revision before
136, populates it the way an owner's development database looks, upgrades, checks the
backfill policy of the scoped-role plan (section 9.1), and round-trips the downgrade:

- administrators receive `admin` and `gm`; open active world Owners receive `gm`;
  everyone else receives `player`;
- campaign `gm` holders are **not** promoted to system `gm` on that basis;
- campaign memberships and roles, world ownership and authorship are untouched;
- the downgrade restores `is_platform_administrator` from unrevoked `admin` rows.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, make_url, text

from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"
_BEFORE = "136_world_viewer_role"
_SYSTEM_ROLES = "137_system_roles"
_WORLD_ROLES = "138_world_roles_and_use_grants"
_TIMEOUT = 300


def _admin_url() -> str:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        pytest.skip("DATABASE_URL is not set; these tests provision a throwaway database.")
    return raw


def _provision() -> tuple[str, str]:
    admin_url = make_url(_admin_url())
    name = f"dnd_ai_136_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=name)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()
    return (
        admin_url.render_as_string(hide_password=False),
        test_url.render_as_string(hide_password=False),
    )


def _drop(admin_url: str, test_url: str) -> None:
    name = make_url(test_url).database
    engine = create_engine(make_url(admin_url), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    engine.dispose()


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _user(conn: Connection, name: str, *, admin: bool = False, status: str = "active") -> uuid.UUID:
    value = conn.execute(
        text("""
            INSERT INTO security.users (display_name, lifecycle_status_id, is_platform_administrator)
            VALUES (:n, (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :s), :a)
            RETURNING user_id
        """),
        {"n": name, "s": status, "a": admin},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _own_world(
    conn: Connection, world_id: uuid.UUID, user_id: uuid.UUID, *, ended: bool = False
) -> None:
    conn.execute(
        text("""
            INSERT INTO security.world_memberships
                (world_id, user_id, world_role_id, membership_status_id, ended_at)
            VALUES (:w, :u,
                    (SELECT world_role_id FROM security.world_roles WHERE code = 'world_owner'),
                    (SELECT membership_status_id FROM security.membership_statuses WHERE code = 'active'),
                    CASE WHEN :ended THEN now() ELSE NULL END)
        """),
        {"w": world_id, "u": user_id, "ended": ended},
    )


def _roles(conn: Connection, user_id: uuid.UUID) -> set[str]:
    return {
        row.code
        for row in conn.execute(
            text("""
                SELECT sr.code FROM security.user_system_roles usr
                JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
                WHERE usr.user_id = :u AND usr.revoked_at IS NULL
            """),
            {"u": user_id},
        )
    }


def test_upgrade_backfills_by_policy_and_round_trips() -> None:
    admin_url, test_url = _provision()
    try:
        _alembic(test_url, "upgrade", _BEFORE)
        engine = create_engine(test_url)
        try:
            with engine.begin() as conn:
                admin = _user(conn, "Old Admin", admin=True)
                dormant_admin = _user(conn, "Dormant Admin", admin=True, status="inactive")
                owner = _user(conn, "World Owner")
                former_owner = _user(conn, "Former Owner")
                co_owner = _user(conn, "Co Owner")
                campaign_gm = _user(conn, "Campaign GM")
                player = _user(conn, "Player")
                world = make_world(conn, f"w-{uuid.uuid4().hex[:6]}")
                _own_world(conn, world, owner)
                other_world = make_world(conn, f"x-{uuid.uuid4().hex[:6]}")
                _own_world(conn, other_world, co_owner)
                _own_world(conn, other_world, former_owner, ended=False)
                conn.execute(
                    text("""
                        UPDATE security.world_memberships SET membership_status_id =
                            (SELECT membership_status_id FROM security.membership_statuses
                             WHERE code = 'suspended')
                        WHERE user_id = :u
                    """),
                    {"u": former_owner},
                )
                timeline = make_timeline(conn, world, is_primary=True)
                campaign = make_campaign(conn, timeline, "Camp", lifecycle_status_code="pending")
                membership = make_campaign_membership(conn, campaign, campaign_gm)
                gm_role = conn.execute(
                    text(
                        "SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL"
                    )
                ).scalar_one()
                make_membership_role(conn, membership, gm_role)
        finally:
            engine.dispose()

        _alembic(test_url, "upgrade", _WORLD_ROLES)

        engine = create_engine(test_url)
        try:
            with engine.connect() as conn:
                assert _roles(conn, admin) == {"admin", "gm"}
                # The backfill covers every lifecycle status, so reactivation restores it.
                assert _roles(conn, dormant_admin) == {"admin", "gm"}
                assert _roles(conn, owner) == {"gm"}
                assert _roles(conn, co_owner) == {"gm"}
                # A suspended owner assignment is not an open active one.
                assert _roles(conn, former_owner) == {"player"}
                # Campaign GM is NOT promoted on the strength of a campaign role.
                assert _roles(conn, campaign_gm) == {"player"}
                assert _roles(conn, player) == {"player"}
                # Nothing was granted by anyone, and the column is gone.
                assert (
                    conn.execute(
                        text(
                            "SELECT count(*) FROM security.user_system_roles WHERE granted_by_user_id IS NOT NULL"
                        )
                    ).scalar_one()
                    == 0
                )
                assert not conn.execute(
                    text("""
                        SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'security' AND table_name = 'users'
                          AND column_name = 'is_platform_administrator')
                    """)
                ).scalar()
                # Campaign memberships, roles and world ownership are untouched.
                assert (
                    conn.execute(
                        text(
                            "SELECT count(*) FROM security.membership_roles WHERE campaign_membership_id = :m"
                        ),
                        {"m": membership},
                    ).scalar_one()
                    == 1
                )
                assert (
                    conn.execute(
                        text(
                            "SELECT count(*) FROM security.world_memberships WHERE world_id = :w AND ended_at IS NULL"
                        ),
                        {"w": world},
                    ).scalar_one()
                    == 1
                )
                assert {
                    r.code for r in conn.execute(text("SELECT code FROM security.world_roles"))
                } == {
                    "world_owner",
                    "world_viewer",
                    "world_editor",
                    "world_reviewer",
                    "world_reader",
                }
        finally:
            engine.dispose()

        # Downgrade both revisions and re-upgrade: the flag comes back from `admin` rows.
        _alembic(test_url, "downgrade", _BEFORE)
        engine = create_engine(test_url)
        try:
            with engine.connect() as conn:
                flags = {
                    row.user_id: row.is_platform_administrator
                    for row in conn.execute(
                        text("SELECT user_id, is_platform_administrator FROM security.users")
                    )
                }
                assert flags[admin] is True and flags[dormant_admin] is True
                assert flags[owner] is False and flags[campaign_gm] is False
                assert {
                    r.code for r in conn.execute(text("SELECT code FROM security.world_roles"))
                } >= {"world_owner"}
        finally:
            engine.dispose()
        _alembic(test_url, "upgrade", _SYSTEM_ROLES)
        _alembic(test_url, "upgrade", _WORLD_ROLES)
        engine = create_engine(test_url)
        try:
            with engine.connect() as conn:
                assert _roles(conn, admin) == {"admin", "gm"}
                assert _roles(conn, owner) == {"gm"}
        finally:
            engine.dispose()
    finally:
        _drop(admin_url, test_url)
