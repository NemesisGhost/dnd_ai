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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal

from sqlalchemy import Connection, RowMapping, text

from .errors import DomainAuthorizationError
from .system_authority import WORLD_ADMINISTER, capabilities_for_system_roles
from .world_authority import WorldAuthority

_TARGET_COLUMNS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)

# Resource-grant delegation policy (Phase 13E-B checkpoint 5): the fixed,
# server-authoritative catalog of which `security.capabilities.code` values
# `dnd_ai.commands.access_grants.create_resource_grant()` accepts for each
# `_TARGET_COLUMNS` kind, and which `dnd_ai.queries.access_overview.
# list_grantable_resource_capabilities()` offers the portal as choices.
# There is no `resource_type`/capability-validity reference table in this
# schema (docs/architecture/DATABASE_MODEL.md §19.6 explicitly rejects a
# universal ACL framework for every table), so this dict is the smallest
# server-side policy that closes the gap: without it, `create_resource_
# grant()` would accept *any* active capability against *any* target kind —
# including a nonsensical pairing (e.g. `character.control` on a `quest_id`)
# that no reader anywhere in this codebase ever checks, and, more
# seriously, `access.manage`/`import.approve`/`rules_source.manage` scoped
# to one resource.
#
# Derived from actual call-site usage, not guessed: every `has_capability(
# ..., character_id=...)`/`resource_grant_targets(cap, "character_id")` call
# in this codebase (`dnd_ai.api.characters`, `.ai_npc`, `.access`) checks
# only a `character.*` code, mirroring `security.character_relationship_
# type_capabilities`' own identical scoping of those same codes to
# character relationships exclusively; every call against the other five
# target columns (`dnd_ai.api.world_explorer`, `.knowledge`, `.quests`,
# `.sessions`, `.dungeon`, `.relationships`, `.summary`) checks only
# `campaign.view` or `canon.edit` — the two capabilities this codebase
# already treats as generically resource-scoped. `access.manage`, `import.
# approve`, and `rules_source.manage` are excluded from every column
# entirely: `has_capability()`'s own contract above ("passing none checks
# only role/character-relationship capabilities") means a resource-scoped
# grant of one of these would be silently inert against every real call
# site in this codebase (each is checked only via `require_campaign_
# capability`, which never passes a resource-target keyword) — and even
# where it would not be inert, this codebase's authorization model has no
# documented notion of *resource-scoped* platform/campaign administration,
# so delegating one through a resource grant is disallowed as policy, not
# merely because it happens to do nothing today.
#
# `character.discover` (checkpoint-5 correction) is deliberately excluded,
# even though it is otherwise a `character.*` code exactly like the nine
# below: its own baseline check (`dnd_ai.api.world_explorer.
# resolve_world_character_visibility`, `discover_all = any(access.
# has_capability(cap) for cap in _DISCOVER_CAPABILITIES)`) passes no resource
# target at all, so `has_capability()`'s own "passing none checks only role/
# character-relationship capabilities" contract means a resource-scoped
# grant can never move that baseline. That same function's per-character
# loop *does* call `has_capability(cap, character_id=character_id)` for each
# discover-tier code, including this one — but only for characters already
# reached through `resource_grant_targets(cap, "character_id")`'s own
# deny/allow sets or an existing character relationship, i.e. it can only
# ever confirm a grant that already exists, never explain how a caller would
# discover a character *before* one exists to check against. In other words:
# a `character.discover` resource grant is not fully inert (the per-character
# loop's narrower use is real), but there is no path by which granting it to
# a membership makes a *previously-undiscoverable* character newly
# discoverable to that membership — no consumer anywhere in this codebase
# resolves "should a resource grant of `character.discover` make character X
# appear in a list" from a bare `(membership, capability)` pair the way
# `character.view_summary`/`.view_full`/etc. do for their own gated actions.
# Advertising it as grantable therefore promises a capability this codebase
# has no real, standalone target-aware consumer for. Re-add it if and when
# such a consumer exists (see `docs/PHASE13E_ACCESS_CONTRACT.md` §3k).
CHARACTER_TARGET_CAPABILITY_CODES = frozenset(
    {
        "character.view_summary",
        "character.view_full",
        "character.view_inventory",
        "character.view_private",
        "character.view_knowledge",
        "character.edit_narrative",
        "character.edit_mechanical_state",
        "character.interact",
        "character.control",
    }
)

GENERIC_TARGET_CAPABILITY_CODES = frozenset({"campaign.view", "canon.edit"})

# Character-relationship policy (Phase 15 checkpoint 15.2A-1).
#
# The maximum capability set each *built-in* relationship type may confer.
# `security.character_relationship_type_capabilities` supplies the default rows
# (migration `114_relationship_defaults`), but a row is authorization-effective
# only if this matrix also permits it: a stray, re-added, or custom-type row
# confers nothing. A type not named here is never admitted (default deny), a
# type with `is_active = false` confers nothing (filtered in SQL), and
# `former_controller` is admitted with an empty set -- continued access needs a
# separate active relationship.
#
# Edit/control/interact capabilities are deliberately withheld until Phase 16
# (no route consumes them today). Only owner, primary_controller, co_controller,
# and portrayer hold `character.view_knowledge`, which is what makes a character
# selectable as a perspective.
#
# These limit *relationship-derived* grants only. Role capabilities
# (`canon.edit`, `gm`'s `character.view_full`/`view_knowledge`, ...) and explicit
# resource grants are independent sources and are not filtered here.
BUILTIN_RELATIONSHIP_CAPABILITIES: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            "character.discover",
            "character.view_summary",
            "character.view_full",
            "character.view_inventory",
            "character.view_knowledge",
            "character.view_private",
        }
    ),
    "primary_controller": frozenset(
        {
            "character.discover",
            "character.view_summary",
            "character.view_full",
            "character.view_inventory",
            "character.view_knowledge",
            "character.view_private",
        }
    ),
    "co_controller": frozenset(
        {
            "character.discover",
            "character.view_summary",
            "character.view_full",
            "character.view_inventory",
            "character.view_knowledge",
        }
    ),
    "portrayer": frozenset(
        {
            "character.discover",
            "character.view_summary",
            "character.view_full",
            "character.view_inventory",
            "character.view_knowledge",
        }
    ),
    # CP-6 / DR-2: a viewer reads the character's inventory through the restricted projection
    # (`dnd_ai.queries.inventory.restrict_inventory_view`) without `character.view_full`.
    "viewer": frozenset(
        {"character.discover", "character.view_summary", "character.view_inventory"}
    ),
    "observer_approved_viewer": frozenset(
        {"character.discover", "character.view_summary", "character.view_inventory"}
    ),
    "former_controller": frozenset(),
}

