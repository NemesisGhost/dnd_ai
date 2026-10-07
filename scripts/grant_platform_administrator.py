"""Out-of-band platform-administrator promotion CLI (Phase 13E checkpoint
9b; owner decision D-10).

Recovers from the single-active-administrator bus factor: by default the
system `admin` role (`security.user_system_roles`, ADR 0020) is granted to an
*existing* account by exactly this script — no HTTP route or portal control
promotes an account unless the deployment enables `DND_AI_ALLOW_IN_APP_ADMIN_GRANT`
(off by default) — the same "trusted infrastructure, never over HTTP" posture `scripts/
bootstrap_admin.py` and `security.timeline_bootstrap_grants` already
establish for their own analogous first-campaign entitlement. Standing
recommendation: promote a second administrator early, so this recovery
path is never actually needed under pressure.

Like `scripts/bootstrap_admin.py`, this is a **database** client, not an
HTTP client, and reads the connection string from the environment only
(`DND_AI_DATABASE_URL`, or the legacy unprefixed `DATABASE_URL`) — never a
command-line argument, since a connection string can embed a password and
argv is routinely visible in process listings and shell history on a
shared host.

Preview-by-default: without `--apply`, this only resolves and prints the
target account's current status and writes nothing. Idempotent: promoting
an account that is already an administrator is a documented no-op, not an
error, either in preview or with `--apply`.

Usage:
  uv run python scripts/grant_platform_administrator.py --login-name gm2
      # preview only -- prints what would happen, changes nothing

  uv run python scripts/grant_platform_administrator.py --login-name gm2 --apply
      # grants the system `admin` role (and nothing else: no GM, world or campaign
      # access), if the account is not already an administrator
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import Connection, Engine, create_engine, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.local_auth import (
    GrantPlatformAdministratorResult,
    PlatformAccountNotFoundError,
    grant_platform_administrator,
    normalize_login_name,
)
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER, is_platform_administrator

_GRANT_COMMAND_NAME = "grant_platform_administrator"


def _database_url() -> str:
    url = os.environ.get("DND_AI_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "DND_AI_DATABASE_URL (or the legacy DATABASE_URL) must be set in the environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url


def _preview(connection: Connection, *, login_name: str) -> int:
    """Read-only: resolves and prints the target account's current status
    without acquiring the advisory lock or writing anything — mirrors
    `grant_platform_administrator`'s own resolution query exactly, so the
    preview can never disagree with what `--apply` would actually do."""
    normalized_login_name = normalize_login_name(login_name)
    row = (
        connection.execute(
            text("""
                SELECT u.user_id, u.display_name
                FROM security.users u
                JOIN security.external_identities ei ON ei.user_id = u.user_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE ei.issuer = :issuer AND ei.subject = :subject
                  AND ei.revoked_at IS NULL AND ls.code = 'active'
            """),
            {"issuer": LOCAL_AUTH_ISSUER, "subject": normalized_login_name},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        print(
            f"Preview: no active local account found for login name {normalized_login_name!r}.",
            file=sys.stderr,
        )
        return 1
    # Password-redacted summary before any write, matching setup_
    # phase13c_dev_data.py's own established convention -- there is no
    # password here to redact, but the target is named plainly and nothing
    # else about the account is printed.
    print("Preview (no changes made):")
    print(f"  user_id: {row['user_id']}")
    print(f"  login_name: {normalized_login_name}")
    print(f"  display_name: {row['display_name']}")
    already_administrator = is_platform_administrator(connection, user_id=row["user_id"])
    print(f"  currently_platform_administrator: {already_administrator}")
    if already_administrator:
        print("  This account is already a platform administrator -- --apply would be a no-op.")
    else:
        print("  Re-run with --apply to promote this account.")
    return 0


def _apply(engine: Engine, *, login_name: str) -> int:
    try:
        result: GrantPlatformAdministratorResult = grant_platform_administrator(
            engine, login_name=login_name
        )
    except PlatformAccountNotFoundError as exc:
        print(f"Grant refused: {exc.safe_message}", file=sys.stderr)
        return 1

    if result.already_administrator:
        print(f"user_id: {result.user_id}")
        print(f"login_name: {result.login_name}")
        print("Already a platform administrator -- no change made.")
        return 0

    # One audit.change_log row with no actor_user_id -- there is no
    # authenticated principal for an operator running this at a shell
    # prompt -- and actor_service naming this script instead, the same
    # "actor is not a person" case that column exists for
    # (dnd_ai.api.local_auth._record_login_failure_audit's identical use).
    with engine.begin() as connection:
        record_change_log(
            connection,
            change_action_code="status_changed",
            schema_name="security",
            table_name="users",
            record_id=result.user_id,
            entity_id=None,
            world_id=None,
            actor_service=_GRANT_COMMAND_NAME,
            correlation_id=None,
            command_name=_GRANT_COMMAND_NAME,
            event_id=None,
            changed_fields={"system_role_assigned": "admin"},
        )

    print(f"user_id: {result.user_id}")
    print(f"login_name: {result.login_name}")
    print("Promoted to platform administrator.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-name", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually promote the account. Without this flag, only a preview is printed.",
    )
    args = parser.parse_args(argv)

    engine = create_engine(_database_url())
    try:
        if not args.apply:
            with engine.connect() as connection:
                return _preview(connection, login_name=args.login_name)
        return _apply(engine, login_name=args.login_name)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
