"""Read-only GM campaign access overview (Phase 13E-A, docs/PLAN.md Phase 13
"13E — GM access tools") plus `list_assignable_campaign_roles`, the small
read-contract addition Phase 13E-B's first mutation checkpoint needs so the
portal never has to hardcode which roles it may offer for a role change,
and `find_eligible_campaign_account` (Phase 13E-B checkpoint 3), the
account-selection read contract for the portal's "Add campaign member"
action — see that function's own docstring for the exact-match/non-
disclosure design.

`get_campaign_access_overview` assembles, for one campaign, every currently
open membership (`security.campaign_memberships.ended_at IS NULL`) together
with its active roles, current character relationships, and explicit
membership-targeted resource grants — the same "currently true" slice
`dnd_ai.domain.access.resolve_access_context` resolves for a single caller,
here assembled for every member at once so a GM can review the campaign's
access as a whole. Each nested collection applies the identical
revoked/expired/timeline filter `resolve_access_context` already uses
(`revoked_at IS NULL`, `expires_at IS NULL OR expires_at > now()`,
`timeline_id IS NULL OR timeline_id = :timeline_id`), so this overview never
shows a relationship or grant that would not currently apply. The explicit
resource-grants query additionally requires `cap.is_active`, matching
`resolve_access_context`'s own resource-grant resolution exactly — an
explicit grant of a deactivated capability confers no effective access
there, so it must not appear here as a current grant either (a review
correction; the first cut joined `security.capabilities` for its
`code`/`display_name` but omitted this check). Character relationships
additionally require `mcr.effective_to_world_time_id IS NULL`
(checkpoint-4 correction) — the identical fictional-time "current record"
rule `dnd_ai.domain.access.resolve_access_context`'s own docstring
explains in full: a relationship with both fictional-time endpoints set is
a closed historical interval, never currently active regardless of where
those endpoints fall, since this schema tracks no "current fictional now"
to compare against — and `core.lifecycle_statuses.code = 'active'` for the
relationship's own character (checkpoint-4 review correction): a character
archived after a relationship was granted previously stayed on this
overview indefinitely, disagreeing with `resolve_access_context`'s own
capability resolution, which already excludes it; the two now apply the
identical join/filter, so this overview's own "current character
relationships" list can never overstate what a member's own effective
access actually is.

Resource grants additionally require their own target to currently be
active (checkpoint 5) — the same generalization `dnd_ai.domain.access.
resolve_access_context`'s own docstring describes in full, applied here so
this overview can never show a grant targeting a resource that resolver
would no longer authorize through. `MemberResourceGrantView.target_
display_name` (checkpoint 5) is populated only for a `character_id` target
— resolved from `core.entities.canonical_name`, the identical safe display
name `character_relationships` already uses — and left `None` for every
other target kind, per this module's own "specific display identity...is a
larger surface than this focused read needs" note below, unchanged for the
other five kinds.

Deliberately out of scope for this first increment (documented here rather
than silently omitted):

- Access-group-targeted resource grants (`resource_grants.
  grantee_access_group_id`) — only membership-targeted grants are included.
  Groups are a separate, not-yet-surfaced concept on this screen.
- `security.users.lifecycle_status_id` (whether the underlying account is
  platform-active/disabled) — that is account-wide administration, a
  different capability scope than this campaign's `access.manage`
  (docs/UI_DESIGN.md's "do not merge account-wide administration with
  campaign administration unless the existing authorization model
  explicitly does so"). Only the campaign-scoped `membership_statuses` value
  is included.
- Pending/outstanding `security.campaign_invitations` — a closed membership
  never existed yet, so it is outside the same "current members" scope this
  overview covers; a future increment may add it once invitation mutations
  themselves are built here.
- The specific display identity of a non-character resource-grant target
  (`entity_id`/`knowledge_item_id`/`quest_id`/`session_id`/`event_id`) —
  resolving a display name for each of five unrelated resource kinds is a
  larger surface than this focused read needs; only the target *kind* is
  returned (`target_type`), never the raw id. A `character_id` target is
  the one exception (checkpoint 5): `target_display_name` resolves it from
  `core.entities.canonical_name`, the same safe name already used for
  character relationships — the portal's own resource-grant management UI
  is scoped to character targets only this checkpoint for the identical
  reason (see `dnd_ai.commands.access_grants`' module docstring and
  `docs/PHASE13E_ACCESS_CONTRACT.md` §3k for the full rationale).

This is a pure read: no idempotency key, no `audit.change_log` row, no
mutation. Authorization is entirely the caller's concern
(`dnd_ai.api.access.require_campaign_capability("access.manage")`) — this
module trusts the `campaign_id`/`timeline_id` it is given, exactly like
`dnd_ai.queries.quest.list_campaign_quests`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from dnd_ai.commands.local_auth import normalize_login_name
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER, RESOURCE_GRANT_CAPABILITY_CATALOG

_GRANT_TARGET_COLUMNS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)


@dataclass(frozen=True)
class MemberRoleView:
    membership_role_id: uuid.UUID
    role_id: uuid.UUID
    code: str
    display_name: str


@dataclass(frozen=True)
class MemberCharacterRelationshipView:
    membership_character_relationship_id: uuid.UUID
    character_id: uuid.UUID
    character_display_name: str
    relationship_type_code: str
    relationship_type_display_name: str
    granted_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class MemberResourceGrantView:
    resource_grant_id: uuid.UUID
    capability_code: str
    capability_display_name: str
    effect: str
    target_type: str
    # Identity only, never rendered as page text — matching every other
    # raw id this module already returns for the same reason (character_id
    # on MemberCharacterRelationshipView, role_id on MemberRoleView).
    # Populated for all six target kinds so the portal can detect an exact
    # active duplicate combination universally, even though only a
    # "character" target has a UI to add through this checkpoint.
    target_id: uuid.UUID
    target_display_name: str | None
    reason: str | None
    granted_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class AssignableRoleView:
    role_id: uuid.UUID
    code: str
    display_name: str


@dataclass(frozen=True)
class CampaignMemberView:
    campaign_membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    status_code: str
    status_display_name: str
    joined_at: datetime
    roles: tuple[MemberRoleView, ...]
    character_relationships: tuple[MemberCharacterRelationshipView, ...]
    grants: tuple[MemberResourceGrantView, ...]


@dataclass(frozen=True)
class EligibleAccountView:
    user_id: uuid.UUID
    display_name: str


@dataclass(frozen=True)
class AssignableCharacterView:
    character_id: uuid.UUID
    display_name: str


@dataclass(frozen=True)
class AssignableCharacterRelationshipTypeView:
    character_relationship_type_id: uuid.UUID
    code: str
    display_name: str


@dataclass(frozen=True)
class GrantableResourceCapabilityView:
    capability_id: uuid.UUID
    code: str
    display_name: str
    target_type: str


def get_campaign_access_overview(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID,
) -> tuple[CampaignMemberView, ...]:
    """Every currently open membership in `campaign_id`, each with its
    active roles, current character relationships, and explicit
    membership-targeted resource grants. `timeline_id` must already be the
    campaign's own pinned timeline (the caller's resolved `AccessContext.
    timeline_id` — never a caller-supplied value), matching every other
    timeline-scoped filter in `dnd_ai.domain.access`."""
    member_rows = (
        connection.execute(
            text("""
            SELECT cm.campaign_membership_id, cm.user_id, u.display_name, cm.joined_at,
                   ms.code AS status_code, ms.display_name AS status_display_name
            FROM security.campaign_memberships cm
            JOIN security.users u ON u.user_id = cm.user_id
            JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.ended_at IS NULL
            ORDER BY u.display_name, cm.campaign_membership_id
        """),
            {"campaign_id": campaign_id},
        )
        .mappings()
        .all()
    )

    roles_by_membership: dict[uuid.UUID, list[MemberRoleView]] = {}
    for row in connection.execute(
        text("""
            SELECT mr.campaign_membership_id, mr.membership_role_id, r.role_id, r.code,
                   r.display_name
            FROM security.membership_roles mr
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.campaign_memberships cm
              ON cm.campaign_membership_id = mr.campaign_membership_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.ended_at IS NULL
              AND mr.revoked_at IS NULL
              AND (mr.expires_at IS NULL OR mr.expires_at > now())
              AND r.is_active
            ORDER BY r.sort_order, r.display_name
        """),
        {"campaign_id": campaign_id},
    ).mappings():
        roles_by_membership.setdefault(row["campaign_membership_id"], []).append(
            MemberRoleView(
                membership_role_id=row["membership_role_id"],
                role_id=row["role_id"],
                code=row["code"],
                display_name=row["display_name"],
            )
        )

    relationships_by_membership: dict[uuid.UUID, list[MemberCharacterRelationshipView]] = {}
    for row in connection.execute(
        text("""
            SELECT mcr.campaign_membership_id, mcr.membership_character_relationship_id,
                   mcr.character_id, e.canonical_name AS character_display_name,
                   rt.code AS relationship_type_code,
                   rt.display_name AS relationship_type_display_name,
                   mcr.granted_at, mcr.expires_at
            FROM security.membership_character_relationships mcr
            JOIN security.campaign_memberships cm
              ON cm.campaign_membership_id = mcr.campaign_membership_id
            JOIN security.character_relationship_types rt
              ON rt.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN core.entities e ON e.entity_id = mcr.character_id
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = e.lifecycle_status_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.ended_at IS NULL
              AND mcr.revoked_at IS NULL
              AND (mcr.expires_at IS NULL OR mcr.expires_at > now())
              AND mcr.effective_to_world_time_id IS NULL
              AND (mcr.timeline_id IS NULL OR mcr.timeline_id = :timeline_id)
              AND cls.code = 'active'
            ORDER BY e.canonical_name, mcr.membership_character_relationship_id
        """),
        {"campaign_id": campaign_id, "timeline_id": timeline_id},
    ).mappings():
        relationships_by_membership.setdefault(row["campaign_membership_id"], []).append(
            MemberCharacterRelationshipView(
                membership_character_relationship_id=row["membership_character_relationship_id"],
                character_id=row["character_id"],
                character_display_name=row["character_display_name"],
                relationship_type_code=row["relationship_type_code"],
                relationship_type_display_name=row["relationship_type_display_name"],
                granted_at=row["granted_at"],
                expires_at=row["expires_at"],
            )
        )

    grants_by_membership: dict[uuid.UUID, list[MemberResourceGrantView]] = {}
    target_column_list = ", ".join(f"rg.{column}" for column in _GRANT_TARGET_COLUMNS)
    for row in connection.execute(
        text(f"""
            SELECT rg.grantee_campaign_membership_id, rg.resource_grant_id,
                   cap.code AS capability_code, cap.display_name AS capability_display_name,
                   rg.effect, rg.reason, rg.granted_at, rg.expires_at,
                   target_entity.canonical_name AS target_entity_display_name,
                   {target_column_list}
            FROM security.resource_grants rg
            JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
            JOIN security.campaign_memberships cm
              ON cm.campaign_membership_id = rg.grantee_campaign_membership_id
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
              AND cm.ended_at IS NULL
              AND rg.grantee_campaign_membership_id IS NOT NULL
              AND rg.revoked_at IS NULL
              AND (rg.expires_at IS NULL OR rg.expires_at > now())
              AND (rg.timeline_id IS NULL OR rg.timeline_id = :timeline_id)
              AND cap.is_active
              AND (
                    (rg.session_id IS NULL AND target_entity_status.code = 'active')
                    OR (rg.session_id IS NOT NULL AND target_session_status.code = 'active')
                  )
            ORDER BY rg.granted_at, rg.resource_grant_id
        """),
        {"campaign_id": campaign_id, "timeline_id": timeline_id},
    ).mappings():
        target_column = next(column for column in _GRANT_TARGET_COLUMNS if row[column] is not None)
        target_type = target_column.removesuffix("_id")
        target_display_name = (
            row["target_entity_display_name"] if target_column == "character_id" else None
        )
        grants_by_membership.setdefault(row["grantee_campaign_membership_id"], []).append(
            MemberResourceGrantView(
                resource_grant_id=row["resource_grant_id"],
                capability_code=row["capability_code"],
                capability_display_name=row["capability_display_name"],
                effect=row["effect"],
                target_type=target_type,
                target_id=row[target_column],
                target_display_name=target_display_name,
                reason=row["reason"],
                granted_at=row["granted_at"],
                expires_at=row["expires_at"],
            )
        )

    return tuple(
        CampaignMemberView(
            campaign_membership_id=row["campaign_membership_id"],
            user_id=row["user_id"],
            display_name=row["display_name"],
            status_code=row["status_code"],
            status_display_name=row["status_display_name"],
            joined_at=row["joined_at"],
            roles=tuple(roles_by_membership.get(row["campaign_membership_id"], [])),
            character_relationships=tuple(
                relationships_by_membership.get(row["campaign_membership_id"], [])
            ),
            grants=tuple(grants_by_membership.get(row["campaign_membership_id"], [])),
        )
        for row in member_rows
    )


def list_assignable_campaign_roles(
    connection: Connection, *, campaign_id: uuid.UUID
) -> tuple[AssignableRoleView, ...]:
    """Every role `dnd_ai.commands.memberships.assign_membership_role()`/
    `change_membership_role()` would actually accept for `campaign_id`
    right now: a system template (`security.roles.campaign_id IS NULL`) or
    one scoped to this specific campaign, and currently `is_active` — the
    identical scope those commands' own `RoleNotUsableByCampaignError`
    check enforces, queried here read-only so the portal never has to
    hardcode or guess the assignable set (docs/PLAN.md Phase 13E-B "Read-
    contract support": present only server-authorized role choices, never
    every internal role for frontend convenience). No hierarchy or
    delegation narrows this further — this codebase's role model is flat
    (`dnd_ai.commands.memberships`' own module docstring), so every role
    `access.manage` may assign is equally assignable regardless of which
    membership holds `access.manage`, including the caller's own."""
    return tuple(
        AssignableRoleView(
            role_id=row["role_id"], code=row["code"], display_name=row["display_name"]
        )
        for row in connection.execute(
            text("""
                SELECT role_id, code, display_name
                FROM security.roles
                WHERE (campaign_id IS NULL OR campaign_id = :campaign_id)
                  AND is_active
                ORDER BY sort_order, display_name
            """),
            {"campaign_id": campaign_id},
        ).mappings()
    )


def list_assignable_campaign_characters(
    connection: Connection, *, world_id: uuid.UUID
) -> tuple[AssignableCharacterView, ...]:
    """Every character `dnd_ai.commands.access_grants.
    grant_character_relationship()`/`change_character_relationship()` would
    actually accept as a same-world target right now: a `character.
    characters` row (never a bare `core.entities` row of some other type)
    belonging to `world_id` — the campaign's own world, resolved server-side
    by the caller from the campaign's pinned timeline, exactly like `grant_
    character_relationship()`'s own `expected_world_id` — and currently
    active (`core.lifecycle_statuses.code = 'active'`), the identical
    "never a legitimate target in the first place" bar that command's own
    hardening now enforces. Queried here read-only so the portal's "Add/
    change character relationship" controls never have to hardcode or guess
    the assignable set, mirroring `list_assignable_campaign_roles`'s
    identical purpose for roles. Not narrowed to player characters only —
    an NPC is a legitimate target too (a portrayer/assistant-GM relationship
    is meaningful for an NPC, per docs/architecture/DATABASE_MODEL.md
    §19.4's own relationship-type list)."""
    return tuple(
        AssignableCharacterView(character_id=row["entity_id"], display_name=row["canonical_name"])
        for row in connection.execute(
            text("""
                SELECT e.entity_id, e.canonical_name
                FROM core.entities e
                JOIN character.characters c ON c.character_id = e.entity_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                WHERE e.world_id = :world_id
                  AND ls.code = 'active'
                ORDER BY e.canonical_name, e.entity_id
            """),
            {"world_id": world_id},
        ).mappings()
    )


def list_assignable_character_relationship_types(
    connection: Connection,
) -> tuple[AssignableCharacterRelationshipTypeView, ...]:
    """Every currently `is_active` `security.character_relationship_types`
    row — the identical scope `dnd_ai.commands.access_grants.
    grant_character_relationship()`/`change_character_relationship()` now
    enforce for their own type argument. Relationship types carry no
    campaign scope of their own (unlike roles), so this is not further
    narrowed by `campaign_id`/`world_id`."""
    return tuple(
        AssignableCharacterRelationshipTypeView(
            character_relationship_type_id=row["character_relationship_type_id"],
            code=row["code"],
            display_name=row["display_name"],
        )
        for row in connection.execute(
            text("""
                SELECT character_relationship_type_id, code, display_name
                FROM security.character_relationship_types
                WHERE is_active
                ORDER BY sort_order, display_name
            """)
        ).mappings()
    )


def list_grantable_resource_capabilities(
    connection: Connection,
) -> tuple[GrantableResourceCapabilityView, ...]:
    """Every currently `is_active` `security.capabilities` row that `dnd_ai.
    commands.access_grants.create_resource_grant()` would actually accept
    for at least one resource-grant target kind right now, one row per
    `(capability, target_type)` pairing it is valid for — the read-contract
    support for the portal's "Add direct resource access" action, mirroring
    `list_assignable_campaign_roles`/`list_assignable_character_relationship_
    types`' identical "never hardcode or guess the assignable set" purpose.

    Server-authoritative and campaign-independent: `dnd_ai.domain.access.
    RESOURCE_GRANT_CAPABILITY_CATALOG` is a fixed policy table, not scoped
    by `campaign_id`/`world_id` — see that constant's own docstring for the
    full delegation-policy rationale (which capability codes apply to which
    target kind, and why `access.manage`/`import.approve`/`rules_source.
    manage` are excluded from every kind entirely). The portal's own
    resource-grant management UI only offers `character` as a selectable
    resource type this checkpoint (see `dnd_ai.commands.access_grants`'
    module docstring for why the other five target kinds are deferred), so
    in practice this currently returns only `target_type == "character"`
    rows — but the shape here is general: a future checkpoint that adds a
    safe display/search contract for another target kind needs no change to
    this function, only a new value in `RESOURCE_GRANT_CAPABILITY_CATALOG`
    to have it appear here automatically."""
    rows = connection.execute(
        text("""
            SELECT capability_id, code, display_name
            FROM security.capabilities
            WHERE is_active
        """)
    ).mappings()
    capabilities = {row["code"]: row for row in rows}
    return tuple(
        GrantableResourceCapabilityView(
            capability_id=capabilities[code]["capability_id"],
            code=code,
            display_name=capabilities[code]["display_name"],
            target_type=target_column.removesuffix("_id"),
        )
        for target_column, allowed_codes in RESOURCE_GRANT_CAPABILITY_CATALOG.items()
        for code in sorted(allowed_codes)
        if code in capabilities
    )


def find_eligible_campaign_account(
    connection: Connection, *, campaign_id: uuid.UUID, login_name: str
) -> EligibleAccountView | None:
    """Resolves `login_name` to the one existing account eligible to be
    added to `campaign_id` right now, or `None` — the read-contract support
    for the portal Access page's "Add campaign member" account-selection
    step (Phase 13E-B checkpoint 3).

    **Exact match, not directory-style search** (a deliberate choice,
    docs/PHASE13E_ACCESS_CONTRACT.md's own instruction to prefer this over
    a search endpoint when the security model favors it): this codebase's
    established non-disclosure posture treats "does an account with this
    name exist" as sensitive everywhere else (`dnd_ai.domain.access.
    resolve_user_by_external_identity`'s login never varies its rejection
    by cause; every `DomainAuthorizationError` folds "doesn't exist" into
    the same shape as "exists but not authorized"). A prefix/substring
    search would let any `access.manage` holder enumerate every account on
    the platform by trying successive queries — a `campaign.view`-scoped
    capability does not imply "may browse the platform's full user
    directory," and this checkpoint's own instructions explicitly forbid
    exposing one merely to support account selection. Exact lookup by a
    login name the caller must already know (out-of-band, from whoever
    administers accounts) closes that gap structurally rather than relying
    on rate limiting or auditing to catch abuse after the fact.

    Only ever resolves a **local** login (`security.external_identities`,
    `issuer = dnd_ai.domain.access.LOCAL_AUTH_ISSUER`) — an OIDC-only
    account has no login name of this kind to look up by (docs/
    architecture/DATABASE_MODEL.md's `security.users.email` is explicitly
    "informational... not the durable external identity key", so it is
    never used as a lookup key here either). A campaign whose members are
    provisioned entirely through OIDC has no accounts this lookup can ever
    find — a known, documented limitation of this checkpoint's scope, not
    an oversight; broadening it to OIDC subjects is deferred to whichever
    future increment needs it. `login_name` is normalized with the same
    `normalize_login_name()` every local-auth login path already applies,
    so a caller's differently-cased or whitespace-padded input still
    matches.

    "Eligible" folds three independent conditions into one `None` result,
    identically, so this endpoint can never be used to distinguish "no such
    account", "account exists but is platform-disabled", and "account
    already has an open membership in this campaign" from one another —
    the same non-disclosure discipline `dnd_ai.commands.memberships.
    AccountNotEligibleError`/`RoleNotUsableByCampaignError` already apply
    to the mutation side:

    - the local identity must resolve to a `security.users` row at all,
      and that identity must not be revoked (`revoked_at IS NULL`);
    - the account must currently be platform-active (`security.users.
      lifecycle_status_id` -> `core.lifecycle_statuses.code = 'active'`);
    - the account must **not** currently hold an open (`ended_at IS NULL`)
      membership in `campaign_id`.

    Pure read: no row lock. `add_campaign_member()` re-resolves and locks
    the account independently at mutation time — this function only
    narrows what the portal offers as a selectable candidate, exactly like
    `list_assignable_campaign_roles` narrows the role choices it offers,
    never the authorization boundary itself."""
    normalized_login_name = normalize_login_name(login_name)
    row = (
        connection.execute(
            text("""
                SELECT u.user_id, u.display_name
                FROM security.external_identities ei
                JOIN security.users u ON u.user_id = ei.user_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE ei.issuer = :issuer
                  AND ei.subject = :subject
                  AND ei.revoked_at IS NULL
                  AND ls.code = 'active'
                  AND NOT EXISTS (
                      SELECT 1 FROM security.campaign_memberships cm
                      WHERE cm.campaign_id = :campaign_id
                        AND cm.user_id = u.user_id
                        AND cm.ended_at IS NULL
                  )
            """),
            {
                "issuer": LOCAL_AUTH_ISSUER,
                "subject": normalized_login_name,
                "campaign_id": campaign_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return EligibleAccountView(user_id=row["user_id"], display_name=row["display_name"])