ADMITTED_RELATIONSHIP_TYPES: frozenset[str] = frozenset(BUILTIN_RELATIONSHIP_CAPABILITIES)


def relationship_capability_permitted(type_code: str, capability_code: str) -> bool:
    """Whether the server policy lets relationship type `type_code` confer
    `capability_code`. Unknown/custom types and any capability outside the
    type's matrix entry are refused. Callers also require the type to be active
    and a database mapping row; this is the code-side half of that conjunction.
    """
    return capability_code in BUILTIN_RELATIONSHIP_CAPABILITIES.get(type_code, frozenset())


# For a character, `campaign.view` and `canon.edit` are *not* in the `character_id` entry: every
# reader looks them up under `entity_id` (the whole-character deny and the per-character
# `canon.edit` deny, ADR 0021 section 2.9 and plan decision D8). `create_resource_grant` therefore
# accepts a character as an `entity_id` target for a `deny` only (P03-A A2a-R, DEF-018); an
# `allow` of either code on a character stays refused.
RESOURCE_GRANT_CAPABILITY_CATALOG: dict[str, frozenset[str]] = {
    "character_id": CHARACTER_TARGET_CAPABILITY_CODES,
    "entity_id": GENERIC_TARGET_CAPABILITY_CODES,
    "knowledge_item_id": GENERIC_TARGET_CAPABILITY_CODES,
    "quest_id": GENERIC_TARGET_CAPABILITY_CODES,
    "session_id": GENERIC_TARGET_CAPABILITY_CODES,
    "event_id": GENERIC_TARGET_CAPABILITY_CODES,
}

_GrantKey = tuple[str, uuid.UUID]

# What a live revelation confers on its one character, and nothing else (P03-A A3b, plan
# section 10.1): discovery and the released public profile. Never `view_summary`, `view_full`,
# `view_inventory`, `view_knowledge`, `view_private`, control or play. A revelation is a source of
# its own and never becomes a relationship capability.
REVELATION_CONFERRED_CAPABILITIES: frozenset[str] = frozenset(
    {"character.discover", "character.view_public_profile"}
)


@dataclass(frozen=True)
class RevelationSource:
    """One live revelation that reaches the caller for one character: its id and audience kind
    code (`member`, `access_group`, `campaign_current`, `campaign_current_and_future`). Kept in
    `AccessContext.revelations`, separate from `character_capabilities`, so each revelation stays
    a distinct, individually revocable source."""

    character_revelation_id: uuid.UUID
    audience_kind: str


