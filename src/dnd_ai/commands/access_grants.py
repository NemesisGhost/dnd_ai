"""Character-relationship and typed-resource-grant commands.

These commands operate over the two `security.*` tables
that let a human actually see or act as something beyond a bare campaign
role: `security.membership_character_relationships` (a membership's
relationship to a character — control, viewing, portrayal) and `security.
resource_grants` (a targeted allow/deny override beyond role/relationship
defaults). Every read path this codebase has already built —
`dnd_ai.domain.access.AccessContext.has_capability`'s `character_id`
target, `dnd_ai.api.access.resolve_party_perspective`/
`resolve_character_view_tier` — has depended on these two tables since
workstream 12, with no command able to populate either through the API
until now.

`create_resource_grant` supports all six `security.resource_grants`
target kinds (`character_id`, `entity_id`, `knowledge_item_id`, `quest_id`,
`session_id`, `event_id`) and `grant_character_relationship` supports
`security.membership_character_relationships`' full temporal scope
(`timeline_id`, `effective_from_world_time_id`/`effective_to_world_time_id`
— the ADR 0010 fictional-time-bounded variant), each pre-checked the same
way `security.enforce_resource_grant_scope()`/`.enforce_membership_
character_relationship_scope()` (migration 080) validate them at the
database layer — see `_validate_resource_grant_target()`'s and `grant_
character_relationship()`'s own docstrings for the exact rules mirrored
and why relying on either trigger's raw `IntegrityError` alone would
surface as an unclassified 500 instead of the intended 400/404.

Every function here is framework-free and trusts its `campaign_id`
argument as already authorized by the API layer
(`require_campaign_capability("access.manage")`) — the same split
`dnd_ai.commands.memberships` follows, including its own reasoning for
why cross-scope invariants are pre-checked here rather than left to
`security.enforce_membership_character_relationship_scope()`/`.
enforce_resource_grant_scope()`'s own `ERRCODE =
'integrity_constraint_violation'` (SQLSTATE `23000`, unrecognized by the
existing generic `IntegrityError` handler, which would otherwise map an
ordinary validation failure to an unclassified 500). The "exactly one
grantee"/"exactly one target" `CHECK` constraints on `security.
resource_grants` are, by contrast, left unduplicated: a violation raises
SQLSTATE `23514`, already correctly classified to a fixed 400.

Phase 13E-B's character-relationship-management checkpoint adds
`change_character_relationship()` (atomically revokes one active
assignment and inserts a new one with a different relationship type,
mirroring `dnd_ai.commands.memberships.change_membership_role()`'s
identical "revoke one, insert one" shape) and hardens the two pre-existing
functions to the same "currently true" eligibility bar `dnd_ai.commands.
memberships` already established for its own membership/role mutations:
`grant_character_relationship()` now requires the target membership to be
open and in the `active` membership status, its underlying user account to
be currently platform-active (`MembershipNotActiveError`), the target
character to be currently active (folded into `TargetNotInCampaignWorldError`),
and the relationship type to be currently `is_active`
(`RelationshipTypeNotActiveError`) — none of these was checked before;
`revoke_character_relationship()` now returns `RevokeCharacterRelationshipResult`
so its caller can tell an actual revocation apart from the pre-existing
harmless no-op on an already-revoked row, needed so `dnd_ai.api.
access_grants`' route can write exactly one audit record per real state
change rather than one per HTTP call — the identical correction Phase
13E-B checkpoint 2 already made to `revoke_membership_role`/`.
revoke_membership_role_endpoint`. See each function's own docstring for
the full contract.

Checkpoint-4 correction: `grant_character_relationship()`/`change_
character_relationship()` now also require `campaign_id` itself to
currently be `active` (`core.lifecycle_statuses.code`), reusing `dnd_ai.
commands.memberships.CampaignNotActiveError` (re-exported from this module
below) rather than a second, parallel error class — the same "currently
true" bar `add_campaign_member()` already applies when *creating* a
membership, now closed for the gap where a campaign could be deactivated
after `require_campaign_capability("access.manage")` had already
authorized the request but before either mutation committed. Deliberately
**not** applied to `revoke_character_relationship()` — revoking access
must remain available for cleanup even against an inactive campaign, the
same asymmetry `dnd_ai.commands.memberships.revoke_membership_role`/`.
end_campaign_membership` already accept implicitly by never checking
campaign lifecycle status either (nothing in this codebase's documented
retention/lifecycle rules requires a *closing* action to be blocked by the
very state it is trying to close out of).

Lock ordering (checkpoint-4 correction): the new `campaign.campaigns FOR
UPDATE` lock is acquired **after** the function's own primary target row
(the membership row for `grant_character_relationship`, the `mcr`/`cm`
pair for `change_character_relationship`) but **before** every other
dependent lookup (user, character, candidate relationship type) —
deliberately not "campaign first," even though that is `add_campaign_
member()`'s own ordering. `add_campaign_member()` can safely lock campaign-
then-user because it never locks a *pre-existing* membership row (it only
ever inserts a fresh one). `assign_membership_role`/`change_membership_
role`/`revoke_membership_role`/`end_campaign_membership`, by contrast, all
lock their own target membership/role row **synchronously**, up front, and
only ever acquire `campaign.campaigns FOR UPDATE` **implicitly, at commit
time**, via the `DEFERRABLE INITIALLY DEFERRED` constraint trigger `security.
assert_campaign_retains_access_manager()` attaches to `security.
membership_roles`/`.campaign_memberships` (migration 080, §18) — a lock
ordering that is, in effect, always "dependent-row-then-campaign-row,"
identically to what this module now does. Locking campaign-then-membership
here instead would invert that relative order and create a genuine A-B-A
deadlock opportunity against any concurrent role mutation targeting the
same campaign (one transaction holding the membership row while waiting on
the campaign row, the other holding the campaign row — via its own
deferred trigger — while waiting on the membership row). Matching the
existing "dependent-row-then-campaign-row" ordering avoids that new
deadlock class entirely rather than introducing a lock_timeout/deadlock
regression while closing this correction's own race.

Checkpoint-4 review correction: `change_character_relationship()` had not
been hardened to the same target-eligibility boundary `grant_character_
relationship()` already enforces for its own, differently-shaped target —
it locked and rechecked the relationship row, its owning membership, the
campaign, and the candidate new type, but never the membership's owning
user account or the relationship's own existing character, so an access
manager could durably change a relationship's type while its account was
platform-disabled or its character archived. Fixed by extending `change_
character_relationship()`'s own eligibility check (`target_is_eligible`)
with the identical two conditions `grant_character_relationship()` already
requires — the owning account currently platform-active, the character
currently active and still in `expected_world_id` (a new required argument,
resolved server-side from the caller's own authorized campaign timeline by
`dnd_ai.api.access_grants`, never accepted from the client) — both folded
into the same non-disclosing `CharacterRelationshipNotActiveError` (409)
this function already raises for every other "no longer eligible" cause,
rather than reusing `grant_character_relationship()`'s own `MembershipNot
ActiveError`/`TargetNotInCampaignWorldError`: those two errors are shaped
around a caller-*supplied* fresh target (a `campaign_membership_id`/
`character_id` argument the caller picks), while `change_character_
relationship()`'s user/character are the *existing* relationship's own,
already-fixed attributes — a caller who already knows this relationship's
id learns nothing new from a uniform "this assignment is no longer
eligible" conflict, the same reasoning already applied to its other four
folded conditions. Locked last, after `campaign.campaigns`, in the same
relative order `grant_character_relationship()` already uses (membership/
relationship, campaign, user, character, type) — never before it — for the
identical deadlock-avoidance reason above. `dnd_ai.domain.access.
resolve_access_context` and `dnd_ai.queries.access_overview.
get_campaign_access_overview` are hardened the same review pass (see each
one's own docstring) so a character deactivated *after* a relationship was
granted or changed stops being authorization-effective on the very next
request, not just at grant/change time — `revoke_character_relationship()`
remains deliberately unchecked against all four of these conditions
(account, character, membership, campaign), matching this module's own
established "closing access must remain possible for cleanup" policy.

Checkpoint 5 (direct resource-grant management): `create_resource_grant()`
is hardened to the identical "currently true" eligibility bar this module
already established for character relationships — a `grantee_campaign_
membership_id` grantee must be open, in the `active` membership status, and
platform-active (`MembershipNotActiveError`, folding all three
identically); `campaign_id` itself must be `active`
(`CampaignNotActiveError`, re-exported from `dnd_ai.commands.memberships`);
whichever of the six target kinds is supplied must currently be active, not
just in-world/in-campaign (`_validate_resource_grant_target()`'s own
"checkpoint-5 correction"); and `capability_code` must both be currently
active and a valid pairing for the supplied target kind under `dnd_ai.
domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG` — the fixed,
server-authoritative delegation policy that excludes `access.manage`/
`import.approve`/`rules_source.manage` from every resource-grant target
entirely, and restricts `character.*` capability codes to a `character_id`
target (`ResourceGrantCapabilityNotGrantableError`, folding "doesn't
exist"/"deactivated"/"incompatible pairing" identically — see that error's
and that catalog's own docstrings for the full policy and its derivation
from this codebase's actual `has_capability(...)`/`resource_grant_targets()`
call sites). `revoke_resource_grant()` stays deliberately unchecked against
every one of these conditions, matching `revoke_character_relationship()`'s
identical "closing access must remain possible for cleanup" policy — see
that function's own docstring.

Lock ordering (checkpoint 5): `create_resource_grant()` locks its grantee
(the membership row, or nothing further for an access-group grantee), then
`campaign.campaigns`, then, separately, the membership grantee's owning
user row, then the target resource row, then the candidate capability row
— grantee, then campaign, then owning user, then target, then capability:
the identical relative order `grant_character_relationship()` uses for its
own disjoint checks (membership, campaign, user, character, type), for the
identical deadlock-avoidance reasoning this module's own "Lock ordering"
section above already gives.

`end_campaign_membership()` (`dnd_ai.commands.memberships`, checkpoint 5)
now also revokes every currently active `security.resource_grants` row
whose `grantee_campaign_membership_id` is the ending membership, in the
same transaction that closes it — the identical silent-reactivation gap
checkpoint 4 closed for character relationships, now closed for resource
grants too; see that function's own docstring for the full reasoning
(`_activate_or_create_membership`'s "reopen the same row in place"
behavior). Access-group-targeted grant *rows* are never touched by any
membership ending — they belong to the group, not to any one member's own
row — but (checkpoint-5 correction) `end_campaign_membership()` now also
closes the ending membership's own `security.access_group_memberships` link
to every group it belonged to, which has the same practical effect: a
group's resource grants stop applying to a departed member (`dnd_ai.domain.
access.resolve_access_context`'s group-membership subquery only ever
considers a currently open `access_group_memberships` row) without the
group's own grant row, or any *other* member's link to that group, being
touched at all.

No `change_resource_grant()` exists, and none is planned for this
checkpoint: unlike a character relationship's single-dimension "swap the
relationship type" change, a resource grant's meaningful fields — target,
capability, effect, and temporal/timeline scope — could each independently
change, and changing more than one of them at once has no single
unambiguous "this is what changed" audit story the way `change_character_
relationship()`'s single-field swap does. Revoking the old grant and
creating a new one (two already-hardened, already-audited, already-
idempotent mutations) is the deliberate replacement for a generic edit
form here — see `docs/PHASE13E_ACCESS_CONTRACT.md` §3k for the full
rationale."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.commands.memberships import CampaignNotActiveError
from dnd_ai.domain.access import RESOURCE_GRANT_CAPABILITY_CATALOG
from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from ._shared import lookup_id, validate_session_campaign

__all__ = [
    "CampaignNotActiveError",
    "MembershipNotInCampaignError",
    "MembershipNotActiveError",
    "RelationshipTypeNotActiveError",
    "CharacterRelationshipNotActiveError",
    "ChangeCharacterRelationshipNoOpError",
    "AccessGroupNotInCampaignError",
    "ResourceGrantNotInCampaignError",
    "ResourceGrantCapabilityNotGrantableError",
    "TargetNotInCampaignWorldError",
    "InvalidRelationshipPeriodError",
    "GrantCharacterRelationshipResult",
    "grant_character_relationship",
    "RevokeCharacterRelationshipResult",
    "revoke_character_relationship",
    "ChangeCharacterRelationshipResult",
    "change_character_relationship",
    "CreateResourceGrantResult",
    "create_resource_grant",
    "RevokeResourceGrantResult",
    "revoke_resource_grant",
]


class MembershipNotInCampaignError(DomainAuthorizationError):
    """Raised when a caller-supplied `campaign_membership_id` (the subject
    of a character relationship, or the membership grantee of a resource
    grant) does not belong to the already-authorized `campaign_id` —
    including a nonexistent membership, identically, so a caller can never
    distinguish "doesn't exist" from "belongs to a different campaign."
    The supplied ids are included only in the constructor's `detail`
    argument (`str(self)`), never in `safe_message`."""


class MembershipNotActiveError(DomainAuthorizationError):
    """Raised by `grant_character_relationship()` (Phase 13E-B character-
    relationship checkpoint hardening) when the target `campaign_membership_id`,
    though it does belong to `campaign_id` (checked first, as `Membership
    NotInCampaignError`), is not currently an eligible, open membership to
    grant a character relationship to — grouped, identically, so a caller
    can never learn which condition applied: the membership has ended, its
    membership status is not currently `active`, or its underlying user
    account is not currently platform-active. Mirrors `dnd_ai.commands.
    memberships.MembershipNotActiveError`'s identical eligibility bar
    exactly, applied here to the same class of caller-supplied membership
    id. 409, not the base class's default 404: the membership's existence
    and campaign scope are already established by the time this raises."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The request could not be completed due to a conflicting change."


