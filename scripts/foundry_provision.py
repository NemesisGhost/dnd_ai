"""Provisioning CLI for the FoundryVTT adapter (Phase 11 workstream 7,
`foundry-module/`; converted to per-device pairing by Phase 11R workstream
I, docs/PLAN.md §23.5/Workstream 11R item 6).

There is no portal UI yet (Phase 13 is not started) to drive the
authenticated management endpoints an operator needs before a Foundry world
can connect, so this script is a thin HTTP client standing in for it — never
a database client (CLAUDE.md rule 3: "Clients never write directly to the
database"): every subcommand below is a plain `httpx` call against the real
application API, authenticated with a bearer token the operator already has
(an OIDC token from the platform's identity provider, or a local-account
session token — either works, since every route here authenticates through
the same `get_authenticated_user_id` chain as any other API caller;
obtaining either credential is out of scope here).

This script issues no credential of its own and never did — it is now a
diagnostic/admin client over the same public pairing API
`foundry-module/scripts/pairing.mjs` uses (Workstream 11R item 6's own
wording): `register` creates the Foundry world's `external_system_id`
record, and `pairing-code` mints a short-lived, single-use code that any
campaign member (not only a GM) redeems from inside the Foundry module
itself (`consumeFoundryPairingCode`) to pair their own device. The device's
own credential and access token are minted directly by `POST /foundry/pair`
inside the Foundry client, never routed through this script, so there is no
long-lived secret for this CLI to ever hold or print.

The superseded `FoundrySystem` shared-credential subcommands
(`issue-key`/`link-identity`/`provision`) that used to live here are
removed, not merely deprecated — Workstream 11R item 6 requires the retained
CLI to "not... issue the superseded credential." A deployment still
operating a pre-Workstream-11R `FoundrySystem` integration administers it,
for the remainder of its short compatibility window, with a direct
authenticated call against `dnd_ai.api.integration`'s existing
`issue_foundry_system_key`/`link_foundry_identity` endpoints (unchanged by
this workstream) rather than through this script — see "Legacy transition"
below.

Usage:
  uv run python scripts/foundry_provision.py register \\
      --api-base-url https://dnd-ai.example.com --campaign-id <uuid> \\
      --display-name "My Foundry World" [--system-type foundry] [--external-reference <ref>]
      # prints the new external_system_id

  uv run python scripts/foundry_provision.py pairing-code \\
      --api-base-url https://dnd-ai.example.com --campaign-id <uuid> \\
      --external-system-id <uuid> --scope combat_sync --scope character_state_sync
      # mints a short-lived (5-10 minute), single-use pairing code for the
      # CALLER's own platform account (whoever --token/DND_AI_OIDC_TOKEN
      # authenticates as - not necessarily the GM: any campaign member with
      # campaign.view can run this for themselves). Prints the raw code
      # EXACTLY ONCE - enter it into the Foundry module's "D&D AI Pairing"
      # settings menu within the printed expiry; it cannot be retrieved
      # again, only reissued as a new code.

A bearer token is required for every subcommand: pass `--token`, or set
`DND_AI_OIDC_TOKEN` in the environment (preferred — keeps it out of shell
history and process listings; the variable name predates local-account
sessions but is unchanged so existing scripts/CI keep working — it accepts
either token type). This script never prints, logs, or otherwise persists
the token anywhere; the one secret it does print (a newly minted pairing
code) is printed exactly once, to stdout only, with an explicit one-time
warning.

## Legacy transition

For a deployment still using the superseded `FoundrySystem` shared
credential, move it to per-device pairing without downtime, in this order
(docs/PLAN.md Workstream 11R item 7):

1. **Deploy** the Phase 11R-updated `foundry-module/` (minimum FoundryVTT
   13) to every client that will need it, alongside the backend's Phase 11R
   migrations — the backend accepts both `FoundrySystem` and `FoundryAccess`
   credentials simultaneously throughout this transition
   (`allow_foundry_system`/`allow_foundry_access` on every affected route),
   so nothing breaks mid-rollout.
2. **Pair** every user who needs Foundry access: `register` (if the world
   isn't already registered) + `pairing-code` per user, then each user
   redeems their own code from inside the Foundry module. Multiple devices
   per user just means running `pairing-code` again and pairing again.
3. **Revoke** the old `FoundrySystem` credential once every client that used
   it has successfully paired and the sync panel is confirmed working end to
   end from the new credential — the deployment operator retires it by no
   longer configuring any client with it (rotating it via a direct API call
   is not itself a revocation; see the module docstring above for why this
   script no longer offers that call at all).
4. **Remove** the backend's `FoundrySystem` verification path
   (`allow_foundry_system`, `resolve_foundry_system_principal`, and the
   `integration.issue_foundry_system_key`/`.link_foundry_identity` endpoints)
   in a future phase once every deployment has completed step 3 — not yet
   done here, since CLAUDE.md rule 2 requires every AI-suggested world
   change to go through validation, and removing a still-relied-upon
   authentication path is exactly the kind of forward-only, no-silent-
   breakage decision this repository's Phase 11R boundaries leave to an
   explicit follow-up rather than making it unilaterally now.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

_TOKEN_ENV_VAR = "DND_AI_OIDC_TOKEN"

# Recognized loopback development hosts only — never a private/LAN address
# (10.0.0.0/8, 192.168.0.0/16, 172.16.0.0/12, ...), which is not
# automatically safe (a shared network can still observe plaintext traffic
# to it). Mirrors foundry-module/scripts/settings.mjs's identical
# `LOOPBACK_HOSTS`/`isLoopbackHost` — the same policy enforced on both the
# module's own pairing form and this CLI, since this script's bearer token
# and the pairing code it prints, and the module's own pairing code/device
# credential/access token, are all equally exposed by a plain-HTTP
# connection.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _validate_api_base_url(value: str) -> None:
    """Issue 2 (transport security): the bearer token this script sends on
    every request, and the pairing code `pairing-code` prints, must never be
    allowed to travel to a plain-HTTP, non-loopback `--api-base-url` — a
    network observer between this machine and that host could read either
    outright. Raises `ProvisioningError` with a message safe to print
    (never includes the token)."""
    parsed = urlsplit(value)
    if parsed.scheme == "https":
        return
    if (
        parsed.scheme == "http"
        and parsed.hostname is not None
        and parsed.hostname.lower() in _LOOPBACK_HOSTS
    ):
        return
    raise ProvisioningError(
        f"--api-base-url {value!r} must use https://, or http:// only for a recognized "
        f"loopback host ({', '.join(sorted(_LOOPBACK_HOSTS))}) — this script sends a bearer "
        "token on every request, and pairing-code prints a secret, in the clear, over a "
        "plain-HTTP connection to any other host."
    )


class ProvisioningError(Exception):
    """Raised for any request this CLI cannot complete. `str(self)` is
    always already safe to print to the operator — built from the
    server's own `error.code`/`error.message` envelope
    (`dnd_ai.api.errors`), never a raw traceback, and never includes the
    bearer token."""


@dataclass(frozen=True)
class ProvisioningContext:
    """`client` is an already-configured `httpx.Client` (real usage:
    `httpx.Client(base_url=api_base_url)`, built once in `main()`) —
    injected rather than each function calling the module-level
    `httpx.post()` against a hardcoded base URL, specifically so
    `tests/database/test_foundry_provision.py` can pass a
    `fastapi.testclient.TestClient` instead (itself an `httpx.Client`
    subclass with the identical `.post()` interface, bound to the real
    FastAPI app + a real PostgreSQL database rather than a live network
    server) and exercise every subcommand's real HTTP behavior without
    spawning one."""

    client: httpx.Client
    campaign_id: uuid.UUID
    token: str

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}


def _raise_for_envelope(response: httpx.Response) -> None:
    """Turns a non-2xx response into a `ProvisioningError` whose message
    is specific about *why* — distinguishing an invalid/expired
    credential (401), insufficient capability (403), and an unresolvable
    reference such as a nonexistent campaign or external system (404) —
    rather than one generic "request failed" for every case, per this
    module's own "surface clear errors" requirement."""
    if response.is_success:
        return
    try:
        envelope = response.json().get("error", {})
    except ValueError:
        envelope = {}
    code = envelope.get("code", "unknown_error")
    message = envelope.get("message", f"Request failed with status {response.status_code}.")

    if response.status_code == 401:
        raise ProvisioningError(
            f"Authentication rejected (401 {code}): {message} "
            "Check that --token/DND_AI_OIDC_TOKEN is a current, valid bearer token "
            "(OIDC or local-account session)."
        )
    if response.status_code == 403:
        raise ProvisioningError(
            f"Insufficient capability (403 {code}): {message} "
            "The authenticated user needs campaign.view (pairing-code) or canon.edit "
            "(register) in this campaign, depending on the subcommand."
        )
    if response.status_code == 404:
        raise ProvisioningError(
            f"Not found (404 {code}): {message} "
            "Check the campaign id and, for pairing-code, the external system id."
        )
    raise ProvisioningError(f"Request failed ({response.status_code} {code}): {message}")