# The live revelations that reach one campaign membership (plan section 10.5, "Resolution"). The
# one definition, shared by `resolve_access_context` and the effective-access explanation so the
# two cannot disagree. A revelation applies while it is unclosed and its character is active and
# canon (an archived or non-canon character is inert, and applies again if restored); the audience
# test is by kind: the member itself, an open link to an active target group, an unremoved
# snapshot row, or every active member (`campaign_current_and_future`). Binds `:campaign_id` and
# `:membership_id`; the membership must already be open and active (the caller checks).
LIVE_REVELATIONS_FOR_MEMBERSHIP_SQL = """
    SELECT r.character_revelation_id, r.character_id, k.code AS audience_kind,
           k.display_name AS audience_kind_display_name,
           e.canonical_name AS character_display_name
    FROM security.character_revelations r
    JOIN security.revelation_audience_kinds k
      ON k.revelation_audience_kind_id = r.revelation_audience_kind_id
    JOIN core.entities e ON e.entity_id = r.character_id
    JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = e.lifecycle_status_id
    JOIN core.canon_statuses ccs ON ccs.canon_status_id = e.canon_status_id
    WHERE r.campaign_id = :campaign_id
      AND r.ended_at IS NULL
      AND cls.code = 'active'
      AND ccs.code = 'canon'
      AND (
            (k.code = 'member' AND r.target_campaign_membership_id = :membership_id)
            OR (
                k.code = 'access_group'
                AND r.target_access_group_id IN (
                    SELECT agm.access_group_id
                    FROM security.access_group_memberships agm
                    JOIN security.access_groups ag
                      ON ag.access_group_id = agm.access_group_id
                    JOIN core.lifecycle_statuses ag_status
                      ON ag_status.lifecycle_status_id = ag.lifecycle_status_id
                    WHERE agm.campaign_membership_id = :membership_id
                      AND agm.removed_at IS NULL
                      AND ag_status.code = 'active'
                )
            )
            OR (
                k.code = 'campaign_current'
                AND EXISTS (
                    SELECT 1
                    FROM security.character_revelation_members rm
                    WHERE rm.character_revelation_id = r.character_revelation_id
                      AND rm.campaign_membership_id = :membership_id
                      AND rm.removed_at IS NULL
                )
            )
            OR k.code = 'campaign_current_and_future'
          )
"""


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
    # The campaign's own lifecycle code at resolution time (Phase 14). The
    # campaign-route dependency refuses `archived`/`deleted` campaigns
    # (`dnd_ai.api.access`); `pending`/`inactive` still authorize because only
    # fixtures produce them.
    campaign_lifecycle_status: str = "active"
    # Live revelations that reach this caller, by character (P03-A A3b, plan section 10.6). Each
    # source is its own revelation; revoking one leaves the others, and every relationship, role
    # and grant, exactly as they were.
    revelations: Mapping[uuid.UUID, frozenset[RevelationSource]] = field(
        default_factory=dict, repr=False
    )

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
        include_revelations: bool = True,
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
            # A live revelation confers discovery and the released public profile for that one
            # character, as a source of its own. A role-only check (no `character_id`) gains
            # nothing, and a resource-grant `deny` below still wins. `include_revelations=False`
            # asks what the caller holds through every *other* source (the D5-c projection).
            baseline = baseline or (
                include_revelations
                and capability_code in REVELATION_CONFERRED_CAPABILITIES
                and bool(self.revelations.get(character_id))
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
    """True iff `user_id` names an active user holding an unrevoked system `admin`
    assignment (`security.user_system_roles`; docs/adr/0020-scoped-system-world-
    and-campaign-roles.md). A deliberately minimal, campaign-independent
    authorization primitive -- `AccessContext`/`resolve_access_context` above
    resolve capabilities *within one campaign membership*, but account-management
    operations (creating a local account, issuing a password-reset token,
    bootstrap) have no campaign to scope against at all (docs/PLAN.md §23.1:
    "possessing an active login account does not grant access to any campaign" --
    the reverse is equally true, campaign roles grant no platform-account
    authority). Admin implies no GM, world, or campaign authority. A deactivated
    administrator's own lifecycle status gates this the same way it gates every
    other login path."""
    value = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM security.user_system_roles usr
                JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
                JOIN security.users u ON u.user_id = usr.user_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE usr.user_id = :user_id
                  AND usr.revoked_at IS NULL
                  AND sr.code = 'admin' AND sr.is_active
                  AND ls.code = 'active'
            )
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


BUILTIN_CAMPAIGN_OWNER_ROLE_CODE = "campaign_owner"
BUILTIN_CAMPAIGN_GM_ROLE_CODE = "gm"


class IsolationLevelError(RuntimeError):
    """The decision statement ran in a transaction that is not `read committed`.

    The R01 argument (docs/R01_FRESH_AUTHORIZATION_PLAN_2026-11-12.md section 3.1) needs one fresh
    snapshot per decision statement, which only READ COMMITTED gives. Under REPEATABLE READ the
    statement would reuse the transaction's first snapshot, taken before the request's lock waits;
    under SERIALIZABLE conflicts surface as serialization failures. A direct `RuntimeError`
    subclass with a fixed message: the API maps it to the fixed 500, and nothing persists because
    the request's transaction is abandoned."""

    def __init__(self) -> None:
        super().__init__("the authorization decision requires a READ COMMITTED transaction")


