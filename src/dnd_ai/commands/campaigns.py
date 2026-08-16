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
   caller may claim it unconditionally — this is a deliberate policy
   choice, not an oversight: nothing in this schema gives a bare world or
   timeline its own entitlement concept independent of the campaigns
   played on it (no `world`/`timeline`-scoped membership table exists,
   and inventing one is a materially larger schema change than this
   defect needs — see CLAUDE.md §5's guidance to flag rather than
   quietly invent a new domain concept). "First authenticated caller may
   claim an unused timeline" mirrors the exact same trust boundary
   `create_campaign` has always had for *any* campaign creation (any
   authenticated user may create the very first campaign anywhere) — it
   is not a new, weaker boundary introduced here.
3. If a `campaign.campaigns` row **does** already reference `timeline_id`,
   the caller must hold an active `access.manage` membership in *at
   least one* of them — the same capability `security.
   assert_campaign_retains_access_manager()` already treats as "this
   user administers this campaign." Anyone else, including a caller who
   only holds `campaign.view` in an existing campaign on that timeline,
   is rejected.
4. Both rejections — a nonexistent `timeline_id` and an existing one the
   caller isn't entitled to reuse — raise the identical
   `TimelineNotAuthorizedError` (a `DomainAuthorizationError`, fixed,
   non-disclosing 404): a caller probing random or guessed UUIDs can never
   learn which case applied, the same folding this codebase already
   applies to every other existence-is-a-disclosure check (`dnd_ai.api.
   access.PartyPerspectiveNotAuthorizedError`, `dnd_ai.commands.
   campaign_invitations.InvitationNotAcceptableError`, etc.).

Step 1's row lock is what makes step 2 concurrency-safe, not merely
convenient: two concurrent `create_campaign` calls naming the *same*,
previously-unused `timeline_id` serialize on that lock rather than both
observing "no campaign yet" and both writing one. Whichever transaction's
`SELECT ... FOR UPDATE` acquires the lock first proceeds through steps 2-4
and commits its own new campaign before the second transaction's identical
`SELECT ... FOR UPDATE` is unblocked; the second transaction then reaches
step 3 and finds the *first* transaction's campaign already there — for
two unrelated callers, the second is correctly rejected (no membership in
the first caller's brand-new campaign), even though at the instant both
requests arrived, neither campaign existed yet. This is proven directly by
`tests/database/test_api_campaigns.py`'s own concurrent-claim case: firing
two `POST /campaigns` calls for the same fresh `timeline_id` from two
threads never leaves both authorized, and never leaves more than one
`campaign.campaigns` row on that timeline.

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

Deliberately out of scope: idempotency-key support. Every other Phase 10
write endpoint durably reserves its `Idempotency-Key` in `security.
idempotent_requests`, but that table's `campaign_id` column is `NOT NULL`
with a foreign key to `campaign.campaigns` (migration 082) — a real
structural requirement, not an oversight, everywhere else in this codebase
that a command endpoint always names an already-existing campaign it was
authorized against. `create_campaign` is the one write with no such
campaign to key a reservation against yet, so a dropped response or a
naive client retry genuinely creates a second campaign rather than
replaying the first. Closing this would need its own schema extension (a
nullable `campaign_id`, or a separate pre-campaign reservation table) —
left to a future workstream that actually needs it, not invented
speculatively here."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError

from ._shared import lookup_id

_CAMPAIGN_OWNER_ROLE_CODE = "campaign_owner"
_ACCESS_MANAGE_CAPABILITY_CODE = "access.manage"
_ACTIVE_LIFECYCLE_STATUS_CODE = "active"
_ACTIVE_MEMBERSHIP_STATUS_CODE = "active"


class TimelineNotAuthorizedError(DomainAuthorizationError):
    """Raised by `create_campaign()` when `timeline_id` does not resolve to
    a real `campaign.timelines` row, or resolves to one already used by an
    existing campaign the caller holds no `access.manage` membership in —
    both indistinguishably (this module's own docstring has the full
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


def _authorize_timeline_reuse(
    connection: Connection, *, timeline_id: uuid.UUID, creator_user_id: uuid.UUID
) -> uuid.UUID:
    """Resolves `timeline_id`'s own `world_id`, having authorized
    `creator_user_id` to attach a new campaign to it. See this module's
    docstring for the full policy and its concurrency-safety argument;
    briefly: locks the timeline row, allows an unclaimed timeline
    unconditionally, and otherwise requires an active `access.manage`
    membership in at least one existing campaign already on it."""
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
        return world_id

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
    return world_id


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
    world_id = _authorize_timeline_reuse(
        connection, timeline_id=timeline_id, creator_user_id=creator_user_id
    )
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

    return CreateCampaignResult(
        campaign_id=campaign_id,
        campaign_membership_id=campaign_membership_id,
        world_id=world_id,
    )
