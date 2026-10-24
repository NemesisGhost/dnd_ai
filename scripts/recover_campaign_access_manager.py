"""Out-of-band recovery of a campaign with no access manager (docs/adr/0019-scoped-
system-world-and-campaign-roles.md, plan section 4.5; owner question Q11: scripts first).

A campaign is stranded when no *active account* holds a non-expiring `access.manage`
assignment in it (the database retention trigger only counts assignment rows, so
disabling the sole manager's account leaves the campaign unmanageable). This script
lets an active platform **Administrator** give the `campaign_owner` role to a named
active account, creating their membership if they have none. It refuses a campaign
that still has an access manager, so it can never take over a healthy campaign, and
it reads no campaign content.

A reason is required and is recorded, with the Administrator as actor, in one
`audit.change_log` row. Database client only; the connection string comes from the
environment (`DND_AI_DATABASE_URL`, or the legacy `DATABASE_URL`). Preview-by-default.

Usage:
  uv run python scripts/recover_campaign_access_manager.py --campaign-id <uuid> \\
      --admin-login admin --new-manager-login gm2 --reason "GM left the group"
  uv run python scripts/recover_campaign_access_manager.py --campaign-id <uuid> \\
      --admin-login admin --new-manager-login gm2 --reason "GM left the group" --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from sqlalchemy import create_engine

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.recovery import recover_campaign_access_manager
from dnd_ai.domain.errors import SafeMessageError
from dnd_ai.queries.world_access import find_active_account

_COMMAND_NAME = "recover_campaign_access_manager"


def _database_url() -> str:
    url = os.environ.get("DND_AI_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "DND_AI_DATABASE_URL (or the legacy DATABASE_URL) must be set in the environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", type=uuid.UUID, required=True)
    parser.add_argument("--admin-login", required=True)
    parser.add_argument("--new-manager-login", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    engine = create_engine(_database_url())
    try:
        with engine.begin() as connection:
            admin = find_active_account(connection, login_name=args.admin_login)
            manager = find_active_account(connection, login_name=args.new_manager_login)
            if admin is None or manager is None:
                print("Both logins must name active local accounts.", file=sys.stderr)
                return 1
            try:
                result = recover_campaign_access_manager(
                    connection,
                    admin_user_id=admin.user_id,
                    campaign_id=args.campaign_id,
                    new_user_id=manager.user_id,
                    reason=args.reason,
                )
            except SafeMessageError as exc:
                print(f"Refused: {exc.safe_message}", file=sys.stderr)
                return 1
            print(f"campaign_id: {result.campaign_id}")
            print(f"new campaign owner: {manager.display_name} ({result.new_manager_user_id})")
            if not args.apply:
                print("Preview (no changes made): re-run with --apply to recover access.")
                connection.rollback()
                return 0
            record_change_log(
                connection,
                change_action_code="created",
                schema_name="security",
                table_name="membership_roles",
                record_id=result.membership_role_id,
                entity_id=None,
                world_id=None,
                actor_user_id=admin.user_id,
                correlation_id=None,
                command_name=_COMMAND_NAME,
                event_id=None,
                reason=args.reason,
                changed_fields={"target_user_id": str(result.new_manager_user_id)},
            )
            print("Access recovered.")
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