class _FreshInstant:
    """The marker for "judge expiry at the instant the statement itself reads"."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "FRESH_INSTANT"


#: Judge every expiry at one `clock_timestamp()` read inside the decision statement (plan section 3):
#: after the statement's relation-lock waits, once, and shared by every expiry predicate in it.
FRESH_INSTANT: Final = _FreshInstant()

#: The instant a read judges expiry at: `None` is the transaction's start (`now()`), the default and
#: what every existing caller gets; a `datetime` is an explicit, deterministic instant;
#: `FRESH_INSTANT` is the single in-statement `clock_timestamp()`.
Instant = datetime | _FreshInstant | None

RevealAuthority = Literal["owner", "delegation", "none"]


@dataclass(frozen=True)
class AuthoritySnapshot:
    """Every authority source one decision declared, read by ONE SQL statement: one MVCC snapshot,
    one `t_auth` (plan sections 3 and 6.1). Reads take no row locks.

    `access` is `None` when the user has no active, authorizing membership. `world_authority` and
    `reveal_authority` are `None` unless declared; `world_authority` is also `None` when the user
    holds none over the declared world, and `reveal_authority` is `"none"` when declared and held by
    nobody. `t_auth` is the instant every expiry was judged at; `isolation` is the transaction
    isolation level the statement reported (always `read committed` here, or the read raised)."""

    t_auth: datetime
    isolation: str
    access: AccessContext | None
    world_id: uuid.UUID | None = None
    world_authority: WorldAuthority | None = None
    reveal_authority: RevealAuthority | None = None


_LIVE_REVELATIONS_IN_STATEMENT_SQL = LIVE_REVELATIONS_FOR_MEMBERSHIP_SQL.replace(
    ":membership_id", "(SELECT campaign_membership_id FROM m)"
)

_INSTANT_SQL = {
    "now": "now()",
    "explicit": "CAST(:as_of AS timestamptz)",
    "fresh": "clock_timestamp()",
}

_T_AUTH = "(SELECT t_auth FROM clock)"
_MEMBERSHIP = "(SELECT campaign_membership_id FROM m)"

# Common table expressions of the access decision. `{t}` is the one instant, `{m}` the caller's
# membership, `{tl}` the campaign's own timeline: every predicate reads the CTEs, never a parameter
# that another statement resolved, so the whole decision is one snapshot.
_ACCESS_CTES = f"""
    m AS (
        SELECT cm.campaign_membership_id
        FROM security.campaign_memberships cm
        JOIN security.membership_statuses ms
          ON ms.membership_status_id = cm.membership_status_id
        WHERE cm.campaign_id = :campaign_id
          AND cm.user_id = :user_id
          AND cm.ended_at IS NULL
          AND ms.code = 'active'
          AND ms.is_active
        ORDER BY cm.campaign_membership_id
        LIMIT 1
    ),
    camp AS (
        SELECT c.timeline_id, ls.code AS lifecycle_code
        FROM campaign.campaigns c
        JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
        WHERE c.campaign_id = :campaign_id
    ),
    roles AS (
        SELECT COALESCE(jsonb_agg(DISTINCT cap.code), '[]'::jsonb) AS codes
        FROM security.membership_roles mr
        JOIN security.roles r ON r.role_id = mr.role_id
        JOIN security.role_capabilities rc ON rc.role_id = r.role_id
        JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
        WHERE mr.campaign_membership_id = {_MEMBERSHIP}
          AND mr.revoked_at IS NULL
          AND (mr.expires_at IS NULL OR mr.expires_at > {_T_AUTH})
          AND r.is_active
          AND cap.is_active
    ),
    rels AS (
        SELECT COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'character_id', mcr.character_id,
                           'code', cap.code,
                           'type_code', crt.code
                       )
                   ),
                   '[]'::jsonb
               ) AS found
        FROM security.membership_character_relationships mcr
        JOIN security.character_relationship_types crt
          ON crt.character_relationship_type_id = mcr.character_relationship_type_id
        JOIN security.character_relationship_type_capabilities rtc
          ON rtc.character_relationship_type_id = mcr.character_relationship_type_id
        JOIN security.capabilities cap ON cap.capability_id = rtc.capability_id
        JOIN core.entities e ON e.entity_id = mcr.character_id
        JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = e.lifecycle_status_id
        JOIN core.canon_statuses ccs ON ccs.canon_status_id = e.canon_status_id
        WHERE mcr.campaign_membership_id = {_MEMBERSHIP}
          AND mcr.revoked_at IS NULL
          AND (mcr.expires_at IS NULL OR mcr.expires_at > {_T_AUTH})
          AND mcr.effective_to_world_time_id IS NULL
          AND (mcr.timeline_id IS NULL OR mcr.timeline_id = (SELECT timeline_id FROM camp))
          AND crt.is_active
          AND cap.is_active
          AND cls.code = 'active'
          -- A draft or unpublished character confers no perspective (Phase 15.2B-1).
          AND ccs.code = 'canon'
    ),
    grants AS (
        SELECT COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           {", ".join(f"'{column}', rg.{column}" for column in _TARGET_COLUMNS)},
                           'capability_code', cap.code,
                           'effect', rg.effect::text
                       )
                   ),
                   '[]'::jsonb
               ) AS found
        FROM security.resource_grants rg
        JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
        LEFT JOIN core.entities target_entity
          ON target_entity.entity_id = COALESCE(
                 rg.character_id, rg.entity_id, rg.knowledge_item_id, rg.quest_id, rg.event_id
             )
        LEFT JOIN core.lifecycle_statuses target_entity_status
          ON target_entity_status.lifecycle_status_id = target_entity.lifecycle_status_id
        LEFT JOIN campaign.sessions target_session ON target_session.session_id = rg.session_id
        LEFT JOIN core.lifecycle_statuses target_session_status
          ON target_session_status.lifecycle_status_id = target_session.lifecycle_status_id
        WHERE rg.campaign_id = :campaign_id
          AND rg.revoked_at IS NULL
          AND (rg.expires_at IS NULL OR rg.expires_at > {_T_AUTH})
          AND (rg.timeline_id IS NULL OR rg.timeline_id = (SELECT timeline_id FROM camp))
          AND cap.is_active
          AND (
                (rg.session_id IS NULL AND target_entity_status.code = 'active')
                OR (rg.session_id IS NOT NULL AND target_session_status.code = 'active')
              )
          AND (
                rg.grantee_campaign_membership_id = {_MEMBERSHIP}
                OR rg.grantee_access_group_id IN (
                    SELECT agm.access_group_id
                    FROM security.access_group_memberships agm
                    JOIN security.access_groups ag
                        ON ag.access_group_id = agm.access_group_id
                    JOIN core.lifecycle_statuses ag_status
                        ON ag_status.lifecycle_status_id = ag.lifecycle_status_id
                    WHERE agm.campaign_membership_id = {_MEMBERSHIP}
                      AND agm.removed_at IS NULL
                      AND ag_status.code = 'active'
                )
              )
    ),
    revs AS (
        SELECT COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'character_revelation_id', q.character_revelation_id,
                           'character_id', q.character_id,
                           'audience_kind', q.audience_kind
                       )
                   ),
                   '[]'::jsonb
               ) AS found
        FROM ({_LIVE_REVELATIONS_IN_STATEMENT_SQL}) q
    )
"""

_ACCESS_COLUMNS = """
        (SELECT campaign_membership_id FROM m) AS membership_id,
        (SELECT timeline_id FROM camp) AS timeline_id,
        (SELECT lifecycle_code FROM camp) AS campaign_lifecycle_code,
        (SELECT codes FROM roles) AS role_codes,
        (SELECT found FROM rels) AS relationships,
        (SELECT found FROM grants) AS grants,
        (SELECT found FROM revs) AS revelations
