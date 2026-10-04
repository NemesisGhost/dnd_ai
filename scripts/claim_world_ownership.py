"""Out-of-band world-ownership claim CLI (Phase 14, ADR 0014).

Worlds created before migration 110 have no owner, so nobody may author them
through the portal. This script is the one supported way to give such a
**legacy, never-owned** world its first owner. It is trusted infrastructure
only -- no HTTP route or portal control ever claims a world -- the same
posture as `scripts/grant_platform_administrator.py` and
`security.timeline_bootstrap_grants`.

`claim_unowned_world` refuses any world that has (or ever had) a membership row
of any status, so this can never take over an owned or previously owned world.

Like the other operator scripts, this is a **database** client: the connection
string comes from the environment only (`DND_AI_DATABASE_URL`, or the legacy
`DATABASE_URL`), never argv. Preview-by-default: nothing is written without
`--apply`.

Usage:
  uv run python scripts/claim_world_ownership.py --list-unowned
  uv run python scripts/claim_world_ownership.py --world-slug my-world --login-name gm1
      # preview only
  uv run python scripts/claim_world_ownership.py --world-slug my-world --login-name gm1 --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from sqlalchemy import Connection, Engine, create_engine, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands.local_auth import normalize_login_name
from dnd_ai.commands.worlds import ClaimWorldResult, claim_unowned_world
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.authoring import WorldAlreadyClaimedError

CLAIM_COMMAND_NAME = "claim_unowned_world"
CLAIM_ACTOR_SERVICE = "claim_world_ownership_script"


def _database_url() -> str:
    url = os.environ.get("DND_AI_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "DND_AI_DATABASE_URL (or the legacy DATABASE_URL) must be set in the environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url


def list_unowned_worlds(connection: Connection) -> list[tuple[uuid.UUID, str, str]]:
    """`(world_id, slug, name)` for every world with no membership row at all."""
    rows = connection.execute(
        text("""
            SELECT w.world_id, w.slug, w.name FROM core.worlds w
            WHERE NOT EXISTS (
                SELECT 1 FROM security.world_memberships wm WHERE wm.world_id = w.world_id
            )
            ORDER BY w.slug
        """)
    ).all()
    return [(row.world_id, str(row.slug), str(row.name)) for row in rows]


def resolve_local_user(connection: Connection, *, login_name: str) -> uuid.UUID | None:
    return connection.execute(
        text("""
            SELECT u.user_id
            FROM security.users u
            JOIN security.external_identities ei ON ei.user_id = u.user_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE ei.issuer = :issuer AND ei.subject = :subject
              AND ei.revoked_at IS NULL AND ls.code = 'active'
        """),
        {"issuer": LOCAL_AUTH_ISSUER, "subject": normalize_login_name(login_name)},
    ).scalar()


def claim_world(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID
) -> ClaimWorldResult:
    """Claim and audit in the caller's transaction (also used by the
    development-data script). One audit row naming this script as the actor,
    since an operator at a shell prompt is not an authenticated principal."""
    result = claim_unowned_world(connection, world_id=world_id, user_id=user_id)
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="security",
        table_name="world_memberships",
        record_id=result.world_membership_id,
        entity_id=None,
        world_id=world_id,
        actor_service=CLAIM_ACTOR_SERVICE,
        correlation_id=None,
        command_name=CLAIM_COMMAND_NAME,
        event_id=None,
        changed_fields={"claimed_by_user_id": str(user_id)},
    )
    return result


def _run(engine: Engine, args: argparse.Namespace) -> int:
    if args.list_unowned:
        with engine.connect() as connection:
            worlds = list_unowned_worlds(connection)
        if not worlds:
            print("No unowned worlds.")
        for world_id, slug, name in worlds:
            print(f"{slug}\t{name}\t{world_id}")
        return 0

    if not args.world_slug or not args.login_name:
        print("--world-slug and --login-name are required.", file=sys.stderr)
        return 2

    with engine.begin() as connection:
        world_id = connection.execute(
            text("SELECT world_id FROM core.worlds WHERE slug = :s"), {"s": args.world_slug}
        ).scalar()
        user_id = resolve_local_user(connection, login_name=args.login_name)
        if world_id is None or user_id is None:
            print("Claim refused: world or active local account not found.", file=sys.stderr)
            return 1
        if not args.apply:
            print("Preview (no changes made):")
            print(f"  world_id: {world_id}")
            print(f"  user_id: {user_id}")
            print("  Re-run with --apply to make this account the world's owner.")
            return 0
        try:
            result = claim_world(connection, world_id=world_id, user_id=user_id)
        except WorldAlreadyClaimedError as exc:
            print(f"Claim refused: {exc}", file=sys.stderr)
            return 1
    print(f"world_id: {result.world_id}")
    print(f"user_id: {result.user_id}")
    print("Claimed: the account now owns the world.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-unowned", action="store_true")
    parser.add_argument("--world-slug")
    parser.add_argument("--login-name")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    engine = create_engine(_database_url())
    try:
        return _run(engine, args)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
