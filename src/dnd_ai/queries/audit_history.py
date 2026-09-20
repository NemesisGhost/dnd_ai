"""Campaign-scoped audit-history read query (Phase 13E-B audit-history
workstream — the independent foundation for a later Access-page UI; see
`docs/AUDIT_HISTORY_API.md`).

`audit.change_log` (docs/architecture/DATABASE_MODEL.md §19, "Audit";
`src/dnd_ai/persistence/tables/audit.py`, revision 007) is an append-only,
cross-campaign, cross-domain ledger: every row carries `world_id` (the
change's world), never a `campaign_id` — a deliberate omission, not a gap,
since most audited tables (character state, quests, relationships,
interactions, ...) are world/entity-scoped and shared across every
campaign playing that world's timeline(s), not owned by one campaign at
all (`campaign.campaigns`'s own comment: "Does not own world entities — it
reaches them through participation, discovery, state, and event
records"). Filtering `audit.change_log` by `world_id` alone would leak a
*different* campaign's membership/role/grant history whenever two
campaigns share a timeline (`campaign.campaigns.timeline_id`'s own
comment: "Not unique: two campaigns may share one timeline").

This module deliberately does **not** attempt a generic "every audited
table, scoped by world" history. It resolves an **exact** `campaign_id`
for a curated, explicit allowlist of `command_name` values — every command
in `dnd_ai.api.memberships`/`.access_grants`/`.campaign_invitations`/
`.campaigns` that writes an `audit.change_log` row for a campaign-access
concern (`docs/PHASE13E_ACCESS_CONTRACT.md` §2/§3) — by joining each row's
`record_id` back to the *actual* table it names (`schema_name`/
`table_name`, also recorded on every row) and reading that table's own
`campaign_id` (directly, or one hop through `security.campaign_memberships
.campaign_id` for a membership-scoped child row). That join is exact, not
approximate: none of these tables is ever physically deleted by an
application command (every one of them closes a row instead — `revoked_at`
/`ended_at`/`consumed_at` — CLAUDE.md rule 9, and each table's own
migration comment above), so a `record_id` this module already knows came
from one of these six tables always resolves. `command_name` is itself
safe to filter and branch on: `dnd_ai.api.audit.record_change_log`'s own
docstring establishes it is always a fixed literal a call site supplies,
never derived from request data.

**Scope (13E-B audit-history foundation).** Exactly the categories the
Access page's own mutations produce — membership, role, character
relationship, resource grant, invitation, and campaign creation. A wider
"every audited table" history is a different, materially harder feature
(entity/state/narrative audit trails are not campaign-scoped at all in
this schema) and is explicitly out of scope here; see this module's and
`docs/AUDIT_HISTORY_API.md`'s own "Known limitations" sections.

**Safe presentation only.** This module never *returns* `audit.change_log
.changed_fields` (arbitrary JSONB), `reason`, `correlation_id`,
`causation_id`, `ai_proposal_id`, or any Foundry-credential column — only
the fixed, reviewed column set a `dnd_ai.api.audit_history` response
allowlists. The one exception to "never reads" is internal to the SQL: the
`change_membership_role` rows of the role branch extract exactly one key, `changed_fields.previous_membership_role_id`, and only after
validating it is a canonical UUID string, to identify a role change's actual
predecessor assignment (`previous_status` is a code that a system role and a
campaign role may share, so it cannot identify one). That identifier is used
solely as a join key and is not part of any selected output column. `change_summary`/action/category labels are generated
server-side from the closed `command_name` vocabulary below, never echoed
from caller-supplied or free-text data.

**Actor/target fidelity (documented limitation).** Every label here —
actor display name, target account/character name, role/relationship-type/
capability display name — is resolved by joining to that record's
*current* row (`security.users.display_name`, `core.entities
.canonical_name`, `security.roles.display_name`, ...), not a point-in-time
snapshot. This schema keeps no such snapshot for these tables. A renamed
account, character, role, or capability shows its **current** name against
a historical event.

The "actor/target was deleted, so this falls back to a fixed placeholder"
branches (`_PLACEHOLDER_*` below) are real code, but — confirmed by
deliberately attempting exactly this during this module's own development
— **provably unreachable** for any of the six tables this module joins
against, while an `audit.change_log` row referencing them survives:
`audit.change_log`'s own `ck_change_log_actor_present` CHECK constraint
("at least one of `actor_user_id`/`actor_service`") makes PostgreSQL
*refuse* to delete a `security.users` row that is the sole actor
identifier of an existing `change_log` row at all — the `ON DELETE SET
NULL` cascade that would otherwise null `actor_user_id` is itself rejected
as a constraint violation before it can complete. Every account/character/
role/relationship-type/capability/access-group target column this module
reads is similarly either `ON DELETE RESTRICT` (blocks the delete
outright) or `ON DELETE CASCADE` from a table this module also joins by
the same `change_log.record_id` (the *whole* row disappears from the
query's result set rather than surfacing with a missing label) — and, per
CLAUDE.md rule 9, no application command in this codebase physically
deletes any of them anyway. The placeholder branches remain as genuine
defense in depth, not dead code to be removed — a direct, out-of-band data
repair is still conceivable — but they are unreachable through any
FK-respecting write path today; `tests/unit/test_audit_history_query.py`
exercises them directly as pure functions for exactly that reason, since
no realistic database fixture can.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

# ---------------------------------------------------------------------------
# The closed command_name -> category/action-label allowlist
# ---------------------------------------------------------------------------
#
# Two independent groupings of the same closed command_name vocabulary —
# deliberately kept separate, not derived from one another:
#
# - The "*_TABLE_COMMANDS" tuples below group commands by which table their
#   audit.change_log.record_id actually resolves against (the SQL UNION ALL
#   branch each command's rows are found in). This is a join-correctness
#   grouping: `accept_campaign_invitation` (dnd_ai.api.campaign_invitations
#   ._activate_or_create_membership) writes record_id = the *membership* it
#   creates/activates, table_name='campaign_memberships' — NOT a
#   campaign_invitations row — so it must be read out of the
#   campaign_memberships branch even though it is presented as the
#   "invitation" *category* below. Grouping by category instead would
#   silently drop every accept_campaign_invitation row (the join to
#   security.campaign_invitations would never match its record_id at all).
# - `_COMMANDS_BY_CATEGORY` groups the identical commands by the *category*
#   a caller filters/sees them under — a presentation grouping, independent
#   of which table branch produced the row.
_MEMBERSHIP_TABLE_COMMANDS: tuple[str, ...] = (
    "add_campaign_member",
    "end_campaign_membership",
    "accept_campaign_invitation",
)
_ROLE_TABLE_COMMANDS: tuple[str, ...] = (
    "assign_membership_role",
    "revoke_membership_role",
    "change_membership_role",
)
_RELATIONSHIP_TABLE_COMMANDS: tuple[str, ...] = (
    "grant_character_relationship",
    "change_character_relationship",
    "revoke_character_relationship",
)
_GRANT_TABLE_COMMANDS: tuple[str, ...] = ("create_resource_grant", "revoke_resource_grant")
_INVITATION_TABLE_COMMANDS: tuple[str, ...] = ("create_campaign_invitation",)
_CAMPAIGN_TABLE_COMMANDS: tuple[str, ...] = ("create_campaign",)
# Phase 13E-B checkpoint 6. Grouped separately from _GRANT_TABLE_COMMANDS
# even though both concern access groups: these resolve against
# security.access_groups/.access_group_memberships directly (the record_id
# *is* the group/membership row), never against security.resource_grants
# — a group-owned resource grant's own create/revoke events already join
# through the existing grant branch above (its grantee_access_group_id
# column resolves grantee_group_name identically for a member- or
# group-targeted grant).
_ACCESS_GROUP_TABLE_COMMANDS: tuple[str, ...] = (
    "create_access_group",
    "update_access_group",
    "deactivate_access_group",
    "reactivate_access_group",
)
_ACCESS_GROUP_MEMBERSHIP_TABLE_COMMANDS: tuple[str, ...] = (
    "add_access_group_member",
    "remove_access_group_member",
)

# Public category vocabulary — the `category` query-parameter filter's
# closed set, and the `category` value returned on every item.
AUDIT_CATEGORIES: tuple[str, ...] = (
    "membership",
    "role",
    "character_relationship",
    "resource_grant",
    "invitation",
    "campaign",
    "access_group",
    "access_group_membership",
)

_COMMANDS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "membership": ("add_campaign_member", "end_campaign_membership"),
    "role": _ROLE_TABLE_COMMANDS,
    "character_relationship": _RELATIONSHIP_TABLE_COMMANDS,
    "resource_grant": _GRANT_TABLE_COMMANDS,
    "invitation": ("create_campaign_invitation", "accept_campaign_invitation"),
    "campaign": _CAMPAIGN_TABLE_COMMANDS,
    "access_group": _ACCESS_GROUP_TABLE_COMMANDS,
    "access_group_membership": _ACCESS_GROUP_MEMBERSHIP_TABLE_COMMANDS,
}

# Every command_name this query recognizes at all, in one flat tuple — the
# outer filter when no `category` was requested.
_ALL_COMMANDS: tuple[str, ...] = tuple(
    command for commands in _COMMANDS_BY_CATEGORY.values() for command in commands
)

_CATEGORY_BY_COMMAND: dict[str, str] = {
    command: category
    for category, commands in _COMMANDS_BY_CATEGORY.items()
    for command in commands
}

# Server-owned, fixed action labels — never derived from free text. Keyed
# by the same closed command_name vocabulary above.
_ACTION_LABEL_BY_COMMAND: dict[str, str] = {
    "add_campaign_member": "Member added",
    "end_campaign_membership": "Member removed",
    "assign_membership_role": "Role added",
    "revoke_membership_role": "Role revoked",
    "change_membership_role": "Role changed",
    "grant_character_relationship": "Character relationship added",
    "change_character_relationship": "Character relationship changed",
    "revoke_character_relationship": "Character relationship revoked",
    "create_resource_grant": "Access grant created",
    "revoke_resource_grant": "Access grant revoked",
    "create_campaign_invitation": "Invitation sent",
    "accept_campaign_invitation": "Invitation accepted",
    "create_campaign": "Campaign created",
    "create_access_group": "Access group created",
    "update_access_group": "Access group updated",
    "deactivate_access_group": "Access group deactivated",
    "reactivate_access_group": "Access group reactivated",
    "add_access_group_member": "Access group member added",
    "remove_access_group_member": "Access group member removed",
}

KEYSET = "campaign_audit_history"

_PLACEHOLDER_ACCOUNT_LABEL = "Removed account"
_PLACEHOLDER_CHARACTER_LABEL = "Removed character"
_PLACEHOLDER_ROLE_LABEL = "Removed role"
_UNKNOWN_PREVIOUS_ROLE_LABEL = "Unknown role"
_PLACEHOLDER_RELATIONSHIP_TYPE_LABEL = "Removed relationship type"
_PLACEHOLDER_CAPABILITY_LABEL = "Removed capability"
_PLACEHOLDER_GROUP_LABEL = "Removed access group"


@dataclass(frozen=True)
class AuditHistoryItem:
    change_log_id: int
    occurred_at: datetime
    category: str
    action_label: str
    actor_label: str
    actor_type: str
    """`"user"` (a resolved `security.users` display name), `"service"`
    (`audit.change_log.actor_service`, itself always a fixed literal), or
    `"unknown"` (defensive fallback — see the module docstring's
    "Actor/target fidelity" section)."""
    target_label: str | None
    target_type: str | None
    """`"account"`, `"character"`, or `"access_group"` — the kind of thing
    `target_label` names, or `None` when this category has no single
    discrete target (invitation, campaign)."""
    change_summary: str | None
    outcome: str | None
    """Reserved for a future category whose action can fail/be denied
    (e.g. a login failure, out of this module's current scope — see the
    module docstring). Always `None` for every category this module
    currently resolves; included so the response contract does not need to
    change shape when one is added."""


def _validate_category(category: str | None) -> tuple[str, ...]:
    if category is None:
        return _ALL_COMMANDS
    if category not in _COMMANDS_BY_CATEGORY:
        raise ValueError(f"unknown audit history category {category!r}")
    return _COMMANDS_BY_CATEGORY[category]


_QUERY = """
    WITH scoped AS (
        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            cm.campaign_id AS resolved_campaign_id,
            cm.user_id AS target_user_id,
            NULL::uuid AS target_character_id,
            NULL::uuid AS role_id,
            NULL::uuid AS relationship_type_id,
            NULL::uuid AS grant_capability_id,
            NULL::uuid AS grantee_membership_id,
            NULL::uuid AS grantee_access_group_id,
            NULL::uuid AS role_membership_id,
            NULL::uuid AS previous_membership_role_id
        FROM audit.change_log cl
        JOIN security.campaign_memberships cm ON cm.campaign_membership_id = cl.record_id
        WHERE cl.command_name = ANY(CAST(:membership_commands AS text[]))

        UNION ALL

        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            cm.campaign_id, cm.user_id, NULL::uuid,
            mr.role_id, NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid,
            mr.campaign_membership_id,
            CASE
                WHEN cl.command_name = 'change_membership_role'
                 AND jsonb_typeof(cl.changed_fields -> 'previous_membership_role_id') = 'string'
                 AND (cl.changed_fields ->> 'previous_membership_role_id')
                     ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN CAST(cl.changed_fields ->> 'previous_membership_role_id' AS uuid)
            END
        FROM audit.change_log cl
        JOIN security.membership_roles mr ON mr.membership_role_id = cl.record_id
        JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
        WHERE cl.command_name = ANY(CAST(:role_commands AS text[]))

        UNION ALL

        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            cm.campaign_id, NULL::uuid, mcr.character_id,
            NULL::uuid, mcr.character_relationship_type_id, NULL::uuid, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::uuid
        FROM audit.change_log cl
        JOIN security.membership_character_relationships mcr
            ON mcr.membership_character_relationship_id = cl.record_id
        JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mcr.campaign_membership_id
        WHERE cl.command_name = ANY(CAST(:relationship_commands AS text[]))

        UNION ALL

        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            rg.campaign_id, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::uuid, rg.capability_id,
            rg.grantee_campaign_membership_id, rg.grantee_access_group_id,
            NULL::uuid, NULL::uuid
        FROM audit.change_log cl
        JOIN security.resource_grants rg ON rg.resource_grant_id = cl.record_id
        WHERE cl.command_name = ANY(CAST(:grant_commands AS text[]))

        UNION ALL

        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            ci.campaign_id, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::uuid
        FROM audit.change_log cl
        JOIN security.campaign_invitations ci ON ci.campaign_invitation_id = cl.record_id
        WHERE cl.command_name = ANY(CAST(:invitation_commands AS text[]))

        UNION ALL

        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            c.campaign_id, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::uuid
        FROM audit.change_log cl
        JOIN campaign.campaigns c ON c.campaign_id = cl.record_id
        WHERE cl.command_name = ANY(CAST(:campaign_commands AS text[]))

        UNION ALL

        -- Phase 13E-B checkpoint 6: security.access_groups' own lifecycle
        -- commands. The record IS the group, so grantee_access_group_id
        -- (otherwise a resource_grants column) is reused here to name it
        -- — the existing grantee_group join below then resolves its name
        -- identically to how it already resolves a group-grantee's name
        -- for the resource-grant branch above.
        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            ag.campaign_id, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid, ag.access_group_id,
            NULL::uuid, NULL::uuid
        FROM audit.change_log cl
        JOIN security.access_groups ag ON ag.access_group_id = cl.record_id
        WHERE cl.command_name = ANY(CAST(:access_group_commands AS text[]))

        UNION ALL

        -- Phase 13E-B checkpoint 6: security.access_group_memberships' own
        -- add/remove commands. target_user_id is reused to name the added/
        -- removed member (the existing target_user join below resolves
        -- their display name identically to the membership/role branches
        -- above); grantee_access_group_id is reused to name the owning
        -- group, exactly like the access_groups branch above.
        SELECT
            cl.change_log_id, cl.command_name, cl.recorded_at,
            cl.actor_user_id, cl.actor_service, cl.previous_status, cl.new_status,
            cm.campaign_id, cm.user_id, NULL::uuid,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid, agm.access_group_id,
            NULL::uuid, NULL::uuid
        FROM audit.change_log cl
        JOIN security.access_group_memberships agm
            ON agm.access_group_membership_id = cl.record_id
        JOIN security.campaign_memberships cm
            ON cm.campaign_membership_id = agm.campaign_membership_id
        WHERE cl.command_name = ANY(CAST(:access_group_membership_commands AS text[]))
    )
    SELECT
        s.change_log_id, s.command_name, s.recorded_at, s.previous_status, s.new_status,
        s.actor_user_id, actor.display_name AS actor_display_name, s.actor_service,
        s.target_user_id, target_user.display_name AS target_user_display_name,
        s.target_character_id, target_entity.canonical_name AS target_character_name,
        role.display_name AS role_display_name,
        prev_role.display_name AS previous_role_display_name,
        rel_type.display_name AS relationship_type_display_name,
        prev_rel_type.display_name AS previous_relationship_type_display_name,
        capability.display_name AS capability_display_name,
        s.grantee_membership_id, grantee_user.display_name AS grantee_user_display_name,
        s.grantee_access_group_id, grantee_group.name AS grantee_group_name
    FROM scoped s
    LEFT JOIN security.users actor ON actor.user_id = s.actor_user_id
    LEFT JOIN security.users target_user ON target_user.user_id = s.target_user_id
    LEFT JOIN core.entities target_entity ON target_entity.entity_id = s.target_character_id
    LEFT JOIN security.roles role ON role.role_id = s.role_id
    -- The previous role is resolved by identity, never by code: a system
    -- role and a role of this campaign may share a `code`, so
    -- `previous_status` alone can match two rows. `previous_membership_role_id`
    -- (recorded by `change_membership_role`, validated as a UUID in the
    -- `scoped` CTE) names the exact revoked assignment; it must belong to
    -- the same membership as the audited row (hence the same campaign), and
    -- its role must be a system template or this campaign's own role whose
    -- `code` still equals the recorded `previous_status`. Every key here is
    -- a primary key, so this can never multiply rows. Anything that fails
    -- validation (legacy row without the key, malformed value, foreign or
    -- unrelated assignment, code disagreement) leaves `prev_role` NULL and
    -- `_change_summary` shows the recorded code as-is rather than guessing.
    LEFT JOIN security.membership_roles prev_mr
        ON prev_mr.membership_role_id = s.previous_membership_role_id
       AND prev_mr.campaign_membership_id = s.role_membership_id
    LEFT JOIN security.roles prev_role
        ON prev_role.role_id = prev_mr.role_id
       AND prev_role.code = s.previous_status
       AND (prev_role.campaign_id IS NULL OR prev_role.campaign_id = s.resolved_campaign_id)
    LEFT JOIN security.character_relationship_types rel_type
        ON rel_type.character_relationship_type_id = s.relationship_type_id
    LEFT JOIN security.character_relationship_types prev_rel_type
        ON s.relationship_type_id IS NOT NULL AND prev_rel_type.code = s.previous_status
    LEFT JOIN security.capabilities capability ON capability.capability_id = s.grant_capability_id
    LEFT JOIN security.campaign_memberships grantee_cm
        ON grantee_cm.campaign_membership_id = s.grantee_membership_id
    LEFT JOIN security.users grantee_user ON grantee_user.user_id = grantee_cm.user_id
    LEFT JOIN security.access_groups grantee_group
        ON grantee_group.access_group_id = s.grantee_access_group_id
    WHERE s.resolved_campaign_id = :campaign_id
      AND (
            CAST(:category_commands AS text[]) IS NULL
            OR s.command_name = ANY(CAST(:category_commands AS text[]))
          )
      AND (CAST(:actor_user_id AS uuid) IS NULL OR s.actor_user_id = CAST(:actor_user_id AS uuid))
      AND (CAST(:occurred_from AS timestamptz) IS NULL
           OR s.recorded_at >= CAST(:occurred_from AS timestamptz))
      AND (CAST(:occurred_to AS timestamptz) IS NULL
           OR s.recorded_at <= CAST(:occurred_to AS timestamptz))
      AND (
            NOT CAST(:has_cursor AS boolean)
            OR (s.recorded_at, s.change_log_id)
               < (CAST(:after_recorded_at AS timestamptz), CAST(:after_change_log_id AS bigint))
          )
    ORDER BY s.recorded_at DESC, s.change_log_id DESC
    LIMIT :limit_plus_one