class RelationshipTypeNotActiveError(DomainAuthorizationError):
    """Raised by `grant_character_relationship()`/`change_character_
    relationship()` when the relevant `security.character_relationship_types`
    row (looked up by `code` for a grant, by id for a change) does not
    exist or is not currently `is_active` — folded identically, so a caller
    can never distinguish "no such relationship type" from "deactivated",
    mirroring `dnd_ai.commands.memberships.RoleNotUsableByCampaignError`'s
    identical reasoning for roles. Relationship types carry no campaign
    scope of their own (`security.character_relationship_types` has no
    `campaign_id`), so this checks only existence plus activeness."""


class CharacterRelationshipNotActiveError(DomainAuthorizationError):
    """Raised by `change_character_relationship()` when the target
    `membership_character_relationship_id` is not currently an eligible,
    active assignment to change: already revoked, expired, fictional-time-
    bounded and therefore closed (both `effective_from_world_time_id`/
    `effective_to_world_time_id` set — checkpoint-4 correction, see `dnd_ai.
    domain.access.resolve_access_context`'s own docstring for the "current
    record" rule this reuses), its owning membership ended or no longer in
    the active membership status, its owning user account no longer
    currently platform-active, or its character no longer currently active
    or no longer in the caller's own `expected_world_id` (the last two,
    checkpoint-4 review correction — see `change_character_relationship()`'s
    own docstring for why these are folded into this same error rather than
    reusing `grant_character_relationship()`'s own `MembershipNotActiveError`/
    `TargetNotInCampaignWorldError`) — the identical "currently true"
    definition `dnd_ai.queries.access_overview.get_campaign_access_overview`'s
    own relationships query already uses to decide what counts as a
    member's *current* relationship, applied here so this mutation can
    never act on a row the read side would no longer show as active.
    Mirrors `dnd_ai.commands.memberships.
    MembershipRoleNotActiveError`'s identical reasoning and 409 conflict
    contract (not the base class's default 404: the relationship
    unambiguously existed and belonged to this campaign, so a caller here
    is retrying against state that has already moved out from under it, not
    probing for a resource's existence)."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The request could not be completed due to a conflicting change."


class ChangeCharacterRelationshipNoOpError(SafeMessageError):
    """Raised by `change_character_relationship()` when `new_relationship_
    type_id` names the same relationship type the target `membership_
    character_relationship_id` already, currently holds — checked before
    any write, mirroring `dnd_ai.commands.memberships.
    ChangeMembershipRoleNoOpError`'s identical reasoning (including why
    this must never be durably cached as a successful idempotent-replay
    result). 422, never 409: this is not a race with anything external."""

    safe_status_code = 422
    safe_error_code = "invalid_relationship_change"
    safe_message = "The selected relationship type is already this assignment's current type."


class AccessGroupNotInCampaignError(DomainAuthorizationError):
    """Raised when a caller-supplied `grantee_access_group_id` does not
    belong to the already-authorized `campaign_id` — including a
    nonexistent access group, identically. The supplied ids are included
    only in the constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


