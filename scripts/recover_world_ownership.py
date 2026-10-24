"""Out-of-band recovery of a stranded world (docs/adr/0019-scoped-system-world-and-
campaign-roles.md, plan section 4.5; owner question Q11: scripts first).

A world is stranded when it has no Owner who can manage it: an Owner needs an active
account **and** the system `gm` role. Disabling the sole Owner's account, or revoking
their system GM, does that. This script lets an active platform **Administrator**
name a new Owner for such a world. It refuses a world that still has a manageable
Owner, so it can never take over a healthy world, and it reads no world content.

The new Owner must be an active account holding the system `gm` role. A reason is
required and is recorded, with the Administrator as actor, in one `audit.change_log`
row (no credentials, no tokens).

Like the other operator scripts this is a **database** client: the connection string
comes from the environment only (`DND_AI_DATABASE_URL`, or the legacy `DATABASE_URL`),
never argv. Preview-by-default: nothing is written without `--apply`.

Usage:
  uv run python scripts/recover_world_ownership.py --list-stranded
  uv run python scripts/recover_world_ownership.py --world-id <uuid> \\
      --admin-login admin --new-owner-login gm2 --reason "Previous owner left"
  uv run python scripts/recover_world_ownership.py --world-id <uuid> \\
      --admin-login admin --new-owner-login gm2 --reason "Previous owner left" --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from sqlalchemy import Connection, create_engine, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.recovery import recover_world_ownership
from dnd_ai.domain.errors import SafeMessageError
from dnd_ai.queries.world_access import find_active_account

_COMMAND_NAME = "recover_world_ownership"


def _database_url() -> str:
    url = os.environ.get("DND_AI_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "DND_AI_DATABASE_URL (or the legacy DATABASE_URL) must be set in the environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url


def _list_stranded(connection: Connection) -> int:
    from dnd_ai.queries.stranded import world_has_manageable_owner

    rows = connection.execute(
        text("""
            SELECT DISTINCT w.world_id, w.name
            FROM core.worlds w
            JOIN security.world_memberships wm ON wm.world_id = w.world_id
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            WHERE wr.code = 'world_owner' AND wm.ended_at IS NULL
            ORDER BY w.name, w.world_id
        """)
    ).all()
    stranded = [r for r in rows if not world_has_manageable_owner(connection, world_id=r.world_id)]
    if not stranded:
        print("No stranded worlds.")
        return 0
    for row in stranded:
        print(f"{row.world_id}  {row.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-stranded", action="store_true")
    parser.add_argument("--world-id", type=uuid.UUID)
    parser.add_argument("--admin-login")
    parser.add_argument("--new-owner-login")
    parser.add_argument("--reason")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    engine = create_engine(_database_url())
    try:
        if args.list_stranded:
            with engine.connect() as connection:
                return _list_stranded(connection)
        if not (args.world_id and args.admin_login and args.new_owner_login and args.reason):
            parser.error("--world-id, --admin-login, --new-owner-login and --reason are required")
        with engine.begin() as connection:
            admin = find_active_account(connection, login_name=args.admin_login)
            new_owner = find_active_account(connection, login_name=args.new_owner_login)
            if admin is None or new_owner is None:
                print("Both logins must name active local accounts.", file=sys.stderr)
                return 1
            try:
                result = recover_world_ownership(
                    connection,
                    admin_user_id=admin.user_id,
                    world_id=args.world_id,
                    new_owner_user_id=new_owner.user_id,
                    reason=args.reason,
                )
            except SafeMessageError as exc:
                print(f"Refused: {exc.safe_message}", file=sys.stderr)
                return 1
            print(f"world_id: {result.world_id}")
            print(f"new owner: {new_owner.display_name} ({result.new_owner_user_id})")
            if not args.apply:
                print("Preview (no changes made): re-run with --apply to recover ownership.")
                connection.rollback()
                return 0
            record_change_log(
                connection,
                change_action_code="created",
                schema_name="security",
                table_name="world_memberships",
                record_id=result.world_membership_id,
                entity_id=None,
                world_id=result.world_id,
                actor_user_id=admin.user_id,
                correlation_id=None,
                command_name=_COMMAND_NAME,
                event_id=None,
                reason=args.reason,
                changed_fields={"new_owner_user_id": str(result.new_owner_user_id)},
            )
            print("Ownership recovered.")
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
