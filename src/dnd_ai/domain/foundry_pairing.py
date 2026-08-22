"""Foundry pairing scope vocabulary (docs/PLAN.md §23.5, Phase 11R
workstream D).

`FOUNDRY_SCOPES` is the single Python-side definition of the closed,
narrow initial scope set §23.5 describes ("Initial Foundry scopes remain
closed and narrow: encounter/current-state reads, synchronization status
reads, combat synchronization, character-state synchronization, and only
the location/state reads required by the module"). `database/migrations/
versions/100_foundry_pairing.py`'s `ck_foundry_connections_granted_scopes_
closed`/`ck_foundry_pairing_codes_requested_scopes_closed` CHECK
constraints mirror this exact set in SQL — the two must be kept in sync by
hand (the same relationship every other Python-closed-set-mirrored-by-a-
SQL-CHECK in this codebase already has, e.g. `ai.proposed_changes.
proposal_kind`); a scope added to one without the other either can never be
granted (Python rejects it first) or is silently unenforceable at the
database layer (SQL would accept it while Python never offers it) —
`tests/database/test_foundry_pairing_commands.py` proves every code this
module allows an actual `INSERT`/`UPDATE` to succeed for, closing that gap.

`resolve_foundry_access_principal` (Phase 11R workstream C) is this
module's other half: the read-only counterpart to `dnd_ai.commands.
foundry_pairing.exchange_foundry_device_credential` that authenticates an
already-issued `security.foundry_access_tokens` bearer value on every
ordinary adapter request, the same role `dnd_ai.domain.access.
resolve_foundry_system_principal` plays for the legacy shared credential.
Lives here rather than in `dnd_ai.domain.access` because it is pairing-
schema-specific — `dnd_ai.domain.access` has no dependency on `security.
foundry_*` and this module keeps that boundary rather than growing
`access.py` for every new credential type; `dnd_ai.api.auth` imports both
resolvers side by side.
"""

from sqlalchemy import Connection, text

from .access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from .credentials import hash_opaque_secret

FOUNDRY_SCOPES = frozenset(
    {
        "encounter_read",
        "sync_status_read",
        "combat_sync",
        "character_state_sync",
        "location_read",
    }
)


class InvalidFoundryScopeError(ValueError):
    """Raised when a caller-supplied scope list names something outside
    `FOUNDRY_SCOPES` or is empty — checked in Python before any database
    round-trip, rather than left to surface as an opaque CHECK-constraint
    violation (`ck_foundry_connections_granted_scopes_closed`/`ck_foundry_
    pairing_codes_requested_scopes_closed`)."""


def validate_foundry_scopes(scopes: frozenset[str] | set[str] | list[str]) -> tuple[str, ...]:
    """Rejects an empty scope list or one naming anything outside
    `FOUNDRY_SCOPES`, and returns a deterministically ordered tuple
    (sorted) — so two calls requesting the same *set* of scopes in a
    different order still produce identical, comparable rows rather than
    two array values PostgreSQL's `<@`/`=` would treat as unequal only by
    ordering accident."""
    scope_set = frozenset(scopes)
    if not scope_set:
        raise InvalidFoundryScopeError("at least one scope must be requested")
    unknown = scope_set - FOUNDRY_SCOPES
    if unknown:
        raise InvalidFoundryScopeError(
            f"unknown Foundry scope(s): {sorted(unknown)!r} — allowed: {sorted(FOUNDRY_SCOPES)!r}"
        )
    return tuple(sorted(scope_set))