class ResourceGrantNotInCampaignError(DomainAuthorizationError):
    """Raised by `revoke_resource_grant()` when a caller-supplied
    `resource_grant_id` does not belong to the already-authorized
    `campaign_id` — including a nonexistent grant, identically. The
    supplied ids are included only in the constructor's `detail` argument
    (`str(self)`), never in `safe_message`."""


class ResourceGrantCapabilityNotGrantableError(DomainAuthorizationError):
    """Raised by `create_resource_grant()` (checkpoint 5) when `capability_
    code` does not currently name an active `security.capabilities` row, or
    names one that `dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG`
    does not list as valid for the target kind actually supplied — folded
    identically, so a caller can never distinguish "no such capability",
    "deactivated", or "not applicable to this resource kind" from one
    another, mirroring `RelationshipTypeNotActiveError`'s identical
    "doesn't exist"/"deactivated" folding for relationship types, extended
    here with a third condition specific to resource grants: a resource
    grant's target kind narrows which capabilities are ever a legitimate
    pairing (see that catalog's own docstring for the full policy and its
    derivation), so a syntactically valid but incompatible pairing (e.g.
    `character.control` against a `quest_id` target) was never a legitimate
    request either, exactly like a deactivated one."""


class TargetNotInCampaignWorldError(DomainAuthorizationError):
    """Raised when a caller-supplied resource-grant target, relationship
    `timeline_id`, or relationship `effective_from_world_time_id`/
    `effective_to_world_time_id` does not belong to the already-authorized
    campaign's own world — including a nonexistent id, identically. Also
    raised for a `session_id`/`event_id` resource-grant target that exists
    and is in the right world but belongs to a different campaign (`dnd_ai.
    commands._shared.validate_session_campaign`'s identical reasoning
    applies here too — a same-world, different-campaign target is exactly
    as much a disclosure risk as a different-world one). The supplied ids
    are included only in the constructor's `detail` argument (`str(self)`),
    never in `safe_message`."""


class InvalidRelationshipPeriodError(ValueError):
    """Raised by `grant_character_relationship()` when `effective_to_
    world_time_id` is supplied without `effective_from_world_time_id` (an
    end with no start), or when the resolved end `sort_key` does not fall
    after the start `sort_key` — mirroring `security.enforce_membership_
    character_relationship_scope()`'s own ordering check (migration 080),
    pre-checked here for the same unclassified-SQLSTATE reason this
    module's docstring gives."""


@dataclass(frozen=True)
class GrantCharacterRelationshipResult:
    membership_character_relationship_id: uuid.UUID


