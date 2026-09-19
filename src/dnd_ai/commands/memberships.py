"""Campaign membership and role-assignment commands.

These functions provide direct membership creation and role
assignment/revocation/change (Phase 13E-B's first checkpoint —
`change_membership_role()`, added alongside the pre-existing `assign_
membership_role()`/`revoke_membership_role()` pair rather than a new
role-mutation model of its own: it atomically revokes one existing
assignment and inserts a new one, reusing every check either pre-existing
function already had) by a caller
already holding `access.manage` in the target campaign — the same
GM/adapter-level scoping every other Phase 10 command router chose for
its own first cut. `security.campaign_invitations` (the token/email
acceptance flow) is deliberately out of scope here: it needs an email-
delivery mechanism this application has no other use for yet, and
`campaign.campaigns`/its first owning membership must already exist by
some path before any `access.manage`-gated command could run at all —
bootstrapping a campaign's very first owner membership is left to
whatever future workstream builds campaign creation itself, not invented
speculatively here. `security.membership_character_relationships` and
`security.resource_grants` (the "many-to-many user-character relationships
and resource-access grants" half of the same deliverable line) are also
deferred to a follow-up workstream.

Every function here is framework-free and trusts its `campaign_id`
argument as already authorized — the same "the API layer, via
`require_campaign_capability`, is the only place `access.manage` is
checked" split every other command module in this codebase follows.
`Connection`-taking only (no `_impl`/engine-wrapper split): unlike a
narrative command, nothing here ever needs to compose with an existing
open transaction from a second call site — each of these is always the
sole write in its own request.

Database-enforced invariants this module deliberately does not duplicate:
`security.roles`/`security.membership_roles`' own `ux_membership_roles_active`
unique index (at most one active assignment of the same role to the same
membership) and `security.campaign_memberships`' own
`ux_campaign_memberships_open` unique index (at most one open membership
per `(campaign_id, user_id)`) both surface as ordinary unique-violation
`IntegrityError`s (SQLSTATE `23505`), already mapped to a fixed 409 by the
existing generic handler — no pre-check needed. What *is* pre-checked here,
proactively, is "is this role usable by this campaign"
(`RoleNotUsableByCampaignError`) and "would revoking this role leave the
campaign with no `access.manage` holder" (a plain `ValueError`): both have
a database-level backstop too
(`security.enforce_membership_role_scope()`/`.
enforce_membership_roles_retain_access_manager()`), but each raises with
the bare `ERRCODE = 'integrity_constraint_violation'` (SQLSTATE `23000`,
the base class code, not a specific recognized subclass) — the existing
generic handler's own "a missing or unrecognized SQLSTATE... maps to a
fixed 500, never guessed at as 400 or 409" rule means relying on that
backstop alone would turn an ordinary, anticipatable validation failure
into a 500. Pre-checking here, the same way `dnd_ai.commands._shared.
validate_campaign_party`/`.validate_session_campaign` pre-check their own
cross-scope invariants, is what keeps the client-facing status code
correct.

Phase 13E-B checkpoint 2 (complete role-assignment management for existing
members — add one additional role, revoke one existing role, both without
touching the membership itself) hardens `assign_membership_role()` to the
same "currently true" eligibility bar `change_membership_role()` already
enforces for its own target/candidate roles: the target membership must be
open and in the `active` membership status, its underlying user account
must currently be platform-active (`MembershipNotActiveError`), and the
role being assigned must be currently `is_active` in addition to being
usable by this campaign's scope (`RoleNotUsableByCampaignError`, extended).
`revoke_membership_role()` now returns `RevokeMembershipRoleResult` so its
caller can tell an actual revocation apart from the pre-existing harmless
no-op on an already-revoked row — needed so `dnd_ai.api.memberships`'
route can write exactly one audit record per real state change rather than
one per HTTP call. See each function's own docstring for the full contract.

Phase 13E-B checkpoint 3 (add an existing account to a campaign; end an
existing membership) adds `add_campaign_member()` and `end_campaign_
membership()` — the two remaining membership-lifecycle mutations this
module's own original docstring above named as deferred ("bootstrapping a
campaign's very first owner membership is left to whatever future
workstream builds campaign creation itself" no longer applies to *every*
subsequent member, only the first). `add_campaign_member()` hardens the
pre-existing, previously-unused `create_campaign_membership()` insert with
the same "currently true" eligibility discipline checkpoint 2 already
established (campaign must be active, target account must be platform-
active, target role must be scoped and active) and folds it into one
atomic call with an initial role assignment, reusing `create_campaign_
membership`'s own bare-insert shape rather than replacing it (existing
direct callers of the unchecked bare insert, if any are added later, are
unaffected). `end_campaign_membership()` is the temporal counterpart to
`create_campaign_membership()`/`add_campaign_member()`: closes a
membership (never physically deletes it) and gives every one of its active
role rows the same disposition `revoke_membership_role()` already gives a
single one, atomically, subject to the identical access-manager retention
invariant every other membership/role mutation in this module already
enforces.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from ._shared import lookup_id


class MembershipNotInCampaignError(DomainAuthorizationError):
    """Raised by `assign_membership_role()`/`revoke_membership_role()`/
    `change_membership_role()` when a caller-supplied
    `campaign_membership_id` (or, for `change_membership_role()`, the
    membership a target `membership_role_id` belongs to) does not belong
    to the (already-authorized) `campaign_id` — including a nonexistent
    membership/role assignment and one belonging to a different campaign,
    identically, so a caller can never distinguish the two (docs/
    architecture/DATABASE_MODEL.md §19.7). The supplied ids are included
    only in the constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


