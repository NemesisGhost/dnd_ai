"""One-time initial-administrator bootstrap CLI (docs/PLAN.md §23.1, Phase
11R workstream A).

Unlike `scripts/foundry_provision.py`, this is deliberately a **database**
client, not an HTTP client — `dnd_ai.commands.local_auth.
bootstrap_initial_admin` is never exposed over HTTP at all (there is no
`dnd_ai.api.local_auth` route for it) and is explicitly meant to run
"never over HTTP," the same posture `security.timeline_bootstrap_grants`'
own migration comment already establishes for that table's analogous
first-campaign entitlement. There is no OIDC/local-session credential to
authenticate this operation with in the first place — it exists precisely
to create the platform's very first account, before any credential of any
kind can log in.

Connects using `DND_AI_DATABASE_URL` (or the legacy unprefixed
`DATABASE_URL`, matching `dnd_ai.config.Settings`'s own precedence) —
never a hardcoded connection string. Refuses to run unless
`security.users` is completely empty (`bootstrap_initial_admin`'s own
fail-closed check, re-verified server-side inside the same transaction,
not merely trusted from this script's own pre-check).

Usage:
  uv run python scripts/bootstrap_admin.py \\
      --login-name admin --display-name "Platform Administrator" \\
      [--email admin@example.com]
      # prints the new user id and a one-time activation token/link the
      # very first administrator uses to choose their own password
      # (POST /auth/activate) — paste it somewhere the administrator can
      # retrieve it; it is never printed, logged, or retrievable again.

The database URL is read from the environment only (`DND_AI_DATABASE_URL`
or `DATABASE_URL`), never accepted as a command-line argument — a
connection string can embed a password, and command-line arguments are
routinely visible in process listings and shell history on a shared host.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine

from dnd_ai.commands.local_auth import AlreadyBootstrappedError, bootstrap_initial_admin


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
    parser.add_argument("--login-name", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--email", default=None)
    args = parser.parse_args(argv)

    engine = create_engine(_database_url())
    try:
        try:
            result = bootstrap_initial_admin(
                engine,
                login_name=args.login_name,
                display_name=args.display_name,
                email=args.email,
            )
        except AlreadyBootstrappedError as exc:
            print(f"Bootstrap refused: {exc.safe_message}", file=sys.stderr)
            return 1
    finally:
        engine.dispose()

    print(f"user_id: {result.user_id}")
    print(f"login_name: {result.login_name}")
    print(f"activation_token_expires_at: {result.expires_at.isoformat()}")
    print()
    print("ONE-TIME ACTIVATION TOKEN (never shown again — record it now):")
    print(result.raw_token)
    print()
    print(
        "Have the administrator submit this token and their chosen password to "
        "POST /auth/activate to complete setup."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
