"""GM-facing provisioning CLI for the FoundryVTT adapter (Phase 11 workstream 7,
`foundry-module/`).

There is no portal UI yet (Phase 13 is not started) to drive the three
OIDC-authenticated management endpoints a GM needs before a Foundry world can
connect: `register_external_system`, `issue_foundry_system_key`, and
`link_foundry_identity` (`dnd_ai.commands.integration`, all gated on
`canon.edit`/`access.manage` per `dnd_ai.api.integration`'s own module
docstring). This script is that missing "explicit GM setup/linking flow" —
a thin HTTP client, never a database client (CLAUDE.md rule 3: "Clients never
write directly to the database"): every subcommand below is a plain
`httpx` call against the real application API, authenticated with an
OIDC bearer token the GM already has from the platform's identity provider
(obtaining that token is existing Phase 10 OIDC infrastructure, out of
scope here).

Deliberately never calls the `FoundrySystem` scheme this script exists to
provision — that credential is what `foundry-module/` itself
authenticates with once configured; this script only ever authenticates
as the human GM.

`issue-key` requires `--foundry-user-id` and binds the minted credential
to whatever platform user that Foundry id is already linked to
(`link-identity` must run first) — the second Phase 11 workstream 2
security correction: a `FoundrySystem` credential now authenticates as
exactly the one principal it was bound to at issuance, never a caller-
selected identity (`dnd_ai.domain.access.resolve_foundry_system_
principal`'s own docstring has the full defect this closes). This MVP's
module only ever runs from the GM's own browser client
(`foundry-module/README.md`'s "Trust boundary" section), so in practice
that means: link the GM's own Foundry account, then issue a key bound to
it — not one per player.

Usage:
  uv run python scripts/foundry_provision.py register \\
      --api-base-url https://dnd-ai.example.com --campaign-id <uuid> \\
      --display-name "My Foundry World" [--system-type foundry] [--external-reference <ref>]
      # prints the new external_system_id

  uv run python scripts/foundry_provision.py link-identity \\
      --api-base-url https://dnd-ai.example.com --campaign-id <uuid> \\
      --external-system-id <uuid> --foundry-user-id <foundry-user-id> --user-id <platform-user-uuid>
      # maps one Foundry-side user id to one existing platform user. Run
      # this BEFORE issue-key: a credential can only be bound to a Foundry
      # user id that is already linked. This MVP's module only ever runs
      # from the GM's own client (foundry-module/README.md's "Trust
      # boundary" section) - link the GM's own Foundry account, not a
      # player's.

  uv run python scripts/foundry_provision.py issue-key \\
      --api-base-url https://dnd-ai.example.com --campaign-id <uuid> \\
      --external-system-id <uuid> --foundry-user-id <foundry-user-id>
      # mints (or rotates) the system credential, BOUND to the platform
      # user --foundry-user-id is already linked to (link-identity must
      # have been run for this exact foundry-user-id first), and prints
      # the raw key EXACTLY ONCE - paste it into the Foundry module's
      # connection settings immediately; it cannot be retrieved again,
      # only rotated (which also re-binds it, possibly to a different
      # principal if a different --foundry-user-id is given).

  uv run python scripts/foundry_provision.py provision \\
      --api-base-url https://dnd-ai.example.com --campaign-id <uuid> \\
      --display-name "My Foundry World" \\
      --foundry-user-id <gm-foundry-user-id> --user-id <gm-platform-user-uuid>
      # convenience: register + link-identity (for the one principal this
      # credential will authenticate as - the GM, for this MVP) +
      # issue-key, in one call, for first-time setup.

An OIDC bearer token is required for every subcommand: pass `--token`, or
set `DND_AI_OIDC_TOKEN` in the environment (preferred — keeps it out of
shell history and process listings). This script never prints, logs, or
otherwise persists the token anywhere; the one secret it does print
(a newly issued system credential) is printed exactly once, to stdout
only, with an explicit one-time warning, exactly as `issue_foundry_
system_key`'s own docstring documents for the raw key it returns.
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
# module's own connection-setup form and this CLI, since both mint or
# transmit the same long-lived `FoundrySystem` credential.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _validate_api_base_url(value: str) -> None:
    """Issue 2 (transport security): a `FoundrySystem` credential this
    script prints (issue-key/provision) or the OIDC bearer token it sends
    on every request must never be allowed to travel to a plain-HTTP,
    non-loopback `--api-base-url` — a network observer between this
    machine and that host could read either outright. Raises
    `ProvisioningError` with a message safe to print (never includes the
    token)."""
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
        f"loopback host ({', '.join(sorted(_LOOPBACK_HOSTS))}) — this script sends an OIDC "
        "bearer token, and issue-key/provision print a long-lived FoundrySystem credential, on "
        "every request; either would travel in the clear over a plain-HTTP connection to any "
        "other host."
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
            "Check that --token/DND_AI_OIDC_TOKEN is a current, valid OIDC bearer token."
        )
    if response.status_code == 403:
        raise ProvisioningError(
            f"Insufficient capability (403 {code}): {message} "
            "The authenticated user needs canon.edit (register) or access.manage "
            "(issue-key, link-identity) in this campaign."
        )
    if response.status_code == 404:
        raise ProvisioningError(
            f"Not found (404 {code}): {message} "
            "Check the campaign id and, for issue-key/link-identity, the external system id."
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


def issue_system_key(
    ctx: ProvisioningContext, *, external_system_id: uuid.UUID, foundry_user_id: str
) -> str:
    """Mints (or rotates) external_system_id's FoundrySystem credential,
    bound to the platform user foundry_user_id is already linked to
    (`link_foundry_identity` must have been called for this exact
    (external_system_id, foundry_user_id) pair first — a 400 `unlinked_
    foundry_principal` otherwise, per `_raise_for_envelope`'s general
    handling below)."""
    response = ctx.client.post(
        f"/campaigns/{ctx.campaign_id}/integration/external-systems/"
        f"{external_system_id}/foundry-system-key",
        headers=ctx.headers(),
        json={"foundry_user_id": foundry_user_id},
    )
    _raise_for_envelope(response)
    raw_key = response.json()["raw_key"]
    assert isinstance(raw_key, str)
    return raw_key


def link_foundry_identity(
    ctx: ProvisioningContext,
    *,
    external_system_id: uuid.UUID,
    foundry_user_id: str,
    user_id: uuid.UUID,
) -> uuid.UUID:
    response = ctx.client.post(
        f"/campaigns/{ctx.campaign_id}/integration/external-systems/"
        f"{external_system_id}/foundry-identities",
        headers=ctx.headers(),
        json={"foundry_user_id": foundry_user_id, "user_id": str(user_id)},
    )
    _raise_for_envelope(response)
    return uuid.UUID(response.json()["external_identity_id"])


def _resolve_token(cli_token: str | None) -> str:
    token = cli_token or os.environ.get(_TOKEN_ENV_VAR)
    if not token:
        raise ProvisioningError(
            f"No OIDC bearer token supplied — pass --token or set {_TOKEN_ENV_VAR}."
        )
    return token


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--campaign-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--token", default=None, help=f"OIDC bearer token; falls back to ${_TOKEN_ENV_VAR}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register", help="Register a new external system")
    register_parser.add_argument("--display-name", required=True)
    register_parser.add_argument("--system-type", default="foundry")
    register_parser.add_argument("--external-reference", default=None)

    issue_key_parser = subparsers.add_parser(
        "issue-key",
        help="Mint or rotate a system's FoundrySystem credential, bound to one platform user",
    )
    issue_key_parser.add_argument("--external-system-id", required=True, type=uuid.UUID)
    issue_key_parser.add_argument(
        "--foundry-user-id",
        required=True,
        help="Must already be linked via link-identity for this external-system-id",
    )

    link_parser = subparsers.add_parser(
        "link-identity", help="Map a Foundry-side user id to a platform user"
    )
    link_parser.add_argument("--external-system-id", required=True, type=uuid.UUID)
    link_parser.add_argument("--foundry-user-id", required=True)
    link_parser.add_argument("--user-id", required=True, type=uuid.UUID)

    provision_parser = subparsers.add_parser(
        "provision",
        help="Convenience: register + link-identity + issue-key, bound to one platform user",
    )
    provision_parser.add_argument("--display-name", required=True)
    provision_parser.add_argument("--system-type", default="foundry")
    provision_parser.add_argument("--external-reference", default=None)
    provision_parser.add_argument(
        "--foundry-user-id",
        required=True,
        help="The Foundry user the issued credential will authenticate as (this MVP's GM)",
    )
    provision_parser.add_argument(
        "--user-id",
        required=True,
        type=uuid.UUID,
        help="The existing platform user --foundry-user-id maps to",
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

        elif args.command == "issue-key":
            raw_key = issue_system_key(
                ctx,
                external_system_id=args.external_system_id,
                foundry_user_id=args.foundry_user_id,
            )
            print(
                "raw_key (shown ONCE - paste it into the Foundry module's connection "
                f"settings now, it cannot be retrieved again): {raw_key}"
            )
            print(f"Bound to the platform user linked to Foundry user {args.foundry_user_id!r}.")

        elif args.command == "link-identity":
            external_identity_id = link_foundry_identity(
                ctx,
                external_system_id=args.external_system_id,
                foundry_user_id=args.foundry_user_id,
                user_id=args.user_id,
            )
            print(f"external_identity_id: {external_identity_id}")

        elif args.command == "provision":
            external_system_id = register_external_system(
                ctx,
                system_type=args.system_type,
                display_name=args.display_name,
                external_reference=args.external_reference,
            )
            print(f"external_system_id: {external_system_id}")
            link_foundry_identity(
                ctx,
                external_system_id=external_system_id,
                foundry_user_id=args.foundry_user_id,
                user_id=args.user_id,
            )
            raw_key = issue_system_key(
                ctx,
                external_system_id=external_system_id,
                foundry_user_id=args.foundry_user_id,
            )
            print(
                "raw_key (shown ONCE - paste it into the Foundry module's connection "
                f"settings now, it cannot be retrieved again): {raw_key}"
            )
            print(
                f"Bound to the platform user (--user-id {args.user_id}) linked to Foundry "
                f"user {args.foundry_user_id!r} — this credential authenticates as that one "
                "principal only. This MVP's module runs only from the GM's own client, so "
                "that should be the GM's own Foundry account and platform user."
            )

    except ProvisioningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