class MembershipNotActiveError(DomainAuthorizationError):
    """Raised by `assign_membership_role()` (Phase 13E-B checkpoint 2) when
    the target `campaign_membership_id`, though it does belong to
    `campaign_id` (checked first, as `MembershipNotInCampaignError`), is not
    currently an eligible, open membership to assign a role to — grouped,
    identically, so a caller can never learn which condition applied:

    - the membership has ended (`ended_at IS NOT NULL`);
    - its membership status is not currently `active`
      (`security.membership_statuses.code <> 'active'` or `.is_active`
      false) — the identical membership half of `MembershipRoleNotActiveError`'s
      own "currently true" definition, applied here to a bare membership
      rather than one of its existing role rows;
    - **or** its underlying user account is not currently active
      (`security.users.lifecycle_status_id` -> `core.lifecycle_statuses.code
      <> 'active'`) — the identical account-usability check `dnd_ai.domain.
      access.resolve_user_by_external_identity`/`.is_platform_administrator`/
      `.resolve_foundry_system_principal` already apply to every login path
      in this codebase, applied here so a disabled platform account is never
      handed a *new* campaign role even though its already-open membership
      row and any roles it already held remain visible on the access
      overview (`dnd_ai.queries.access_overview` deliberately never
      consults account-wide lifecycle status for *display* — see that
      module's own docstring — but granting new authority to an account
      that cannot even authenticate is a different question this write path
      answers independently).

    409, matching `MembershipRoleNotActiveError`'s own conflict contract for
    the same "this may have been fine a moment ago, and the caller cannot
    tell from the outside which condition now blocks it" family of checks —
    never the base class's default 404, since the membership's existence
    and campaign scope are already established by the time this raises."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The request could not be completed due to a conflicting change."


class RoleNotUsableByCampaignError(DomainAuthorizationError):
    """Raised by `assign_membership_role()`/`change_membership_role()` when
    a target `role_id` is neither a system template (`security.roles.
    campaign_id IS NULL`) nor scoped to the target campaign, **or** is not
    currently `is_active` — including a nonexistent role, identically, so a
    caller can never distinguish "doesn't exist" from "belongs to a
    different campaign" from "has been deactivated." An inactive role was
    never a legitimate assignment target in the first place (unlike
    `MembershipRoleNotActiveError` below, which covers a target that *was*
    valid a moment ago and has since gone stale) — grouping it with the
    existing "not usable by this campaign" cases keeps that same
    non-disclosing 404 shape rather than introducing a new one. Mirrors
    `security.enforce_membership_role_scope()`'s own database-level check
    for the scope half, applied proactively — see this module's docstring
    for why relying on that trigger's raw `IntegrityError` alone would
    surface as an unclassified 500 instead. The supplied ids are included
    only in the constructor's `detail` argument (`str(self)`), never in
    `safe_message`.

    `assign_membership_role()` (Phase 13E-B checkpoint 2 hardening) applies
    the identical scope-plus-`is_active` check `change_membership_role()`
    already applied to its own `new_role_id` — the original checkpoint-1-era
    `assign_membership_role()` checked scope only, so a caller could assign
    an already-deactivated campaign-scoped or system-template role, silently
    diverging from `dnd_ai.queries.access_overview.
    list_assignable_campaign_roles`'s own `is_active`-filtered "what may
    actually be assigned" contract. Matching that contract exactly (rather
    than merely scope) closes the gap."""


class MembershipRoleNotActiveError(DomainAuthorizationError):
    """Raised by `change_membership_role()` when the target
    `membership_role_id` is not currently an eligible, active assignment to
    change: already revoked, expired (`expires_at` in the past), its
    current role deactivated (`security.roles.is_active = false`), or its
    membership ended or no longer in the active membership status
    (`security.campaign_memberships.ended_at IS NOT NULL`, or `security.
    membership_statuses.code <> 'active'`/`.is_active = false`) — the
    identical "currently true" definition `dnd_ai.queries.access_overview.
    get_campaign_access_overview`'s own roles query already uses to decide
    what counts as a member's *current* role, applied here so this mutation
    can never act on a row the read side would no longer show as active.
    All of these raise identically, so a caller can never learn *which*
    condition applied — only that the assignment is no longer a valid
    target. Most plausibly a second caller's concurrent change/revoke (or a
    role/membership deactivation) landing first.

    Deliberately a *conflict*, not the base class's default 404: the
    membership role unambiguously existed and belonged to this campaign
    (that check runs first, still as `MembershipNotInCampaignError`/404),
    so a caller here is not probing for a resource's existence — it is
    retrying against state that has already moved out from under it.
    `safe_status_code`/`safe_error_code` are overridden to the identical
    409/`conflict` contract `dnd_ai.api.errors.ConflictError` already gives
    a racing unique-index violation elsewhere in this module (see this
    module's own docstring, "Database-enforced invariants..."), so a client
    sees one consistent shape for "this changed under you" regardless of
    which check caught it."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The request could not be completed due to a conflicting change."


class CampaignNotActiveError(DomainAuthorizationError):
    """Raised by `add_campaign_member()` (Phase 13E-B checkpoint 3) when the
    target `campaign_id`, though it exists and the caller is authorized for
    it, is not currently `active` (`core.lifecycle_statuses.code`). Adding a
    member to a campaign that is not currently running mirrors the same
    "this may have been fine a moment ago" conflict family as
    `MembershipNotActiveError` — a `pending`/`archived` campaign may become
    active later, so this is a conflict (409), not the base class's default
    404: the campaign's existence and the caller's `access.manage`
    authorization for it are already established by the time this raises
    (`require_campaign_capability` itself never consults campaign lifecycle
    status). Locking `campaign.campaigns` `FOR UPDATE` before this check
    (see `add_campaign_member`) means a concurrent transition of the
    campaign out of `active` cannot slip in between this check and the
    membership insert that follows it."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The request could not be completed due to a conflicting change."


class AccountNotEligibleError(DomainAuthorizationError):
    """Raised by `add_campaign_member()` when the target `user_id` is
    nonexistent, is not currently a platform-active account
    (`security.users.lifecycle_status_id` -> `core.lifecycle_statuses.code
    <> 'active'`), or has no currently unrevoked local-login identity
    (`security.external_identities` row with `issuer = dnd_ai.domain.
    access.LOCAL_AUTH_ISSUER` and `revoked_at IS NULL`) — folded
    identically, so a caller can never learn which condition applied,
    mirroring `RoleNotUsableByCampaignError`'s own reasoning: none of these
    was ever a legitimate target in the first place, so this is the base
    class's default 404, not a conflict.

    The local-identity check (review correction) matches `dnd_ai.queries.
    access_overview.find_eligible_campaign_account`'s own eligibility
    definition exactly — that read contract already requires an unrevoked
    local identity before ever offering an account as a selectable
    candidate, so the mutation must enforce the identical bar rather than
    trusting the portal to have gone through that lookup first. Without
    this, a caller who already knows (or guesses) an active user's raw
    `user_id` — an OIDC-only account, or a local account whose one login
    identity has since been revoked — could add it directly, bypassing the
    read side's own non-disclosure/eligibility contract entirely. An
    OIDC-only account is therefore never addable through this mutation at
    all (matching that query's own documented scope limitation), and a
    revoked local identity is treated exactly like a disabled account:
    never a legitimate target, not a "this changed a moment ago" conflict.

    A target that already holds an open membership in this campaign is
    deliberately *not* checked here — see this module's docstring,
    "Database-enforced invariants this module deliberately does not
    duplicate": `ux_campaign_memberships_open` rejects that case as an
    ordinary 409 `IntegrityError` at insert time, exactly like every other
    invariant this module relies on the database for rather than
    pre-checking."""


class ChangeMembershipRoleNoOpError(SafeMessageError):
    """Raised by `change_membership_role()` when `new_role_id` names the
    same role the target `membership_role_id` already, currently holds —
    checked before any write, so a no-op request never revokes/reinserts a
    row, never writes an audit entry, and (critically) never lets its
    caller — `dnd_ai.api.memberships`' own route — reach `complete_
    idempotent_request()`, so an `Idempotency-Key` submitted for a no-op is
    never durably cached as a "successful" no-op result; a caller that
    corrects its selection and retries with the *same* key still gets the
    real command run. A plain `SafeMessageError`, not `DomainAuthorization
    Error`: nothing about this case is a disclosure risk — the caller
    already knows both the target assignment and the role it named, so
    there is nothing to hide by being specific. Mapped to 422 (`safe_
    status_code` override below) — "malformed or invalid role request" —
    never 409: this is not a race with anything external, the request as
    submitted simply asks for no effective change, which is knowable from
    the request alone."""

    safe_status_code = 422
    safe_error_code = "invalid_role_change"
    safe_message = "The selected role is already this member's current role for this assignment."


@dataclass(frozen=True)
class CreateCampaignMembershipResult:
    campaign_membership_id: uuid.UUID


def create_campaign_membership(
    connection: Connection, *, campaign_id: uuid.UUID, user_id: uuid.UUID
) -> CreateCampaignMembershipResult:
    """Creates an active `security.campaign_memberships` row for `user_id`
    in `campaign_id`. A retry naming a user who already has an open
    membership in this campaign is rejected as a 409 by
    `ux_campaign_memberships_open` (existing `IntegrityError` handler) —
    never silently creating a second one — and a nonexistent `user_id`
    is rejected as a 400 by the `security.users` foreign key."""
    membership_status_id = lookup_id(
        connection, "security", "membership_statuses", "membership_status_id", "active"
    )
    membership_id = connection.execute(
        text("""
            INSERT INTO security.campaign_memberships
                (campaign_id, user_id, membership_status_id, joined_at)
            VALUES (:campaign, :user, :status, now())
            RETURNING campaign_membership_id
        """),
        {"campaign": campaign_id, "user": user_id, "status": membership_status_id},
    ).scalar()
    assert isinstance(membership_id, uuid.UUID)
    return CreateCampaignMembershipResult(campaign_membership_id=membership_id)


@dataclass(frozen=True)
class AssignMembershipRoleResult:
    membership_role_id: uuid.UUID


def assign_membership_role(
    connection: Connection,
    *,
    campaign_membership_id: uuid.UUID,
    role_id: uuid.UUID,
    campaign_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
    expires_at: datetime | None = None,
) -> AssignMembershipRoleResult:
    """Assigns `role_id` to `campaign_membership_id`, recording
    `granted_by_membership_id` (always the caller's own resolved
    `AccessContext.campaign_membership_id`, never caller-supplied — so it
    is same-campaign by construction and needs no separate check the way
    `campaign_membership_id`/`role_id` do).

    Raises `MembershipNotInCampaignError` for a nonexistent
    `campaign_membership_id`, or one outside `campaign_id` (checked first,
    so this stays indistinguishable from "it never existed" for an
    unauthorized caller). Raises `MembershipNotActiveError` (409, Phase
    13E-B checkpoint 2) if the membership itself is not currently an
    eligible, open target — ended, its own status not `active`, or its
    underlying user account not currently active; see that error's own
    docstring for the full "currently true" definition. Raises
    `RoleNotUsableByCampaignError` (404) for a `role_id` that is neither a
    system template nor scoped to `campaign_id`, or is not currently
    `is_active` — identical to `change_membership_role()`'s own scope-plus-
    activeness check on its `new_role_id`. A retry assigning the same
    still-active role again is rejected as a 409 by `ux_membership_roles_
    active` (existing `IntegrityError` handler) — deliberately not
    pre-checked here, matching this module's own documented "database-
    enforced invariants this module deliberately does not duplicate"
    policy.

    Locks the target membership row and, separately, its owning user row
    (`FOR UPDATE OF cm`/`FOR UPDATE OF u`) before evaluating the membership-
    eligibility check above, and locks the candidate role row (`FOR
    UPDATE`) before evaluating its own — so a concurrent ending of this
    membership, a concurrent deactivation of its owning user account, or a
    concurrent deactivation of the candidate role cannot slip in between
    this function's own read and its later `INSERT`: whichever transaction
    acquires the relevant row lock first forces the other to wait, then
    re-observes the first's committed effect rather than a stale, moment-
    of-check snapshot. Locks are always acquired membership-then-role (the
    same order `change_membership_role()` uses for its own target-row/
    candidate-role pair), so the two commands can never deadlock against
    each other."""
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
            "membership to assign a role to"
        )

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

    role_row = (
        connection.execute(
            text(
                "SELECT campaign_id, is_active FROM security.roles WHERE role_id = :role FOR UPDATE"
            ),
            {"role": role_id},
        )
        .mappings()
        .one_or_none()
    )
    if (
        role_row is None
        or (role_row["campaign_id"] is not None and role_row["campaign_id"] != campaign_id)
        or not role_row["is_active"]
    ):
        raise RoleNotUsableByCampaignError(
            f"role {role_id} is not usable by campaign {campaign_id} "
            f"(actual campaign: {role_row['campaign_id'] if role_row is not None else None})"
        )

    membership_role_id = connection.execute(
        text("""
            INSERT INTO security.membership_roles
                (campaign_membership_id, role_id, granted_by_membership_id, expires_at)
            VALUES (:membership, :role, :granted_by, :expires)
            RETURNING membership_role_id
        """),
        {
            "membership": campaign_membership_id,
            "role": role_id,
            "granted_by": granted_by_membership_id,
            "expires": expires_at,
        },
    ).scalar()
    assert isinstance(membership_role_id, uuid.UUID)
    return AssignMembershipRoleResult(membership_role_id=membership_role_id)


@dataclass(frozen=True)
class RevokeMembershipRoleResult:
    """`revoked` (Phase 13E-B checkpoint 2) is `True` only when this
    specific call transitioned the row from active to revoked — `False`
    for the documented harmless-no-op case (already revoked). `dnd_ai.api.
    memberships.revoke_membership_role_endpoint` uses this to write exactly
    one `audit.change_log` row per *actual* revocation, never one per HTTP
    call — see that route's own docstring for why the pre-existing
    unconditional audit write was a real (if narrow) duplicate-audit gap on
    an ordinary retry with no `Idempotency-Key` reuse."""

    revoked: bool


def revoke_membership_role(
    connection: Connection, *, membership_role_id: uuid.UUID, campaign_id: uuid.UUID
) -> RevokeMembershipRoleResult:
    """Revokes `membership_role_id` (sets `revoked_at`), or does nothing if
    it was already revoked — a retry is a harmless no-op, needing no
    idempotency-key store to stay state-idempotent (see `RevokeMembership
    RoleResult.revoked` above for how a caller distinguishes the two
    outcomes without this function itself needing one). Raises
    `MembershipNotInCampaignError` for a nonexistent `membership_role_id` or
    one belonging to a different campaign than `campaign_id`. Raises a
    plain `ValueError` (mapped by the existing generic handler to a fixed
    400, like every other unclassified domain validation failure in this
    codebase) if revoking it would leave an *active* campaign with no
    membership holding `access.manage` — mirroring `security.
    assert_campaign_retains_access_manager()`'s own "only active campaigns
    are checked" scope exactly, via the same read-only `security.
    campaign_has_access_manager()` helper that function's own docstring
    names as the pre-check counterpart; skipped entirely when this call is
    itself a no-op, since an already-revoked row cannot newly violate an
    invariant nothing about this call changed. Locks the target row (`FOR
    UPDATE`) before evaluating either check, so a concurrent revoke or
    change of the identical row, or a concurrent revoke of a different role
    in the same campaign, cannot race past this one."""
    row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, mr.revoked_at
                FROM security.membership_roles mr
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = mr.campaign_membership_id
                WHERE mr.membership_role_id = :membership_role
                FOR UPDATE OF mr
            """),
            {"membership_role": membership_role_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership role {membership_role_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    already_revoked = row["revoked_at"] is not None
    if already_revoked:
        return RevokeMembershipRoleResult(revoked=False)

    connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() "
            "WHERE membership_role_id = :membership_role AND revoked_at IS NULL"
        ),
        {"membership_role": membership_role_id},
    )

    _assert_active_campaign_retains_access_manager(
        connection,
        campaign_id=campaign_id,
        detail=(
            f"revoking membership role {membership_role_id} would leave active campaign "
            f"{campaign_id} with no membership holding access.manage"
        ),
    )

    return RevokeMembershipRoleResult(revoked=True)


def _assert_active_campaign_retains_access_manager(
    connection: Connection, *, campaign_id: uuid.UUID, detail: str
) -> None:
    """Shared post-write check for `revoke_membership_role()`/
    `change_membership_role()`: only an *active* campaign is checked
    (mirroring `security.assert_campaign_retains_access_manager()`'s own
    scope), via the same read-only `security.campaign_has_access_manager()`
    helper that function's own docstring names as the pre-check
    counterpart. Raises a plain `ValueError` (mapped by the existing
    generic handler to a fixed 400, like every other unclassified domain
    validation failure in this codebase) — never a `SafeMessageError`, so
    this stays the identical response shape `revoke_membership_role()`
    already had before this helper existed, for both call sites."""
    campaign_status_code = connection.execute(
        text("""
            SELECT ls.code FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign
        """),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_status_code != "active":
        return
    still_has_manager = connection.execute(
        text("SELECT security.campaign_has_access_manager(:campaign)"),
        {"campaign": campaign_id},
    ).scalar()
    if not still_has_manager:
        raise ValueError(detail)


@dataclass(frozen=True)
class ChangeMembershipRoleResult:
    membership_role_id: uuid.UUID
    previous_membership_role_id: uuid.UUID
    previous_role_code: str
    new_role_code: str


def change_membership_role(
    connection: Connection,
    *,
    membership_role_id: uuid.UUID,
    campaign_id: uuid.UUID,
    new_role_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
) -> ChangeMembershipRoleResult:
    """Changes one existing, currently-active role assignment
    (`membership_role_id`) to a different role (`new_role_id`), atomically:
    revokes the old `security.membership_roles` row and inserts a new one
    for the same `campaign_membership_id`, in the caller's own transaction.
    This targets exactly the one role assignment named — any *other* active
    role the same membership independently holds is untouched, so a
    multi-role membership never has its whole role set silently replaced.
    Preserves full temporal history (the old row's `revoked_at` is set, its
    `role_id`/`granted_by_membership_id`/`granted_at` rows are never
    overwritten) rather than updating `role_id` in place, exactly like
    `assign_membership_role()`/`revoke_membership_role()` never update a
    row's identity-defining columns either.

    Raises `MembershipNotInCampaignError` for a nonexistent
    `membership_role_id` or one belonging to a different campaign than
    `campaign_id` (checked first, so this stays indistinguishable from "it
    never existed" for an unauthorized caller). Raises
    `MembershipRoleNotActiveError` (409) if `membership_role_id` is not
    currently an eligible, active assignment — already revoked, expired,
    its current role deactivated, or its membership ended or no longer in
    the active membership status; see that error's own docstring for the
    full "currently true" definition (matching the access-overview read
    side exactly, so this mutation can never act on a row the read side
    would no longer show as active). Raises `RoleNotUsableByCampaignError`
    for a `new_role_id` that is neither a system template nor scoped to
    `campaign_id`, or is not currently `is_active` — identical to `assign_
    membership_role()`'s own scope check, extended to activeness. Raises
    `ChangeMembershipRoleNoOpError` (422) if `new_role_id` names the role
    `membership_role_id` already, currently holds — checked before any
    write; see that error's own docstring for why this matters for
    idempotency. Raises a plain `ValueError` (400) if the change would
    leave an *active* campaign with no membership holding `access.manage`
    — the identical retention invariant `revoke_membership_role()`
    enforces, evaluated *after* both the revoke and the new assignment
    have applied within this same transaction, so a change that merely
    moves `access.manage` from one still-active assignment to another
    (rather than removing it) is never rejected. A retry naming a
    `new_role_id` the membership already holds actively (from some other
    assignment) is rejected as a 409 by `ux_membership_roles_active`
    (existing `IntegrityError` handler) — deliberately not pre-checked
    here, matching this module's own documented "database-enforced
    invariants this module deliberately does not duplicate" policy.

    Every check above runs, and every row lock below is taken, before any
    write — a rejection therefore never leaves a partial write behind, and
    (since `dnd_ai.api.deps.get_connection` rolls the whole request's
    transaction back on any exception) never leaves a stray idempotency-key
    reservation or audit entry either, regardless of which check raised.

    Locks the target row, its owning membership, and its current role (`FOR
    UPDATE OF mr, cm, r`) before evaluating any eligibility check, and
    separately locks the candidate new role row before evaluating its own
    — so a concurrent change/revoke of this exact assignment, a concurrent
    deactivation of its current or new role, or a concurrent ending of its
    membership cannot race between this function's own check and write:
    whichever transaction acquires the relevant row lock first forces the
    other to wait, then re-observes the first's committed effect rather
    than the moment-of-check snapshot. The campaign-wide `access.manage`
    retention invariant is a separate concern with its own, pre-existing
    concurrency guarantee — `security.assert_campaign_retains_access_
    manager()`'s `campaign.campaigns` row lock, invoked by the `DEFERRABLE
    INITIALLY DEFERRED` constraint trigger on `security.membership_roles`
    (migration 080) — which this function relies on rather than duplicates;
    see `docs/PHASE13E_ACCESS_CONTRACT.md` §3a for the full argument."""
    row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, cm.ended_at,
                       ms.code AS membership_status_code,
                       ms.is_active AS membership_status_is_active,
                       mr.campaign_membership_id, mr.role_id, mr.revoked_at,
                       (mr.expires_at IS NOT NULL AND mr.expires_at <= now()) AS role_is_expired,
                       r.code AS role_code, r.is_active AS role_is_active
                FROM security.membership_roles mr
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = mr.campaign_membership_id
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                JOIN security.roles r ON r.role_id = mr.role_id
                WHERE mr.membership_role_id = :membership_role
                FOR UPDATE OF mr, cm, r
            """),
            {"membership_role": membership_role_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership role {membership_role_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    target_is_eligible = (
        row["revoked_at"] is None
        and not row["role_is_expired"]
        and row["role_is_active"]
        and row["ended_at"] is None
        and row["membership_status_code"] == "active"
        and row["membership_status_is_active"]
    )
    if not target_is_eligible:
        raise MembershipRoleNotActiveError(
            f"membership role {membership_role_id} is not currently an eligible, active "
            "assignment to change"
        )

    new_role_row = (
        connection.execute(
            text(
                "SELECT campaign_id, code, is_active FROM security.roles "
                "WHERE role_id = :role FOR UPDATE"
            ),
            {"role": new_role_id},
        )
        .mappings()
        .one_or_none()
    )
    if (
        new_role_row is None
        or (new_role_row["campaign_id"] is not None and new_role_row["campaign_id"] != campaign_id)
        or not new_role_row["is_active"]
    ):
        raise RoleNotUsableByCampaignError(
            f"role {new_role_id} is not usable by campaign {campaign_id} "
            f"(actual campaign: {new_role_row['campaign_id'] if new_role_row is not None else None})"
        )

    if new_role_id == row["role_id"]:
        raise ChangeMembershipRoleNoOpError(
            f"role {new_role_id} is already the current role for membership role "
            f"{membership_role_id}"
        )

    connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() "
            "WHERE membership_role_id = :membership_role AND revoked_at IS NULL"
        ),
        {"membership_role": membership_role_id},
    )

    new_membership_role_id = connection.execute(
        text("""
            INSERT INTO security.membership_roles
                (campaign_membership_id, role_id, granted_by_membership_id)
            VALUES (:membership, :role, :granted_by)
            RETURNING membership_role_id
        """),
        {
            "membership": row["campaign_membership_id"],
            "role": new_role_id,
            "granted_by": granted_by_membership_id,
        },
    ).scalar()
    assert isinstance(new_membership_role_id, uuid.UUID)

    _assert_active_campaign_retains_access_manager(
        connection,
        campaign_id=campaign_id,
        detail=(
            f"changing membership role {membership_role_id} to role {new_role_id} would leave "
            f"active campaign {campaign_id} with no membership holding access.manage"
        ),
    )

    return ChangeMembershipRoleResult(
        membership_role_id=new_membership_role_id,
        previous_membership_role_id=membership_role_id,
        previous_role_code=row["role_code"],
        new_role_code=new_role_row["code"],
    )


@dataclass(frozen=True)
class AddCampaignMemberResult:
    campaign_membership_id: uuid.UUID
    membership_role_id: uuid.UUID


def add_campaign_member(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    added_by_membership_id: uuid.UUID,
) -> AddCampaignMemberResult:
    """Adds an existing, eligible account to `campaign_id` with one initial
    role — the portal Access page's "Add campaign member" action (Phase
    13E-B checkpoint 3). Creates exactly two new rows, atomically: a fresh
    `security.campaign_memberships` row (never reactivating an earlier
    ended one — see below) and its one initial `security.membership_roles`
    row, in the caller's own transaction, mirroring `change_membership_
    role`'s "every check runs, every row lock is taken, before any write"
    discipline so a rejection never leaves a partial write behind.

    Every check below is proactive (raised before any write), the same
    "avoid an unclassified 500 from a bare database trigger" reasoning this
    module's own docstring gives for `RoleNotUsableByCampaignError`/the
    access-manager retention `ValueError`:

    - `campaign_id` must currently be `active` (`core.lifecycle_statuses.
      code`) — `CampaignNotActiveError` (409). Locks `campaign.campaigns`
      `FOR UPDATE` first, so a concurrent transition of the campaign out of
      `active` cannot slip in between this check and the insert below.
    - `user_id` must exist and currently be a platform-active account
      (`security.users.lifecycle_status_id` -> `core.lifecycle_statuses.
      code = 'active'`) — `AccountNotEligibleError` (404; an ineligible
      account was never a legitimate target, unlike the 409 cases above).
      Locks the target `security.users` row `FOR UPDATE`, so a concurrent
      disablement of the account cannot slip in either.
    - `user_id` must also hold at least one currently unrevoked local-login
      identity (`security.external_identities`, `issuer = dnd_ai.domain.
      access.LOCAL_AUTH_ISSUER`, `revoked_at IS NULL`) — `AccountNotEligibleError`
      again, the identical "currently true" eligibility bar `dnd_ai.queries.
      access_overview.find_eligible_campaign_account` already requires
      before ever offering this account as a selectable candidate (review
      correction: this command previously trusted the read side's own
      eligibility check instead of re-deriving it, letting a caller who
      already knew — or guessed — an active OIDC-only user's `user_id`, or
      one whose sole local identity had since been revoked, add it
      directly). Locks every matching `security.external_identities` row
      `FOR UPDATE`, so a concurrent revocation of the account's local
      identity cannot slip in either; locked *after* the `security.users`
      row above, the same order every check in this function already
      follows (top-to-bottom, each check's own row locked immediately
      before it runs).
    - `role_id` must be a system template or scoped to `campaign_id`, and
      currently `is_active` — `RoleNotUsableByCampaignError` (404),
      identical to `assign_membership_role`'s own check. Locks the
      candidate role row `FOR UPDATE`.

    A target `user_id` who already holds an *open* membership in
    `campaign_id` is deliberately not pre-checked — see this module's
    docstring, "Database-enforced invariants this module deliberately does
    not duplicate": `ux_campaign_memberships_open` rejects that race as an
    ordinary 409 `IntegrityError` at insert time, so two concurrent adds of
    the same account (with different idempotency keys, or none) can never
    both succeed regardless of which one's pre-checks ran first.

    Re-entry after an earlier departure always creates a **new** temporal
    row — this never reactivates (clears `ended_at`/`ended_by_membership_id`
    on) an existing closed membership the way `dnd_ai.commands.
    campaign_invitations._activate_or_create_membership` deliberately does
    for its own, different, invitation-acceptance flow; that reactivation
    behavior is out of this checkpoint's scope (docs/PHASE13E_ACCESS_
    CONTRACT.md, "membership reactivation" is explicitly excluded), and
    `ux_campaign_memberships_open` has no objection to a second, later row
    for the same `(campaign_id, user_id)` once the earlier one is closed.

    No access-manager retention check is needed here (unlike `revoke_
    membership_role`/`change_membership_role`/`end_campaign_membership`):
    granting a new membership and role can only ever add to a campaign's
    set of qualifying managers, never remove from it."""
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

    account_status_code = connection.execute(
        text("""
            SELECT ls.code FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.user_id = :user
            FOR UPDATE OF u
        """),
        {"user": user_id},
    ).scalar()
    if account_status_code != "active":
        raise AccountNotEligibleError(
            f"user {user_id} does not exist or is not currently an active platform account"
        )

    has_unrevoked_local_identity = connection.execute(
        text("""
            SELECT 1 FROM security.external_identities
            WHERE user_id = :user AND issuer = :issuer AND revoked_at IS NULL
            FOR UPDATE
        """),
        {"user": user_id, "issuer": LOCAL_AUTH_ISSUER},
    ).first()
    if has_unrevoked_local_identity is None:
        raise AccountNotEligibleError(
            f"user {user_id} has no currently unrevoked local-login identity"
        )

    role_row = (
        connection.execute(
            text(
                "SELECT campaign_id, is_active FROM security.roles WHERE role_id = :role FOR UPDATE"
            ),
            {"role": role_id},
        )
        .mappings()
        .one_or_none()
    )
    if (
        role_row is None
        or (role_row["campaign_id"] is not None and role_row["campaign_id"] != campaign_id)
        or not role_row["is_active"]
    ):
        raise RoleNotUsableByCampaignError(
            f"role {role_id} is not usable by campaign {campaign_id} "
            f"(actual campaign: {role_row['campaign_id'] if role_row is not None else None})"
        )

    campaign_membership_id = create_campaign_membership(
        connection, campaign_id=campaign_id, user_id=user_id
    ).campaign_membership_id

    membership_role_id = connection.execute(
        text("""
            INSERT INTO security.membership_roles
                (campaign_membership_id, role_id, granted_by_membership_id)
            VALUES (:membership, :role, :granted_by)
            RETURNING membership_role_id
        """),
        {
            "membership": campaign_membership_id,
            "role": role_id,
            "granted_by": added_by_membership_id,
        },
    ).scalar()
    assert isinstance(membership_role_id, uuid.UUID)

    return AddCampaignMemberResult(
        campaign_membership_id=campaign_membership_id, membership_role_id=membership_role_id
    )


@dataclass(frozen=True)
class EndCampaignMembershipResult:
    """`ended` (mirroring `RevokeMembershipRoleResult.revoked`'s identical
    purpose) is `True` only when this specific call transitioned the
    membership from open to ended — `False` for the documented harmless
    no-op case (already ended). `dnd_ai.api.memberships.
    end_campaign_membership_endpoint` uses this to write exactly one
    `audit.change_log` row per *actual* removal, never one per HTTP call.
    `revoked_membership_role_ids`/`revoked_membership_character_relationship_ids`
    are both empty for the no-op case (nothing was touched) and otherwise
    list every role/character-relationship row this call revoked, for that
    same audit record's `changed_fields` (checkpoint-4 correction added the
    relationship half — see `end_campaign_membership()`'s own docstring for
    the silent-reactivation gap this closes)."""

    campaign_membership_id: uuid.UUID
    ended: bool
    revoked_membership_role_ids: tuple[uuid.UUID, ...]
    revoked_membership_character_relationship_ids: tuple[uuid.UUID, ...]


def end_campaign_membership(
    connection: Connection,
    *,
    campaign_membership_id: uuid.UUID,
    campaign_id: uuid.UUID,
    ended_by_membership_id: uuid.UUID,
) -> EndCampaignMembershipResult:
    """Ends `campaign_membership_id` (sets `ended_at`/`ended_by_membership_
    id`, and moves its `membership_status_id` to the `revoked` status —
    "Closed by a GM or owner action", `database/seeds/security.
    membership_statuses.yaml`'s own words, which this always is: every
    route reaching this command already required `access.manage`, even for
    a self-removal) — the portal Access page's "Remove member" action
    (Phase 13E-B checkpoint 3). Never reactivated and never physically
    deleted, matching every other closed-membership row in this schema
    (`security.campaign_memberships`' own table comment).

    Preserves temporal history for *all three* affected tables in the same
    transaction: every currently active `security.membership_roles` row
    **and** every currently active (`revoked_at IS NULL`) `security.
    membership_character_relationships` row belonging to this membership is
    revoked (`revoked_at` set, exactly like `revoke_membership_role`'s own
    single-row update — never deleted, never reassigned) before the
    membership row itself is closed, so a person who no longer belongs to a
    campaign is never left holding rows the read side (`dnd_ai.queries.
    access_overview`) would still describe as an active current role or
    character relationship, even though that same read side already
    excludes the closed membership itself (`cm.ended_at IS NULL`)
    regardless.

    Checkpoint-4 correction: the character-relationship half of this was
    previously missing entirely — `end_campaign_membership()` closed a
    membership's roles but left its `membership_character_relationships`
    rows untouched. `dnd_ai.commands.campaign_invitations.
    _activate_or_create_membership` (the invitation-acceptance flow's own
    "reopen a closed membership" path) reactivates the *same*
    `campaign_membership_id` row in place — it clears `ended_at`/`ended_
    by_membership_id` and resets `membership_status_id`, never inserting a
    fresh membership row — so any relationship row this function left
    `revoked_at IS NULL` on would immediately regain effect the moment that
    membership reopened, silently restoring whatever character
    perspective/capabilities the departed member held before, with no new
    `grant_character_relationship()` call and no new `audit.change_log`
    entry to explain why. Revoking every such row here, in the same
    transaction that closes the membership, means a reopened membership
    always starts with zero character relationships, exactly like it always
    already started with zero roles — any perspective it should regain
    requires an explicit new grant, auditable the normal way.

    Or does nothing (a harmless no-op, exactly like `revoke_membership_
    role`'s identical "already revoked" case) if `campaign_membership_id`
    is already ended — see `EndCampaignMembershipResult.ended`'s own
    docstring for how a caller distinguishes the two outcomes.

    Raises `MembershipNotInCampaignError` for a nonexistent `campaign_
    membership_id`, or one belonging to a different campaign than
    `campaign_id` (checked first, so this stays indistinguishable from "it
    never existed" for an unauthorized caller).

    Raises a plain `ValueError` (mapped by the existing generic handler to
    a fixed 400) if ending this membership would leave an *active* campaign
    with no membership holding `access.manage` — the identical retention
    invariant `revoke_membership_role`/`change_membership_role` enforce,
    via the same shared `_assert_active_campaign_retains_access_manager`
    helper; self-removal is permitted, with no special-case check anywhere
    in this function, subject to that same invariant exactly like every
    other self-mutation in this module. Skipped entirely for the no-op
    case, since an already-ended membership cannot newly violate an
    invariant nothing about this call changed.

    Locks the target membership row (`FOR UPDATE`) before evaluating
    anything, matching `revoke_membership_role`'s identical discipline for
    its own target row — so a concurrent removal of the same membership,
    or a concurrent role add/change/revoke against one of its role rows
    (each of which independently locks that specific `membership_roles`
    row, and, for `assign_membership_role`, the membership row itself), or
    (checkpoint-4 correction) a concurrent `grant_character_relationship`/
    `change_character_relationship` against one of its relationship rows
    (each of which independently locks the same membership row `FOR UPDATE
    OF cm`) cannot race between this function's own read and its writes:
    whichever transaction acquires the relevant lock first forces the
    other to wait, then re-observes the first's committed effect."""
    row = (
        connection.execute(
            text("""
                SELECT campaign_id, ended_at
                FROM security.campaign_memberships
                WHERE campaign_membership_id = :membership
                FOR UPDATE
            """),
            {"membership": campaign_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {campaign_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    if row["ended_at"] is not None:
        return EndCampaignMembershipResult(
            campaign_membership_id=campaign_membership_id,
            ended=False,
            revoked_membership_role_ids=(),
            revoked_membership_character_relationship_ids=(),
        )

    revoked_role_ids = (
        connection.execute(
            text("""
                UPDATE security.membership_roles SET revoked_at = now()
                WHERE campaign_membership_id = :membership AND revoked_at IS NULL
                RETURNING membership_role_id
            """),
            {"membership": campaign_membership_id},
        )
        .scalars()
        .all()
    )

    revoked_relationship_ids = (
        connection.execute(
            text("""
                UPDATE security.membership_character_relationships SET revoked_at = now()
                WHERE campaign_membership_id = :membership AND revoked_at IS NULL
                RETURNING membership_character_relationship_id
            """),
            {"membership": campaign_membership_id},
        )
        .scalars()
        .all()
    )

    revoked_status_id = lookup_id(
        connection, "security", "membership_statuses", "membership_status_id", "revoked"
    )
    connection.execute(
        text("""
            UPDATE security.campaign_memberships
            SET ended_at = now(), ended_by_membership_id = :actor, membership_status_id = :status
            WHERE campaign_membership_id = :membership
        """),
        {
            "actor": ended_by_membership_id,
            "status": revoked_status_id,
            "membership": campaign_membership_id,
        },
    )

    _assert_active_campaign_retains_access_manager(
        connection,
        campaign_id=campaign_id,
        detail=(
            f"ending membership {campaign_membership_id} would leave active campaign "
            f"{campaign_id} with no membership holding access.manage"
        ),
    )

    return EndCampaignMembershipResult(
        campaign_membership_id=campaign_membership_id,
        ended=True,
        revoked_membership_role_ids=tuple(revoked_role_ids),
        revoked_membership_character_relationship_ids=tuple(revoked_relationship_ids),
    )
