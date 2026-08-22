"""Effective access resolution (docs/architecture/DATABASE_MODEL.md §19.7,
docs/PLAN.md §23.3).

Centralizes campaign membership, role-derived capability, character
relationship-derived capability, and typed resource-grant resolution into
one `AccessContext` so every command and query service authorizes the same
way instead of re-deriving `security.*` joins independently
(docs/architecture/SYSTEM_ARCHITECTURE.md §5.4 — no HTTP or framework types
here). Read-only: this module never mutates state.

`AuthenticatedPrincipal` (Phase 11 workstream 2, twice corrected) is the
other half of this module's contract: `resolve_access_context` still
resolves an `AccessContext` purely from a bare `user_id`, but a caller
authenticated via a delegated adapter credential
(`FOUNDRY_SYSTEM_AUTH_METHOD`) carries more than a `user_id` — it carries
*which* `integration.external_systems` row, and therefore which
`core.worlds` row, actually vouched for that request, and that scope must
be enforced on every campaign authorization performed for it, not just the
linked user's own membership graph. The first correction pass closed that
world/campaign scope gap; a second, more severe pass closed a Critical
defect in *how* `user_id` itself was resolved — a caller-supplied Foundry
identity header, combined with a credential Foundry distributes to every
connected client regardless of `config: false`, could authenticate as any
linked user merely by naming them. See `AuthenticatedPrincipal`'s and
`resolve_foundry_system_principal`'s own docstrings for the full account of
both defects and their fixes. `FOUNDRY_SYSTEM_AUTH_METHOD` itself is
retired as of a subsequent Workstream 11R High-severity correction —
`resolve_foundry_system_principal` is never called from `dnd_ai.api.auth.
get_authenticated_user_id` any more, so no principal of this type can
reach `dnd_ai.api.access.require_campaign_capability` from a real request
(that function's own `allow_foundry_system` gate and world check, which
used to enforce the campaign/world scope described above, were removed
along with it — its sibling `allow_foundry_access`/`foundry_scope` gate
now serves the equivalent role for `FOUNDRY_ACCESS_AUTH_METHOD`).
`assert_foundry_system_matches` remains, and still handles both auth
methods uniformly, for the sibling per-request check a route performs
when its own path/body names an `external_system_id` directly.

Deferred to later Phase 10 workstreams, per §19.7's own step list:

- step 6, party/public knowledge-derived access — depends on the knowledge
  domain's own visibility rules (docs/architecture/DATABASE_MODEL.md §14)
  and is resolved by the query layer that already has a character
  perspective, not duplicated here;
- step 8, filtering rows/fields/search/AI context — that is what callers do
  *with* an `AccessContext`, not part of resolving one;
- step 9, auditing sensitive reads — only the caller knows which read was
  sensitive; this module is called far too often (every query, every
  command) to be the right place to decide that.
"""

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from .errors import DomainAuthorizationError

_TARGET_COLUMNS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)

_GrantKey = tuple[str, uuid.UUID]


def _as_uuid(value: object) -> uuid.UUID:
    assert isinstance(value, uuid.UUID)
    return value


def _as_str(value: object) -> str:
    assert isinstance(value, str)
    return value


