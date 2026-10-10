"""Out-of-band world-membership administration CLI
(docs/adr/0019-world-visibility-and-viewer-role.md).

World memberships have no HTTP route or portal control in the current product
scope. This script is the supported way to change one after a world has an
owner: grant read-only `world_viewer` access, end a membership, or transfer
ownership. It is trusted infrastructure only, like
`scripts/claim_world_ownership.py` and `scripts/grant_platform_administrator.py`.

It is also the remediation path for a **historical player-owned world**: one
created before world creation was limited to platform administrators and
effective GMs (docs/adr/0018-world-creation-eligibility.md). Nothing revokes
such ownership automatically and no world is deleted:

  1. `--list-ineligible-owners` reports every open `world_owner` membership
     whose holder no longer satisfies the creation policy;
  2. `--transfer-to <login>` hands ownership to an eligible account and, with
     `--retain-viewer`, leaves the former owner read-only `world_viewer`
     access; without it they keep no world role.

Either way the former owner keeps whatever their *campaign* roles grant —
`campaign.view` still opens each of their campaigns' World Explorer — and
gains no authoring access. A world whose only owner is ineligible and has no
eligible successor is left as it is: report it, decide, then transfer.

Like the other operator scripts, this is a **database** client: the connection
string comes from the environment only (`DND_AI_DATABASE_URL`, or the legacy
`DATABASE_URL`), never argv. Preview-by-default: nothing is written without
`--apply`. Every row opened or closed gets one `audit.change_log` row naming
this script as the actor.

Usage:
  uv run python scripts/manage_world_membership.py --list-ineligible-owners
  uv run python scripts/manage_world_membership.py --world-slug w --list
  uv run python scripts/manage_world_membership.py --world-slug w --login-name p1 \\
      --set-role world_viewer [--apply]
  uv run python scripts/manage_world_membership.py --world-slug w --login-name p1 \\
      --end [--apply]
  uv run python scripts/manage_world_membership.py --world-slug w --login-name p1 \\
      --transfer-to gm1 [--retain-viewer] [--apply]
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, create_engine, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.local_auth import normalize_login_name
from dnd_ai.commands.world_memberships import (
    WorldMembershipChange,
    end_world_membership,
    set_world_role,
    transfer_world_ownership,
)
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.authoring import WorldMembershipChangeRefusedError
from dnd_ai.domain.world_authority import WORLD_OWNER_ROLE
from dnd_ai.queries.world_authority import may_create_worlds

ACTOR_SERVICE = "manage_world_membership_script"


@dataclass(frozen=True)
class IneligibleOwner:
    world_id: uuid.UUID
    world_slug: str
    world_name: str
    user_id: uuid.UUID
    display_name: str


def _database_url() -> str:
    url = os.environ.get("DND_AI_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "DND_AI_DATABASE_URL (or the legacy DATABASE_URL) must be set in the environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url


def resolve_local_user(connection: Connection, *, login_name: str) -> uuid.UUID | None:
    return connection.execute(
        text("""
            SELECT u.user_id
            FROM security.users u
            JOIN security.external_identities ei ON ei.user_id = u.user_id
            WHERE ei.issuer = :issuer AND ei.subject = :subject AND ei.revoked_at IS NULL
        """),
        {"issuer": LOCAL_AUTH_ISSUER, "subject": normalize_login_name(login_name)},
    ).scalar()


def list_ineligible_owners(connection: Connection) -> list[IneligibleOwner]:
    """Open `world_owner` memberships whose holder may not create worlds
    today (ADR 0018) — the candidates for transfer. Read-only."""
    rows = connection.execute(
        text("""
            SELECT w.world_id, w.slug, w.name, u.user_id, u.display_name
            FROM security.world_memberships wm
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            JOIN core.worlds w ON w.world_id = wm.world_id
            JOIN security.users u ON u.user_id = wm.user_id
            WHERE wm.ended_at IS NULL AND wr.code = :owner
            ORDER BY w.slug, u.display_name, u.user_id
        """),
        {"owner": WORLD_OWNER_ROLE},
    ).all()
    return [
        IneligibleOwner(
            world_id=row.world_id,
            world_slug=str(row.slug),
            world_name=str(row.name),
            user_id=row.user_id,
            display_name=str(row.display_name),
        )
        for row in rows
        if not may_create_worlds(connection, user_id=row.user_id)
    ]


def list_world_memberships(connection: Connection, *, world_id: uuid.UUID) -> list[tuple[str, ...]]:
    rows = connection.execute(
        text("""
            SELECT u.display_name, wr.code, ms.code AS status,
                   wm.joined_at, wm.ended_at
            FROM security.world_memberships wm
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = wm.membership_status_id
            JOIN security.users u ON u.user_id = wm.user_id
            WHERE wm.world_id = :w
            ORDER BY wm.joined_at, wm.world_membership_id
        """),
        {"w": world_id},
    ).all()
    return [
        (
            str(row.display_name),
            str(row.code),
            str(row.status),
            row.joined_at.isoformat(),
            "open" if row.ended_at is None else f"ended {row.ended_at.isoformat()}",
        )
        for row in rows
    ]


def audit_changes(
    connection: Connection, *, changes: list[WorldMembershipChange], command_name: str
) -> None:
    """One audit row per membership row opened or closed, in the caller's
    transaction. An operator at a shell prompt is not an authenticated
    principal, so the actor is this script."""
    for change in changes:
        record_change_log(
            connection,
            change_action_code="created" if change.action == "created" else "updated",
            schema_name="security",
            table_name="world_memberships",
            record_id=change.world_membership_id,
            entity_id=None,
            world_id=change.world_id,
            actor_service=ACTOR_SERVICE,
            correlation_id=None,
            command_name=command_name,
            event_id=None,
            changed_fields={
                "user_id": str(change.user_id),
                "world_role": change.role_code,
                "membership": change.action,
            },
        )


def apply_set_role(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID, role_code: str
) -> list[WorldMembershipChange]:
    changes = set_world_role(connection, world_id=world_id, user_id=user_id, role_code=role_code)
    audit_changes(connection, changes=changes, command_name="set_world_role")
    return changes


def apply_end(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID
) -> list[WorldMembershipChange]:
    changes = end_world_membership(connection, world_id=world_id, user_id=user_id)
    audit_changes(connection, changes=changes, command_name="end_world_membership")
    return changes


def apply_transfer(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    from_user_id: uuid.UUID,
    to_user_id: uuid.UUID,
    retain_viewer: bool,
) -> list[WorldMembershipChange]:
    changes = transfer_world_ownership(
        connection,
        world_id=world_id,
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        retain_viewer=retain_viewer,
    )
    audit_changes(connection, changes=changes, command_name="transfer_world_ownership")
    return changes


def _describe(changes: list[WorldMembershipChange]) -> None:
    if not changes:
        print("No change: the membership is already in that state.")
    for change in changes:
        print(f"  {change.action}: {change.role_code} for user {change.user_id}")


def _run(engine: Engine, args: argparse.Namespace) -> int:
    if args.list_ineligible_owners:
        with engine.connect() as connection:
            owners = list_ineligible_owners(connection)
        if not owners:
            print("Every world owner satisfies the world-creation policy.")
        for owner in owners:
            print(f"{owner.world_slug}\t{owner.world_name}\t{owner.display_name}\t{owner.user_id}")
        return 0

    if not args.world_slug:
        print("--world-slug is required.", file=sys.stderr)
        return 2

    # `engine.begin()` commits only when the block exits normally; a preview
    # rolls back by raising out of it.
    class _Preview(Exception):
        pass

    try:
        with engine.begin() as connection:
            world_id = connection.execute(
                text("SELECT world_id FROM core.worlds WHERE slug = :s"), {"s": args.world_slug}
            ).scalar()
            if world_id is None:
                print("Refused: world not found.", file=sys.stderr)
                return 1
            if args.list:
                for row in list_world_memberships(connection, world_id=world_id):
                    print("\t".join(row))
                return 0

            if not args.login_name:
                print("--login-name is required.", file=sys.stderr)
                return 2
            user_id = resolve_local_user(connection, login_name=args.login_name)
            if user_id is None:
                print("Refused: local account not found.", file=sys.stderr)
                return 1

            if args.transfer_to:
                to_user_id = resolve_local_user(connection, login_name=args.transfer_to)
                if to_user_id is None:
                    print("Refused: new owner's local account not found.", file=sys.stderr)
                    return 1
                changes = apply_transfer(
                    connection,
                    world_id=world_id,
                    from_user_id=user_id,
                    to_user_id=to_user_id,
                    retain_viewer=args.retain_viewer,
                )
            elif args.set_role:
                changes = apply_set_role(
                    connection, world_id=world_id, user_id=user_id, role_code=args.set_role
                )
            elif args.end:
                changes = apply_end(connection, world_id=world_id, user_id=user_id)
            else:
                print("Choose --set-role, --end, or --transfer-to.", file=sys.stderr)
                return 2

            if not args.apply:
                print("Preview (nothing written):")
                _describe(changes)
                print("Re-run with --apply to make this change.")
                raise _Preview
            print("Applied:")
            _describe(changes)
            return 0
    except _Preview:
        return 0
    except WorldMembershipChangeRefusedError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-ineligible-owners", action="store_true")
    parser.add_argument("--world-slug")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--login-name")
    parser.add_argument("--set-role", choices=["world_owner", "world_viewer"])
    parser.add_argument("--end", action="store_true")
    parser.add_argument("--transfer-to")
    parser.add_argument("--retain-viewer", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    engine = create_engine(_database_url())
    try:
        return _run(engine, args)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