def _resolve_world_time_sort_key(
    connection: Connection, *, world_time_id: uuid.UUID, expected_world_id: uuid.UUID
) -> int:
    row = (
        connection.execute(
            text("SELECT world_id, sort_key FROM core.world_times WHERE world_time_id = :wt"),
            {"wt": world_time_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["world_id"] != expected_world_id:
        raise TargetNotInCampaignWorldError(
            f"world time {world_time_id} does not exist in world {expected_world_id} "
            f"(actual world: {row['world_id'] if row is not None else None})"
        )
    sort_key = row["sort_key"]
    assert isinstance(sort_key, int)
    return sort_key


def _resolve_active_relationship_type_id_by_code(connection: Connection, code: str) -> uuid.UUID:
    """`grant_character_relationship()`'s relationship-type resolution —
    unlike the plain `lookup_id()` helper, also requires `is_active`, so an
    already-deactivated type (never a legitimate grant target, mirroring
    `dnd_ai.commands.memberships.RoleNotUsableByCampaignError`'s identical
    "not usable" reasoning for roles) is rejected here instead of silently
    granted."""
    row = (
        connection.execute(
            text(
                "SELECT character_relationship_type_id, is_active "
                "FROM security.character_relationship_types WHERE code = :code FOR UPDATE"
            ),
            {"code": code},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["is_active"]:
        raise RelationshipTypeNotActiveError(
            f"relationship type code {code!r} does not exist or is not currently active"
        )
    relationship_type_id = row["character_relationship_type_id"]
    assert isinstance(relationship_type_id, uuid.UUID)
    return relationship_type_id


def grant_character_relationship(
    connection: Connection,
    *,
    campaign_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    relationship_type_code: str,
    campaign_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
    effective_from_world_time_id: uuid.UUID | None = None,
    effective_to_world_time_id: uuid.UUID | None = None,
) -> GrantCharacterRelationshipResult:
    """Grants `campaign_membership_id` a relationship of type `relationship_
    type_code` to `character_id`, unbounded and campaign-wide by default,
    or timeline-scoped and/or fictional-time-bounded (ADR 0010) when
    `timeline_id`/`effective_from_world_time_id`/`effective_to_world_
    time_id` are supplied.

    Checkpoint-4 correction — supplying **both** `effective_from_world_
    time_id` and `effective_to_world_time_id` records a fully-bounded,
    already-closed historical interval, never a currently-authorizing one:
    `dnd_ai.domain.access.resolve_access_context` (and every other reader
    of "current" relationships — see its own docstring for the full "current
    record" rule) requires `effective_to_world_time_id IS NULL` before a
    row grants any capability at all, since this schema tracks no "current
    fictional now" a bounded window could be compared against. Supplying
    only `effective_from_world_time_id` (or neither) grants normally and
    remains current indefinitely, matching `campaign.party_memberships`'
    own identical "from is always already-past, to null means still
    current" precedent — only a caller who supplies *both* endpoints gets a
    row that records history without ever granting access.

    Raises `MembershipNotInCampaignError` for a `campaign_membership_id`
    outside `campaign_id`. Raises `MembershipNotActiveError` (409, character-
    relationship checkpoint hardening) if the target membership, though it
    belongs to `campaign_id`, is not currently an eligible, open membership
    — ended, its own status not `active`, or its underlying user account
    not currently platform-active — mirroring `dnd_ai.commands.memberships.
    assign_membership_role()`'s identical eligibility bar for the same
    class of caller-supplied membership id. Raises `CampaignNotActiveError`
    (409, checkpoint-4 correction, re-exported from `dnd_ai.commands.
    memberships`) if `campaign_id` itself is not currently `active` —
    closing the gap where a campaign could be deactivated after `require_
    campaign_capability("access.manage")` had already authorized the
    request but before this write committed; see this module's own
    docstring, "Checkpoint-4 correction," for why this is checked *after*
    the membership-eligibility check above rather than before it. Raises
    `TargetNotInCampaignWorldError` for a `character_id` that does not
    exist, is not currently active (`core.lifecycle_statuses.code`), or
    whose world does not match `expected_world_id` — folded identically,
    the same "never a legitimate target" reasoning `RoleNotUsableByCampaignError`
    already applies to roles — and for a `timeline_id`/world-time id whose
    world does not match `expected_world_id`. Raises `RelationshipTypeNotActiveError`
    for a `relationship_type_code` that does not exist or is not currently
    `is_active`. Raises `InvalidRelationshipPeriodError` for an
    `effective_to_world_time_id` supplied without `effective_from_world_
    time_id`, or one that does not resolve to a later `sort_key` — all
    before any row is written, mirroring `security.enforce_membership_
    character_relationship_scope()`'s own checks (see this module's
    docstring for why relying on that trigger's raw `IntegrityError` alone
    would surface as an unclassified 500). `effective_period` itself is
    left for that same trigger to derive from the two world-time ids on
    `INSERT` — never computed or passed here — since it is documented as
    "derived, never client-authoritative." A retry granting the same
    still-active relationship type again is rejected as a 409 by `ux_
    membership_character_relationships_active_type` (existing
    `IntegrityError` handler).

    Locks the target membership row, then `campaign.campaigns`
    (checkpoint-4 correction), then, separately, the membership's owning
    user row (`FOR UPDATE OF cm`/`FOR UPDATE OF c`/`FOR UPDATE OF u`), then
    the target character row (`FOR UPDATE OF e`), then the candidate
    relationship-type row, before evaluating each one's own eligibility
    check — the same "membership-then-role" lock ordering `assign_
    membership_role()` uses, extended by campaign-then-character-then-
    relationship-type, so a concurrent ending of this membership,
    deactivation of the campaign, deactivation of its owning user account,
    deactivation/archival of the character, or deactivation of the
    relationship type cannot slip in between this function's own read and
    its later `INSERT`, and so this function can never deadlock against
    `assign_membership_role()`/`change_membership_role()` (which lock
    membership/user/role in the same relative order over disjoint row
    sets) nor against any campaign-role mutation's own deferred `campaign.
    campaigns` lock (acquired membership/role-row-first, campaign-last, at
    commit — see this module's own docstring, "Checkpoint-4 correction",
    for why campaign is locked here right after the membership row rather
    than before it)."""
    membership_row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, cm.ended_at, cm.user_id,
                       ms.code AS membership_status_code, ms.is_active AS membership_status_is_active
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :membership
                FOR UPDATE OF cm
            """),
            {"membership": campaign_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    if membership_row is None or membership_row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {campaign_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {membership_row['campaign_id'] if membership_row is not None else None})"
        )

    membership_is_eligible = (
        membership_row["ended_at"] is None
        and membership_row["membership_status_code"] == "active"
        and membership_row["membership_status_is_active"]
    )
    if not membership_is_eligible:
        raise MembershipNotActiveError(
            f"membership {campaign_membership_id} is not currently an eligible, open "
            "membership to grant a character relationship to"
        )

    campaign_status_code = connection.execute(
        text("""
            SELECT ls.code FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign
            FOR UPDATE OF c
        """),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_status_code != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")

    user_lifecycle_status_code = connection.execute(
        text("""
            SELECT ls.code
            FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.user_id = :user
            FOR UPDATE OF u
        """),
        {"user": membership_row["user_id"]},
    ).scalar()
    if user_lifecycle_status_code != "active":
        raise MembershipNotActiveError(
            f"membership {campaign_membership_id}'s user {membership_row['user_id']} is not "
            "currently an active platform account"
        )

    character_row = (
        connection.execute(
            text("""
                SELECT e.world_id, ls.code AS lifecycle_status_code
                FROM core.entities e
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                WHERE e.entity_id = :character
                FOR UPDATE OF e
            """),
            {"character": character_id},
        )
        .mappings()
        .one_or_none()
    )
    character_is_eligible = (
        character_row is not None
        and character_row["world_id"] == expected_world_id
        and character_row["lifecycle_status_code"] == "active"
    )
    if not character_is_eligible:
        raise TargetNotInCampaignWorldError(
            f"character {character_id} does not exist in world {expected_world_id}, or is not "
            "currently active "
            f"(actual world: {character_row['world_id'] if character_row is not None else None})"
        )

    if timeline_id is not None:
        timeline_world_id = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :timeline"),
            {"timeline": timeline_id},
        ).scalar()
        if timeline_world_id is None or timeline_world_id != expected_world_id:
            raise TargetNotInCampaignWorldError(
                f"timeline {timeline_id} does not exist in world {expected_world_id} "
                f"(actual world: {timeline_world_id})"
            )

    if effective_to_world_time_id is not None and effective_from_world_time_id is None:
        raise InvalidRelationshipPeriodError(
            "effective_to_world_time_id requires effective_from_world_time_id"
        )

    if effective_from_world_time_id is not None:
        from_sort_key = _resolve_world_time_sort_key(
            connection,
            world_time_id=effective_from_world_time_id,
            expected_world_id=expected_world_id,
        )
        if effective_to_world_time_id is not None:
            to_sort_key = _resolve_world_time_sort_key(
                connection,
                world_time_id=effective_to_world_time_id,
                expected_world_id=expected_world_id,
            )
            if to_sort_key <= from_sort_key:
                raise InvalidRelationshipPeriodError(
                    f"relationship end (sort_key {to_sort_key}) must be later than its start "
                    f"(sort_key {from_sort_key})"
                )

    relationship_type_id = _resolve_active_relationship_type_id_by_code(
        connection, relationship_type_code
    )
    membership_character_relationship_id = connection.execute(
        text("""
            INSERT INTO security.membership_character_relationships
                (campaign_membership_id, character_id, character_relationship_type_id,
                 timeline_id, effective_from_world_time_id, effective_to_world_time_id,
                 granted_by_membership_id)
            VALUES (:membership, :character, :relationship_type, :timeline, :from_time,
                    :to_time, :granted_by)
            RETURNING membership_character_relationship_id
        """),
        {
            "membership": campaign_membership_id,
            "character": character_id,
            "relationship_type": relationship_type_id,
            "timeline": timeline_id,
            "from_time": effective_from_world_time_id,
            "to_time": effective_to_world_time_id,
            "granted_by": granted_by_membership_id,
        },
    ).scalar()
    assert isinstance(membership_character_relationship_id, uuid.UUID)
    return GrantCharacterRelationshipResult(
        membership_character_relationship_id=membership_character_relationship_id
    )


@dataclass(frozen=True)
class RevokeCharacterRelationshipResult:
    """`revoked` is `True` only when this specific call transitioned the row
    from active to revoked — `False` for the documented harmless-no-op case
    (already revoked). Mirrors `dnd_ai.commands.memberships.
    RevokeMembershipRoleResult` exactly: `dnd_ai.api.access_grants.
    revoke_character_relationship_endpoint` uses this to write exactly one
    `audit.change_log` row per *actual* revocation, never one per HTTP
    call."""

    revoked: bool


def revoke_character_relationship(
    connection: Connection,
    *,
    membership_character_relationship_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> RevokeCharacterRelationshipResult:
    """Revokes `membership_character_relationship_id` (sets
    `revoked_at`), or does nothing if it was already revoked — a retry is
    a harmless no-op, state-idempotent on its own; see `RevokeCharacter
    RelationshipResult.revoked` above for how a caller distinguishes an
    actual revocation from that no-op without this function itself needing
    a durable idempotency-key store. Raises `MembershipNotInCampaignError`
    for a nonexistent `membership_character_relationship_id` or one
    belonging to a membership outside `campaign_id`. Unlike `dnd_ai.
    commands.memberships.revoke_membership_role`, there is no retention
    invariant to re-check here — a character relationship never carries
    `access.manage` (character-scoped capabilities and the campaign-wide
    `access.manage` capability are disjoint concerns)."""
    row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, mcr.revoked_at
                FROM security.membership_character_relationships mcr
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = mcr.campaign_membership_id
                WHERE mcr.membership_character_relationship_id = :relationship
                FOR UPDATE OF mcr
            """),
            {"relationship": membership_character_relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership character relationship {membership_character_relationship_id} does not "
            f"belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    already_revoked = row["revoked_at"] is not None
    if already_revoked:
        return RevokeCharacterRelationshipResult(revoked=False)

    connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :relationship AND revoked_at IS NULL"
        ),
        {"relationship": membership_character_relationship_id},
    )

    return RevokeCharacterRelationshipResult(revoked=True)


@dataclass(frozen=True)
class ChangeCharacterRelationshipResult:
    membership_character_relationship_id: uuid.UUID
    previous_membership_character_relationship_id: uuid.UUID
    previous_relationship_type_code: str
    new_relationship_type_code: str


def change_character_relationship(
    connection: Connection,
    *,
    membership_character_relationship_id: uuid.UUID,
    campaign_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    new_relationship_type_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
) -> ChangeCharacterRelationshipResult:
    """Changes one existing, currently-active character-relationship
    assignment (`membership_character_relationship_id`) to a different
    relationship type (`new_relationship_type_id`), atomically: revokes the
    old `security.membership_character_relationships` row and inserts a new
    one for the same `campaign_membership_id`/`character_id`, in the
    caller's own transaction — mirroring `dnd_ai.commands.memberships.
    change_membership_role()`'s identical "revoke one, insert one" shape.
    This targets exactly the one relationship assignment named — any
    *other* active relationship the same membership independently holds
    (to this character or any other) is untouched, so a member with
    several simultaneous character relationships never has an unrelated one
    silently replaced. The new row carries forward the old row's own
    `timeline_id`/`effective_from_world_time_id`/`effective_to_world_time_id`
    scope unchanged — only the relationship type changes — and preserves
    full temporal history (the old row's `revoked_at` is set, its
    `character_relationship_type_id`/`granted_by_membership_id`/
    `granted_at` are never overwritten) rather than updating the type in
    place.

    Raises `MembershipNotInCampaignError` for a nonexistent
    `membership_character_relationship_id` or one belonging to a different
    campaign than `campaign_id` (checked first, so this stays
    indistinguishable from "it never existed" for an unauthorized caller).
    Raises `CampaignNotActiveError` (409, checkpoint-4 correction,
    re-exported from `dnd_ai.commands.memberships`) if `campaign_id` itself
    is not currently `active` — checked immediately after, before the
    target's own eligibility below, so a caller can never change a
    relationship's type on the strength of an authorization check that
    already ran against a campaign that has since been deactivated. Raises
    `CharacterRelationshipNotActiveError` (409) if `membership_
    character_relationship_id` is not currently an eligible, active
    assignment — already revoked, expired, fictional-time-bounded and
    therefore closed, its membership ended or no longer in the active
    membership status, its owning user account no longer currently
    platform-active (review correction: previously unchecked — the target
    eligibility boundary now matches `grant_character_relationship()`'s own
    account check exactly, closing the gap where a durable type change
    could be made while the account was disabled, then silently exposed on
    a later reactivation), or its character no longer currently active or
    no longer in `expected_world_id` (review correction: also previously
    unchecked — folded into this same 409 rather than `grant_character_
    relationship()`'s own `TargetNotInCampaignWorldError`, since the
    character here is not a caller-supplied fresh target the way `grant_
    character_relationship()`'s `character_id` argument is — it is the
    existing relationship's own already-fixed character, so a caller who
    already knows this relationship's id is not disclosed anything new by
    a uniform "this assignment is no longer eligible" conflict); see that
    error's own docstring for the full "currently true" definition
    (matching the access-overview read side and `dnd_ai.domain.access.
    resolve_access_context` exactly, both hardened the same way in this
    same review pass, so this mutation can never act on a row the read
    side would no longer show as active). Raises `RelationshipTypeNotActiveError`
    for a `new_relationship_type_id` that does not exist or is not
    currently `is_active`. Raises `ChangeCharacterRelationshipNoOpError`
    (422) if `new_relationship_type_id` names the type `membership_
    character_relationship_id` already, currently holds — checked before
    any write. A retry naming a `new_relationship_type_id` the same
    membership/character pair already holds actively (from some other
    assignment) is rejected as a 409 by `ux_membership_character_
    relationships_active_type` (existing `IntegrityError` handler) —
    deliberately not pre-checked here, matching `change_membership_role()`'s
    own "database-enforced invariants deliberately not duplicated" policy.

    Every check above runs, and every row lock below is taken, before any
    write — a rejection therefore never leaves a partial write behind.

    Locks the target row and its owning membership (`FOR UPDATE OF mcr,
    cm`), then `campaign.campaigns` (checkpoint-4 correction, `FOR UPDATE
    OF c`), then, separately, the membership's owning user row and the
    relationship's own character row (review correction, `FOR UPDATE OF
    u`/`FOR UPDATE OF e`), before evaluating the target's own eligibility
    check, and separately locks the candidate new relationship-type row
    before evaluating its own — relationship/membership, then campaign,
    then owning user, then character, then candidate type: the identical
    order `grant_character_relationship()` uses for its own disjoint
    checks (membership, campaign, user, character, type), so a concurrent
    change/revoke of this exact assignment, a concurrent deactivation of
    the campaign, the owning user account, the character, or the new
    relationship type cannot race between this function's own check and
    write, and so this function can never deadlock against `grant_
    character_relationship()`/`change_membership_role()` (which lock their
    own, disjoint row sets in the same relative order) nor against any
    campaign-role mutation's own deferred `campaign.campaigns` lock (see
    `grant_character_relationship()`'s own docstring, and this module's
    "Checkpoint-4 correction" section, for why campaign is locked here
    right after the target row rather than before)."""
    row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, cm.ended_at, cm.user_id,
                       ms.code AS membership_status_code,
                       ms.is_active AS membership_status_is_active,
                       mcr.campaign_membership_id, mcr.character_id,
                       mcr.character_relationship_type_id, mcr.timeline_id,
                       mcr.effective_from_world_time_id, mcr.effective_to_world_time_id,
                       mcr.revoked_at,
                       (mcr.expires_at IS NOT NULL AND mcr.expires_at <= now())
                           AS relationship_is_expired,
                       rt.code AS relationship_type_code
                FROM security.membership_character_relationships mcr
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = mcr.campaign_membership_id
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                JOIN security.character_relationship_types rt
                    ON rt.character_relationship_type_id = mcr.character_relationship_type_id
                WHERE mcr.membership_character_relationship_id = :relationship
                FOR UPDATE OF mcr, cm
            """),
            {"relationship": membership_character_relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership character relationship {membership_character_relationship_id} does not "
            f"belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    campaign_status_code = connection.execute(
        text("""
            SELECT ls.code FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign
            FOR UPDATE OF c
        """),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_status_code != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")

    user_lifecycle_status_code = connection.execute(
        text("""
            SELECT ls.code
            FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.user_id = :user
            FOR UPDATE OF u
        """),
        {"user": row["user_id"]},
    ).scalar()

    character_row = (
        connection.execute(
            text("""
                SELECT e.world_id, ls.code AS lifecycle_status_code
                FROM core.entities e
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                WHERE e.entity_id = :character
                FOR UPDATE OF e
            """),
            {"character": row["character_id"]},
        )
        .mappings()
        .one_or_none()
    )
    character_is_eligible = (
        character_row is not None
        and character_row["world_id"] == expected_world_id
        and character_row["lifecycle_status_code"] == "active"
    )

    target_is_eligible = (
        row["revoked_at"] is None
        and not row["relationship_is_expired"]
        and row["effective_to_world_time_id"] is None
        and row["ended_at"] is None
        and row["membership_status_code"] == "active"
        and row["membership_status_is_active"]
        and user_lifecycle_status_code == "active"
        and character_is_eligible
    )
    if not target_is_eligible:
        raise CharacterRelationshipNotActiveError(
            f"membership character relationship {membership_character_relationship_id} is not "
            "currently an eligible, active assignment to change"
        )

    new_type_row = (
        connection.execute(
            text(
                "SELECT code, is_active FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :type FOR UPDATE"
            ),
            {"type": new_relationship_type_id},
        )
        .mappings()
        .one_or_none()
    )
    if new_type_row is None or not new_type_row["is_active"]:
        raise RelationshipTypeNotActiveError(
            f"relationship type {new_relationship_type_id} does not exist or is not currently "
            "active"
        )

    if new_relationship_type_id == row["character_relationship_type_id"]:
        raise ChangeCharacterRelationshipNoOpError(
            f"relationship type {new_relationship_type_id} is already the current type for "
            f"membership character relationship {membership_character_relationship_id}"
        )

    connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :relationship AND revoked_at IS NULL"
        ),
        {"relationship": membership_character_relationship_id},
    )

    new_membership_character_relationship_id = connection.execute(
        text("""
            INSERT INTO security.membership_character_relationships
                (campaign_membership_id, character_id, character_relationship_type_id,
                 timeline_id, effective_from_world_time_id, effective_to_world_time_id,
                 granted_by_membership_id)
            VALUES (:membership, :character, :new_type, :timeline, :from_time, :to_time,
                    :granted_by)
            RETURNING membership_character_relationship_id
        """),
        {
            "membership": row["campaign_membership_id"],
            "character": row["character_id"],
            "new_type": new_relationship_type_id,
            "timeline": row["timeline_id"],
            "from_time": row["effective_from_world_time_id"],
            "to_time": row["effective_to_world_time_id"],
            "granted_by": granted_by_membership_id,
        },
    ).scalar()
    assert isinstance(new_membership_character_relationship_id, uuid.UUID)

    return ChangeCharacterRelationshipResult(
        membership_character_relationship_id=new_membership_character_relationship_id,
        previous_membership_character_relationship_id=membership_character_relationship_id,
        previous_relationship_type_code=row["relationship_type_code"],
        new_relationship_type_code=new_type_row["code"],
    )


@dataclass(frozen=True)
class CreateResourceGrantResult:
    resource_grant_id: uuid.UUID


_RESOURCE_GRANT_TARGET_FIELDS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)


def _resource_grant_target_field_name(
    *,
    character_id: uuid.UUID | None,
    entity_id: uuid.UUID | None,
    knowledge_item_id: uuid.UUID | None,
    quest_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    event_id: uuid.UUID | None,
) -> str | None:
    """Returns the one target column name that is non-`None`, or `None` if
    zero or more than one are — the malformed-shape case `security.
    resource_grants`' own `ck_resource_grants_exactly_one_target` `CHECK`
    constraint (SQLSTATE `23514`) is left to reject at `INSERT` time,
    exactly as `_validate_resource_grant_target()`'s own docstring already
    establishes for this module. Used by `create_resource_grant()` (checkpoint
    5) to select which `dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_
    CATALOG` entry governs the candidate `capability_code` — for the
    malformed-shape case, capability validation is skipped entirely and the
    plain, uncatalogued `lookup_id()` lookup runs instead, so the `CHECK`
    constraint's own 400 remains the one error a caller sees, never masked
    by an unrelated capability-catalog rejection first."""
    values = {
        "character_id": character_id,
        "entity_id": entity_id,
        "knowledge_item_id": knowledge_item_id,
        "quest_id": quest_id,
        "session_id": session_id,
        "event_id": event_id,
    }
    supplied = [name for name in _RESOURCE_GRANT_TARGET_FIELDS if values[name] is not None]
    if len(supplied) != 1:
        return None
    return supplied[0]


def _validate_resource_grant_target(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    character_id: uuid.UUID | None,
    entity_id: uuid.UUID | None,
    knowledge_item_id: uuid.UUID | None,
    quest_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    event_id: uuid.UUID | None,
) -> None:
    """Pre-checks whichever one of the six target columns is non-`None`
    against `security.enforce_resource_grant_scope()`'s own rules
    (migration 080): `character_id`/`entity_id`/`knowledge_item_id`/
    `quest_id`/`event_id` are all `core.entities` rows via class-table
    inheritance, so each is checked identically, by world, against that
    one shared table; `session_id` is checked by campaign instead (`dnd_ai.
    commands._shared.validate_session_campaign` — a session has no
    `world_id` of its own, and campaign agreement is the stronger,
    directly-relevant check `campaign.sessions` supports); `event_id` is
    additionally checked by campaign when the event itself carries one
    (`narrative.events.campaign_id` is nullable — a world-level,
    campaign-less event has nothing further to check, matching the
    trigger's own `IF v_target_campaign IS NOT NULL` guard). If the
    caller's target is `None` for every one of the six kinds — or more
    than one is non-`None` — this function does nothing further; `security.
    resource_grants`' own `ck_resource_grants_exactly_one_target` `CHECK`
    constraint (SQLSTATE `23514`, already correctly classified to a fixed
    400) is the actual enforcement for that shape, exactly like `create_
    resource_grant`'s existing "exactly one grantee" reasoning.

    Checkpoint-5 correction: previously checked only world/campaign scope,
    never whether the target itself is currently active — a resource grant
    could be created (or, more subtly, silently regain effect on the read
    side after a later reactivation) naming an already-archived character,
    entity, knowledge item, quest, or event, or an already-ended session, the
    same class of gap checkpoint 4 closed for `grant_character_relationship()`'s
    own `character_id` target. Fixed by locking and checking each target's
    own currently-active status here, before any write, folded into the
    same `TargetNotInCampaignWorldError` this function already raises for
    "wrong world"/"wrong campaign" — mirroring `grant_character_relationship()`'s
    own identical folding of "wrong world" and "not active" for its
    character target, so a caller can never distinguish "doesn't exist",
    "wrong world/campaign", or "deactivated" from one another. `dnd_ai.
    domain.access.resolve_access_context`/`dnd_ai.queries.access_overview.
    get_campaign_access_overview` apply the identical exclusion on the read
    side (same checkpoint), so a resource grant's target deactivated *after*
    the grant was created stops being authorization-effective on the very
    next request too, not just at creation time.

    Locks whichever target row is supplied `FOR UPDATE` (`FOR UPDATE OF e`
    for the five entity-rooted kinds, a plain `FOR UPDATE` on `campaign.
    sessions` for `session_id`) as part of this same check, so a concurrent
    deactivation of the target cannot slip in between this read and `create_
    resource_grant()`'s later `INSERT` — locked after the grantee/campaign/
    owning-user locks `create_resource_grant()` itself takes first, matching
    this module's established "dependent-row-then-campaign-row,
    then-target-then-candidate-type" relative ordering (see this module's
    own docstring, "Lock ordering")."""
    entity_rooted_target = character_id or entity_id or knowledge_item_id or quest_id or event_id
    if entity_rooted_target is not None:
        target_row = (
            connection.execute(
                text("""
                    SELECT e.world_id, ls.code AS lifecycle_status_code
                    FROM core.entities e
                    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                    WHERE e.entity_id = :target
                    FOR UPDATE OF e
                """),
                {"target": entity_rooted_target},
            )
            .mappings()
            .one_or_none()
        )
        target_is_eligible = (
            target_row is not None
            and target_row["world_id"] == expected_world_id
            and target_row["lifecycle_status_code"] == "active"
        )
        if not target_is_eligible:
            raise TargetNotInCampaignWorldError(
                f"resource grant target {entity_rooted_target} does not exist in world "
                f"{expected_world_id}, or is not currently active "
                f"(actual world: {target_row['world_id'] if target_row is not None else None})"
            )

    if event_id is not None:
        event_campaign_id = connection.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :event"),
            {"event": event_id},
        ).scalar()
        if event_campaign_id is not None and event_campaign_id != campaign_id:
            raise TargetNotInCampaignWorldError(
                f"event {event_id} belongs to campaign {event_campaign_id}, not {campaign_id}"
            )

    if session_id is not None:
        validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

        session_lifecycle_status_code = connection.execute(
            text("""
                SELECT ls.code
                FROM campaign.sessions s
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = s.lifecycle_status_id
                WHERE s.session_id = :session
                FOR UPDATE OF s
            """),
            {"session": session_id},
        ).scalar()
        if session_lifecycle_status_code != "active":
            raise TargetNotInCampaignWorldError(f"session {session_id} is not currently active")


def _resolve_grantable_capability_id(
    connection: Connection, *, capability_code: str, target_field_name: str
) -> uuid.UUID:
    """`create_resource_grant()`'s capability resolution (checkpoint 5) —
    like `_resolve_active_relationship_type_id_by_code()`, requires
    `is_active`, and additionally requires `capability_code` to be listed in
    `dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG[target_field_name]`
    — the server-authoritative delegation policy for which capability codes
    are ever a legitimate pairing with which resource-grant target kind.
    Raises `ResourceGrantCapabilityNotGrantableError` for a nonexistent,
    deactivated, or catalog-incompatible code, identically (see that error's
    own docstring)."""
    row = (
        connection.execute(
            text(
                "SELECT capability_id, is_active FROM security.capabilities "
                "WHERE code = :code FOR UPDATE"
            ),
            {"code": capability_code},
        )
        .mappings()
        .one_or_none()
    )
    allowed_codes = RESOURCE_GRANT_CAPABILITY_CATALOG.get(target_field_name, frozenset())
    if row is None or not row["is_active"] or capability_code not in allowed_codes:
        raise ResourceGrantCapabilityNotGrantableError(
            f"capability code {capability_code!r} does not exist, is not currently active, or is "
            f"not a valid capability for a {target_field_name!r} resource-grant target"
        )
    capability_id = row["capability_id"]
    assert isinstance(capability_id, uuid.UUID)
    return capability_id


def create_resource_grant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID | None,
    grantee_access_group_id: uuid.UUID | None,
    capability_code: str,
    effect: str,
    expected_world_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
    character_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    knowledge_item_id: uuid.UUID | None = None,
    quest_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> CreateResourceGrantResult:
    """Creates a `security.resource_grants` row for exactly one of
    `grantee_campaign_membership_id`/`grantee_access_group_id` and exactly
    one of the six target kinds (`character_id`, `entity_id`, `knowledge_
    item_id`, `quest_id`, `session_id`, `event_id`) — the caller supplies
    exactly one of each pair/group; `security.resource_grants`' own `CHECK`
    constraints reject any other shape as a clean 400, needing no pre-check
    here (see this function's and `_validate_resource_grant_target()`'s own
    docstrings).

    Raises `MembershipNotInCampaignError`/`AccessGroupNotInCampaignError`
    for a grantee outside `campaign_id`. Raises `MembershipNotActiveError`
    (409, checkpoint 5) for a `grantee_campaign_membership_id` that,
    though it belongs to `campaign_id`, is not currently an eligible, open
    membership — ended, its own status not `active`, or its underlying user
    account not currently platform-active — mirroring `grant_character_
    relationship()`'s identical eligibility bar for the same class of
    caller-supplied membership id; not applicable to a `grantee_access_
    group_id` grantee, which carries no such lifecycle of its own. Raises
    `CampaignNotActiveError` (409, checkpoint 5) if `campaign_id` itself is
    not currently `active` — the identical gap-closing check checkpoint 4
    added to `grant_character_relationship()`/`change_character_relationship()`,
    applied here for the same reason (`require_campaign_capability` never
    itself consults campaign lifecycle status). Raises
    `TargetNotInCampaignWorldError`/`SessionNotInCampaignError` for a target
    outside `expected_world_id`/`campaign_id`, or not currently active
    (checkpoint 5 — see `_validate_resource_grant_target()`'s own docstring).
    Raises `ResourceGrantCapabilityNotGrantableError` (404, checkpoint 5)
    for a `capability_code` that does not exist, is not currently active,
    or is not a valid pairing for the supplied target kind under `dnd_ai.
    domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG` — see that constant's
    own docstring for the full delegation policy this enforces (excludes
    `access.manage`/`import.approve`/`rules_source.manage` entirely, and
    restricts `character.*` codes to a `character_id` target). All of the
    above runs, and every row lock below is taken, before any write — a
    rejection never leaves a partial write behind. A retry creating the
    same still-active grant again is rejected as a 409 by `ux_resource_
    grants_active` (existing `IntegrityError` handler) — deliberately not
    pre-checked, matching this module's own "database-enforced invariants
    deliberately not duplicated" policy.

    Locks the grantee (the membership row `FOR UPDATE OF cm`, or nothing
    further for an access-group grantee — groups carry no mutable lifecycle
    to protect), then `campaign.campaigns` (`FOR UPDATE OF c`), then,
    separately, the membership grantee's owning user row (`FOR UPDATE OF u`,
    skipped for an access-group grantee), then the target resource row
    (`_validate_resource_grant_target()`'s own lock), then the candidate
    capability row (`FOR UPDATE`) — grantee, then campaign, then owning
    user, then target, then capability: the identical relative order
    `grant_character_relationship()` uses for its own disjoint checks
    (membership, campaign, user, character, type), so a concurrent ending of
    this membership, deactivation of the campaign, deactivation of its
    owning user account, deactivation of the target resource, or
    deactivation of the candidate capability cannot slip in between this
    function's own read and its later `INSERT`, and so this function can
    never deadlock against `grant_character_relationship()`/`change_
    character_relationship()`/`change_membership_role()` (which lock their
    own, disjoint row sets in the same relative order) nor against any
    campaign-role mutation's own deferred `campaign.campaigns` lock (see
    `grant_character_relationship()`'s own docstring for why campaign is
    locked here right after the grantee row rather than before it)."""
    membership_owner_user_id: uuid.UUID | None = None
    if grantee_campaign_membership_id is not None:
        membership_row = (
            connection.execute(
                text("""
                    SELECT cm.campaign_id, cm.ended_at, cm.user_id,
                           ms.code AS membership_status_code,
                           ms.is_active AS membership_status_is_active
                    FROM security.campaign_memberships cm
                    JOIN security.membership_statuses ms
                        ON ms.membership_status_id = cm.membership_status_id
                    WHERE cm.campaign_membership_id = :membership
                    FOR UPDATE OF cm
                """),
                {"membership": grantee_campaign_membership_id},
            )
            .mappings()
            .one_or_none()
        )
        if membership_row is None or membership_row["campaign_id"] != campaign_id:
            raise MembershipNotInCampaignError(
                f"membership {grantee_campaign_membership_id} does not belong to campaign "
                f"{campaign_id} "
                f"(actual campaign: {membership_row['campaign_id'] if membership_row is not None else None})"
            )

        membership_is_eligible = (
            membership_row["ended_at"] is None
            and membership_row["membership_status_code"] == "active"
            and membership_row["membership_status_is_active"]
        )
        if not membership_is_eligible:
            raise MembershipNotActiveError(
                f"membership {grantee_campaign_membership_id} is not currently an eligible, open "
                "membership to grant a resource grant to"
            )
        membership_owner_user_id = membership_row["user_id"]
    elif grantee_access_group_id is not None:
        group_campaign_id = connection.execute(
            text("SELECT campaign_id FROM security.access_groups WHERE access_group_id = :group"),
            {"group": grantee_access_group_id},
        ).scalar()
        if group_campaign_id is None or group_campaign_id != campaign_id:
            raise AccessGroupNotInCampaignError(
                f"access group {grantee_access_group_id} does not belong to campaign "
                f"{campaign_id} (actual campaign: {group_campaign_id})"
            )

    campaign_status_code = connection.execute(
        text("""
            SELECT ls.code FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign
            FOR UPDATE OF c
        """),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_status_code != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")

    if membership_owner_user_id is not None:
        user_lifecycle_status_code = connection.execute(
            text("""
                SELECT ls.code
                FROM security.users u
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE u.user_id = :user
                FOR UPDATE OF u
            """),
            {"user": membership_owner_user_id},
        ).scalar()
        if user_lifecycle_status_code != "active":
            raise MembershipNotActiveError(
                f"membership {grantee_campaign_membership_id}'s user "
                f"{membership_owner_user_id} is not currently an active platform account"
            )

    _validate_resource_grant_target(
        connection,
        campaign_id=campaign_id,
        expected_world_id=expected_world_id,
        character_id=character_id,
        entity_id=entity_id,
        knowledge_item_id=knowledge_item_id,
        quest_id=quest_id,
        session_id=session_id,
        event_id=event_id,
    )

    target_field_name = _resource_grant_target_field_name(
        character_id=character_id,
        entity_id=entity_id,
        knowledge_item_id=knowledge_item_id,
        quest_id=quest_id,
        session_id=session_id,
        event_id=event_id,
    )
    capability_id = (
        _resolve_grantable_capability_id(
            connection, capability_code=capability_code, target_field_name=target_field_name
        )
        if target_field_name is not None
        else lookup_id(connection, "security", "capabilities", "capability_id", capability_code)
    )
    resource_grant_id = connection.execute(
        text("""
            INSERT INTO security.resource_grants
                (campaign_id, grantee_campaign_membership_id, grantee_access_group_id,
                 capability_id, effect, character_id, entity_id, knowledge_item_id, quest_id,
                 session_id, event_id, granted_by_membership_id, reason)
            VALUES (:campaign, :grantee_membership, :grantee_group, :capability, :effect,
                    :character, :entity, :knowledge_item, :quest, :session, :event,
                    :granted_by, :reason)
            RETURNING resource_grant_id
        """),
        {
            "campaign": campaign_id,
            "grantee_membership": grantee_campaign_membership_id,
            "grantee_group": grantee_access_group_id,
            "capability": capability_id,
            "effect": effect,
            "character": character_id,
            "entity": entity_id,
            "knowledge_item": knowledge_item_id,
            "quest": quest_id,
            "session": session_id,
            "event": event_id,
            "granted_by": granted_by_membership_id,
            "reason": reason,
        },
    ).scalar()
    assert isinstance(resource_grant_id, uuid.UUID)
    return CreateResourceGrantResult(resource_grant_id=resource_grant_id)


@dataclass(frozen=True)
class RevokeResourceGrantResult:
    """`revoked` is `True` only when this specific call transitioned the
    row from active to revoked — `False` for the documented harmless-no-op
    case (already revoked). Mirrors `RevokeCharacterRelationshipResult`
    exactly (checkpoint 5): `dnd_ai.api.access_grants.
    revoke_resource_grant_endpoint` uses this to write exactly one `audit.
    change_log` row per *actual* revocation, never one per HTTP call.

    `grantee_campaign_membership_id`/`grantee_access_group_id`/`target_field_
    name`/`target_id`/`capability_code`/`effect` (checkpoint-5 correction)
    are the revoked row's own identifying columns, read server-side from the
    same locked row `revoke_resource_grant()` already reads to decide
    `revoked` — never re-derived from caller-supplied input, since a caller
    only ever supplies `resource_grant_id`. `dnd_ai.api.access_grants.
    revoke_resource_grant_endpoint` uses these to record a bounded,
    non-free-form `changed_fields` payload identifying exactly what was
    revoked (see that route's own docstring for why the *pre-correction*
    audit row, naming only `resource_grant_id`, was not enough to reconstruct
    what access actually changed without a second query against a row that
    may since have been superseded). All six are `None` for the documented
    no-op case (`revoked=False`) — nothing was actually revoked, so there is
    nothing for a caller to record."""

    revoked: bool
    grantee_campaign_membership_id: uuid.UUID | None = None
    grantee_access_group_id: uuid.UUID | None = None
    target_field_name: str | None = None
    target_id: uuid.UUID | None = None
    capability_code: str | None = None
    effect: str | None = None


def revoke_resource_grant(
    connection: Connection, *, resource_grant_id: uuid.UUID, campaign_id: uuid.UUID
) -> RevokeResourceGrantResult:
    """Revokes `resource_grant_id` (sets `revoked_at`), or does nothing if
    it was already revoked — a retry is a harmless no-op, state-idempotent
    on its own; see `RevokeResourceGrantResult.revoked` above for how a
    caller distinguishes an actual revocation from that no-op without this
    function itself needing a durable idempotency-key store. Raises
    `ResourceGrantNotInCampaignError` for a nonexistent `resource_grant_id`
    or one belonging to a different campaign. `security.resource_grants.
    campaign_id` is a direct column (unlike `security.membership_roles`/
    `.membership_character_relationships`, which resolve it through their
    owning membership), so no join is needed to check it.

    Deliberately checks none of `create_resource_grant()`'s own eligibility
    conditions — not the grantee membership's own status, not its owning
    user account, not the campaign's lifecycle status, not the target
    resource's own status — matching this module's own established "closing
    access must remain possible for cleanup" policy (see this module's own
    docstring, and `revoke_character_relationship()`'s identical policy for
    the same reasoning)."""
    row = (
        connection.execute(
            text(f"""
                SELECT rg.campaign_id, rg.revoked_at, rg.grantee_campaign_membership_id,
                       rg.grantee_access_group_id, rg.effect, cap.code AS capability_code,
                       {", ".join(f"rg.{column}" for column in _RESOURCE_GRANT_TARGET_FIELDS)}
                FROM security.resource_grants rg
                JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
                WHERE rg.resource_grant_id = :grant
                FOR UPDATE OF rg
            """),
            {"grant": resource_grant_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise ResourceGrantNotInCampaignError(
            f"resource grant {resource_grant_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    if row["revoked_at"] is not None:
        return RevokeResourceGrantResult(revoked=False)

    connection.execute(
        text(
            "UPDATE security.resource_grants SET revoked_at = now() "
            "WHERE resource_grant_id = :grant AND revoked_at IS NULL"
        ),
        {"grant": resource_grant_id},
    )

    target_field_name = _resource_grant_target_field_name(
        character_id=row["character_id"],
        entity_id=row["entity_id"],
        knowledge_item_id=row["knowledge_item_id"],
        quest_id=row["quest_id"],
        session_id=row["session_id"],
        event_id=row["event_id"],
    )
    return RevokeResourceGrantResult(
        revoked=True,
        grantee_campaign_membership_id=row["grantee_campaign_membership_id"],
        grantee_access_group_id=row["grantee_access_group_id"],
        target_field_name=target_field_name,
        target_id=row[target_field_name] if target_field_name is not None else None,
        capability_code=row["capability_code"],
        effect=row["effect"],
    )