@dataclass(frozen=True)
class AccessContext:
    """A resolved snapshot of one user's effective access to one campaign
    timeline, per docs/architecture/DATABASE_MODEL.md §19.7 steps 1-7.

    Resolve fresh per request rather than caching across requests — roles,
    relationships, and grants can change between calls, and nothing here
    subscribes to invalidation.

    `principal`, when set, is the full `AuthenticatedPrincipal` this context
    was resolved for — `dnd_ai.api.access.require_campaign_capability`
    attaches it (via `dataclasses.replace`, since `resolve_access_context`
    itself only ever takes a bare `user_id`) once it has already used the
    principal to gate/scope the request, so route code with an
    `AccessContext` in hand can still recover *how* the caller
    authenticated — e.g. to call `assert_foundry_system_matches` against a
    request's own `external_system_id` — without threading a second
    parameter through every handler. `None` for an `AccessContext` obtained
    any other way (most directly, from `resolve_access_context` itself, or
    in a test that constructs one without going through the API-layer
    dependency).
    """

    user_id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID
    timeline_id: uuid.UUID
    role_capabilities: frozenset[str]
    character_capabilities: dict[uuid.UUID, frozenset[str]]
    grant_effects: dict[_GrantKey, dict[str, str]] = field(repr=False)
    principal: "AuthenticatedPrincipal | None" = None

    def has_capability(
        self,
        capability_code: str,
        *,
        character_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        knowledge_item_id: uuid.UUID | None = None,
        quest_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
    ) -> bool:
        """Deny-by-default: True only if a role, character relationship, or
        active `allow` resource grant supplies the capability, and no
        matching active `deny` resource grant overrides it (§19.6 — an
        explicit deny overrides an allow at the same or broader path).

        At most one resource-target keyword may be supplied — a caller
        checking a character-scoped capability passes `character_id`; one
        checking any other protected resource passes exactly one of the
        others. Passing none checks only role/character-relationship
        capabilities with no resource grant involved.
        """
        targets: dict[str, uuid.UUID | None] = {
            "character_id": character_id,
            "entity_id": entity_id,
            "knowledge_item_id": knowledge_item_id,
            "quest_id": quest_id,
            "session_id": session_id,
            "event_id": event_id,
        }
        supplied = [
            (field_name, value) for field_name, value in targets.items() if value is not None
        ]
        if len(supplied) > 1:
            raise ValueError("has_capability accepts at most one resource target")

        baseline = capability_code in self.role_capabilities
        if character_id is not None:
            baseline = baseline or capability_code in self.character_capabilities.get(
                character_id, frozenset()
            )

        if not supplied:
            return baseline

        field_name, target_id = supplied[0]
        effect = self.grant_effects.get((field_name, target_id), {}).get(capability_code)
        if effect == "deny":
            return False
        if effect == "allow":
            return True
        return baseline

    def resource_grant_targets(
        self, capability_code: str, field_name: str
    ) -> tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]:
        """The resource IDs of `field_name` (one of `_TARGET_COLUMNS`) for
        which an active, resolved resource grant sets `capability_code` to
        `deny`/`allow` respectively.

        `has_capability()` resolves deny-overrides-allow-overrides-baseline
        for one resource at a time — the right shape for a single-resource
        endpoint, but a *list* endpoint (many rows, one baseline capability
        check, individually-targetable resource grants layered on top) has
        no single resource to pass it. Calling `has_capability()` once per
        row would work but means re-deriving the same `grant_effects` scan
        per row; this instead exposes the two sets once, so a caller can
        push per-row visibility into a SQL `WHERE`/`CASE` (denied IDs
        excluded outright, allowed IDs included regardless of the row's own
        baseline) without loading unfiltered rows just to discard them
        after the fact. A row's own baseline — the role/character-
        relationship check alone, with no resource target — is still the
        caller's own responsibility, exactly as it is for `has_capability()`
        when no resource-target keyword is supplied.
        """
        if field_name not in _TARGET_COLUMNS:
            raise ValueError(f"{field_name!r} is not a resource-grant target column")
        denied = frozenset(
            target_id
            for (target_field, target_id), effects in self.grant_effects.items()
            if target_field == field_name and effects.get(capability_code) == "deny"
        )
        allowed = frozenset(
            target_id
            for (target_field, target_id), effects in self.grant_effects.items()
            if target_field == field_name and effects.get(capability_code) == "allow"
        )
        return denied, allowed


OIDC_AUTH_METHOD = "oidc"
FOUNDRY_SYSTEM_AUTH_METHOD = "foundry_system"
LOCAL_SESSION_AUTH_METHOD = "local_session"
FOUNDRY_ACCESS_AUTH_METHOD = "foundry_access"

