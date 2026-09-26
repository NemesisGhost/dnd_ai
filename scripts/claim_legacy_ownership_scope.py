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

Delegates the actual claim to `dnd_ai.commands.ownership.
claim_unclaimed_ownership_scope`, which refuses unconditionally once the
target scope has even one membership row of any status (active, revoked,
or otherwise) — running this twice, or on a database that has none of the
migration's default-named legacy scope (e.g. a fresh install where every
world was created directly against its own scope), fails safely rather
than adding a second owner silently or guessing which scope was meant.
That command is a narrow, unauthorized bootstrap path used *only* for a
scope nobody has ever administered — it is not available for, and cannot
be reused against, a scope that already has an owner (ordinary membership
changes go through `add_ownership_scope_member`/`remove_ownership_scope_
member`, which require an already-authorized owner to call).

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

from dnd_ai.commands.ownership import (
    AlreadyClaimedOwnershipScopeError,
    claim_unclaimed_ownership_scope,
)

_LEGACY_OWNERSHIP_SCOPE_NAME = "Legacy Self-Hosted Worlds (unclaimed)"


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

            try:
                result = claim_unclaimed_ownership_scope(
                    connection,
                    ownership_scope_id=ownership_scope_id,
                    user_id=args.user_id,
                )
            except AlreadyClaimedOwnershipScopeError as exc:
                print(
                    f"Ownership scope {ownership_scope_id} already has membership history — "
                    f"refusing to claim it via this one-time bootstrap script ({exc}).",
                    file=sys.stderr,
                )
                return 1
    finally:
        engine.dispose()

    print(f"ownership_scope_id: {ownership_scope_id}")
    print(f"ownership_scope_membership_id: {result.ownership_scope_membership_id}")
    print(f"owner user_id: {args.user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
