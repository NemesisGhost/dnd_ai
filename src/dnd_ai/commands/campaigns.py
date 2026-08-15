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
the system-template `campaign_owner` role — the one role/capability
pairing `security.assert_campaign_retains_access_manager()` itself
requires to exist, per migration 080's own seed comment — all in one
transaction. `campaign.campaigns`' own `tr_campaigns_retain_access_manager`
constraint trigger (`security.enforce_campaigns_retain_access_manager`,
`AFTER INSERT`, `DEFERRABLE INITIALLY DEFERRED`) therefore evaluates the
fully-written-within-the-transaction state at commit — never a two-step
"create the campaign, then separately add yourself as owner" sequence,
which would leave a window (or a legitimately failed second step) with an
active campaign nobody could manage.

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
`timeline_id` foreign key, so that FK is never reached). `_resolve_
timeline_world()` closes the `timeline_id` gap with a dedicated
`TimelineNotFoundError`; `_check_ruleset_allowed()` closes the
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

from ._shared import lookup_id

_CAMPAIGN_OWNER_ROLE_CODE = "campaign_owner"
_ACTIVE_LIFECYCLE_STATUS_CODE = "active"
_ACTIVE_MEMBERSHIP_STATUS_CODE = "active"


class TimelineNotFoundError(ValueError):
    """Raised by `create_campaign()` when `timeline_id` does not resolve to
    a real `campaign.timelines` row. Pre-checked here rather than left to
    `campaign.campaigns.timeline_id`'s own foreign key — see this module's
    docstring for why the `BEFORE INSERT`-fired `campaign.
    enforce_campaign_ruleset_allowed()` trigger would otherwise swallow
    this into an unclassified 500 first, before that FK is ever reached."""


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


def _resolve_timeline_world(connection: Connection, timeline_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :timeline"),
        {"timeline": timeline_id},
    ).scalar()
    if world_id is None:
        raise TimelineNotFoundError(f"timeline {timeline_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
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
    world_id = _resolve_timeline_world(connection, timeline_id)
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
