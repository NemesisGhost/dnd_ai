"""Campaign-creation bootstrap command (docs/PLAN.md Phase 10 "Still to
come" list: "the invitation-token acceptance flow and campaign-creation
bootstrap deferred at workstream 20" —
`dnd_ai.commands.memberships`'s own docstring reasoned that
`campaign.campaigns`/its first owning membership "must already exist by
some path before any `access.manage`-gated command could run at all —
bootstrapping a campaign's very first owner membership is left to whatever
future workstream builds campaign creation itself." This is that
workstream: without it, no campaign could ever be created through the
application API at all (CLAUDE.md rule 3), only by a test factory or a
direct database write.

Every other Phase 10 command trusts an already-resolved `AccessContext`'s
`campaign_id` as authorized; `create_campaign` has no such campaign to
authorize against yet — it is the one command in this codebase any
authenticated user may call unconditionally (see `dnd_ai.api.campaigns`'
own docstring for the authorization reasoning at the API layer).
`timeline_id`/`ruleset_version_id` are therefore genuinely caller-supplied,
untrusted values here, unlike almost every other command in this codebase,
which trusts campaign-scoped ids resolved from an already-authorized
`AccessContext`.

Creates `campaign.campaigns`, its first `security.campaign_memberships`
row for the creating user, and a `security.membership_roles` row assigning
the system-template `campaign_owner` role — the one role migration 080
seeded `security.assert_campaign_retains_access_manager()`'s own required
pairing onto (`access.manage`), and that migration 085 extended to the
full functional-owner capability set (`access.manage`, `campaign.view`,
`canon.edit`) this vertical slice's own gating routes actually need — all
in one transaction. `campaign.campaigns`' own
`tr_campaigns_retain_access_manager` constraint trigger (`security.
enforce_campaigns_retain_access_manager`, `AFTER INSERT`, `DEFERRABLE
INITIALLY DEFERRED`) therefore evaluates the fully-written-within-the-
transaction state at commit — never a two-step "create the campaign, then
separately add yourself as owner" sequence, which would leave a window (or
a legitimately failed second step) with an active campaign nobody could
manage. Because `campaign_owner` is the shared system-template row every
campaign's own owner membership references by `role_id` (migration 085's
own docstring), the creator immediately passes every `campaign.view`-gated
read and every `canon.edit`-gated command this codebase has — no separate
role-creation step, and no direct `security.roles`/`.role_capabilities`
write, is needed before a freshly created campaign is actually usable by
its owner.

`timeline_id` *does* need a per-caller entitlement check — a lesson
learned the hard way (docs/PLAN.md's own workstream 30 entry has the full
defect narrative): migration 085 gave a fresh campaign's owner `campaign.
view`/`canon.edit` in that campaign, which made "any authenticated user
may create a campaign on any existing timeline" (the original workstream
23 policy, when `create_campaign` only checked `timeline_id` *exists*) a
genuine privilege-escalation path — an attacker could manufacture a new
campaign over a *victim's* timeline and use their own fresh `campaign_
owner` membership to read that timeline's shared, GM-only canon (hidden
dungeon content, knowledge ground truth, internal organization
descriptions, anything else gated on `canon.edit`) despite never being
invited to the victim's own campaign. Docs/DOMAIN_MODEL.md §2.2's
"Multiple campaigns may share a timeline" documents that *sharing* a
timeline across campaigns is supported — it never says every authenticated
user is entitled to *initiate* that sharing for an arbitrary existing
timeline; `campaign.timelines` still carries no owner/entitlement column
of its own, so this workstream added the entitlement check at the one
place that does have an owner concept — `campaign.campaigns`' own
`security.campaign_memberships`/`.membership_roles`.

`_authorize_timeline_reuse()` (below) is the resulting policy, checked
before anything is written:

1. `SELECT ... FOR UPDATE` locks `timeline_id`'s own `campaign.timelines`
   row for the rest of the transaction. A nonexistent `timeline_id` raises
   `TimelineNotAuthorizedError` immediately — nothing to lock.
2. If **no** `campaign.campaigns` row references `timeline_id` yet, the
   caller must hold a live `security.timeline_bootstrap_grants` row
   naming both `timeline_id` and their own `creator_user_id` (`SELECT
   ... FOR UPDATE`, `consumed_at IS NULL`, `revoked_at IS NULL`,
   `expires_at > now()`). See "First-campaign entitlement" below for why
   "nobody has created a campaign here yet" was, on its own, a second
   Critical defect (docs/PLAN.md's own workstream 32 entry has the full
   narrative) rather than a legitimate policy — worlds/timelines/dungeon
   content/knowledge can all be authored before any campaign exists (the
   vertical-slice scenario's own step ordering depends on it), so absence
   of a prior campaign is not evidence the caller was ever meant to be the
   one who creates the first one.
3. If a `campaign.campaigns` row **does** already reference `timeline_id`,
   the caller must hold an active `access.manage` membership in *at
   least one* of them — the same capability `security.
   assert_campaign_retains_access_manager()` already treats as "this
   user administers this campaign." Anyone else, including a caller who
   only holds `campaign.view` in an existing campaign on that timeline,
   or who holds an otherwise-valid bootstrap grant for it (that grant
   only ever authorized being *first*; it is never consulted once a
   campaign already exists), is rejected. No bootstrap grant is consumed
   or even looked up on this branch.
4. Every rejection — a nonexistent `timeline_id`, an unclaimed one with
   no matching bootstrap grant, and an already-claimed one the caller
   isn't entitled to reuse — raises the identical
   `TimelineNotAuthorizedError` (a `DomainAuthorizationError`, fixed,
   non-disclosing 404): a caller probing random or guessed UUIDs, or a
   caller who once held a now-consumed/expired/revoked grant, can never
   learn which case applied, the same folding this codebase already
   applies to every other existence-is-a-disclosure check (`dnd_ai.api.
   access.PartyPerspectiveNotAuthorizedError`, `dnd_ai.commands.
   campaign_invitations.InvitationNotAcceptableError`, etc.).

## First-campaign entitlement: `security.timeline_bootstrap_grants`

A grant row (`timeline_bootstrap_grant_id`, `timeline_id`, `granted_to_
user_id`, an optional `granted_by_user_id` for provenance, `expires_at`,
`revoked_at`, and `consumed_at`/`consumed_by_campaign_id`, migration 087)
is the positive, server-verifiable entitlement step 2 requires — never a
bearer token like `security.campaign_invitations`: `granted_to_user_id`
binds the grant directly to an already-known `security.users` row, since
world-authoring infrastructure always knows exactly which user it is
bootstrapping a timeline for (there is no "invite an unknown email"
scenario here). This removes token leakage as an attack surface entirely,
directly satisfying "do not use UUID secrecy... as authorization" — a
caller who merely learns a `timeline_id` (by any means) still has nothing
usable unless a grant naming *their own* `user_id` also exists.

`grant_timeline_bootstrap()` (below) is the one function that writes this
table, called only by trusted world-authoring/import infrastructure —
never exposed over HTTP, the identical "no authoring endpoint exists yet"
scope boundary every other piece of pre-campaign content in this codebase
already has (`tests/factories.py`'s own world/timeline/dungeon/knowledge
helpers are exactly this same trust boundary today; a future import job is
the production caller). `create_campaign()` both validates *and consumes*
the matching grant in the identical transaction that creates the campaign
it authorizes — the `UPDATE ... SET consumed_at = now(), consumed_by_
campaign_id = :campaign` runs only after the campaign/membership/role
rows are fully written, so a later failure in that same request (the
ruleset check, most concretely) rolls back everything, including the
grant's own consumption: the grant is exactly as usable after a failed
attempt as it was before, proven by `tests/database/test_api_campaigns.
py`'s own atomicity case. Revocation and expiration are both checked by
the same authorization query (`revoked_at IS NULL`, `expires_at > now()`)
but, like `security.campaign_invitations.revoked_at`, have no dedicated
command that sets them yet — trusted infrastructure may set `revoked_at`
directly today, exactly as it does to create the grant in the first
place; migration 087's own docstring records this as a deliberate,
narrower scope than a full grant-management API, not an oversight.

Step 1's row lock is what makes step 2's grant consumption concurrency-
safe, not merely convenient: two concurrent `create_campaign` calls naming
the *same*, previously-unused `timeline_id` — whether they hold the same
grant (a retried request from the same user) or two different users' own
independent grants for it — serialize on that lock rather than both
observing "not yet consumed" and both consuming. Whichever transaction's
`SELECT ... FOR UPDATE` acquires the lock first proceeds through steps 2-4
and commits its own new campaign (consuming its own grant) before the
second transaction's identical `SELECT ... FOR UPDATE` is unblocked; the
second transaction then reaches step 3 (a campaign now exists) and, unless
it happens to already hold `access.manage` there, is correctly rejected —
its own still-valid, never-consumed grant notwithstanding, since a
bootstrap grant only ever authorizes being *first*. This is proven
directly by `tests/database/test_api_campaigns.py`'s own concurrent-claim
case: firing two `POST /campaigns` calls for the same fresh `timeline_id`,
each with its own valid grant, from two threads never leaves both
authorized, and never leaves more than one `campaign.campaigns` row on
that timeline.

Once authorized, a second campaign attaching to a timeline another
campaign already uses is exactly the "shared, reusable world content"
capability docs/DOMAIN_MODEL.md §2.2 describes — the persistent-world
model's whole premise is that a shared timeline's mutable state (dungeon
layout, NPCs, quest state) outlives and is visible across the campaigns
that play through it, while each campaign's own security state
(memberships, roles, resource grants) and each party's own knowledge
(`knowledge.party_discoveries`) stay isolated because those tables are
keyed by `campaign_id`/`party_id`, never by `timeline_id` alone. A newly
authorized campaign therefore still starts with zero memberships, zero
roles, and zero resource grants of its own — proven by `tests/database.
test_api_campaigns.py`'s own timeline-reuse case and by `tests/scenario.
test_vertical_slice_api.py`'s steps 17-18 (a second campaign on the same
timeline sees the first party's altered-but-not-hidden dungeon state,
never its private discoveries).

`granted_by_membership_id` is deliberately `NULL` for this one role
assignment: unlike `dnd_ai.commands.memberships.assign_membership_role`
(which always attributes a grant to the calling `AccessContext`'s own
pre-existing membership), there is no *other* membership yet that could
have granted this one — the creator's own brand-new membership is the row
being granted a role by the act of creating it, not a distinct grantor.

Both cross-scope invariants `campaign.enforce_campaign_ruleset_allowed()`
(migration 024) would otherwise enforce are pre-checked here instead,
proactively — mirroring `dnd_ai.commands.memberships`'s own "why relying on
the trigger alone would surface as an unclassified 500" reasoning. That
trigger fires `BEFORE INSERT`, resolves `NEW.ruleset_version_id` to a
ruleset before ever checking it exists, and raises the bare `ERRCODE =
'integrity_constraint_violation'` (SQLSTATE `23000`, unrecognized by the
generic `IntegrityError` handler) whenever the resulting `EXISTS` check
against `rules.world_rulesets` fails — which happens identically for a
`ruleset_version_id` that is a real ruleset version just not allowed for
the timeline's world, one that doesn't exist at all (comparing against a
NULL resolved `ruleset_id` never matches), and, more surprisingly, for a
`timeline_id` that doesn't exist at all either (a NULL resolved `world_id`
never matches, and the trigger fires ahead of `campaign.campaigns`' own
`timeline_id` foreign key, so that FK is never reached). `_authorize_
timeline_reuse()` already closes the `timeline_id` gap as part of its own
authorization check, above; `_check_ruleset_allowed()` closes the
`ruleset_version_id` gap with `CampaignRulesetNotAllowedError`, raised
identically for "doesn't exist" and "belongs to a disallowed ruleset
family" — mirroring `RoleNotUsableByCampaignError`'s identical folding, so
a caller probing with random UUIDs can't distinguish which ruleset
versions genuinely exist.

Idempotency-key support lives entirely at the API layer, not here: `dnd_ai.
api.campaigns.create_campaign_endpoint` reserves/replays via `dnd_ai.api.
idempotency.begin_campaign_creation_request()`/`complete_campaign_creation_
request()` against `security.campaign_creation_reservations` (migration
088) — a dedicated pre-campaign store, since the general-purpose `security.
idempotent_requests` table's `campaign_id` column is `NOT NULL` and this is
the one write in this codebase with no existing campaign to key a
reservation against until `create_campaign` itself returns. This command
function stays unaware of idempotency entirely, the same separation of
concerns every other Phase 10 command/API pair already keeps. Without it, a
dropped response and a naive client retry would fall through to `_
authorize_timeline_reuse()`'s *reuse* branch (the retry's own creator now
holds `access.manage` on the timeline it just claimed) and mint a second
campaign, membership, owner role, and audit row for what the caller
believes is one logical request — see `dnd_ai.api.idempotency`'s module
docstring for the full mechanism and concurrency argument."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError

from ._shared import lookup_id

_CAMPAIGN_OWNER_ROLE_CODE = "campaign_owner"
_ACCESS_MANAGE_CAPABILITY_CODE = "access.manage"
_ACTIVE_LIFECYCLE_STATUS_CODE = "active"
_ACTIVE_MEMBERSHIP_STATUS_CODE = "active"
_DEFAULT_BOOTSTRAP_GRANT_TTL = timedelta(days=7)


class TimelineNotAuthorizedError(DomainAuthorizationError):
    """Raised by `create_campaign()` when `timeline_id` does not resolve to
    a real `campaign.timelines` row, resolves to one no campaign has
    claimed yet but the caller holds no live `security.
    timeline_bootstrap_grants` row for it, or resolves to one already used
    by an existing campaign the caller holds no `access.manage` membership
    in — all indistinguishably (this module's own docstring has the full
    policy). Pre-checked here rather than left to `campaign.campaigns.
    timeline_id`'s own foreign key — see this module's docstring for why
    the `BEFORE INSERT`-fired `campaign.enforce_campaign_ruleset_allowed()`
    trigger would otherwise swallow a nonexistent `timeline_id` into an
    unclassified 500 first, before that FK is ever reached. The supplied
    `timeline_id`/`creator_user_id` are included only in the constructor's
    `detail` argument (`str(self)`), never in `safe_message`."""


class CampaignRulesetNotAllowedError(ValueError):
    """Raised by `create_campaign()` when `ruleset_version_id` does not
    resolve to a real `rules.ruleset_versions` row, or resolves to one
    whose ruleset family is not in `rules.world_rulesets` for
    `timeline_id`'s own world — both indistinguishably, mirroring
    `dnd_ai.commands.memberships.RoleNotUsableByCampaignError`'s identical
    "doesn't exist vs. not usable here" folding. See this module's
    docstring for why relying on `campaign.
    enforce_campaign_ruleset_allowed()`'s own raw `IntegrityError` alone
    would surface as an unclassified 500."""


@dataclass(frozen=True)
class CreateCampaignResult:
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID
    world_id: uuid.UUID


@dataclass(frozen=True)
class GrantTimelineBootstrapResult:
    timeline_bootstrap_grant_id: uuid.UUID


def grant_timeline_bootstrap(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    granted_to_user_id: uuid.UUID,
    granted_by_user_id: uuid.UUID | None = None,
    ttl: timedelta = _DEFAULT_BOOTSTRAP_GRANT_TTL,
) -> GrantTimelineBootstrapResult:
    """Issues a single-use `security.timeline_bootstrap_grants` row
    authorizing `granted_to_user_id` — and only that user — to create the
    *first* `campaign.campaigns` row on `timeline_id`. See this module's
    own docstring ("First-campaign entitlement") for the full policy this
    implements.

    Callable only by trusted world-authoring/import infrastructure —
    deliberately not exposed over HTTP, the same scope boundary every
    other piece of pre-campaign content in this codebase already has
    (`tests/factories.py`'s own world/timeline/dungeon/knowledge helpers
    are this exact trust boundary today; a future import job is the
    production caller). No pre-check against `timeline_id`/`granted_to_
    user_id` existing is performed here — an invalid id surfaces as an
    ordinary foreign-key `IntegrityError`, acceptable for a function with
    no untrusted caller, unlike every HTTP-reachable command in this
    package.

    `granted_by_user_id` is optional provenance only (who issued the
    grant), never part of the authorization check itself — `NULL`
    represents a system/import-job-issued grant with no human actor to
    attribute it to, the same "administrative source" concept CLAUDE.md
    rule 6 already accepts for event-less state changes."""
    grant_id = connection.execute(
        text("""
            INSERT INTO security.timeline_bootstrap_grants
                (timeline_id, granted_to_user_id, granted_by_user_id, expires_at)
            VALUES (:timeline, :granted_to, :granted_by, now() + :ttl)
            RETURNING timeline_bootstrap_grant_id
        """),
        {
            "timeline": timeline_id,
            "granted_to": granted_to_user_id,
            "granted_by": granted_by_user_id,
            "ttl": ttl,
        },
    ).scalar()
    assert isinstance(grant_id, uuid.UUID)
    return GrantTimelineBootstrapResult(timeline_bootstrap_grant_id=grant_id)


@dataclass(frozen=True)
class _TimelineAuthorization:
    world_id: uuid.UUID
    # Set only on the first-campaign (grant-consuming) path; None on the
    # reuse (access.manage) path, which never touches a bootstrap grant.
    bootstrap_grant_id: uuid.UUID | None


def _authorize_timeline_reuse(
    connection: Connection, *, timeline_id: uuid.UUID, creator_user_id: uuid.UUID
) -> _TimelineAuthorization:
    """Resolves `timeline_id`'s own `world_id`, having authorized
    `creator_user_id` to attach a new campaign to it — and, on the first-
    campaign path, having locked (but not yet consumed) the matching
    bootstrap grant, so `create_campaign` can mark it consumed only after
    the campaign it authorizes actually exists. See this module's
    docstring for the full policy and its concurrency-safety argument;
    briefly: locks the timeline row, requires a live bootstrap grant for
    an unclaimed timeline, and otherwise requires an active `access.
    manage` membership in at least one existing campaign already on it."""
    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :timeline FOR UPDATE"),
        {"timeline": timeline_id},
    ).scalar()
    if world_id is None:
        raise TimelineNotAuthorizedError(f"timeline {timeline_id} does not exist")
    assert isinstance(world_id, uuid.UUID)

    already_used = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM campaign.campaigns WHERE timeline_id = :timeline)"),
        {"timeline": timeline_id},
    ).scalar()

    if not already_used:
        grant_id = connection.execute(
            text("""
                SELECT timeline_bootstrap_grant_id
                FROM security.timeline_bootstrap_grants
                WHERE timeline_id = :timeline
                  AND granted_to_user_id = :user
                  AND consumed_at IS NULL
                  AND revoked_at IS NULL
                  AND expires_at > now()
                FOR UPDATE
            """),
            {"timeline": timeline_id, "user": creator_user_id},
        ).scalar()
        if grant_id is None:
            raise TimelineNotAuthorizedError(
                f"user {creator_user_id} holds no live bootstrap grant for unclaimed timeline "
                f"{timeline_id}"
            )
        assert isinstance(grant_id, uuid.UUID)
        return _TimelineAuthorization(world_id=world_id, bootstrap_grant_id=grant_id)

    is_entitled = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM campaign.campaigns c
                JOIN security.campaign_memberships cm ON cm.campaign_id = c.campaign_id
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                JOIN security.membership_roles mr
                    ON mr.campaign_membership_id = cm.campaign_membership_id
                JOIN security.roles r ON r.role_id = mr.role_id
                JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
                WHERE c.timeline_id = :timeline
                  AND cm.user_id = :user
                  AND cm.ended_at IS NULL
                  AND ms.code = 'active' AND ms.is_active
                  AND mr.revoked_at IS NULL
                  AND (mr.expires_at IS NULL OR mr.expires_at > now())
                  AND r.is_active
                  AND cap.code = :capability AND cap.is_active
            )
        """),
        {
            "timeline": timeline_id,
            "user": creator_user_id,
            "capability": _ACCESS_MANAGE_CAPABILITY_CODE,
        },
    ).scalar()
    if not is_entitled:
        raise TimelineNotAuthorizedError(
            f"user {creator_user_id} holds no active access.manage membership in any existing "
            f"campaign on timeline {timeline_id}"
        )
    return _TimelineAuthorization(world_id=world_id, bootstrap_grant_id=None)