def resolve_foundry_access_principal(
    connection: Connection, *, raw_access_token: str
) -> AuthenticatedPrincipal | None:
    """Authenticates a Foundry-adapter request bearing `Authorization:
    FoundryAccess <raw_access_token>` and resolves it to a full
    `AuthenticatedPrincipal` — the paired-device counterpart to `dnd_ai.
    domain.access.resolve_foundry_system_principal`, called by `dnd_ai.
    api.auth.get_authenticated_user_id` so every route already wired to
    that one dependency becomes reachable by a paired Foundry client, under
    the same `require_campaign_capability` authorization every other
    caller goes through (once that function's `allow_foundry_access` gate
    is opted into — Phase 11R workstream F).

    Read-only and revalidates fresh on every call — this is the same
    "revalidation, not caching" contract `dnd_ai.commands.foundry_pairing.
    exchange_foundry_device_credential`'s own docstring establishes for
    token issuance, applied here to token *use*: a revoked connection,
    revoked device, or deactivated user takes effect on this credential's
    very next request, since nothing about a prior successful resolution is
    ever cached or trusted here. Unlike `exchange_foundry_device_
    credential`, this function does **not** re-check the bound user's
    active campaign membership — `dnd_ai.api.access.require_campaign_
    capability`'s own `resolve_access_context` call already performs that
    exact check for every principal type uniformly (OIDC, local-session,
    and Foundry alike), so duplicating it here would only re-run the same
    query for no additional protection. It also never bumps `last_used_at`
    on the token or device row — the identical policy `dnd_ai.api.auth`'s
    own module docstring already states for OIDC ("turning every
    authenticated request into an implicit write... [is] unnecessary write
    load for a bare verification dependency"); `exchange_foundry_device_
    credential` is the (far lower-frequency) place device `last_used_at` is
    actually recorded.

    Returns `None`, uniformly, for every failure mode — unknown token,
    revoked or expired token, revoked or expired device (device `revoked_
    at` is an *effective revocation time*, not a boolean flag, identical to
    `exchange_foundry_device_credential`'s own check — a device mid-
    rotation's bounded overlap window must keep authenticating), revoked
    connection, or an inactive bound user — deliberately without
    distinguishing which, the same fail-closed, non-disclosing contract
    every other principal resolver in this codebase already establishes.

    Also selects `fc.granted_scopes` and carries it onto the returned
    principal's own `foundry_scopes` — the High-severity fix for scopes
    being persisted at pairing time but never actually enforced. Selected
    fresh on every call, from the connection row itself, never from any
    snapshot the access token or device might carry — a scope revoked from
    the connection (e.g. by re-pairing with a narrower `requested_scopes`
    set, which upserts `granted_scopes` in place) therefore takes effect
    starting with this credential's very next request, even though the
    presented access token itself is untouched and still unexpired. This is
    the same "revalidation, not caching" principle this function's own
    docstring already establishes for every other field — scope is not
    special-cased or weakened relative to them."""
    token_hash = hash_opaque_secret(raw_access_token)
    row = (
        connection.execute(
            text("""
                SELECT fc.user_id, fc.campaign_id, fc.external_system_id, es.world_id,
                       fc.foundry_connection_id, fd.foundry_device_id, fc.granted_scopes
                FROM security.foundry_access_tokens fat
                JOIN security.foundry_devices fd ON fd.foundry_device_id = fat.foundry_device_id
                JOIN security.foundry_connections fc
                  ON fc.foundry_connection_id = fd.foundry_connection_id
                JOIN integration.external_systems es
                  ON es.external_system_id = fc.external_system_id
                JOIN security.users u ON u.user_id = fc.user_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE fat.token_hash = :hash
                  AND fat.revoked_at IS NULL
                  AND fat.expires_at > now()
                  AND (fd.revoked_at IS NULL OR fd.revoked_at > now())
                  AND fd.expires_at > now()
                  AND fc.revoked_at IS NULL
                  AND ls.code = 'active'
            """),
            {"hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return AuthenticatedPrincipal(
        user_id=row["user_id"],
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=row["external_system_id"],
        foundry_world_id=row["world_id"],
        campaign_id=row["campaign_id"],
        foundry_connection_id=row["foundry_connection_id"],
        foundry_device_id=row["foundry_device_id"],
        foundry_scopes=frozenset(row["granted_scopes"]),
    )