def register_external_system(
    ctx: ProvisioningContext,
    *,
    system_type: str,
    display_name: str,
    external_reference: str | None = None,
) -> uuid.UUID:
    response = ctx.client.post(
        f"/campaigns/{ctx.campaign_id}/integration/external-systems",
        headers=ctx.headers(),
        json={
            "system_type": system_type,
            "display_name": display_name,
            "external_reference": external_reference,
        },
    )
    _raise_for_envelope(response)
    return uuid.UUID(response.json()["external_system_id"])


def create_pairing_code(
    ctx: ProvisioningContext, *, external_system_id: uuid.UUID, requested_scopes: list[str]
) -> tuple[str, list[str], str]:
    """`POST /campaigns/{campaign_id}/foundry/pairing-codes` — mints a
    pairing code for the platform user `ctx.token` authenticates as (any
    active campaign member with `campaign.view`, not only the GM; see
    `dnd_ai.api.foundry_pairing.create_foundry_pairing_code_endpoint`'s own
    docstring). Returns `(raw_code, requested_scopes, expires_at)`; the raw
    code is shown to the caller exactly once and never persisted or logged
    by this script."""
    response = ctx.client.post(
        f"/campaigns/{ctx.campaign_id}/foundry/pairing-codes",
        headers=ctx.headers(),
        json={"external_system_id": str(external_system_id), "requested_scopes": requested_scopes},
    )
    _raise_for_envelope(response)
    body = response.json()
    raw_code = body["raw_code"]
    assert isinstance(raw_code, str)
    return raw_code, list(body["requested_scopes"]), body["expires_at"]


