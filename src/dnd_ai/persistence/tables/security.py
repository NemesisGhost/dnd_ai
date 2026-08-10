"""Security tables — security schema (revisions 003, 080).

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.

CHECK constraints and triggers are not declared here — see that same
__init__.py note for why (alembic does not compare them; tests cover them).
"""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INT8RANGE, JSONB, TIMESTAMP, UUID

from ._shared import (
    NONNEGATIVE_INTEGER,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
)

# ---------------------------------------------------------------------------
# Lookups (revision 080)
# ---------------------------------------------------------------------------

membership_statuses = _lookup_table(
    "security",
    "membership_statuses",
    "membership_status_id",
    "Lifecycle of a security.campaign_memberships row: invited, active, "
    "suspended, revoked, departed (docs/architecture/DATABASE_MODEL.md §19.2).",
)

character_relationship_types = _lookup_table(
    "security",
    "character_relationship_types",
    "character_relationship_type_id",
    "Semantic relationship between a campaign membership and a character — "
    "owner, primary_controller, co_controller, viewer, portrayer, "
    "former_controller, observer_approved_viewer (docs/architecture/"
    "DATABASE_MODEL.md §19.4).",
)

capabilities = _lookup_table(
    "security",
    "capabilities",
    "capability_id",
    "A stable, dot-namespaced operation code — campaign.view, canon.edit, "
    "character.control, and similar — assigned to roles "
    "(security.role_capabilities) and character-relationship types "
    "(security.character_relationship_type_capabilities). One shared "
    "vocabulary for both (docs/architecture/DATABASE_MODEL.md §19.3, §19.4).",
)

# ---------------------------------------------------------------------------
# Identity (revision 003, reshaped by revision 080)
# ---------------------------------------------------------------------------

users = Table(
    "users",
    metadata,
    _uuid_pk("user_id"),
    Column(
        "email",
        Text(),
        comment="Nullable: service-linked or imported accounts may have no address.",
    ),
    Column("display_name", Text(), nullable=False),
    Column(
        "lifecycle_status_id",
        UUID(),
        ForeignKey("core.lifecycle_statuses.lifecycle_status_id", ondelete="RESTRICT"),
        nullable=False,
        comment=(
            "Whether this identity is currently usable by the platform — replaces the "
            "old is_active boolean (conventions §11: lookup tables over booleans)."
        ),
    ),
    Column(
        "last_login_at",
        TIMESTAMP(timezone=True),
        comment=(
            "Updated by the application on successful authentication; NULL for a user "
            "who has never logged in."
        ),
    ),
    *_timestamps(),
    schema="security",
    comment=(
        "Application identity independent of any login provider. Authentication is "
        "delegated to external identity providers via security.external_identities — "
        "this table is identity for attribution and authorization only "
        "(docs/architecture/DATABASE_MODEL.md §19.1)."
    ),
)

Index("ix_users_lifecycle_status_id", users.c.lifecycle_status_id)