"""

# World authority (`dnd_ai.queries.world_authority.resolve_world_authority`), as CTEs of the same
# statement. The caller's system roles are returned as codes; `may_administer` is derived from them
# in Python by the same `capabilities_for_system_roles` the standalone resolver uses.
_WORLD_CTES = """
    w AS (
        SELECT wls.code AS world_status
        FROM core.worlds w
        JOIN core.lifecycle_statuses wls ON wls.lifecycle_status_id = w.lifecycle_status_id
        WHERE w.world_id = :world_id
    ),
    wroles AS (
        SELECT COALESCE(jsonb_agg(wr.code), '[]'::jsonb) AS codes
        FROM security.world_memberships wm
        JOIN security.membership_statuses ms
          ON ms.membership_status_id = wm.membership_status_id
        JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
        JOIN security.users u ON u.user_id = wm.user_id
        JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
        WHERE wm.world_id = :world_id
          AND wm.user_id = :user_id
          AND wm.ended_at IS NULL
          AND ms.code = 'active' AND ms.is_active
          AND wr.is_active
          AND uls.code = 'active'
    ),
    wuse AS (
        SELECT EXISTS (
            SELECT 1
            FROM security.world_use_grants g
            JOIN security.users u ON u.user_id = g.user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            WHERE g.world_id = :world_id AND g.user_id = :user_id
              AND g.revoked_at IS NULL AND uls.code = 'active'
        ) AS held
    ),
    sysroles AS (
        SELECT COALESCE(jsonb_agg(sr.code), '[]'::jsonb) AS codes
        FROM security.user_system_roles usr
        JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
        JOIN security.users u ON u.user_id = usr.user_id
        JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
        WHERE usr.user_id = :user_id
          AND usr.revoked_at IS NULL
          AND sr.is_active
          AND ls.code = 'active'
    )
"""

_WORLD_COLUMNS = """
        (SELECT world_status FROM w) AS world_status,
        (SELECT codes FROM wroles) AS world_role_codes,
        (SELECT held FROM wuse) AS world_use_grant,
        (SELECT codes FROM sysroles) AS system_role_codes
"""

# Reveal authority (`dnd_ai.domain.reveal_authority.resolve_reveal_authority`, lock `none`): a live
# built-in `campaign_owner` assignment; failing that, a live built-in `gm` assignment (the first by
# id, as `find_live_builtin_gm_assignment` takes it) that an unrevoked delegation is bound to. Expiry
# is judged at `t_auth`. Needs the caller's membership (`m`).
_REVEAL_CTES = f"""
    live_assignments AS (
        SELECT mr.membership_role_id, r.code AS role_code
        FROM security.membership_roles mr
        JOIN security.roles r ON r.role_id = mr.role_id
        JOIN security.campaign_memberships cm
          ON cm.campaign_membership_id = mr.campaign_membership_id
        JOIN security.membership_statuses ms
          ON ms.membership_status_id = cm.membership_status_id
        JOIN security.users u ON u.user_id = cm.user_id
        JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
        WHERE mr.campaign_membership_id = {_MEMBERSHIP}
          AND cm.campaign_id = :campaign_id
          AND r.campaign_id IS NULL
          AND r.code IN ('{BUILTIN_CAMPAIGN_OWNER_ROLE_CODE}', '{BUILTIN_CAMPAIGN_GM_ROLE_CODE}')
          AND r.is_active
          AND mr.revoked_at IS NULL
          AND (mr.expires_at IS NULL OR mr.expires_at > {_T_AUTH})
          AND cm.ended_at IS NULL
          AND ms.code = 'active'
          AND ms.is_active
          AND uls.code = 'active'
    ),
    reveal AS (
        SELECT CASE
            WHEN EXISTS (
                SELECT 1 FROM live_assignments
                WHERE role_code = '{BUILTIN_CAMPAIGN_OWNER_ROLE_CODE}'
            ) THEN 'owner'
            WHEN (
                SELECT membership_role_id FROM live_assignments
                WHERE role_code = '{BUILTIN_CAMPAIGN_GM_ROLE_CODE}'
                ORDER BY membership_role_id
                LIMIT 1
            ) IS NOT NULL
            AND (
                SELECT gm_membership_role_id
                FROM security.character_reveal_delegations
                WHERE campaign_id = :campaign_id
                  AND grantee_campaign_membership_id = {_MEMBERSHIP}
                  AND revoked_at IS NULL
                LIMIT 1
            ) = (
                SELECT membership_role_id FROM live_assignments
                WHERE role_code = '{BUILTIN_CAMPAIGN_GM_ROLE_CODE}'
                ORDER BY membership_role_id
                LIMIT 1
            ) THEN 'delegation'
            ELSE 'none'
        END AS source
    )
"""

_REVEAL_COLUMNS = """
        (SELECT source FROM reveal) AS reveal_source