def _resolve_token(cli_token: str | None) -> str:
    token = cli_token or os.environ.get(_TOKEN_ENV_VAR)
    if not token:
        raise ProvisioningError(f"No bearer token supplied — pass --token or set {_TOKEN_ENV_VAR}.")
    return token


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--campaign-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--token",
        default=None,
        help=f"Bearer token (OIDC or local-account session); falls back to ${_TOKEN_ENV_VAR}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register", help="Register a new external system")
    register_parser.add_argument("--display-name", required=True)
    register_parser.add_argument("--system-type", default="foundry")
    register_parser.add_argument("--external-reference", default=None)

    pairing_code_parser = subparsers.add_parser(
        "pairing-code",
        help="Mint a pairing code for the caller's own account (current, recommended)",
    )
    pairing_code_parser.add_argument("--external-system-id", required=True, type=uuid.UUID)
    pairing_code_parser.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        required=True,
        help="A requested Foundry scope; repeat for more than one (e.g. --scope combat_sync "
        "--scope character_state_sync)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        _validate_api_base_url(args.api_base_url)
        with httpx.Client(base_url=args.api_base_url) as client:
            ctx = ProvisioningContext(
                client=client,
                campaign_id=args.campaign_id,
                token=_resolve_token(args.token),
            )
            return _run_command(args, ctx)
    except ProvisioningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run_command(args: argparse.Namespace, ctx: ProvisioningContext) -> int:
    try:
        if args.command == "register":
            external_system_id = register_external_system(
                ctx,
                system_type=args.system_type,
                display_name=args.display_name,
                external_reference=args.external_reference,
            )
            print(f"external_system_id: {external_system_id}")

        elif args.command == "pairing-code":
            raw_code, granted_scopes, expires_at = create_pairing_code(
                ctx, external_system_id=args.external_system_id, requested_scopes=args.scopes
            )
            print(
                'raw_code (shown ONCE - enter it into the Foundry module\'s "D&D AI Pairing" '
                f"settings menu before it expires, it cannot be retrieved again): {raw_code}"
            )
            print(f"scopes: {', '.join(granted_scopes)}")
            print(f"expires_at: {expires_at}")

    except ProvisioningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