external_identities = Table(
    "external_identities",
    metadata,
    _uuid_pk("external_identity_id"),
    Column(
        "user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("issuer", Text(), nullable=False),
    Column("subject", Text(), nullable=False),
    Column("email_at_last_login", Text()),
    Column(
        "claims_snapshot",
        JSONB(),
        comment=("A minimal allow-listed set of claims kept for diagnostics — never raw tokens."),
    ),
    Column("linked_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_authenticated_at", TIMESTAMP(timezone=True)),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    schema="security",
    comment=(
        "Maps one security.users row to one or more OIDC identities (issuer, "
        "subject) — never raw tokens (docs/architecture/DATABASE_MODEL.md §19.1). "
        "Email is informational, not the identity key, since it may change or be "
        "reused by the provider."
    ),
)

Index("ix_external_identities_user_id", external_identities.c.user_id)
Index(
    "ux_external_identities_issuer_subject",
    external_identities.c.issuer,
    external_identities.c.subject,
    unique=True,
    postgresql_where=external_identities.c.revoked_at.is_(None),
)

service_accounts = Table(
    "service_accounts",
    metadata,
    _uuid_pk("service_account_id"),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint("code", name="ux_service_accounts_code"),
    schema="security",
    comment=(
        "A non-human application principal. Never gains campaign access merely by "
        "existing — capabilities are assigned through explicit service-account "
        "grants or narrowly scoped application configuration, and all actions "
        "identify the service principal in audit records (docs/architecture/"
        "DATABASE_MODEL.md §19.1)."
    ),
)

# ---------------------------------------------------------------------------
# Campaign membership and invitations (revision 080)
# ---------------------------------------------------------------------------

campaign_memberships = Table(
    "campaign_memberships",
    metadata,
    _uuid_pk("campaign_membership_id"),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "membership_status_id",
        UUID(),
        ForeignKey("security.membership_statuses.membership_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("joined_at", TIMESTAMP(timezone=True)),
    Column("ended_at", TIMESTAMP(timezone=True)),
    Column(
        "ended_by_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    schema="security",
    comment=(
        "The many-to-many association between users and campaigns and the root of "
        "human authorization within a campaign (docs/architecture/DATABASE_MODEL.md "
        "§19.2). user_id is ON DELETE RESTRICT, not CASCADE — membership history "
        "must survive a user delete. Revoked/departed rows are closed (ended_at "
        "set), never deleted."
    ),
)

Index("ix_campaign_memberships_campaign_id", campaign_memberships.c.campaign_id)
Index("ix_campaign_memberships_user_id", campaign_memberships.c.user_id)
Index("ix_campaign_memberships_membership_status_id", campaign_memberships.c.membership_status_id)
Index(
    "ix_campaign_memberships_ended_by_membership_id",
    campaign_memberships.c.ended_by_membership_id,
    postgresql_where=campaign_memberships.c.ended_by_membership_id.isnot(None),
)
Index(
    "ux_campaign_memberships_open",
    campaign_memberships.c.campaign_id,
    campaign_memberships.c.user_id,
    unique=True,
    postgresql_where=campaign_memberships.c.ended_at.is_(None),
)

campaign_invitations = Table(
    "campaign_invitations",
    metadata,
    _uuid_pk("campaign_invitation_id"),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("invited_email", Text()),
    Column("invitation_token_hash", Text(), nullable=False),
    Column(
        "invited_by_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column(
        "accepted_by_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    Column("accepted_at", TIMESTAMP(timezone=True)),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("invitation_token_hash", name="ux_campaign_invitations_token_hash"),
    schema="security",
    comment=(
        "Tracks an invitation without pre-creating a durable membership for an "
        "unknown recipient (docs/architecture/DATABASE_MODEL.md §19.2). Only the "
        "token hash is retained. Acceptance creates or activates a "
        "security.campaign_memberships row through an application command and is "
        "idempotent."
    ),
)

Index("ix_campaign_invitations_campaign_id", campaign_invitations.c.campaign_id)
Index(
    "ix_campaign_invitations_invited_by_membership_id",
    campaign_invitations.c.invited_by_membership_id,
)
Index(
    "ix_campaign_invitations_accepted_by_user_id",
    campaign_invitations.c.accepted_by_user_id,
    postgresql_where=campaign_invitations.c.accepted_by_user_id.isnot(None),
)

# ---------------------------------------------------------------------------
# Roles and capabilities (revision 080)
# ---------------------------------------------------------------------------

roles = Table(
    "roles",
    metadata,
    _uuid_pk("role_id"),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("sort_order", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint("campaign_id", "code", name="uq_roles_campaign_code"),
    schema="security",
    comment=(
        "A configurable campaign role — campaign owner, GM, assistant GM, player, "
        "observer, import reviewer, rules curator (docs/architecture/"
        "DATABASE_MODEL.md §19.3). campaign_id NULL means a system template usable "
        "by any campaign; non-NULL scopes the role to one campaign. "
        "uq_roles_campaign_code does not by itself stop two system templates "
        "sharing a code (NULL <> NULL) — see ux_roles_system_code below."
    ),
)

Index(
    "ux_roles_system_code",
    roles.c.code,
    unique=True,
    postgresql_where=roles.c.campaign_id.is_(None),
)
Index(
    "ix_roles_campaign_id",
    roles.c.campaign_id,
    postgresql_where=roles.c.campaign_id.isnot(None),
)

role_capabilities = Table(
    "role_capabilities",
    metadata,
    Column(
        "role_id",
        UUID(),
        ForeignKey("security.roles.role_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "capability_id",
        UUID(),
        ForeignKey("security.capabilities.capability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("role_id", "capability_id"),
    schema="security",
    comment=(
        "Many-to-many default capabilities for a role (docs/architecture/"
        "DATABASE_MODEL.md §19.3). ON DELETE RESTRICT against capabilities so a "
        "capability in active use cannot vanish out from under its holders."
    ),
)

Index("ix_role_capabilities_capability_id", role_capabilities.c.capability_id)

membership_roles = Table(
    "membership_roles",
    metadata,
    _uuid_pk("membership_role_id"),
    Column(
        "campaign_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "role_id",
        UUID(),
        ForeignKey("security.roles.role_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "granted_by_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="SET NULL"),
    ),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    schema="security",
    comment=(
        "Many-to-many role assignment from a campaign membership to a role "
        "(docs/architecture/DATABASE_MODEL.md §19.3). A membership may hold "
        "multiple roles concurrently. Revocation closes the row (revoked_at set) "
        "rather than deleting it."
    ),
)

Index("ix_membership_roles_campaign_membership_id", membership_roles.c.campaign_membership_id)
Index("ix_membership_roles_role_id", membership_roles.c.role_id)
Index(
    "ix_membership_roles_granted_by_membership_id",
    membership_roles.c.granted_by_membership_id,
    postgresql_where=membership_roles.c.granted_by_membership_id.isnot(None),
)
Index(
    "ux_membership_roles_active",
    membership_roles.c.campaign_membership_id,
    membership_roles.c.role_id,
    unique=True,
    postgresql_where=membership_roles.c.revoked_at.is_(None),
)

# ---------------------------------------------------------------------------
# Human-to-character relationships (revision 080)
# ---------------------------------------------------------------------------

membership_character_relationships = Table(
    "membership_character_relationships",
    metadata,
    _uuid_pk("membership_character_relationship_id"),
    Column(
        "campaign_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "character_relationship_type_id",
        UUID(),
        ForeignKey(
            "security.character_relationship_types.character_relationship_type_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
    ),
    Column(
        "effective_from_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column(
        "effective_to_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column(
        "effective_period",
        INT8RANGE(),
        comment=(
            "Derived, never client-authoritative: an INT8RANGE over "
            "effective_from_world_time_id/effective_to_world_time_id's sort_key "
            "values, maintained by security."
            "enforce_membership_character_relationship_scope()."
        ),
    ),
    Column(
        "granted_by_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="SET NULL"),
    ),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("notes", Text()),
    schema="security",
    comment=(
        "Many-to-many, typed relationship between an active campaign membership "
        "and a character (docs/architecture/DATABASE_MODEL.md §19.4). The "
        "membership's campaign, the character's world, and an optional timeline "
        "must agree — enforced by security."
        "enforce_membership_character_relationship_scope(), which also derives "
        "effective_period from the world-time endpoints, mirroring campaign."
        "sync_party_membership_period() (revision 009). A transfer of ownership "
        "or control closes the prior relationship (revoked_at) and creates a new "
        "row rather than overwriting history."
    ),
)

Index(
    "ix_membership_character_relationships_campaign_membership_id",
    membership_character_relationships.c.campaign_membership_id,
)
Index(
    "ix_membership_character_relationships_character_id",
    membership_character_relationships.c.character_id,
)
Index(
    "ix_membership_character_relationships_relationship_type_id",
    membership_character_relationships.c.character_relationship_type_id,
)
Index(
    "ix_membership_character_relationships_timeline_id",
    membership_character_relationships.c.timeline_id,
    postgresql_where=membership_character_relationships.c.timeline_id.isnot(None),
)
Index(
    # Shortened to "from"/"to" — the full "..._effective_from_world_time_id"
    # name exceeds PostgreSQL's 63-character identifier limit.
    "ix_membership_character_relationships_from_world_time_id",
    membership_character_relationships.c.effective_from_world_time_id,
    postgresql_where=membership_character_relationships.c.effective_from_world_time_id.isnot(None),
)
Index(
    "ix_membership_character_relationships_to_world_time_id",
    membership_character_relationships.c.effective_to_world_time_id,
    postgresql_where=membership_character_relationships.c.effective_to_world_time_id.isnot(None),
)
Index(
    "ix_membership_character_relationships_granted_by_membership_id",
    membership_character_relationships.c.granted_by_membership_id,
    postgresql_where=membership_character_relationships.c.granted_by_membership_id.isnot(None),
)
Index(
    "ux_membership_character_relationships_active_type",
    membership_character_relationships.c.campaign_membership_id,
    membership_character_relationships.c.character_id,
    membership_character_relationships.c.character_relationship_type_id,
    unique=True,
    postgresql_where=membership_character_relationships.c.revoked_at.is_(None),
)

character_relationship_type_capabilities = Table(
    "character_relationship_type_capabilities",
    metadata,
    Column(
        "character_relationship_type_id",
        UUID(),
        ForeignKey(
            "security.character_relationship_types.character_relationship_type_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    Column(
        "capability_id",
        UUID(),
        ForeignKey("security.capabilities.capability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_relationship_type_id", "capability_id"),
    schema="security",
    comment=(
        "Default capabilities a character-relationship type grants — discover, "
        "view_summary, view_full, view_private, view_character_knowledge, "
        "edit_narrative, edit_mechanical_state, interact, control, manage_access "
        "(docs/architecture/DATABASE_MODEL.md §19.4). A direct security."
        "resource_grants row may extend or restrict a specific membership beyond "
        "these defaults."
    ),
)

Index(
    "ix_character_relationship_type_capabilities_capability_id",
    character_relationship_type_capabilities.c.capability_id,
)

# ---------------------------------------------------------------------------
# Access groups (revision 080)
# ---------------------------------------------------------------------------

access_groups = Table(
    "access_groups",
    metadata,
    _uuid_pk("access_group_id"),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    *_timestamps(),
    UniqueConstraint("campaign_id", "name", name="ux_access_groups_campaign_name"),
    schema="security",
    comment=(
        "A campaign-scoped named set of memberships — livestream observers, "
        "former players, a GM-curated lore audience (docs/architecture/"
        "DATABASE_MODEL.md §19.5). Does not represent an in-world party; adding a "
        "membership to a group never touches campaign.party_memberships or "
        "in-world knowledge."
    ),
)

Index("ix_access_groups_campaign_id", access_groups.c.campaign_id)

access_group_memberships = Table(
    "access_group_memberships",
    metadata,
    _uuid_pk("access_group_membership_id"),
    Column(
        "access_group_id",
        UUID(),
        ForeignKey("security.access_groups.access_group_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "campaign_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "added_by_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="SET NULL"),
    ),
    Column("added_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("removed_at", TIMESTAMP(timezone=True)),
    schema="security",
    comment=(
        "Many-to-many association between campaign memberships and access groups "
        "(docs/architecture/DATABASE_MODEL.md §19.5). Removal closes the row "
        "(removed_at set) rather than deleting it."
    ),
)

Index("ix_access_group_memberships_access_group_id", access_group_memberships.c.access_group_id)
Index(
    "ix_access_group_memberships_campaign_membership_id",
    access_group_memberships.c.campaign_membership_id,
)
Index(
    "ix_access_group_memberships_added_by_membership_id",
    access_group_memberships.c.added_by_membership_id,
    postgresql_where=access_group_memberships.c.added_by_membership_id.isnot(None),
)
Index(
    "ux_access_group_memberships_open",
    access_group_memberships.c.access_group_id,
    access_group_memberships.c.campaign_membership_id,
    unique=True,
    postgresql_where=access_group_memberships.c.removed_at.is_(None),
)

# ---------------------------------------------------------------------------
# Resource grants (revision 080)
# ---------------------------------------------------------------------------

resource_grants = Table(
    "resource_grants",
    metadata,
    _uuid_pk("resource_grant_id"),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
    ),
    Column(
        "grantee_campaign_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="CASCADE"),
    ),
    Column(
        "grantee_access_group_id",
        UUID(),
        ForeignKey("security.access_groups.access_group_id", ondelete="CASCADE"),
    ),
    Column(
        "capability_id",
        UUID(),
        ForeignKey("security.capabilities.capability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "effect",
        Text(),
        nullable=False,
        server_default=text("'allow'::text"),
        comment=(
            "allow or deny. An explicit deny overrides an allow at the same or broader "
            "inherited path. A deny here is always scoped to one specific resource target "
            "(never the whole campaign — no campaign-wide target exists), so it can never "
            "by itself remove the campaign-wide access.manage capability the campaign "
            "owner/access-manager retention invariant protects (§19.6, §22 rule 19) — that "
            "invariant is database-enforced separately, by security."
            "assert_campaign_retains_access_manager() against role-derived capabilities."
        ),
    ),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
    ),
    Column(
        "entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
    ),
    Column(
        "knowledge_item_id",
        UUID(),
        ForeignKey("knowledge.knowledge_items.knowledge_item_id", ondelete="CASCADE"),
    ),
    Column(
        "quest_id",
        UUID(),
        ForeignKey("narrative.quests.quest_id", ondelete="CASCADE"),
    ),
    Column(
        "session_id",
        UUID(),
        ForeignKey("campaign.sessions.session_id", ondelete="CASCADE"),
    ),
    Column(
        "event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="CASCADE"),
    ),
    Column(
        "granted_by_membership_id",
        UUID(),
        ForeignKey("security.campaign_memberships.campaign_membership_id", ondelete="SET NULL"),
    ),
    Column("grant_source", Text(), nullable=False, server_default=text("'manual'::text")),
    Column("reason", Text()),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    schema="security",
    comment=(
        "Explicit many-to-many access to a protected record, without an "
        "unenforced (resource_type, resource_id) polymorphic reference "
        "(docs/architecture/DATABASE_MODEL.md §19.6). Exactly one grantee column "
        "and exactly one typed target column are non-null. Scoped to the six "
        "target kinds the Phase 10 vertical slice needs (character, entity, "
        "knowledge item, quest, session, event) — source_document_id, "
        "ai_proposed_change_id, and import_job_id are added by the migration "
        "that introduces their target table (§19.6's own extension rule). "
        "Revocation closes a row (revoked_at set) rather than deleting it."
    ),
)

Index("ix_resource_grants_campaign_id", resource_grants.c.campaign_id)
Index(
    "ix_resource_grants_timeline_id",
    resource_grants.c.timeline_id,
    postgresql_where=resource_grants.c.timeline_id.isnot(None),
)
Index(
    "ix_resource_grants_grantee_campaign_membership_id",
    resource_grants.c.grantee_campaign_membership_id,
    postgresql_where=resource_grants.c.grantee_campaign_membership_id.isnot(None),
)
Index(
    "ix_resource_grants_grantee_access_group_id",
    resource_grants.c.grantee_access_group_id,
    postgresql_where=resource_grants.c.grantee_access_group_id.isnot(None),
)
Index("ix_resource_grants_capability_id", resource_grants.c.capability_id)
Index(
    "ix_resource_grants_character_id",
    resource_grants.c.character_id,
    postgresql_where=resource_grants.c.character_id.isnot(None),
)
Index(
    "ix_resource_grants_entity_id",
    resource_grants.c.entity_id,
    postgresql_where=resource_grants.c.entity_id.isnot(None),
)
Index(
    "ix_resource_grants_knowledge_item_id",
    resource_grants.c.knowledge_item_id,
    postgresql_where=resource_grants.c.knowledge_item_id.isnot(None),
)
Index(
    "ix_resource_grants_quest_id",
    resource_grants.c.quest_id,
    postgresql_where=resource_grants.c.quest_id.isnot(None),
)
Index(
    "ix_resource_grants_session_id",
    resource_grants.c.session_id,
    postgresql_where=resource_grants.c.session_id.isnot(None),
)
Index(
    "ix_resource_grants_event_id",
    resource_grants.c.event_id,
    postgresql_where=resource_grants.c.event_id.isnot(None),
)
Index(
    "ix_resource_grants_granted_by_membership_id",
    resource_grants.c.granted_by_membership_id,
    postgresql_where=resource_grants.c.granted_by_membership_id.isnot(None),
)
Index(
    "ux_resource_grants_active",
    resource_grants.c.grantee_campaign_membership_id,
    resource_grants.c.grantee_access_group_id,
    resource_grants.c.character_id,
    resource_grants.c.entity_id,
    resource_grants.c.knowledge_item_id,
    resource_grants.c.quest_id,
    resource_grants.c.session_id,
    resource_grants.c.event_id,
    resource_grants.c.timeline_id,
    resource_grants.c.capability_id,
    resource_grants.c.effect,
    unique=True,
    postgresql_where=resource_grants.c.revoked_at.is_(None),
    postgresql_nulls_not_distinct=True,
)