"""


#: Every table the single-statement authority reader reads (the access, world-authority and
#: reveal-authority sources). A post-write plan is valid only for a request that writes none of them,
#: except the reviewed classes below (R01 plan section 6.3); `tests/unit/test_r01_authorization_structure.py`
#: keeps this constant equal to the tables the statement really names, and checks every post-write
#: route's write targets against it. Reviewed classes, each with a stated argument in the plan:
#: `core.entities` and `campaign.sessions` (inputs only of targeted requirements on OTHER resources)
#: and the two `character_revelation*` tables (S2 must show the revelation requirement does not read
#: the rows its own command writes).
AUTHORITY_READER_TABLES: Final[frozenset[str]] = frozenset(
    {
        "campaign.campaigns",
        "campaign.sessions",
        "core.canon_statuses",
        "core.entities",
        "core.lifecycle_statuses",
        "core.worlds",
        "security.access_group_memberships",
        "security.access_groups",
        "security.campaign_memberships",
        "security.capabilities",
        "security.character_relationship_type_capabilities",
        "security.character_relationship_types",
        "security.character_reveal_delegations",
        "security.character_revelation_members",
        "security.character_revelations",
        "security.membership_character_relationships",
        "security.membership_roles",
        "security.membership_statuses",
        "security.resource_grants",
        "security.revelation_audience_kinds",
        "security.role_capabilities",
        "security.roles",
        "security.system_roles",
        "security.user_system_roles",
        "security.users",
        "security.world_memberships",
        "security.world_roles",
        "security.world_use_grants",
    }
)

#: The reader tables a post-write request MAY write (reviewed classes, plan section 6.3).
REVIEWED_POST_WRITE_TABLES: Final[frozenset[str]] = frozenset(
    {
        "core.entities",
        "campaign.sessions",
        "security.character_revelations",
        "security.character_revelation_members",
    }
)


def _authority_snapshot_sql(*, instant: str, with_world: bool, with_reveal: bool) -> str:
    ctes = [f"clock AS MATERIALIZED (SELECT {_INSTANT_SQL[instant]} AS t_auth)", _ACCESS_CTES]
    columns = [
        f"{_T_AUTH} AS t_auth",
        "current_setting('transaction_isolation') AS isolation",
        _ACCESS_COLUMNS,
    ]
    if with_world:
        ctes.append(_WORLD_CTES)
        columns.append(_WORLD_COLUMNS)
    if with_reveal:
        ctes.append(_REVEAL_CTES)
        columns.append(_REVEAL_COLUMNS)
    return "WITH " + ",\n".join(part.strip() for part in ctes) + "\nSELECT " + ",\n".join(columns)


def read_authority_snapshot(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
    world_id: uuid.UUID | None = None,
    with_reveal: bool = False,
    as_of: Instant = None,
) -> AuthoritySnapshot:
    """Read the declared authority sources in ONE statement and return them with the instant expiry
    was judged at (plan sections 3 and 6.1). Always declared: the caller's access to the campaign.
    Optionally: the caller's authority over `world_id`, and the caller's reveal authority
    (`with_reveal`). No row locks are taken.

    `as_of` selects the instant (see `Instant`): the transaction's start by default, an explicit
    `datetime`, or `FRESH_INSTANT`, the single in-statement `clock_timestamp()` that follows the
    statement's own relation-lock waits. Raises `IsolationLevelError` unless the transaction is
    `read committed` (section 3.1), checked from the same statement."""
    if isinstance(as_of, _FreshInstant):
        instant = "fresh"
    elif as_of is None:
        instant = "now"
    else:
        instant = "explicit"
    sql = _authority_snapshot_sql(
        instant=instant, with_world=world_id is not None, with_reveal=with_reveal
    )
    parameters: dict[str, object] = {"campaign_id": campaign_id, "user_id": user_id}
    if instant == "explicit":
        parameters["as_of"] = as_of
    if world_id is not None:
        parameters["world_id"] = world_id
    row = connection.execute(text(sql), parameters).mappings().one()

    isolation = _as_str(row["isolation"])
    if isolation != "read committed":
        raise IsolationLevelError()

    world_authority = None
    if world_id is not None:
        world_authority = _world_authority_from_row(row, user_id=user_id, world_id=world_id)
    reveal_authority: RevealAuthority | None = None
    if with_reveal:
        # No membership resolves to no authority, exactly as the standalone resolver would.
        source = _as_str(row["reveal_source"])
        if source == "owner":
            reveal_authority = "owner"
        elif source == "delegation":
            reveal_authority = "delegation"
        else:
            assert source == "none"
            reveal_authority = "none"

    return AuthoritySnapshot(
        t_auth=row["t_auth"],
        isolation=isolation,
        access=_access_context_from_row(
            row, user_id=user_id, campaign_id=campaign_id, timeline_id=timeline_id
        ),
        world_id=world_id,
        world_authority=world_authority,
        reveal_authority=reveal_authority,
    )


def _world_authority_from_row(
    row: RowMapping, *, user_id: uuid.UUID, world_id: uuid.UUID
) -> WorldAuthority | None:
    if row["world_status"] is None:
        return None
    role_codes = frozenset(_as_str(code) for code in row["world_role_codes"])
    has_use_grant = bool(row["world_use_grant"])
    if not role_codes and not has_use_grant:
        return None
    return WorldAuthority(
        world_id=world_id,
        user_id=user_id,
        role_codes=role_codes,
        world_lifecycle_status=_as_str(row["world_status"]),
        may_administer=WORLD_ADMINISTER
        in capabilities_for_system_roles(
            frozenset(_as_str(code) for code in row["system_role_codes"]),
            allow_in_app_admin_grant=False,
        ),
        has_use_grant=has_use_grant,
    )


def _access_context_from_row(
    row: RowMapping,
    *,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID | None,
) -> AccessContext | None:
    if row["membership_id"] is None:
        return None
    membership_id = _as_uuid(row["membership_id"])
    if row["timeline_id"] is None:
        raise ValueError(f"campaign {campaign_id} does not exist")
    campaign_timeline_id = _as_uuid(row["timeline_id"])
    campaign_lifecycle_status = _as_str(row["campaign_lifecycle_code"])

    if timeline_id is not None and timeline_id != campaign_timeline_id:
        raise UnauthorizedTimelineError(
            f"timeline {timeline_id} is not campaign {campaign_id}'s own timeline "
            f"({campaign_timeline_id}) — resolve_access_context only resolves access "
            "for a campaign's own pinned timeline; see its docstring for the rule."
        )

    role_capabilities = frozenset(_as_str(code) for code in row["role_codes"])

    character_capabilities: dict[uuid.UUID, set[str]] = {}
    for relationship in row["relationships"]:
        # A database mapping is effective only if the code-defined matrix also
        # permits it (default deny for unknown/custom types and stray rows).
        if not relationship_capability_permitted(
            _as_str(relationship["type_code"]), _as_str(relationship["code"])
        ):
            continue
        character_id = uuid.UUID(_as_str(relationship["character_id"]))
        character_capabilities.setdefault(character_id, set()).add(_as_str(relationship["code"]))

    grant_effects: dict[_GrantKey, dict[str, str]] = {}
    for grant in row["grants"]:
        target_field = next(column for column in _TARGET_COLUMNS if grant[column] is not None)
        key = (target_field, uuid.UUID(_as_str(grant[target_field])))
        capability_code = _as_str(grant["capability_code"])
        bucket = grant_effects.setdefault(key, {})
        if bucket.get(capability_code) == "deny":
            continue
        bucket[capability_code] = _as_str(grant["effect"])

    revelations: dict[uuid.UUID, set[RevelationSource]] = {}
    for revelation in row["revelations"]:
        revelations.setdefault(uuid.UUID(_as_str(revelation["character_id"])), set()).add(
            RevelationSource(
                character_revelation_id=uuid.UUID(_as_str(revelation["character_revelation_id"])),
                audience_kind=_as_str(revelation["audience_kind"]),
            )
        )

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
        campaign_lifecycle_status=campaign_lifecycle_status,
        revelations={
            character_id: frozenset(sources) for character_id, sources in revelations.items()
        },
    )


def resolve_access_context(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
    as_of: Instant = None,
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

    Fictional-time-bounded character relationships (checkpoint-4
    correction): a `security.membership_character_relationships` row may
    carry `effective_from_world_time_id`/`effective_to_world_time_id`
    (ADR 0010) in addition to `revoked_at`/`expires_at` — a *fictional*-time
    scope layered on top of the row's real-time lifecycle. This codebase has
    no tracked "current fictional now" for a timeline anywhere (no `campaign.
    timelines` column, no session/event pointer) to compare those bounds
    against, and inventing one here would be exactly the "client-authoritative
    time" this domain's own conventions reject. So this resolver applies the
    same "current record" pattern every other ADR-0010-shaped interval in
    this schema already uses for currentness — `campaign.party_memberships`/
    `world.organization_memberships`/`world.employment_relationships` all
    treat `effective_to_*_id IS NULL` as "still current," never a comparison
    against some external clock (docs/architecture/DATABASE_MODEL.md §12.4,
    §6.3) — applied here as `mcr.effective_to_world_time_id IS NULL`: a row
    with only `effective_from_world_time_id` set (or neither) still
    currently grants its capabilities, since "from" always names an
    already-past grant moment, exactly like a party join. A row with
    *both* endpoints set is, by that same precedent, a closed historical
    interval — it never currently grants access, regardless of where its
    endpoints fall — this is the fail-closed policy this correction adds:
    previously, this query ignored both world-time columns entirely, so a
    fully-bounded (and therefore already-closed) relationship was treated
    identically to an unbounded one. `dnd_ai.queries.access_overview.
    get_campaign_access_overview` and `dnd_ai.commands.access_grants.
    change_character_relationship`'s own eligibility check apply the
    identical rule, so a relationship this resolver would no longer
    authorize through never appears as "current" on the read side or as a
    valid `change` target either.

    Deactivated-character exclusion (checkpoint-4 review correction): the
    character-capabilities join above also requires `core.lifecycle_
    statuses.code = 'active'` for the relationship's own `character_id` —
    previously unchecked here, so a character archived *after* a
    relationship was granted (or changed) stayed authorization-effective
    indefinitely, even though `dnd_ai.commands.access_grants.grant_
    character_relationship()`/`.change_character_relationship()` both
    already refuse to *create* or *change* a relationship naming an
    inactive character. This closes the gap for the read side: a character
    that is later deactivated stops granting any capability on the very
    next call to this resolver, with no separate cleanup step — exactly
    the same "resolved fresh every call, nothing cached" guarantee that
    already made a *revoked relationship* disappear immediately. `dnd_ai.
    queries.access_overview.get_campaign_access_overview` applies the
    identical join/filter so the GM overview and the effective-access
    resolver can never disagree about whether a relationship is current.

    Deactivated-resource-grant-target exclusion (checkpoint 5): the
    resource-grants query below also requires the grant's own target to be
    currently active — `core.lifecycle_statuses.code = 'active'` for the
    five entity-rooted target kinds (`character_id`/`entity_id`/`knowledge_
    item_id`/`quest_id`/`event_id`, all `core.entities` rows via class-table
    inheritance, exactly like `dnd_ai.commands.access_grants.
    _validate_resource_grant_target`'s own reasoning), or the same check
    against `campaign.sessions.lifecycle_status_id` for `session_id` —
    mirroring the deactivated-character exclusion above, generalized to
    every resource-grant target kind: a resource later archived/deactivated
    after a grant was issued must stop being authorization-effective on the
    very next call, not remain effective indefinitely because this resolver
    never re-checked it. `dnd_ai.queries.access_overview.
    get_campaign_access_overview` applies the identical join/filter.

    Deactivated-group exclusion (checkpoint 6): the group-membership
    subquery feeding the resource-grants query's `grantee_access_group_id`
    branch now also requires the group itself to currently be `active`
    (`security.access_groups.lifecycle_status_id`, revision 105) — under
    normal operation `dnd_ai.commands.access_groups.
    deactivate_access_group()` already revokes every grant a group owns
    and closes every membership in it at deactivation time, so this is
    defense in depth (matching the deactivated-target/deactivated-character
    exclusions above) rather than the only thing keeping an archived
    group's grants from applying — but it means a caller's group-derived
    access can never outlive the group's own status by so much as one
    request, even against a hypothetical direct data repair that left a
    stray open membership or unrevoked grant behind.

    `as_of` selects the instant expiry is judged at (`Instant`): `None`, the default every existing
    caller gets, is the transaction's start (`now()`); a `datetime` is an explicit, deterministic
    instant; `FRESH_INSTANT` is one `clock_timestamp()` read inside the statement.

    The whole resolution is ONE SQL statement (`read_authority_snapshot`): one MVCC snapshot, one
    instant. It raises `IsolationLevelError` unless the transaction is `read committed` (R01 plan
    section 3.1).
    """
    return read_authority_snapshot(
        connection,
        user_id=user_id,
        campaign_id=campaign_id,
        timeline_id=timeline_id,
        as_of=as_of,
    ).access


