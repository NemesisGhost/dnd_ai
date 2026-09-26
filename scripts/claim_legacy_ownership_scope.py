"""One-time operator action: claim the legacy ownership scope the
world-ownership-scope migration (`107_world_ownership_scope`) created for
pre-existing worlds (ADR 0014, docs/architecture/DATABASE_MODEL.md §19.9).

That migration cannot safely guess which human should own worlds that
existed before the ownership-scope model did, so it backfills every
pre-existing `core.worlds` row onto one explicit legacy ownership scope
("Legacy Self-Hosted Worlds (unclaimed)") with **zero memberships**. This
script is how an operator assigns that scope's first `owner` — most
naturally, whoever `scripts/bootstrap_admin.py` created as the platform's
first administrator, though this script does not require that; any
existing `security.users` row may be named.

A no-op (refuses) if the legacy scope already has an active `owner` —
running this twice, or on a database that has none of the migration's
default-named legacy scope (e.g. a fresh install where every world was
created directly against its own scope), fails safely rather than adding a
second owner silently or guessing which scope was meant.

Usage:
  uv run python scripts/claim_legacy_ownership_scope.py --user-id <uuid>

The database URL is read from the environment only (`DND_AI_DATABASE_URL`
or the legacy `DATABASE_URL`), never accepted as a command-line argument —
matching `scripts/bootstrap_admin.py`'s own reasoning.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from sqlalchemy import create_engine, text

from dnd_ai.commands.ownership import add_ownership_scope_member

_LEGACY_OWNERSHIP_SCOPE_NAME = "Legacy Self-Hosted Worlds (unclaimed)"
_OWNER_ROLE_CODE = "owner"


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
    parser.add_argument("--user-id", required=True, type=uuid.UUID)
    args = parser.parse_args(argv)

    engine = create_engine(_database_url())
    try:
        with engine.begin() as connection:
            ownership_scope_id = connection.execute(
                text("SELECT ownership_scope_id FROM security.ownership_scopes WHERE name = :name"),
                {"name": _LEGACY_OWNERSHIP_SCOPE_NAME},
            ).scalar()
            if ownership_scope_id is None:
                print(
                    f"No ownership scope named {_LEGACY_OWNERSHIP_SCOPE_NAME!r} exists — "
                    "nothing to claim.",
                    file=sys.stderr,
                )
                return 1

            active_owner_count = connection.execute(
                text("""
                    SELECT count(*)
                    FROM security.ownership_scope_memberships osm
                    JOIN security.ownership_scope_roles r
                        ON r.ownership_scope_role_id = osm.ownership_scope_role_id
                    WHERE osm.ownership_scope_id = :scope
                      AND osm.ended_at IS NULL
                      AND r.code = :owner_role
                """),
                {"scope": ownership_scope_id, "owner_role": _OWNER_ROLE_CODE},
            ).scalar()
            if active_owner_count:
                print(
                    f"Ownership scope {ownership_scope_id} already has an active owner — "
                    "refusing to add another via this one-time claim script.",
                    file=sys.stderr,
                )
                return 1

            result = add_ownership_scope_member(
                connection,
                ownership_scope_id=ownership_scope_id,
                user_id=args.user_id,
                role_code=_OWNER_ROLE_CODE,
                actor_user_id=args.user_id,
            )
    finally:
        engine.dispose()

    print(f"ownership_scope_id: {ownership_scope_id}")
    print(f"ownership_scope_membership_id: {result.ownership_scope_membership_id}")
    print(f"owner user_id: {args.user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
