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
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

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
    `safe_message`."""


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
    `campaign_membership_id`/`role_id` do). Raises
    `MembershipNotInCampaignError` for a `campaign_membership_id` outside
    `campaign_id`, or `RoleNotUsableByCampaignError` for a `role_id` that
    is neither a system template nor scoped to `campaign_id` — both before
    any row is written. A retry assigning the same still-active role again
    is rejected as a 409 by `ux_membership_roles_active` (existing
    `IntegrityError` handler)."""
    membership_campaign_id = connection.execute(
        text(
            "SELECT campaign_id FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :membership"
        ),
        {"membership": campaign_membership_id},
    ).scalar()
    if membership_campaign_id is None or membership_campaign_id != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {campaign_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {membership_campaign_id})"
        )

    role_row = (
        connection.execute(
            text("SELECT campaign_id FROM security.roles WHERE role_id = :role"),
            {"role": role_id},
        )
        .mappings()
        .one_or_none()
    )
    if role_row is None or (
        role_row["campaign_id"] is not None and role_row["campaign_id"] != campaign_id
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


def revoke_membership_role(
    connection: Connection, *, membership_role_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """Revokes `membership_role_id` (sets `revoked_at`), or does nothing if
    it was already revoked — a retry is a harmless no-op, needing no
    idempotency-key store. Raises `MembershipNotInCampaignError` for a
    nonexistent `membership_role_id` or one belonging to a different
    campaign than `campaign_id`. Raises a plain `ValueError` (mapped by
    the existing generic handler to a fixed 400, like every other
    unclassified domain validation failure in this codebase) if revoking
    it would leave an *active* campaign with no membership holding
    `access.manage` — mirroring `security.
    assert_campaign_retains_access_manager()`'s own "only active campaigns
    are checked" scope exactly, via the same read-only `security.
    campaign_has_access_manager()` helper that function's own docstring
    names as the pre-check counterpart. Locks the target row (`FOR UPDATE`)
    before evaluating either check, so a concurrent revoke of a different
    role in the same campaign cannot race past this one."""
    row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id
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