OwnerAssignmentLock = Literal["none", "share", "update"]

_OWNER_ASSIGNMENT_LOCK_CLAUSES: dict[str, str] = {
    "none": "",
    "share": "FOR SHARE OF mr",
    "update": "FOR UPDATE OF mr",
}


def is_builtin_campaign_owner_role(*, role_campaign_id: uuid.UUID | None, role_code: str) -> bool:
    """Whether a `security.roles` row is the built-in owner template. `security.roles.code` is
    unique only among templates, so the code alone never identifies it: a campaign-scoped role may
    be named `campaign_owner` and is not this role."""
    return role_campaign_id is None and role_code == BUILTIN_CAMPAIGN_OWNER_ROLE_CODE


def find_live_builtin_owner_assignment(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    lock: OwnerAssignmentLock = "none",
    as_of: datetime | None = None,
) -> uuid.UUID | None:
    """The `membership_role_id` of this membership's live built-in `campaign_owner` assignment in
    `campaign_id`, or `None`. The single definition of "is a current campaign owner", shared by the
    ownership gate on the commands that hand out the owner role and by the reveal-authority
    resolver, so the two cannot drift.

    Live means: the role row is the built-in template (matched by `role_id` through
    `campaign_id IS NULL`, never by code alone) and is active; the assignment is neither revoked nor
    expired; the membership belongs to `campaign_id`, is open and in the `active` status; and the
    account is active.

    `lock` takes a row lock on the assignment: `share` for a caller that only needs it to stay live
    until commit (revoking, ending or relinquishing it waits for the caller), `update` for a caller
    that goes on to change that same row (taking `share` first would turn the later write into a
    lock upgrade that deadlocks against a concurrent identical request).

    `as_of` is the instant expiry is judged at; the default is the transaction's start (`now()`).
    A caller that has waited on locks passes a fresh `clock_timestamp()` read taken after the
    waits, because an assignment can expire during a wait and `now()` would still call it live
    (DEF-011)."""
    return _find_live_builtin_assignment(
        connection,
        role_code=BUILTIN_CAMPAIGN_OWNER_ROLE_CODE,
        campaign_id=campaign_id,
        campaign_membership_id=campaign_membership_id,
        lock=lock,
        as_of=as_of,
    )