"""


def _change_summary(row: dict[str, object], *, command_name: str) -> str | None:
    previous_status = row.get("previous_status")
    if command_name == "change_membership_role":
        # `previous_role_display_name` is only ever set when the query proved
        # the exact predecessor assignment (see `_QUERY`'s `prev_role` join).
        # Otherwise (a legacy row with no recorded predecessor id, or one
        # that fails validation) the ledger's own recorded code is shown
        # verbatim — never a display name picked from a code that more than
        # one role (system vs. campaign) may share — and a row that recorded
        # no code at all is labelled unknown, not "removed".
        old = (
            row.get("previous_role_display_name") or previous_status or _UNKNOWN_PREVIOUS_ROLE_LABEL
        )
        new = row.get("role_display_name") or _PLACEHOLDER_ROLE_LABEL
        return f"{old} → {new}"
    if command_name in ("assign_membership_role", "revoke_membership_role"):
        role_label = row.get("role_display_name") or _PLACEHOLDER_ROLE_LABEL
        return str(role_label)
    if command_name == "change_character_relationship":
        old = (
            row.get("previous_relationship_type_display_name")
            or previous_status
            or _PLACEHOLDER_RELATIONSHIP_TYPE_LABEL
        )
        new = row.get("relationship_type_display_name") or _PLACEHOLDER_RELATIONSHIP_TYPE_LABEL
        return f"{old} → {new}"
    if command_name in ("grant_character_relationship", "revoke_character_relationship"):
        type_label = (
            row.get("relationship_type_display_name") or _PLACEHOLDER_RELATIONSHIP_TYPE_LABEL
        )
        return str(type_label)
    if command_name in ("create_resource_grant", "revoke_resource_grant"):
        capability_label = row.get("capability_display_name") or _PLACEHOLDER_CAPABILITY_LABEL
        grantee = row.get("grantee_user_display_name") or row.get("grantee_group_name")
        if grantee is not None:
            return f"{capability_label} — {grantee}"
        return str(capability_label)
    if command_name == "update_access_group":
        # previous_status/new_status hold the group's own previous/new name
        # here (dnd_ai.api.access_groups.update_access_group_endpoint),
        # unlike every other command_name above where they hold a fixed
        # code. Both are always recorded together; if they are equal (a
        # description-only edit) there is nothing meaningful to arrow
        # between, so this returns None rather than "X → X".
        new_status = row.get("new_status")
        if previous_status is None or new_status is None or previous_status == new_status:
            return None
        return f"{previous_status} → {new_status}"
    if command_name in ("add_access_group_member", "remove_access_group_member"):
        group_label = row.get("grantee_group_name") or _PLACEHOLDER_GROUP_LABEL
        return str(group_label)
    return None


def _resolve_target(row: dict[str, object], *, command_name: str) -> tuple[str | None, str | None]:
    if command_name in _MEMBERSHIP_TABLE_COMMANDS or command_name in _ROLE_TABLE_COMMANDS:
        if row.get("target_user_id") is not None:
            label = row.get("target_user_display_name") or _PLACEHOLDER_ACCOUNT_LABEL
            return str(label), "account"
        return None, None
    if command_name in _RELATIONSHIP_TABLE_COMMANDS:
        if row.get("target_character_id") is not None:
            label = row.get("target_character_name") or _PLACEHOLDER_CHARACTER_LABEL
            return str(label), "character"
        return None, None
    if command_name in _GRANT_TABLE_COMMANDS:
        grantee_user = row.get("grantee_user_display_name")
        grantee_group = row.get("grantee_group_name")
        if grantee_user is not None:
            return str(grantee_user), "account"
        if grantee_group is not None:
            return str(grantee_group), "access_group"
        # security.resource_grants requires exactly one grantee column
        # non-null and neither is ever deleted (CLAUDE.md rule 9), so this
        # is unreachable in practice — defensive only. Distinguishes which
        # grantee kind was named so the placeholder never claims a
        # membership grantee was actually a group, or vice versa.
        if row.get("grantee_membership_id") is not None:
            return _PLACEHOLDER_ACCOUNT_LABEL, "account"
        if row.get("grantee_access_group_id") is not None:
            return _PLACEHOLDER_GROUP_LABEL, "access_group"
        return _PLACEHOLDER_ACCOUNT_LABEL, "account"
    if command_name in _ACCESS_GROUP_TABLE_COMMANDS:
        group_name = row.get("grantee_group_name")
        label = group_name if group_name is not None else _PLACEHOLDER_GROUP_LABEL
        return str(label), "access_group"
    if command_name in _ACCESS_GROUP_MEMBERSHIP_TABLE_COMMANDS:
        if row.get("target_user_id") is not None:
            label = row.get("target_user_display_name") or _PLACEHOLDER_ACCOUNT_LABEL
            return str(label), "account"
        return None, None
    # invitation / campaign: no single discrete target to name safely.
    return None, None


def _resolve_actor(row: dict[str, object]) -> tuple[str, str]:
    actor_user_id = row.get("actor_user_id")
    if actor_user_id is not None:
        display_name = row.get("actor_display_name")
        return (
            str(display_name) if display_name is not None else _PLACEHOLDER_ACCOUNT_LABEL
        ), "user"
    actor_service = row.get("actor_service")
    if actor_service is not None:
        return str(actor_service), "service"
    return "Unknown actor", "unknown"


def list_campaign_audit_history(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    category: str | None,
    actor_user_id: uuid.UUID | None,
    occurred_from: datetime | None,
    occurred_to: datetime | None,
    limit: int,
    after_recorded_at: datetime | None,
    after_change_log_id: int | None,
) -> tuple[AuditHistoryItem, ...]:
    """Up to `limit + 1` campaign-access audit-history items for
    `campaign_id`, newest first (`recorded_at DESC, change_log_id DESC` —
    a deterministic total order even when two rows share a timestamp).
    Raises `ValueError` for an unrecognized `category` (mapped to a 422 by
    the API layer, matching `dnd_ai.queries.knowledge_browse.list_knowledge`'s
    identical "unknown view" contract) — never silently ignored.

    Returns an empty tuple for a campaign with no matching history — not
    an error, and not an existence signal either way, matching this
    codebase's non-disclosure discipline (the caller has already proven
    campaign access via `require_campaign_capability` before this function
    ever runs)."""
    commands = _validate_category(category)
    rows = connection.execute(
        text(_QUERY),
        {
            "campaign_id": campaign_id,
            "membership_commands": list(_MEMBERSHIP_TABLE_COMMANDS),
            "role_commands": list(_ROLE_TABLE_COMMANDS),
            "relationship_commands": list(_RELATIONSHIP_TABLE_COMMANDS),
            "grant_commands": list(_GRANT_TABLE_COMMANDS),
            "invitation_commands": list(_INVITATION_TABLE_COMMANDS),
            "campaign_commands": list(_CAMPAIGN_TABLE_COMMANDS),
            "access_group_commands": list(_ACCESS_GROUP_TABLE_COMMANDS),
            "access_group_membership_commands": list(_ACCESS_GROUP_MEMBERSHIP_TABLE_COMMANDS),
            # NULL (no category requested) disables this filter entirely —
            # every branch above already restricts itself to its own fixed
            # command_name set, so `_ALL_COMMANDS` would be redundant here.
            "category_commands": list(commands) if category is not None else None,
            "actor_user_id": actor_user_id,
            "occurred_from": occurred_from,
            "occurred_to": occurred_to,
            "has_cursor": after_change_log_id is not None,
            "after_recorded_at": after_recorded_at,
            "after_change_log_id": after_change_log_id,
            "limit_plus_one": limit + 1,
        },
    ).mappings()

    items: list[AuditHistoryItem] = []
    for r in rows:
        row: dict[str, object] = dict(r)
        command_name = str(row["command_name"])
        if command_name not in commands:
            # Defense in depth only — `category_commands` above already
            # applies this exact filter in SQL, before LIMIT. A command_name
            # this module doesn't recognize at all can never reach here (no
            # branch of `scoped` would have produced it), so this only ever
            # fires if the SQL-level filter and this Python-level one were
            # ever allowed to drift apart.
            continue
        actor_label, actor_type = _resolve_actor(row)
        target_label, target_type = _resolve_target(row, command_name=command_name)
        occurred_at = row["recorded_at"]
        assert isinstance(occurred_at, datetime)
        raw_change_log_id = row["change_log_id"]
        assert isinstance(raw_change_log_id, int)
        items.append(
            AuditHistoryItem(
                change_log_id=raw_change_log_id,
                occurred_at=occurred_at,
                category=_CATEGORY_BY_COMMAND[command_name],
                action_label=_ACTION_LABEL_BY_COMMAND[command_name],
                actor_label=actor_label,
                actor_type=actor_type,
                target_label=target_label,
                target_type=target_type,
                change_summary=_change_summary(row, command_name=command_name),
                outcome=None,
            )
        )
    return tuple(items)