def _check_ruleset_allowed(
    connection: Connection, *, world_id: uuid.UUID, ruleset_version_id: uuid.UUID
) -> None:
    allowed = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM rules.ruleset_versions rv
                JOIN rules.world_rulesets wr ON wr.ruleset_id = rv.ruleset_id
                WHERE rv.ruleset_version_id = :ruleset_version AND wr.world_id = :world
            )
        """),
        {"ruleset_version": ruleset_version_id, "world": world_id},
    ).scalar()
    if not allowed:
        raise CampaignRulesetNotAllowedError(
            f"ruleset version {ruleset_version_id} is not allowed for world {world_id}"
        )


def create_campaign(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
    name: str,
    creator_user_id: uuid.UUID,
    description: str | None = None,
) -> CreateCampaignResult:
    """Creates `campaign.campaigns` plus the creator's own `campaign_owner`
    membership, atomically. See this module's docstring for the full
    reasoning, including why `timeline_id`/`ruleset_version_id` are
    pre-checked before anything is written."""
    authorization = _authorize_timeline_reuse(
        connection, timeline_id=timeline_id, creator_user_id=creator_user_id
    )
    world_id = authorization.world_id
    _check_ruleset_allowed(connection, world_id=world_id, ruleset_version_id=ruleset_version_id)

    active_lifecycle_status_id = lookup_id(
        connection,
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        _ACTIVE_LIFECYCLE_STATUS_CODE,
    )
    campaign_id = connection.execute(
        text("""
            INSERT INTO campaign.campaigns
                (timeline_id, name, description, lifecycle_status_id, ruleset_version_id,
                 started_at)
            VALUES (:timeline, :name, :description, :status, :ruleset_version, now())
            RETURNING campaign_id
        """),
        {
            "timeline": timeline_id,
            "name": name,
            "description": description,
            "status": active_lifecycle_status_id,
            "ruleset_version": ruleset_version_id,
        },
    ).scalar()
    assert isinstance(campaign_id, uuid.UUID)

    active_membership_status_id = lookup_id(
        connection,
        "security",
        "membership_statuses",
        "membership_status_id",
        _ACTIVE_MEMBERSHIP_STATUS_CODE,
    )
    campaign_membership_id = connection.execute(
        text("""
            INSERT INTO security.campaign_memberships
                (campaign_id, user_id, membership_status_id, joined_at)
            VALUES (:campaign, :user, :status, now())
            RETURNING campaign_membership_id
        """),
        {
            "campaign": campaign_id,
            "user": creator_user_id,
            "status": active_membership_status_id,
        },
    ).scalar()
    assert isinstance(campaign_membership_id, uuid.UUID)

    # Deliberately not dnd_ai.commands._shared.lookup_id: that helper
    # matches on code alone, but security.roles.code is only guaranteed
    # unique among system templates (ux_roles_system_code, WHERE
    # campaign_id IS NULL) — a campaign-scoped role could coincidentally
    # reuse the same code. The brand-new campaign created above can't yet
    # own such a role, but this stays explicit about which row is wanted
    # rather than relying on that.
    campaign_owner_role_id = connection.execute(
        text("SELECT role_id FROM security.roles WHERE code = :code AND campaign_id IS NULL"),
        {"code": _CAMPAIGN_OWNER_ROLE_CODE},
    ).scalar()
    assert isinstance(campaign_owner_role_id, uuid.UUID)

    connection.execute(
        text("""
            INSERT INTO security.membership_roles
                (campaign_membership_id, role_id, granted_by_membership_id)
            VALUES (:membership, :role, NULL)
        """),
        {"membership": campaign_membership_id, "role": campaign_owner_role_id},
    )

    # Consumed last, only once the campaign it authorized is fully
    # written — a failure anywhere above (including the ruleset check,
    # before this point) rolls back the whole transaction and leaves the
    # grant exactly as usable as it was before the attempt. See this
    # module's docstring ("First-campaign entitlement") for why this
    # can't simply be a pre-check: the grant only makes sense to mark
    # spent once it is certain a campaign now exists to attribute it to.
    if authorization.bootstrap_grant_id is not None:
        connection.execute(
            text("""
                UPDATE security.timeline_bootstrap_grants
                SET consumed_at = now(), consumed_by_campaign_id = :campaign
                WHERE timeline_bootstrap_grant_id = :grant
            """),
            {"campaign": campaign_id, "grant": authorization.bootstrap_grant_id},
        )

    return CreateCampaignResult(
        campaign_id=campaign_id,
        campaign_membership_id=campaign_membership_id,
        world_id=world_id,
    )
