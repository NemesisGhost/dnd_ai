"""Verify the scoped-role upgrade (revisions 137 and 138) against a database you control.

Two read-only steps, run before and after `alembic upgrade head` on the SAME database, so the
offline upgrade in docs/LOCAL_DEPLOYMENT.md can be checked on a restored copy of a real database
before it is trusted with the real one (docs/adr/0020-scoped-system-world-and-campaign-roles.md):

    # on a copy at revision 136_world_viewer_role
    DATABASE_URL=... uv run python scripts/operations/verify_scoped_role_upgrade.py snapshot pre.json
    # alembic -c database/alembic.ini upgrade head
    DATABASE_URL=... uv run python scripts/operations/verify_scoped_role_upgrade.py verify pre.json

`snapshot` records what the upgrade must not change (accounts and their lifecycle status, campaign
memberships and roles, world memberships, invitations, character relationships, resource grants,
and row counts of the main aggregates) plus the old `is_platform_administrator` flag and the
open world Owner rows the backfill reads. `verify` then checks, on the upgraded database:

- every recorded identifier is still there with the same key columns (nothing renumbered, ended,
  revoked or deleted);
- each account holds exactly the system roles the backfill policy gives it: a legacy administrator
  (of any lifecycle status) holds `admin` and `gm`; an open active world Owner who is not one holds
  `gm`; everyone else holds `player`; **no campaign GM is promoted** on that basis;
- the boolean column is gone, and the three new world roles exist.

Grants, default privileges and migration drift are checked separately (docs/DEVELOPMENT.md): run
`tests/database/test_role_grants.py` and `alembic check` against the upgraded copy.

The script only reads. It writes nothing to the database it is pointed at, and it never creates,
drops or migrates a database: restore a dump to a new name, run the steps, discard the copy.
The database URL comes from the environment (`DATABASE_URL`), never an argument.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, create_engine, text

# Tables whose rows the upgrade must carry over untouched: (name, SQL producing stable key columns).
_KEYED: dict[str, str] = {
    "users": (
        "SELECT u.user_id::text AS id, ls.code AS status FROM security.users u "
        "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id"
    ),
    "campaign_memberships": (
        "SELECT cm.campaign_membership_id::text AS id, cm.campaign_id::text AS campaign, "
        "cm.user_id::text AS usr, (cm.ended_at IS NULL) AS open "
        "FROM security.campaign_memberships cm"
    ),
    "membership_roles": (
        "SELECT mr.membership_role_id::text AS id, mr.campaign_membership_id::text AS membership, "
        "r.code AS role, (mr.revoked_at IS NULL) AS open FROM security.membership_roles mr "
        "JOIN security.roles r ON r.role_id = mr.role_id"
    ),
    "world_memberships": (
        "SELECT wm.world_membership_id::text AS id, wm.world_id::text AS world, "
        "wm.user_id::text AS usr, wr.code AS role, (wm.ended_at IS NULL) AS open "
        "FROM security.world_memberships wm "
        "JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id"
    ),
    "campaign_invitations": (
        "SELECT i.campaign_invitation_id::text AS id, i.campaign_id::text AS campaign "
        "FROM security.campaign_invitations i"
    ),
    "character_relationships": (
        "SELECT c.membership_character_relationship_id::text AS id, "
        "c.campaign_membership_id::text AS membership FROM security.membership_character_relationships c"
    ),
    "resource_grants": (
        "SELECT g.resource_grant_id::text AS id, g.campaign_id::text AS campaign, "
        "g.effect::text AS effect FROM security.resource_grants g"
    ),
}

_COUNTED = (
    "core.worlds",
    "campaign.campaigns",
    "campaign.timelines",
    "core.entities",
    "campaign.sessions",
    "narrative.events",
    "audit.change_log",
)

_NEW_WORLD_ROLES = {"world_editor", "world_reviewer", "world_reader"}


def _engine() -> Any:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (the environment is the only source of the URL).")
    return create_engine(url)


def _has_column(conn: Connection, schema: str, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = :c)"
            ),
            {"s": schema, "t": table, "c": column},
        ).scalar()
    )


def _rows(conn: Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in conn.execute(text(sql))]


def _snapshot(conn: Connection) -> dict[str, Any]:
    revision = conn.execute(text("SELECT version_num FROM core.alembic_version")).scalar()
    snap: dict[str, Any] = {"revision": revision, "tables": {}, "counts": {}}
    for name, sql in _KEYED.items():
        try:
            snap["tables"][name] = _rows(conn, sql)
        except Exception as exc:  # a table this revision does not have is recorded, not guessed
            conn.rollback()
            snap["tables"][name] = {"unavailable": type(exc).__name__}
    for table in _COUNTED:
        snap["counts"][table] = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
    if _has_column(conn, "security", "users", "is_platform_administrator"):
        snap["legacy_admins"] = [
            row["id"]
            for row in _rows(
                conn,
                "SELECT user_id::text AS id FROM security.users WHERE is_platform_administrator",
            )
        ]
    else:
        snap["legacy_admins"] = None
    snap["open_active_world_owners"] = sorted(
        {
            row["usr"]
            for row in _rows(
                conn,
                "SELECT wm.user_id::text AS usr FROM security.world_memberships wm "
                "JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id "
                "JOIN security.membership_statuses ms ON ms.membership_status_id = wm.membership_status_id "
                "WHERE wr.code = 'world_owner' AND wm.ended_at IS NULL AND ms.code = 'active'",
            )
        }
    )
    return snap


def _system_roles(conn: Connection) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = {}
    for row in conn.execute(
        text(
            "SELECT usr.user_id::text AS usr, sr.code AS code FROM security.user_system_roles usr "
            "JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id "
            "WHERE usr.revoked_at IS NULL"
        )
    ):
        roles.setdefault(row.usr, set()).add(row.code)
    return roles


def cmd_snapshot(path: Path) -> int:
    with _engine().connect() as conn:
        snap = _snapshot(conn)
    if snap["legacy_admins"] is None:
        sys.exit(
            "snapshot must be taken before the upgrade: the legacy admin flag is already gone."
        )
    path.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"snapshot of revision {snap['revision']}: "
        f"{len(snap['tables']['users'])} accounts, {len(snap['legacy_admins'])} legacy administrators, "
        f"{len(snap['open_active_world_owners'])} world owners -> {path}"
    )
    return 0


def cmd_verify(path: Path) -> int:
    before = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    with _engine().connect() as conn:
        after = _snapshot(conn)
        roles = _system_roles(conn)
        new_world_roles = {
            row.code
            for row in conn.execute(text("SELECT code FROM security.world_roles"))
            if row.code in _NEW_WORLD_ROLES
        }
        owns_system_role_table = _has_column(conn, "security", "user_system_roles", "user_id")
        campaign_gms = {
            row.usr
            for row in conn.execute(
                text(
                    "SELECT DISTINCT cm.user_id::text AS usr FROM security.membership_roles mr "
                    "JOIN security.campaign_memberships cm "
                    "  ON cm.campaign_membership_id = mr.campaign_membership_id "
                    "JOIN security.roles r ON r.role_id = mr.role_id "
                    "WHERE r.code = 'gm' AND mr.revoked_at IS NULL AND cm.ended_at IS NULL"
                )
            )
        }

    if not owns_system_role_table:
        failures.append("security.user_system_roles does not exist: the upgrade did not run")
    if after["legacy_admins"] is not None:
        failures.append("security.users.is_platform_administrator is still present")
    if new_world_roles != _NEW_WORLD_ROLES:
        failures.append(f"world roles missing: {sorted(_NEW_WORLD_ROLES - new_world_roles)}")

    for name, rows in before["tables"].items():
        if isinstance(rows, dict):
            continue
        now = {row["id"]: row for row in after["tables"][name]}
        for row in rows:
            if now.get(row["id"]) != row:
                failures.append(
                    f"{name}: {row['id']} changed or disappeared: {row} -> {now.get(row['id'])}"
                )
    for table, count in before["counts"].items():
        if after["counts"][table] < count:
            failures.append(f"{table}: {count} rows before, {after['counts'][table]} after")

    legacy_admins = set(before["legacy_admins"])
    owners = set(before["open_active_world_owners"])
    promoted_campaign_gms: list[str] = []
    for user in before["tables"]["users"]:
        uid = user["id"]
        expected = (
            {"admin", "gm"} if uid in legacy_admins else ({"gm"} if uid in owners else {"player"})
        )
        # An administrator who also owns a world still holds exactly admin + gm.
        held = roles.get(uid, set())
        if held != expected:
            failures.append(f"account {uid}: holds {sorted(held)}, expected {sorted(expected)}")
        if uid in campaign_gms and uid not in legacy_admins and uid not in owners and "gm" in held:
            promoted_campaign_gms.append(uid)
    if promoted_campaign_gms:
        failures.append(f"campaign GMs promoted to system gm: {promoted_campaign_gms}")

    report = {
        "from_revision": before["revision"],
        "to_revision": after["revision"],
        "accounts": len(before["tables"]["users"]),
        "legacy_administrators": len(legacy_admins),
        "world_owners": len(owners),
        "campaign_only_gms": len(campaign_gms - legacy_admins - owners),
        "failures": failures,
    }
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "verify"):
        sub.add_parser(name).add_argument("file", type=Path)
    args = parser.parse_args()
    return cmd_snapshot(args.file) if args.command == "snapshot" else cmd_verify(args.file)


if __name__ == "__main__":
    sys.exit(main())
