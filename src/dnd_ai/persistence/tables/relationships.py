"""Relationships and organizations tables — world schema.

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.

CHECK constraints, exclusion constraints, and triggers are not declared
here — see that same __init__.py note for why (alembic does not compare
them; tests cover them instead).
"""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INT8RANGE, TIMESTAMP, UUID

from ._shared import (
    PERCENTAGE_0_100,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
)

# ---------------------------------------------------------------------------
# world — universal relationships, participants, perspectives (revision 076)
# ---------------------------------------------------------------------------

relationship_types = _lookup_table(
    "world",
    "relationship_types",
    "relationship_type_id",
    "The kind of association a world.relationships row records "
    "(docs/DOMAIN_MODEL.md §11.1) — family, employment, membership, "
    "ownership, alliance, rivalry, war, control, worship, adjacency, "
    "capital_of, parent_of, other.",
)

relationship_participant_roles = _lookup_table(
    "world",
    "relationship_participant_roles",
    "relationship_participant_role_id",
    "How a participating entity relates to a relationship, allowing "
    "asymmetric relationships (docs/DOMAIN_MODEL.md §11.2) — parent/"
    "child, employer/employee, owner/property, ruler/territory, plus "
    "generic subject/object and member/organization.",
)

relationships = Table(
    "relationships",
    metadata,
    _uuid_pk("relationship_id"),
    Column(
        "world_id", UUID(), ForeignKey("core.worlds.world_id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "relationship_type_id",
        UUID(),
        ForeignKey("world.relationship_types.relationship_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("description", Text()),
    Column(
        "started_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column(
        "ended_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column("source_id", UUID(), ForeignKey("core.sources.source_id", ondelete="SET NULL")),
    *_timestamps(),
    schema="world",
    comment=(
        "Connects entities through a meaningful association (docs/DOMAIN_MODEL.md "
        "§11.1). Not entity-rooted — a world-scoped structural record with no "
        "independent canonical identity, same reasoning as world.area_connections "
        "(revision 039) and interaction.interactions (revision 061). Shared/"
        "objective facts only; subjective perception lives in "
        "world.relationship_perspectives (baseline) and campaign.relationship_state "
        "(current, timeline-scoped, event-driven)."
    ),
)

Index("ix_relationships_world_id", relationships.c.world_id)
Index("ix_relationships_relationship_type_id", relationships.c.relationship_type_id)
Index(
    "ix_relationships_source_id",
    relationships.c.source_id,
    postgresql_where=relationships.c.source_id.isnot(None),
)
Index(
    "ix_relationships_started_world_time_id",
    relationships.c.started_world_time_id,
    postgresql_where=relationships.c.started_world_time_id.isnot(None),
)
Index(
    "ix_relationships_ended_world_time_id",
    relationships.c.ended_world_time_id,
    postgresql_where=relationships.c.ended_world_time_id.isnot(None),
)

relationship_participants = Table(
    "relationship_participants",
    metadata,
    _uuid_pk("relationship_participant_id"),
    Column(
        "relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "participant_role_id",
        UUID(),
        ForeignKey(
            "world.relationship_participant_roles.relationship_participant_role_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("notes", Text()),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "relationship_id",
        "entity_id",
        "participant_role_id",
        name="ux_relationship_participants_relationship_entity_role",
    ),
    schema="world",
    comment=(
        "Identifies an entity's role in a relationship, allowing asymmetric "
        "relationships (docs/DOMAIN_MODEL.md §11.2). Append-only."
    ),
)

Index("ix_relationship_participants_relationship_id", relationship_participants.c.relationship_id)
Index("ix_relationship_participants_entity_id", relationship_participants.c.entity_id)
Index(
    "ix_relationship_participants_participant_role_id",
    relationship_participants.c.participant_role_id,
)

relationship_perspectives = Table(
    "relationship_perspectives",
    metadata,
    _uuid_pk("relationship_perspective_id"),
    Column(
        "relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "perspective_holder_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("affinity", SmallInteger()),
    Column("trust", SmallInteger()),
    Column("respect", SmallInteger()),
    Column("fear", SmallInteger()),
    Column("obligation", SmallInteger()),
    Column("emotional_tone", Text()),
    Column("private_interpretation", Text()),
    *_timestamps(),
    UniqueConstraint(
        "relationship_id",
        "perspective_holder_entity_id",
        name="ux_relationship_perspectives_relationship_holder",
    ),
    schema="world",
    comment=(
        "A participant's authored, world-scoped baseline subjective view of a "
        "relationship — affinity, trust, respect, fear, obligation, emotional "
        "tone, private interpretation (docs/DOMAIN_MODEL.md §11.3). Stable "
        "content, not timeline-mutable — comparable to "
        "character.npc_characteristics. The CURRENT, event-driven, per-timeline "
        "view is campaign.relationship_state, below (objective/subjective split, "
        "conventions/rule 5)."
    ),
)

Index("ix_relationship_perspectives_relationship_id", relationship_perspectives.c.relationship_id)
Index(
    "ix_relationship_perspectives_perspective_holder_entity_id",
    relationship_perspectives.c.perspective_holder_entity_id,
)

# ---------------------------------------------------------------------------
# world — organizations and subtypes (revision 076)
# ---------------------------------------------------------------------------

organization_types = _lookup_table(
    "world",
    "organization_types",
    "organization_type_id",
    "The kind of organization a world.organizations row is "
    "(docs/DOMAIN_MODEL.md §10.1) — government, business, guild, "
    "military_unit, religious_organization, criminal_organization, "
    "political_faction, secret_society, other. Five of these (all but "
    "guild/criminal_organization/secret_society/other) additionally get "
    "their own CTI leaf table below.",
)

organizations = Table(
    "organizations",
    metadata,
    Column(
        "organization_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "organization_type_id",
        UUID(),
        ForeignKey("world.organization_types.organization_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "parent_organization_id",
        UUID(),
        ForeignKey("world.organizations.organization_id", ondelete="SET NULL"),
    ),
    Column(
        "founded_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column(
        "dissolved_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column(
        "headquarters_location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="SET NULL"),
    ),
    Column("public_description", Text()),
    Column("internal_description", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A persistent group with identity, membership, goals, and relationships "
        "(docs/DOMAIN_MODEL.md §10.1). Entity-rooted — title, summary, canon "
        "status, and source are inherited from core.entities. Operational "
        "status (active/dissolved/dormant/banned/underground) is timeline state "
        "(campaign.organization_state, below), not a column here — the same "
        "definition/state split narrative.quests draws against "
        "campaign.quest_state."
    ),
)

Index("ix_organizations_organization_type_id", organizations.c.organization_type_id)
Index(
    "ix_organizations_parent_organization_id",
    organizations.c.parent_organization_id,
    postgresql_where=organizations.c.parent_organization_id.isnot(None),
)
Index(
    "ix_organizations_headquarters_location_id",
    organizations.c.headquarters_location_id,
    postgresql_where=organizations.c.headquarters_location_id.isnot(None),
)
Index(
    "ix_organizations_founded_world_time_id",
    organizations.c.founded_world_time_id,
    postgresql_where=organizations.c.founded_world_time_id.isnot(None),
)
Index(
    "ix_organizations_dissolved_world_time_id",
    organizations.c.dissolved_world_time_id,
    postgresql_where=organizations.c.dissolved_world_time_id.isnot(None),
)

businesses = Table(
    "businesses",
    metadata,
    Column(
        "business_id",
        UUID(),
        ForeignKey("world.organizations.organization_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("business_type", Text()),
    Column("operating_status", Text(), nullable=False, server_default=text("'operating'::text")),
    Column("reputation", SmallInteger()),
    *_timestamps(),
    schema="world",
    comment=(
        "A business organization engaged in trade, services, or production "
        "(docs/DOMAIN_MODEL.md §10.3). Locations/employees/owners are "
        "expressed through world.organizations.headquarters_location_id and "
        "the employment/ownership specialized relationships, not duplicated "
        "here; inventory and prices belong to the item domain."
    ),
)

governments = Table(
    "governments",
    metadata,
    Column(
        "government_id",
        UUID(),
        ForeignKey("world.organizations.organization_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("government_form", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A government organization (docs/DOMAIN_MODEL.md §10.1). "
        "Jurisdiction/territorial control is expressed through the universal "
        "relationship model (relationship_type = control), per "
        "a domain example, not a typed column here; offices/"
        "leaders are organization_memberships, agencies are child "
        "organizations (parent_organization_id)."
    ),
)

military_units = Table(
    "military_units",
    metadata,
    Column(
        "military_unit_id",
        UUID(),
        ForeignKey("world.organizations.organization_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("unit_type", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A military organization — army, militia, mercenary company, or "
        "guard force. Not described in further detail by "
        "docs/architecture/DATABASE_MODEL.md §10.3's hierarchy beyond naming "
        "the table; deliberately minimal, same latitude character.npcs took "
        "in revision 017."
    ),
)

political_factions = Table(
    "political_factions",
    metadata,
    Column(
        "political_faction_id",
        UUID(),
        ForeignKey("world.organizations.organization_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("ideology", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A political faction. Not described in further detail by "
        "docs/architecture/DATABASE_MODEL.md §10.3's hierarchy beyond naming "
        "the table; deliberately minimal, same latitude character.npcs took "
        "in revision 017."
    ),
)

# ---------------------------------------------------------------------------
# world — religions and religious organizations (revision 076)
# ---------------------------------------------------------------------------

religions = Table(
    "religions",
    metadata,
    Column(
        "religion_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("pantheon_structure", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A belief system, theology, or doctrine (docs/DOMAIN_MODEL.md §10.5) — "
        "distinct from a religious organization (a church, temple, order, or "
        "cult that serves it, world.religious_organizations, below). "
        "pantheon_structure is illustrative free text (monotheistic, "
        "polytheistic, pantheistic, animistic, philosophical, ...). Holy sites "
        "and reverence are expressed through the universal relationship model "
        '(the "religion reveres deity" relationship), not typed '
        "columns here; doctrines/rituals/sacred texts/symbols/traditions are "
        "descriptive lore carried by the inherited core.entities.summary and "
        "core.entity_names, with no exit criterion requiring structured "
        "columns for them yet."
    ),
)

religious_organizations = Table(
    "religious_organizations",
    metadata,
    Column(
        "religious_organization_id",
        UUID(),
        ForeignKey("world.organizations.organization_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "religion_id",
        UUID(),
        ForeignKey("world.religions.religion_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    *_timestamps(),
    schema="world",
    comment=(
        "An organization affiliated with a religion — a church, temple, order, "
        "or cult (docs/DOMAIN_MODEL.md §10.6)."
    ),
)

Index("ix_religious_organizations_religion_id", religious_organizations.c.religion_id)

# ---------------------------------------------------------------------------
# world — specialized relationships (revision 076)
# ---------------------------------------------------------------------------

organization_memberships = Table(
    "organization_memberships",
    metadata,
    Column(
        "relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "organization_id",
        UUID(),
        ForeignKey("world.organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "member_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", Text()),
    Column("rank", Text()),
    Column("is_public", Boolean(), nullable=False, server_default=text("true")),
    Column(
        "effective_from_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "effective_to_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column("membership_period", INT8RANGE(), nullable=False),
    *_timestamps(),
    schema="world",
    comment=(
        "A specialized relationship: an entity's membership in an organization "
        "— role, rank, public/secret, joining and leaving, multiple memberships "
        "over time (docs/DOMAIN_MODEL.md §10.2). Rejoining creates a new row "
        "(a new world.relationships parent) rather than reopening an old one, "
        "the same pattern campaign.party_memberships uses; the exclusion "
        "constraint rejects overlapping stints for the same (organization, "
        "member), concurrency-safe in a way an application check is not "
        "(ADR 0010)."
    ),
)

Index("ix_organization_memberships_organization_id", organization_memberships.c.organization_id)
Index("ix_organization_memberships_member_entity_id", organization_memberships.c.member_entity_id)
Index(
    "ix_organization_memberships_effective_from_world_time_id",
    organization_memberships.c.effective_from_world_time_id,
)
Index(
    "ix_organization_memberships_effective_to_world_time_id",
    organization_memberships.c.effective_to_world_time_id,
    postgresql_where=organization_memberships.c.effective_to_world_time_id.isnot(None),
)

employment_relationships = Table(
    "employment_relationships",
    metadata,
    Column(
        "relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "employer_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "employee_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("job_title", Text()),
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
    *_timestamps(),
    schema="world",
    comment=(
        "A specialized relationship: employer and employee "
        "(docs/architecture/DATABASE_MODEL.md §10.2). Currentness follows "
        'conventions §12.4\'s "effective_to_world_time_id IS NULL" pattern — the '
        "one pattern per domain the convention requires, chosen over a separate "
        "is_current column so contradictory current/end-dated combinations are "
        "structurally impossible rather than merely guarded. No ADR 0010 "
        "exclusion constraint — see this revision's docstring scoping note."
    ),
)

Index(
    "ix_employment_relationships_employer_entity_id", employment_relationships.c.employer_entity_id
)
Index(
    "ix_employment_relationships_employee_entity_id", employment_relationships.c.employee_entity_id
)
Index(
    "ix_employment_relationships_effective_from_world_time_id",
    employment_relationships.c.effective_from_world_time_id,
    postgresql_where=employment_relationships.c.effective_from_world_time_id.isnot(None),
)
Index(
    "ix_employment_relationships_effective_to_world_time_id",
    employment_relationships.c.effective_to_world_time_id,
    postgresql_where=employment_relationships.c.effective_to_world_time_id.isnot(None),
)

ownership_relationships = Table(
    "ownership_relationships",
    metadata,
    Column(
        "relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "owner_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "owned_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ownership_share", PERCENTAGE_0_100),
    Column("is_public", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    schema="world",
    comment=(
        "A specialized relationship: an entity owning another non-item entity "
        "— a business, a building, another organization "
        "(docs/architecture/DATABASE_MODEL.md §10.2). Item ownership stays with "
        "campaign.item_ownership rather than "
        "this table."
    ),
)

Index("ix_ownership_relationships_owner_entity_id", ownership_relationships.c.owner_entity_id)
Index("ix_ownership_relationships_owned_entity_id", ownership_relationships.c.owned_entity_id)

family_relationships = Table(
    "family_relationships",
    metadata,
    Column(
        "relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("family_unit_name", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A specialized relationship: family ties "
        "(docs/architecture/DATABASE_MODEL.md §10.2). Participants (parent/"
        "child, sibling, spouse, ...) are expressed through "
        "world.relationship_participants' typed roles, not duplicated here; "
        "family_unit_name is the one genuinely typed addition (e.g. a shared "
        "house name) beyond that generic shape."
    ),
)

political_relationships = Table(
    "political_relationships",
    metadata,
    Column(
        "relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    Column("treaty_terms", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A specialized relationship: political control, alliance, or rivalry "
        "(docs/architecture/DATABASE_MODEL.md §10.2). The kind of political "
        "relationship is world.relationships.relationship_type_id (alliance/"
        "rivalry/war/control/...); is_active/treaty_terms are the typed "
        "additions beyond that generic shape."
    ),
)