def find_live_builtin_gm_assignment(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    lock: OwnerAssignmentLock = "none",
    as_of: datetime | None = None,
) -> uuid.UUID | None:
    """The `membership_role_id` of this membership's live built-in `gm` assignment in
    `campaign_id`, or `None`: the same definition of "live" as
    `find_live_builtin_owner_assignment` (built-in template matched by `role_id` through
    `campaign_id IS NULL`, active; assignment neither revoked nor expired; membership open and
    `active`; account active) applied to the `gm` template. A campaign-scoped role named `gm`
    and the `assistant_gm` role are not this role. A reveal delegation binds to the row this
    returns."""
    return _find_live_builtin_assignment(
        connection,
        role_code=BUILTIN_CAMPAIGN_GM_ROLE_CODE,
        campaign_id=campaign_id,
        campaign_membership_id=campaign_membership_id,
        lock=lock,
        as_of=as_of,
    )


def _find_live_builtin_assignment(
    connection: Connection,
    *,
    role_code: str,
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    lock: OwnerAssignmentLock,
    as_of: datetime | None,
) -> uuid.UUID | None:
    return connection.execute(
        text(f"""
            SELECT mr.membership_role_id
            FROM security.membership_roles mr
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.campaign_memberships cm
                ON cm.campaign_membership_id = mr.campaign_membership_id
            JOIN security.membership_statuses ms
                ON ms.membership_status_id = cm.membership_status_id
            JOIN security.users u ON u.user_id = cm.user_id
            JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
            WHERE mr.campaign_membership_id = :membership
              AND cm.campaign_id = :campaign
              AND r.campaign_id IS NULL
              AND r.code = :role_code
              AND r.is_active
              AND mr.revoked_at IS NULL
              AND (
                  mr.expires_at IS NULL
                  OR mr.expires_at > COALESCE(CAST(:as_of AS timestamptz), now())
              )
              AND cm.ended_at IS NULL
              AND ms.code = 'active'
              AND ms.is_active
              AND uls.code = 'active'
            ORDER BY mr.membership_role_id
            LIMIT 1
            {_OWNER_ASSIGNMENT_LOCK_CLAUSES[lock]}
        """),  # noqa: S608 - the lock clause comes from a closed literal mapping
        {
            "membership": campaign_membership_id,
            "campaign": campaign_id,
            "role_code": role_code,
            "as_of": as_of,
        },
    ).scalar()