# auth_methods that carry a foundry_external_system_id/foundry_world_id
# scope — both the legacy shared-secret credential and its Phase 11R
# paired-device replacement authenticate as one specific Foundry world,
# never a bare user_id alone. FOUNDRY_ACCESS_AUTH_METHOD additionally
# carries its own campaign_id (see AuthenticatedPrincipal's docstring) —
# a narrower, per-connection scope FOUNDRY_SYSTEM_AUTH_METHOD never had.
_FOUNDRY_SYSTEM_WORLD_AUTH_METHODS = frozenset(
    {FOUNDRY_SYSTEM_AUTH_METHOD, FOUNDRY_ACCESS_AUTH_METHOD}
)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Who is making this request, and how they authenticated — resolved
    once per request by `dnd_ai.api.auth.get_authenticated_user_id` and
    threaded through every downstream authorization/audit decision that
    needs to distinguish an OIDC end-user action from an adapter-delegated
    one, or scope a `FoundrySystem` credential to the world/system it
    actually authenticated as.

    Fixes a critical scope defect in the first cut of Phase 11 workstream 2:
    that version resolved a `FoundrySystem` credential straight down to a
    bare `security.users.user_id` — identical in shape to an OIDC-resolved
    one — and discarded which `integration.external_systems` row (and
    therefore which `core.worlds` row) the credential actually
    authenticated as. `require_campaign_capability` (`dnd_ai.api.access`)
    then had no way to tell a request authenticated by a Foundry adapter
    for world A apart from an ordinary OIDC request by the same linked
    user, so a valid world-A credential could authorize against any
    *other* campaign that same user happened to hold membership in
    (including a different world's campaign, or one reached only via
    `access.manage`-gated identity/credential-management routes), and
    nothing checked that a request's own path/body `external_system_id`
    (where one is supplied) matched the system that actually authenticated
    it. `resolve_access_context`'s campaign-membership/role/capability
    resolution is unaffected by this record's addition — it continues to
    resolve purely from `user_id` — but every caller that authorizes a
    *Foundry* principal specifically (originally `dnd_ai.api.access.
    require_campaign_capability`'s now-removed `allow_foundry_system` gate,
    still this module's own `assert_foundry_system_matches`) now has the
    fields it needs to bind that authorization to the credential's own
    system/world, not merely the linked user's overall membership graph.

    `user_id` is always the resolved `security.users` row — for OIDC, the
    identity itself; for `FOUNDRY_SYSTEM_AUTH_METHOD`, the *one* platform
    principal `issue_foundry_system_key` bound to this credential at
    issuance time (`integration.external_systems.
    system_key_principal_user_id`) — never a caller-selected identity. See
    `resolve_foundry_system_principal`'s own docstring for the second,
    more severe defect this field's resolution was corrected to close: the
    first cut of this design (Phase 11 workstream 2, migrations 089-091)
    still resolved `user_id` from a client-supplied `X-Foundry-User-Id`
    header against `security.external_identities` — a world-shared
    credential (Foundry distributes every world-scope `game.settings`
    value, `foundry-module/`'s own `systemCredential` included, to every
    connected client regardless of `config: false`) combined with a
    caller-chosen identity meant any connected player who extracted that
    shared credential could name the GM's own Foundry user id and
    authenticate as the GM. `foundry_claimed_actor_id` below is what
    replaced that header's role in authorization — nothing now, ever.

    `foundry_external_system_id`/`foundry_world_id` are populated if, and
    only if, `auth_method == FOUNDRY_SYSTEM_AUTH_METHOD` — enforced by
    `__post_init__` so no caller can construct a `FOUNDRY_SYSTEM_AUTH_METHOD`
    principal that silently carries no system/world to scope against, or an
    `OIDC_AUTH_METHOD` one that carries a stray one.

    `foundry_claimed_actor_id` is the client-supplied `X-Foundry-Actor-Id`
    header value (if any), carried forward *purely as untrusted metadata*
    for `audit.change_log.acting_foundry_actor_id` — never read by any
    authorization or identity-resolution logic anywhere in this codebase.
    `__post_init__` enforces the mirror-image rule from the pair above: an
    `OIDC_AUTH_METHOD` principal must never carry one (there is no
    "Foundry actor" concept for a request that didn't authenticate via a
    Foundry credential at all), and a `FOUNDRY_SYSTEM_AUTH_METHOD`
    principal may or may not (a Foundry client that sends no claimed actor
    is authenticated exactly the same as one that does — the field changes
    nothing about who `user_id` resolves to either way).

    `local_session_id` (Phase 11R workstream A/B) is the authenticating
    `security.browser_sessions.browser_session_id` row for a
    `LOCAL_SESSION_AUTH_METHOD` principal — set if, and only if,
    `auth_method == LOCAL_SESSION_AUTH_METHOD`, enforced by
    `__post_init__` the same way the Foundry pair above is. Carried through
    to `audit.change_log` (workstream G) and to the session-revocation
    check every downstream command performs — a session that is revoked or
    expires between issuance and use is rejected at resolution time
    (`dnd_ai.commands.local_auth.resolve_local_session_principal`), before
    this dataclass is even constructed, so its mere presence here already
    means "this specific session was valid as of this request."

    `FOUNDRY_ACCESS_AUTH_METHOD` (Phase 11R workstream C) is the paired-
    device replacement for `FOUNDRY_SYSTEM_AUTH_METHOD`, resolved by
    `dnd_ai.domain.foundry_pairing.resolve_foundry_access_principal` from
    an `Authorization: FoundryAccess <token>` header — see that function's
    own docstring for the full resolution/revalidation contract. It
    carries the same `foundry_external_system_id`/`foundry_world_id` pair
    `FOUNDRY_SYSTEM_AUTH_METHOD` does (both are Foundry-world-scoped
    credentials), plus fields that credential never had: `campaign_id`
    (the *one* campaign this connection was paired for — `security.
    foundry_connections.campaign_id`, required, non-`None`, and the only
    field of its kind on any principal type; every other method resolves
    campaign scope per-request from the URL instead), `foundry_connection_
    id`/`foundry_device_id` identifying exactly which paired connection and
    device authenticated, and `foundry_scopes` (below) naming what that
    connection may actually do. Where `FOUNDRY_SYSTEM_AUTH_METHOD` could
    authorize against *any* campaign in its bound world (checked by
    comparing `foundry_world_id` to the requested campaign's own world —
    a check `dnd_ai.api.access.require_campaign_capability`'s now-removed
    `allow_foundry_system` gate used to perform), `FOUNDRY_ACCESS_AUTH_
    METHOD` is exact-campaign-scoped from the moment it was paired — a
    strictly narrower authorization surface, enforced by that same
    function's `allow_foundry_access` gate comparing `campaign_id`
    directly rather than deriving a world and comparing that. There is no
    Foundry-device counterpart on this dataclass: a device credential's
    only valid action (obtaining a fresh access token, docs/PLAN.md §23.5
    step 6) is handled directly by `dnd_ai.commands.foundry_pairing.
    exchange_foundry_device_credential`, never through `get_authenticated_
    user_id`/this dataclass — introducing a principal type with exactly
    one single-purpose caller would be exactly the kind of speculative
    abstraction this codebase avoids; see that command's own docstring.

    `foundry_scopes` (High-severity finding: Foundry scopes were persisted
    on `security.foundry_connections.granted_scopes` but never read back
    onto the principal, so `dnd_ai.api.access.require_campaign_capability`
    had no way to enforce them — every `allow_foundry_access=True` route
    was reachable by any paired connection regardless of what scopes it was
    actually granted at pairing time) is populated if, and only if,
    `auth_method == FOUNDRY_ACCESS_AUTH_METHOD`, enforced by `__post_init__`
    exactly like the `campaign_id`/`foundry_connection_id`/`foundry_
    device_id` trio above — deliberately narrower than that trio's shared
    `_FOUNDRY_SYSTEM_WORLD_AUTH_METHODS` gate: a `FOUNDRY_SYSTEM_AUTH_
    METHOD` principal must never carry a scope set, so the legacy credential
    can never accidentally acquire scope-gated behavior merely by this
    field existing on the same dataclass. A frozenset, matching `role_
    capabilities`' own immutability — nothing downstream may mutate a
    resolved principal's own authorization. `dnd_ai.domain.foundry_pairing.
    resolve_foundry_access_principal` populates this from the connection's
    *current* `granted_scopes` on every single call (never cached, never
    frozen onto the access-token row itself) — see that function's own
    docstring for why this means revoking a scope from a connection takes
    effect on the very next request, even one presenting an access token
    that has not itself expired."""

    user_id: uuid.UUID
    auth_method: str
    foundry_external_system_id: uuid.UUID | None = None
    foundry_world_id: uuid.UUID | None = None
    foundry_claimed_actor_id: str | None = None
    local_session_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    foundry_connection_id: uuid.UUID | None = None
    foundry_device_id: uuid.UUID | None = None
    foundry_scopes: frozenset[str] | None = None

    def __post_init__(self) -> None:
        has_system_world_scope = self.auth_method in _FOUNDRY_SYSTEM_WORLD_AUTH_METHODS
        has_foundry_fields = (
            self.foundry_external_system_id is not None and self.foundry_world_id is not None
        )
        if has_system_world_scope != has_foundry_fields:
            raise ValueError(
                "foundry_external_system_id/foundry_world_id must be set if, and only if, "
                f"auth_method is one of {sorted(_FOUNDRY_SYSTEM_WORLD_AUTH_METHODS)!r} "
                f"(got auth_method={self.auth_method!r}, "
                f"foundry_external_system_id={self.foundry_external_system_id!r}, "
                f"foundry_world_id={self.foundry_world_id!r})"
            )
        if (
            self.auth_method != FOUNDRY_SYSTEM_AUTH_METHOD
            and self.foundry_claimed_actor_id is not None
        ):
            raise ValueError(
                "foundry_claimed_actor_id must be None unless "
                f"auth_method == {FOUNDRY_SYSTEM_AUTH_METHOD!r} "
                f"(got auth_method={self.auth_method!r}, "
                f"foundry_claimed_actor_id={self.foundry_claimed_actor_id!r})"
            )
        is_local_session = self.auth_method == LOCAL_SESSION_AUTH_METHOD
        has_local_session_id = self.local_session_id is not None
        if is_local_session != has_local_session_id:
            raise ValueError(
                "local_session_id must be set if, and only if, "
                f"auth_method == {LOCAL_SESSION_AUTH_METHOD!r} "
                f"(got auth_method={self.auth_method!r}, "
                f"local_session_id={self.local_session_id!r})"
            )
        is_foundry_access = self.auth_method == FOUNDRY_ACCESS_AUTH_METHOD
        has_connection_device = (
            self.foundry_connection_id is not None and self.foundry_device_id is not None
        )
        if is_foundry_access != has_connection_device:
            raise ValueError(
                "foundry_connection_id/foundry_device_id must be set if, and only if, "
                f"auth_method == {FOUNDRY_ACCESS_AUTH_METHOD!r} "
                f"(got auth_method={self.auth_method!r}, "
                f"foundry_connection_id={self.foundry_connection_id!r}, "
                f"foundry_device_id={self.foundry_device_id!r})"
            )
        if is_foundry_access != (self.campaign_id is not None):
            raise ValueError(
                "campaign_id must be set if, and only if, "
                f"auth_method == {FOUNDRY_ACCESS_AUTH_METHOD!r} "
                f"(got auth_method={self.auth_method!r}, campaign_id={self.campaign_id!r})"
            )
        if is_foundry_access != (self.foundry_scopes is not None):
            raise ValueError(
                "foundry_scopes must be set if, and only if, "
                f"auth_method == {FOUNDRY_ACCESS_AUTH_METHOD!r} "
                f"(got auth_method={self.auth_method!r}, foundry_scopes={self.foundry_scopes!r}) "
                "— a FOUNDRY_SYSTEM_AUTH_METHOD principal must never carry a scope set, so the "
                "legacy credential can never acquire scope-gated behavior by accident"
            )
        if is_foundry_access and not self.foundry_scopes:
            raise ValueError(
                "foundry_scopes must be non-empty for a FOUNDRY_ACCESS_AUTH_METHOD principal "
                f"(got foundry_scopes={self.foundry_scopes!r})"
            )


class ForeignExternalSystemError(DomainAuthorizationError):
    """Raised by `assert_foundry_system_matches()` when a `FoundrySystem`-
    authenticated request names a path or body `external_system_id` other
    than the one that actually authenticated it — e.g. system A's
    credential submitting a combat-sync payload whose own
    `external_system_id` names system B. A fixed, non-disclosing 404 (via
    `DomainAuthorizationError`), the same "confirming this belongs to
    someone else is itself a disclosure" reasoning `dnd_ai.commands.
    integration.ExternalSystemNotFoundError` already applies to the
    cross-world case — this is that same family of check, scoped to
    "does the credential match the system it claims to act for," not "does
    the system belong to the caller's authorized world" (both must hold;
    see `dnd_ai.api.access.require_campaign_capability`'s own world check
    for the latter)."""


def assert_foundry_system_matches(
    principal: AuthenticatedPrincipal, external_system_id: uuid.UUID
) -> None:
    """Raises `ForeignExternalSystemError` if `principal` authenticated as a
    Foundry system other than `external_system_id` — a no-op for an OIDC or
    local-session principal (neither has a system of its own to compare
    against) and for a Foundry principal whose own `foundry_external_
    system_id` already matches. Applies identically to both `FOUNDRY_
    SYSTEM_AUTH_METHOD` (the legacy shared credential) and `FOUNDRY_
    ACCESS_AUTH_METHOD` (Phase 11R workstream C's paired-device
    replacement) — both carry the same `foundry_external_system_id` field,
    and both are exactly as able to name a foreign system in a request
    body/path without this check. Every adapter-facing route that accepts
    an `external_system_id` from the request itself (a path parameter or,
    for `apply_foundry_combat_sync_endpoint`, a body field) must call this
    once `principal` is known — without it, a valid credential for system A
    could name system B's `external_system_id` in the request and act as
    system B merely because both happen to resolve to campaigns the same
    linked user can reach."""
    if (
        principal.auth_method in _FOUNDRY_SYSTEM_WORLD_AUTH_METHODS
        and principal.foundry_external_system_id != external_system_id
    ):
        raise ForeignExternalSystemError(
            f"{principal.auth_method} credential authenticated as external system "
            f"{principal.foundry_external_system_id}, not {external_system_id}"
        )


def resolve_user_by_external_identity(
    connection: Connection, *, issuer: str, subject: str
) -> uuid.UUID | None:
    """Resolve an OIDC (issuer, subject) pair to its linked `security.users`
    row (docs/architecture/DATABASE_MODEL.md §19.1 step 1). Returns None for
    an unknown or revoked identity, or one linked to a user whose own
    lifecycle status code is not `'active'` — the caller decides how to
    respond (for example, provisioning a new user on first login is an
    application command, not this lookup). A revoked external identity or
    a non-active (inactive/archived/deleted) user must not authenticate
    even though the row itself still exists.

    Checks `core.lifecycle_statuses.code = 'active'` only — deliberately
    never that lookup row's own `is_active` flag. Per revision
    `080_security_identity_and_access.py`'s own "Deliberate scoping
    decisions" (and docs/architecture/DATABASE_MODEL.md §19's account of
    it), `is_active` on a lookup table means whether that *value* is
    currently offered for *new* assignment — a different question from
    whether a user already assigned `'active'` should retroactively stop
    counting as one, which is exactly why that same revision's own
    `security.campaign_has_access_manager()` deliberately excludes
    `core.lifecycle_statuses.is_active` from its otherwise-analogous
    `membership_statuses`/`capabilities` `is_active` checks. Extending
    that semantics here would be the same scope creep that decision
    already declined."""
    value = connection.execute(
        text("""
            SELECT ei.user_id
            FROM security.external_identities ei
            JOIN security.users u ON u.user_id = ei.user_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE ei.issuer = :issuer
              AND ei.subject = :subject
              AND ei.revoked_at IS NULL
              AND ls.code = 'active'
        """),
        {"issuer": issuer, "subject": subject},
    ).scalar()
    return _as_uuid(value) if value is not None else None


def is_platform_administrator(connection: Connection, *, user_id: uuid.UUID) -> bool:
    """True iff `user_id` names an active user with `security.users.
    is_platform_administrator` set (Phase 11R workstream A). This is a
    deliberately minimal, campaign-independent authorization primitive —
    `AccessContext`/`resolve_access_context` above resolve capabilities
    *within one campaign membership*, but account-management operations
    (creating a local account, issuing a password-reset token, bootstrap)
    have no campaign to scope against at all (docs/PLAN.md §23.1:
    "possessing an active login account does not grant access to any
    campaign" — the reverse is equally true, campaign roles grant no
    platform-account authority). A deactivated administrator's own
    lifecycle status already gates this the same way it gates every other
    login path — there is no separate "revoke admin" step beyond
    deactivating the account."""
    value = connection.execute(
        text("""
            SELECT u.is_platform_administrator
            FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.user_id = :user_id AND ls.code = 'active'
        """),
        {"user_id": user_id},
    ).scalar()
    return bool(value)


def foundry_issuer(external_system_id: uuid.UUID) -> str:
    """The synthetic `security.external_identities.issuer` value that scopes
    a Foundry-side user id to one registered `integration.external_systems`
    row (docs/architecture/DATABASE_MODEL.md §19.1). The single source of
    truth for this format — `dnd_ai.commands.integration.
    link_foundry_identity` (which writes the mapping) and
    `resolve_foundry_system_principal` below (which reads it back during
    authentication) both call this rather than each formatting their own
    copy of the string, so the two can never drift apart."""
    return f"foundry:{external_system_id}"


# The synthetic security.external_identities.issuer value for a local
# username/password login — the identical "reuse the generic identity-
# mapping table with a synthetic issuer" pattern foundry_issuer()
# established above, applied to (issuer="local", subject=<normalized
# login name>) instead of (issuer=f"foundry:{system}", subject=<Foundry
# user id>). dnd_ai.commands.local_auth is the only writer/reader of rows
# with this issuer; resolve_user_by_external_identity (already generic)
# resolves a login name to a user_id with no new lookup code needed.
LOCAL_AUTH_ISSUER = "local"


def hash_foundry_system_key(raw_key: str) -> str:
    """sha256 hex digest of a Foundry-adapter system key. Same rehash-and-
    compare pattern as `dnd_ai.commands.campaign_invitations`'
    `invitation_token_hash` — that module's own docstring justifies plain
    SHA-256 over a slow password-hashing KDF: the input is 256 bits of
    `secrets.token_urlsafe` CSPRNG entropy, never attacker-guessable text,
    so there is nothing here for a slow KDF to protect against that a fast,
    indexable hash doesn't already close off. Shared by `dnd_ai.commands.
    integration.issue_foundry_system_key` (which mints and stores the hash)
    and `resolve_foundry_system_principal` below (which recomputes it from a
    presented key and compares by lookup) so both sides always agree on
    exactly how a raw key becomes its stored hash."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def resolve_foundry_system_principal(
    connection: Connection,
    *,
    external_system_id: uuid.UUID,
    raw_key: str,
    claimed_foundry_actor_id: str | None,
) -> AuthenticatedPrincipal | None:
    """Authenticates a Foundry-adapter request as "system external_system_id,
    acting as the platform principal that credential is bound to" and
    resolves it to a full `AuthenticatedPrincipal` — the Foundry-adapter
    counterpart to `resolve_user_by_external_identity` above, used by
    `dnd_ai.api.auth.get_authenticated_user_id` so every existing
    command/query endpoint already wired to that one dependency becomes
    reachable by a Foundry adapter with no per-route changes, under the
    exact same `require_campaign_capability` authorization every other
    caller goes through — scoped to the authenticated system/world via the
    returned principal's own `foundry_external_system_id`/`foundry_world_id`
    (see `AuthenticatedPrincipal`'s own docstring for the world/campaign-
    scope defect the *first* Phase 11 workstream 2 correction pass closed).

    `claimed_foundry_actor_id` is never an authorization input — see the
    paragraph below for why, and `AuthenticatedPrincipal.
    foundry_claimed_actor_id`'s own docstring for what it *is* used for
    (purely descriptive audit metadata). Passing `None` (no
    `X-Foundry-Actor-Id` header at all) authenticates exactly the same
    principal as passing any string value would.

    Second Phase 11 workstream 2 correction — a Critical defect the first
    pass (world/campaign scoping, above) did not touch: that pass fixed
    *where* a FoundrySystem credential could authorize, but every version
    of this function up to and including the first pass still resolved
    `user_id` from a client-supplied Foundry user id (originally a
    function parameter of that name, checked against `security.
    external_identities`) — an identity the *caller* chose, not one the
    credential itself determined. `integration.external_systems.
    system_key_hash` is stored as a Foundry *world*-scoped `game.settings`
    value (`foundry-module/scripts/settings.mjs`), and Foundry distributes
    every world-scope setting to every client connected to that world —
    `config: false` only hides it from the ordinary settings UI, it does
    not narrow *distribution*. Any connected player who extracted that
    shared credential from their own browser (a real, unprivileged
    capability — Foundry world settings are not access-controlled per
    client) could therefore construct a request bearing the correct
    credential and simply *name* the GM's own, publicly-visible Foundry
    user id in the identity header, and this function would have resolved
    that request to the GM's own `security.users.user_id` — full GM-level
    platform access. `game.user.isGM` checks in `foundry-module/` only
    ever suppressed the *module's own* client-side behavior; they were
    never consulted by, and could never be enforced by, this server-side
    resolution.

    Fixed by removing the "caller names an identity" step entirely rather
    than adding a check that identity is legitimate (there is no
    server-verifiable way to confirm which human is really typing at a
    given Foundry browser tab from an HTTP request alone — a client-side
    claim of any kind, `X-Foundry-Actor-Id` included, must never become an
    authorization input). `dnd_ai.commands.integration.
    issue_foundry_system_key` now binds each credential, at the moment it
    is minted, to exactly one already-linked platform user
    (`integration.external_systems.system_key_principal_user_id`,
    migration 092) — the credential itself *is* the identity from here on,
    the same "possession of the secret is the authorization" model every
    other server-generated, hash-verified credential in this codebase
    already uses (`security.campaign_invitations`), just no longer paired
    with a second, independently-selectable identity claim layered on top
    of it. This is a deliberately narrow, GM-client-only design (see
    `foundry-module/README.md`'s "Trust boundary" section and
    `foundry-module/scripts/hooks.mjs`, whose sync logic already only ever
    runs on the GM's own client): true per-player identity delegation
    through a single shared module installation is not delivered by this
    correction and is out of scope for this MVP.

    Checks, all required: (1) raw_key, rehashed, must match the active
    `integration.external_systems.system_key_hash` for external_system_id,
    and that row's own `is_active` must be true; (2) that row's
    `system_key_principal_user_id` must be set (a credential that has
    never been bound, or whose bound user was subsequently deleted, cannot
    authenticate anything); (3) the bound user's own lifecycle status must
    be `'active'` — the identical check `resolve_user_by_external_identity`
    already applies to an OIDC identity's linked user, so a deactivated
    platform user cannot keep authenticating merely because a Foundry
    credential still names them. Returns `None`, uniformly, for every
    failure mode (unknown system, inactive system, wrong key, unbound
    credential, inactive bound user) deliberately without distinguishing
    which — the same fail-closed, non-disclosing contract
    `resolve_user_by_external_identity` already establishes for its own
    callers, so `get_authenticated_user_id` can raise one uniform
    `UnauthorizedError` regardless of cause."""
    key_hash = hash_foundry_system_key(raw_key)
    row = connection.execute(
        text("""
            SELECT es.world_id, es.system_key_principal_user_id
            FROM integration.external_systems es
            JOIN security.users u ON u.user_id = es.system_key_principal_user_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE es.external_system_id = :system
              AND es.system_key_hash = :hash
              AND es.is_active
              AND ls.code = 'active'
        """),
        {"system": external_system_id, "hash": key_hash},
    ).one_or_none()
    if row is None:
        return None
    return AuthenticatedPrincipal(
        user_id=_as_uuid(row.system_key_principal_user_id),
        auth_method=FOUNDRY_SYSTEM_AUTH_METHOD,
        foundry_external_system_id=external_system_id,
        foundry_world_id=_as_uuid(row.world_id),
        foundry_claimed_actor_id=claimed_foundry_actor_id,
    )


class UnauthorizedTimelineError(DomainAuthorizationError):
    """Raised by `resolve_access_context()` when a caller-supplied
    `timeline_id` is not the campaign's own pinned timeline. A domain
    error, not an HTTP concern (docs/DEVELOPMENT.md §9) — but one that
    carries the supplied, campaign, and canonical timeline IDs in its own
    message (`str(self)`), which is exactly the kind of detail
    `DomainAuthorizationError.safe_message` exists to withhold from an API
    client while still leaving it available for server-side logs. Every
    caller of `resolve_access_context()`, present and future, gets the same
    non-disclosing 404 mapping automatically via `dnd_ai.api.errors`'
    `SafeMessageError` handler — no per-endpoint try/except required."""


def resolve_access_context(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
) -> AccessContext | None:
    """Resolve §19.7 steps 2-7 into one `AccessContext`, or None if the user
    has no active, authorizing membership in the campaign (suspended,
    revoked, departed, or never-invited all resolve to None — a bare
    membership existing is not enough).

    Timeline scope rule: `campaign.campaigns.timeline_id` is a single
    non-nullable column — "the timeline this campaign is played on"
    (docs/architecture/DATABASE_MODEL.md's campaign.campaigns entry) — and
    nothing in the domain model gives one campaign more than one active
    timeline to resolve access against. §19.2 places any *narrower* timeline
    scoping on the individual relationship/grant row that needs it ("the
    membership belongs to the campaign's timeline through campaign.
    campaigns; narrower timeline scope is placed on the particular
    relationship or grant that requires it"), not on request-level
    substitution of a different timeline entirely. So the only valid value
    for `timeline_id` here is the campaign's own pinned timeline — not an
    ancestor, not a branch/descendant, not a timeline from another world.
    Passing `None` resolves it from the campaign automatically; passing the
    campaign's own timeline explicitly is accepted as a caller's
    self-check; passing anything else raises `UnauthorizedTimelineError`
    rather than silently using it to select timeline-scoped character
    capabilities or resource grants (finding 2) — a branch timeline is
    rejected exactly like an unrelated same-world or different-world one,
    since none of them are the campaign's own timeline.
    """
    membership_id = connection.execute(
        text("""
            SELECT cm.campaign_membership_id
            FROM security.campaign_memberships cm
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = cm.membership_status_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.user_id = :user_id
              AND cm.ended_at IS NULL
              AND ms.code = 'active'
              AND ms.is_active
        """),
        {"campaign_id": campaign_id, "user_id": user_id},
    ).scalar()
    if membership_id is None:
        return None
    membership_id = _as_uuid(membership_id)

    campaign_timeline = connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :campaign_id"),
        {"campaign_id": campaign_id},
    ).scalar()
    if campaign_timeline is None:
        raise ValueError(f"campaign {campaign_id} does not exist")
    campaign_timeline_id = _as_uuid(campaign_timeline)

    if timeline_id is not None and timeline_id != campaign_timeline_id:
        raise UnauthorizedTimelineError(
            f"timeline {timeline_id} is not campaign {campaign_id}'s own timeline "
            f"({campaign_timeline_id}) — resolve_access_context only resolves access "
            "for a campaign's own pinned timeline; see its docstring for the rule."
        )

    role_capabilities = frozenset(
        _as_str(code)
        for code in connection.execute(
            text("""
                SELECT DISTINCT cap.code
                FROM security.membership_roles mr
                JOIN security.roles r ON r.role_id = mr.role_id
                JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
                WHERE mr.campaign_membership_id = :membership_id
                  AND mr.revoked_at IS NULL
                  AND (mr.expires_at IS NULL OR mr.expires_at > now())
                  AND r.is_active
                  AND cap.is_active
            """),
            {"membership_id": membership_id},
        ).scalars()
    )

    character_capabilities: dict[uuid.UUID, set[str]] = {}
    for row in connection.execute(
        text("""
            SELECT mcr.character_id, cap.code
            FROM security.membership_character_relationships mcr
            JOIN security.character_relationship_type_capabilities rtc
              ON rtc.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN security.capabilities cap ON cap.capability_id = rtc.capability_id
            WHERE mcr.campaign_membership_id = :membership_id
              AND mcr.revoked_at IS NULL
              AND (mcr.expires_at IS NULL OR mcr.expires_at > now())
              AND (mcr.timeline_id IS NULL OR mcr.timeline_id = :timeline_id)
              AND cap.is_active
        """),
        {"membership_id": membership_id, "timeline_id": campaign_timeline_id},
    ).mappings():
        character_id = _as_uuid(row["character_id"])
        character_capabilities.setdefault(character_id, set()).add(_as_str(row["code"]))

    grant_effects: dict[_GrantKey, dict[str, str]] = {}
    target_column_list = ", ".join(f"rg.{column}" for column in _TARGET_COLUMNS)
    for row in connection.execute(
        text(f"""
            SELECT {target_column_list}, cap.code AS capability_code, rg.effect
            FROM security.resource_grants rg
            JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
            WHERE rg.campaign_id = :campaign_id
              AND rg.revoked_at IS NULL
              AND (rg.expires_at IS NULL OR rg.expires_at > now())
              AND (rg.timeline_id IS NULL OR rg.timeline_id = :timeline_id)
              AND cap.is_active
              AND (
                    rg.grantee_campaign_membership_id = :membership_id
                    OR rg.grantee_access_group_id IN (
                        SELECT agm.access_group_id
                        FROM security.access_group_memberships agm
                        WHERE agm.campaign_membership_id = :membership_id
                          AND agm.removed_at IS NULL
                    )
                  )
        """),
        {
            "campaign_id": campaign_id,
            "timeline_id": campaign_timeline_id,
            "membership_id": membership_id,
        },
    ).mappings():
        target_field = next(column for column in _TARGET_COLUMNS if row[column] is not None)
        key = (target_field, _as_uuid(row[target_field]))
        capability_code = _as_str(row["capability_code"])
        bucket = grant_effects.setdefault(key, {})
        if bucket.get(capability_code) == "deny":
            continue
        bucket[capability_code] = _as_str(row["effect"])

    return AccessContext(
        user_id=user_id,
        campaign_id=campaign_id,
        campaign_membership_id=membership_id,
        timeline_id=campaign_timeline_id,
        role_capabilities=role_capabilities,
        character_capabilities={
            character_id: frozenset(codes) for character_id, codes in character_capabilities.items()
        },
        grant_effects=grant_effects,
    )
