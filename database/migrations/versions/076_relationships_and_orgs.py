"""Relationships and organizations domain: universal relationships,
perspectives, specialized relationships, organizations and subtypes,
religions, memberships, and their timeline state.

Revision ID: 076_relationships_and_orgs
Revises: 075_phase7_reparent_guards
Create Date: 2026-08-07 12:00:00.000000

Purpose:
    Phase 8 ("Relationships and organizations", docs/PLAN.md §23) delivers
    the universal relationship model (docs/architecture/DATABASE_MODEL.md
    §10), the organization/business/government/religious-organization/
    military-unit/political-faction CTI hierarchy, the religion/religious-
    affiliation distinction (§10.4), and the two timeline-state tables §17
    already names but no earlier phase built: campaign.organization_state
    and campaign.relationship_state.

    world.relationships is not entity-rooted — same reasoning
    DATABASE_MODEL.md §9/§16 gives for world.area_connections and
    interaction.interactions: it is a structural record connecting
    entities, with no independent canonical identity of its own (no name,
    no discoverable history beyond its participants and type).
    world.organizations and world.religions ARE entity-rooted (§10's
    erDiagram: `CORE_ENTITIES ||--|| WORLD_ORGANIZATIONS : is`), mirroring
    the quest/story-arc split revision 073 already established.

    Definition versus timeline state (rule 5): world.relationship_perspectives
    holds the authored, world-scoped BASELINE subjective disposition for a
    participant (comparable to character.npc_characteristics — stable
    content, not something an event updates). campaign.relationship_state is
    the CURRENT, timeline-scoped, event-driven view that can diverge after a
    branch and is what docs/PLAN.md's exit criterion ("NPC and faction
    reactions can evolve from events") actually requires. It reuses the same
    nullable-dimension idiom campaign.quest_state established for party_id:
    perspective_holder_entity_id NULL means the row is the shared/objective
    status of the relationship; set, it is that one participant's current
    subjective reaction. "Shared and subjective relationship data are
    separate" (the second exit criterion) is this NULL/non-NULL split,
    enforced by the two partial unique indexes below, not two separate
    tables — the same choice quest_state/objective_state already made for
    "timeline-wide vs. party-specific."

    world.organizations.organization_type_id (lookup: government, business,
    guild, military_unit, religious_organization, criminal_organization,
    political_faction, secret_society, other) covers every subtype
    docs/DOMAIN_MODEL.md §10.1 names. Five of those additionally get their
    own CTI leaf table (world.businesses/.governments/
    .religious_organizations/.military_units/.political_factions) because
    DATABASE_MODEL.md §10.3's hierarchy diagram names them explicitly and
    each needs at least one typed column beyond the generic organization
    row; guild/criminal_organization/secret_society/other do not get their
    own table, the same way character.characters has no bare, subtype-less
    row in practice but the CTI mechanism does not forbid one.

    Jurisdiction/territorial control, organizational offices/leaders, and
    political alliances are deliberately NOT typed columns on
    world.governments — docs/PLAN.md's own example ("organization controls
    settlement") already names the mechanism: the universal relationship
    model (relationship_type = controls/political), reused rather than
    duplicated. world.governments therefore carries only government_form.

    Forward-reference placeholders closed: narrative.event_effects gains
    target_relationship_id (the seventh column in the knowledge_items/
    interaction.targets/quest_objectives "at-most-one-typed-target"
    pattern, extending the CHECK revision 073 last extended), and
    interaction.consequences gains resulting_relationship_state_id, closing
    revision 061's own docstring note ("relationship_change ... consequence
    types have no FK target at all yet ... Phase 7/8 domains don't exist")
    for its relationship half — the quest half was already closed by
    revision 073.

Forward migration:
    - core.entity_types rows: organization (base, required_subtype_table =
      'world.organizations'), business/government/religious_organization/
      military_unit/political_faction (children of organization, each
      required_subtype_table pointing at its own leaf table), religion
      (separate root, required_subtype_table = 'world.religions')
    - world.relationship_types (lookup), seeded
    - world.relationship_participant_roles (lookup), seeded
    - world.relationships (not entity-rooted), with
      world.enforce_relationship_validity()
    - world.relationship_participants, with
      world.enforce_relationship_participant_world()
    - world.relationship_perspectives, with
      world.enforce_relationship_perspective_participant()
    - world.organization_types (lookup), seeded
    - world.organizations (entity-rooted), with
      world.enforce_organization_world()
    - world.businesses / world.governments / world.military_units /
      world.political_factions (CTI leaves of world.organizations)
    - world.religious_organizations (CTI leaf of world.organizations, plus
      world.enforce_religious_organization_world() for its religion_id)
    - world.religions (entity-rooted, separate CTI chain)
    - character.character_religious_affiliations, with
      character.enforce_character_religious_affiliation_world()
    - world.organization_memberships (CTI leaf of world.relationships), an
      ADR 0010-shaped exclusion constraint over
      (organization_id, member_entity_id, membership_period) via
      world.sync_organization_membership_period() — the same overlap-
      prevention shape campaign.party_memberships established
    - world.employment_relationships / world.ownership_relationships (CTI
      leaves of world.relationships, each with its own world-agreement
      trigger) and world.family_relationships / world.political_relationships
      (CTI leaves with no additional entity reference to validate)
    - campaign.organization_statuses (lookup), seeded
    - campaign.organization_state, with
      campaign.enforce_organization_state_world() and the shared
      campaign.enforce_state_event_timeline() (revision 066)
    - campaign.relationship_statuses (lookup), seeded
    - campaign.relationship_state, with
      campaign.enforce_relationship_state_world() and the shared
      campaign.enforce_state_event_timeline()
    - narrative.event_types: two new seed rows, relationship_changed and
      organization_status_changed
    - narrative.event_effects.target_relationship_id (extends the
      at-most-one-target CHECK to seven columns)
    - interaction.consequences.resulting_relationship_state_id

Rollback:
    Supported. Drops everything created here in FK-dependency order, then
    the entity_types/event_types seed additions and the two extended
    columns on pre-existing tables.

Data implications:
    Seeds five small lookups (~49 rows total) and two event_types rows. No
    relationship, organization, religion, or state rows.

Locking considerations:
    Two ADD COLUMN statements against narrative.event_effects and
    interaction.consequences — both metadata-only (no default, no rewrite).
    Every other statement creates a new, empty object.

Deliberate scoping decisions:
    - world.organization_memberships does not verify that its parent
      world.relationships row's relationship_type_id is actually
      'membership' — the command layer is expected to set this when it
      creates the pair, the same latitude narrative.quests takes with its
      story_arc_id (no check that the arc is "about" this quest).
    - world.employment_relationships tracks validity with a current-records
      shape (§12.4: `effective_to_world_time_id IS NULL` means current)
      rather than an ADR 0010 exclusion constraint like
      organization_memberships. No exit criterion requires overlap
      prevention for employment specifically, and building a second
      exclusion-constrained interval table for every specialized
      relationship without a concrete caller would be speculative — see
      docs/DATABASE_CONVENTIONS.md §33.1. A deployable-integrity review
      found the original draft mixed that pattern with a redundant,
      unenforced `is_current` column with no world/chronology validation of
      its own at all — §12.4 requires choosing one current-records pattern
      per domain, not both — and removed the column. world.
      ownership_relationships carries no temporal validity columns at all
      (only `is_public`, an unrelated visibility flag), so it was never
      part of this shape and needed no corresponding fix.
    - world.family_relationships/.political_relationships add one genuinely
      typed column each (family_unit_name; is_active/treaty_terms) beyond
      the generic participant/perspective shape, and no direct entity
      reference of their own — participants are expressed through
      world.relationship_participants, the same way narrative.quests leans
      on narrative.quest_participants rather than duplicating entity
      references on the quest row itself.
    - Perspective/reaction measurements (affinity, trust, respect, fear,
      obligation) are plain nullable SMALLINT with an inline -100..100
      CHECK on both world.relationship_perspectives and
      campaign.relationship_state, rather than a new shared core.* DOMAIN.
      No other table needs a signed bounded scale yet; promoting it to a
      shared domain the moment a second caller exists is consistent with
      how core.percentage_0_100/rating_1_10 themselves were introduced.

See: docs/PLAN.md Phase 8 (relationships and organizations)
     docs/architecture/DATABASE_MODEL.md §10 (organizations and
     relationships), §17 (typed timeline state)
     docs/DOMAIN_MODEL.md §10 (organization and society domain), §11
     (relationship domain)
     docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency), §12.5
     (overlap prevention), §13 (timeline-state conventions)
     docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "076_relationships_and_orgs"
down_revision = "075_phase7_reparent_guards"
branch_labels = None
depends_on = None

RELATIONSHIP_TYPES = [
    ("family", "Family"),
    ("employment", "Employment"),
    ("membership", "Membership"),
    ("ownership", "Ownership"),
    ("alliance", "Alliance"),
    ("rivalry", "Rivalry"),
    ("war", "War"),
    ("control", "Control"),
    ("worship", "Worship"),
    ("adjacency", "Adjacency"),
    ("capital_of", "Capital Of"),
    ("parent_of", "Parent Of"),
    ("other", "Other"),
]

RELATIONSHIP_PARTICIPANT_ROLES = [
    ("subject", "Subject"),
    ("object", "Object"),
    ("parent", "Parent"),
    ("child", "Child"),
    ("employer", "Employer"),
    ("employee", "Employee"),
    ("owner", "Owner"),
    ("property", "Property"),
    ("ruler", "Ruler"),
    ("territory", "Territory"),
    ("member", "Member"),
    ("organization", "Organization"),
    ("ally", "Ally"),
    ("rival", "Rival"),
    ("other", "Other"),
]

ORGANIZATION_TYPES = [
    ("government", "Government"),
    ("business", "Business"),
    ("guild", "Guild"),
    ("military_unit", "Military Unit"),
    ("religious_organization", "Religious Organization"),
    ("criminal_organization", "Criminal Organization"),
    ("political_faction", "Political Faction"),
    ("secret_society", "Secret Society"),
    ("other", "Other"),
]

ORGANIZATION_STATUSES = [
    ("active", "Active"),
    ("dissolved", "Dissolved"),
    ("dormant", "Dormant"),
    ("banned", "Banned"),
    ("underground", "Underground"),
    ("unknown", "Unknown"),
]

RELATIONSHIP_STATUSES = [
    ("active", "Active"),
    ("ended", "Ended"),
    ("broken", "Broken"),
    ("estranged", "Estranged"),
    ("dormant", "Dormant"),
    ("unknown", "Unknown"),
]

NEW_EVENT_TYPES = [
    ("relationship_changed", "Relationship Changed"),
    ("organization_status_changed", "Organization Status Changed"),
]

AFFINITY_COLUMNS = ("affinity", "trust", "respect", "fear", "obligation")


def _lookup_table(schema: str, table: str, pk: str, comment: str) -> None:
    op.execute(f"""
        CREATE TABLE {schema}.{table} (
            {pk}          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_{table}_code UNIQUE (code),
            CONSTRAINT ck_{table}_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_{table}_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute(f"COMMENT ON TABLE {schema}.{table} IS '{comment}';")
    op.execute(f"""
        COMMENT ON COLUMN {schema}.{table}.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_{table}_set_updated_at
        BEFORE UPDATE ON {schema}.{table}
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)


def _affinity_checks(table: str) -> str:
    return ",\n            ".join(
        f"CONSTRAINT ck_{table}_{col}_range CHECK ({col} IS NULL OR {col} BETWEEN -100 AND 100)"
        for col in AFFINITY_COLUMNS
    )


def _organization_subtype(table: str, pk: str, extra_columns: str, comment: str) -> None:
    """A CTI leaf of world.organizations needing no trigger beyond the two
    every organization subtype gets: updated_at and subtype enforcement."""
    op.execute(f"""
        CREATE TABLE world.{table} (
            {pk}        UUID PRIMARY KEY
                        REFERENCES world.organizations(organization_id) ON DELETE CASCADE,
            {extra_columns}
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    escaped_comment = comment.replace("'", "''")
    op.execute(f"COMMENT ON TABLE world.{table} IS '{escaped_comment}';")
    op.execute(f"""
        CREATE TRIGGER tr_{table}_set_updated_at
        BEFORE UPDATE ON world.{table}
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(f"""
        CREATE TRIGGER tr_{table}_enforce_subtype
        AFTER INSERT OR UPDATE ON world.{table}
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('{pk}');
    """)


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.entity_types rows
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, required_subtype_table, required_subtype_pk_column)
        VALUES ('organization', 'Organization', 'world.organizations', 'organization_id')
        ON CONFLICT (code) DO NOTHING;
    """)
    for code, display_name, table, pk_column in [
        ("business", "Business", "world.businesses", "business_id"),
        ("government", "Government", "world.governments", "government_id"),
        (
            "religious_organization",
            "Religious Organization",
            "world.religious_organizations",
            "religious_organization_id",
        ),
        ("military_unit", "Military Unit", "world.military_units", "military_unit_id"),
        (
            "political_faction",
            "Political Faction",
            "world.political_factions",
            "political_faction_id",
        ),
    ]:
        op.execute(f"""
            INSERT INTO core.entity_types
                (code, display_name, parent_entity_type_id, required_subtype_table,
                 required_subtype_pk_column)
            VALUES (
                '{code}', '{display_name}',
                (SELECT entity_type_id FROM core.entity_types WHERE code = 'organization'),
                '{table}', '{pk_column}'
            )
            ON CONFLICT (code) DO NOTHING;
        """)
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, required_subtype_table, required_subtype_pk_column)
        VALUES ('religion', 'Religion', 'world.religions', 'religion_id')
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. world.relationship_types / world.relationship_participant_roles
    # ==========================================================================
    _lookup_table(
        "world",
        "relationship_types",
        "relationship_type_id",
        "The kind of association a world.relationships row records "
        "(docs/DOMAIN_MODEL.md §11.1) — family, employment, membership, "
        "ownership, alliance, rivalry, war, control, worship, adjacency, "
        "capital_of, parent_of, other.",
    )
    for sort_order, (code, display_name) in enumerate(RELATIONSHIP_TYPES):
        op.execute(f"""
            INSERT INTO world.relationship_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    _lookup_table(
        "world",
        "relationship_participant_roles",
        "relationship_participant_role_id",
        "How a participating entity relates to a relationship, allowing "
        "asymmetric relationships (docs/DOMAIN_MODEL.md §11.2) — parent/"
        "child, employer/employee, owner/property, ruler/territory, plus "
        "generic subject/object and member/organization.",
    )
    for sort_order, (code, display_name) in enumerate(RELATIONSHIP_PARTICIPANT_ROLES):
        op.execute(f"""
            INSERT INTO world.relationship_participant_roles (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 3. world.relationships (not entity-rooted — see docstring)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.relationships (
            relationship_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id                UUID NOT NULL
                                    REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            relationship_type_id    UUID NOT NULL
                                    REFERENCES world.relationship_types(relationship_type_id)
                                    ON DELETE RESTRICT,
            description              TEXT,
            started_world_time_id    UUID
                                    REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            ended_world_time_id      UUID
                                    REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            source_id                UUID REFERENCES core.sources(source_id) ON DELETE SET NULL,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_relationships_ended_requires_started CHECK (
                ended_world_time_id IS NULL OR started_world_time_id IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.relationships IS
        'Connects entities through a meaningful association (docs/DOMAIN_MODEL.md '
        '§11.1). Not entity-rooted — a world-scoped structural record with no '
        'independent canonical identity, same reasoning as world.area_connections '
        '(revision 039) and interaction.interactions (revision 061). Shared/'
        'objective facts only; subjective perception lives in '
        'world.relationship_perspectives (baseline) and campaign.relationship_state '
        '(current, timeline-scoped, event-driven).';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationships_set_updated_at
        BEFORE UPDATE ON world.relationships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_relationships_world_id ON world.relationships (world_id);")
    op.execute(
        "CREATE INDEX ix_relationships_relationship_type_id "
        "ON world.relationships (relationship_type_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationships_source_id ON world.relationships (source_id) "
        "WHERE source_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_relationships_started_world_time_id "
        "ON world.relationships (started_world_time_id) "
        "WHERE started_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_relationships_ended_world_time_id "
        "ON world.relationships (ended_world_time_id) "
        "WHERE ended_world_time_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_relationship_validity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_start_world     UUID;
            v_start_sort_key  BIGINT;
            v_end_world       UUID;
            v_end_sort_key    BIGINT;
        BEGIN
            IF NEW.started_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_start_world, v_start_sort_key
                FROM core.world_times WHERE world_time_id = NEW.started_world_time_id;

                IF v_start_world IS DISTINCT FROM NEW.world_id THEN
                    RAISE EXCEPTION
                        'Relationship % belongs to world %, but started_world_time_id % '
                        'belongs to world %',
                        NEW.relationship_id, NEW.world_id, NEW.started_world_time_id, v_start_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.ended_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_end_world, v_end_sort_key
                FROM core.world_times WHERE world_time_id = NEW.ended_world_time_id;

                IF v_end_world IS DISTINCT FROM NEW.world_id THEN
                    RAISE EXCEPTION
                        'Relationship % belongs to world %, but ended_world_time_id % '
                        'belongs to world %',
                        NEW.relationship_id, NEW.world_id, NEW.ended_world_time_id, v_end_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;

                IF v_end_sort_key <= v_start_sort_key THEN
                    RAISE EXCEPTION
                        'Relationship % ended_world_time_id must be strictly after '
                        'started_world_time_id', NEW.relationship_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_relationship_validity() IS
        'Validity-window guard for world.relationships: started/ended_world_time_id, '
        'when set, must belong to the relationship''s own world, and an end must be '
        'strictly after the start (conventions §12.3).';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationships_enforce_validity
        BEFORE INSERT OR UPDATE ON world.relationships
        FOR EACH ROW EXECUTE FUNCTION world.enforce_relationship_validity();
    """)
    op.execute("""
        CREATE TRIGGER tr_relationships_enforce_immutable
        BEFORE UPDATE ON world.relationships
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('world_id');
    """)

    # ==========================================================================
    # 4. world.relationship_participants
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.relationship_participants (
            relationship_participant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            relationship_id               UUID NOT NULL
                                          REFERENCES world.relationships(relationship_id)
                                          ON DELETE CASCADE,
            entity_id                     UUID NOT NULL
                                          REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            participant_role_id           UUID NOT NULL
                                          REFERENCES world.relationship_participant_roles
                                              (relationship_participant_role_id)
                                          ON DELETE RESTRICT,
            notes                         TEXT,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_relationship_participants_relationship_entity_role UNIQUE (
                relationship_id, entity_id, participant_role_id
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.relationship_participants IS
        'Identifies an entity''s role in a relationship, allowing asymmetric '
        'relationships (docs/DOMAIN_MODEL.md §11.2). Append-only.';
    """)
    op.execute(
        "CREATE INDEX ix_relationship_participants_relationship_id "
        "ON world.relationship_participants (relationship_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationship_participants_entity_id "
        "ON world.relationship_participants (entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationship_participants_participant_role_id "
        "ON world.relationship_participants (participant_role_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_relationship_participant_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_relationship_world  UUID;
            v_entity_world        UUID;
        BEGIN
            SELECT world_id INTO v_relationship_world
            FROM world.relationships WHERE relationship_id = NEW.relationship_id;

            SELECT world_id INTO v_entity_world
            FROM core.entities WHERE entity_id = NEW.entity_id;

            IF v_entity_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Relationship % belongs to world %, but participant entity % '
                    'belongs to world %',
                    NEW.relationship_id, v_relationship_world, NEW.entity_id, v_entity_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_relationship_participant_world() IS
        'Same-world guard for world.relationship_participants (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_participants_enforce_world
        BEFORE INSERT OR UPDATE ON world.relationship_participants
        FOR EACH ROW EXECUTE FUNCTION world.enforce_relationship_participant_world();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_relationship_participant_removal()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_relationship_exists  BOOLEAN;
            v_other_participant    BOOLEAN;
            v_orphaned_perspective UUID;
            v_orphaned_state       UUID;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.relationship_id = OLD.relationship_id
               AND NEW.entity_id = OLD.entity_id THEN
                RETURN NEW;
            END IF;

            -- A cascading delete of the whole relationship removes perspectives
            -- and relationship_state independently, through their own ON DELETE
            -- CASCADE FKs to world.relationships. Skip the orphan check in that
            -- case so a legitimate whole-relationship deletion is never blocked
            -- by the order cascades happen to fire in.
            SELECT EXISTS (
                SELECT 1 FROM world.relationships WHERE relationship_id = OLD.relationship_id
            ) INTO v_relationship_exists;
            IF NOT v_relationship_exists THEN
                RETURN COALESCE(NEW, OLD);
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM world.relationship_participants
                WHERE relationship_id = OLD.relationship_id
                  AND entity_id = OLD.entity_id
                  AND relationship_participant_id != OLD.relationship_participant_id
            ) INTO v_other_participant;
            IF v_other_participant THEN
                RETURN COALESCE(NEW, OLD);
            END IF;

            SELECT relationship_perspective_id INTO v_orphaned_perspective
            FROM world.relationship_perspectives
            WHERE relationship_id = OLD.relationship_id
              AND perspective_holder_entity_id = OLD.entity_id
            LIMIT 1;
            IF v_orphaned_perspective IS NOT NULL THEN
                RAISE EXCEPTION
                    'Cannot remove entity % as a participant in relationship %: '
                    'relationship_perspective % still holds a perspective on it',
                    OLD.entity_id, OLD.relationship_id, v_orphaned_perspective
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            SELECT relationship_state_id INTO v_orphaned_state
            FROM campaign.relationship_state
            WHERE relationship_id = OLD.relationship_id
              AND perspective_holder_entity_id = OLD.entity_id
            LIMIT 1;
            IF v_orphaned_state IS NOT NULL THEN
                RAISE EXCEPTION
                    'Cannot remove entity % as a participant in relationship %: '
                    'relationship_state % is still scoped to it',
                    OLD.entity_id, OLD.relationship_id, v_orphaned_state
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            RETURN COALESCE(NEW, OLD);
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_relationship_participant_removal() IS
        'Reverse guard for world.relationship_participants: rejects an UPDATE '
        'that changes (relationship_id, entity_id) or a DELETE when no other '
        'participant row would still cover that pairing and an existing '
        'world.relationship_perspectives or holder-scoped campaign.'
        'relationship_state row still depends on it as a participant. Skipped '
        'entirely when the parent world.relationships row no longer exists, so '
        'deleting an entire relationship (and its cascading children) is never '
        'blocked by cascade ordering.';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_participants_enforce_removal
        BEFORE UPDATE OR DELETE ON world.relationship_participants
        FOR EACH ROW EXECUTE FUNCTION world.enforce_relationship_participant_removal();
    """)

    # ==========================================================================
    # 5. world.relationship_perspectives (authored baseline — see docstring)
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE world.relationship_perspectives (
            relationship_perspective_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            relationship_id                UUID NOT NULL
                                           REFERENCES world.relationships(relationship_id)
                                           ON DELETE CASCADE,
            perspective_holder_entity_id   UUID NOT NULL
                                           REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            affinity                       SMALLINT,
            trust                          SMALLINT,
            respect                        SMALLINT,
            fear                           SMALLINT,
            obligation                     SMALLINT,
            emotional_tone                 TEXT,
            private_interpretation         TEXT,
            created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_relationship_perspectives_relationship_holder UNIQUE (
                relationship_id, perspective_holder_entity_id
            ),
            {_affinity_checks("relationship_perspectives")}
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.relationship_perspectives IS
        'A participant''s authored, world-scoped baseline subjective view of a '
        'relationship — affinity, trust, respect, fear, obligation, emotional '
        'tone, private interpretation (docs/DOMAIN_MODEL.md §11.3). Stable '
        'content, not timeline-mutable — comparable to '
        'character.npc_characteristics. The CURRENT, event-driven, per-timeline '
        'view is campaign.relationship_state, below (objective/subjective split, '
        'conventions/rule 5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_perspectives_set_updated_at
        BEFORE UPDATE ON world.relationship_perspectives
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_relationship_perspectives_relationship_id "
        "ON world.relationship_perspectives (relationship_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationship_perspectives_perspective_holder_entity_id "
        "ON world.relationship_perspectives (perspective_holder_entity_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_relationship_perspective_participant()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM world.relationship_participants
                WHERE relationship_id = NEW.relationship_id
                  AND entity_id = NEW.perspective_holder_entity_id
            ) THEN
                RAISE EXCEPTION
                    'perspective_holder_entity_id % is not a participant in relationship %',
                    NEW.perspective_holder_entity_id, NEW.relationship_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_relationship_perspective_participant() IS
        'A perspective''s holder must be a participant in the relationship it '
        'perceives.';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_perspectives_enforce_participant
        BEFORE INSERT OR UPDATE ON world.relationship_perspectives
        FOR EACH ROW EXECUTE FUNCTION world.enforce_relationship_perspective_participant();
    """)

    # ==========================================================================
    # 6. world.organization_types
    # ==========================================================================
    _lookup_table(
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
    for sort_order, (code, display_name) in enumerate(ORGANIZATION_TYPES):
        op.execute(f"""
            INSERT INTO world.organization_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 7. world.organizations (entity-rooted)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.organizations (
            organization_id            UUID PRIMARY KEY
                                       REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            organization_type_id       UUID NOT NULL
                                       REFERENCES world.organization_types(organization_type_id)
                                       ON DELETE RESTRICT,
            parent_organization_id     UUID
                                       REFERENCES world.organizations(organization_id)
                                       ON DELETE SET NULL,
            founded_world_time_id      UUID
                                       REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            dissolved_world_time_id    UUID
                                       REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            headquarters_location_id   UUID
                                       REFERENCES world.locations(location_id) ON DELETE SET NULL,
            public_description         TEXT,
            internal_description       TEXT,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_organizations_parent_not_self CHECK (
                parent_organization_id IS DISTINCT FROM organization_id
            ),
            CONSTRAINT ck_organizations_dissolved_requires_founded CHECK (
                dissolved_world_time_id IS NULL OR founded_world_time_id IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.organizations IS
        'A persistent group with identity, membership, goals, and relationships '
        '(docs/DOMAIN_MODEL.md §10.1). Entity-rooted — title, summary, canon '
        'status, and source are inherited from core.entities. Operational '
        'status (active/dissolved/dormant/banned/underground) is timeline state '
        '(campaign.organization_state, below), not a column here — the same '
        'definition/state split narrative.quests draws against '
        'campaign.quest_state.';
    """)
    op.execute("""
        CREATE TRIGGER tr_organizations_set_updated_at
        BEFORE UPDATE ON world.organizations
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_organizations_enforce_subtype
        AFTER INSERT OR UPDATE ON world.organizations
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('organization_id');
    """)
    op.execute(
        "CREATE INDEX ix_organizations_organization_type_id "
        "ON world.organizations (organization_type_id);"
    )
    op.execute(
        "CREATE INDEX ix_organizations_parent_organization_id "
        "ON world.organizations (parent_organization_id) "
        "WHERE parent_organization_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_organizations_headquarters_location_id "
        "ON world.organizations (headquarters_location_id) "
        "WHERE headquarters_location_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_organizations_founded_world_time_id "
        "ON world.organizations (founded_world_time_id) "
        "WHERE founded_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_organizations_dissolved_world_time_id "
        "ON world.organizations (dissolved_world_time_id) "
        "WHERE dissolved_world_time_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_organization_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world        UUID;
            v_parent_world     UUID;
            v_hq_world         UUID;
            v_founded_world    UUID;
            v_founded_sort_key BIGINT;
            v_dissolved_world  UUID;
            v_dissolved_sort_key BIGINT;
        BEGIN
            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.organization_id;

            IF NEW.parent_organization_id IS NOT NULL THEN
                SELECT e.world_id INTO v_parent_world
                FROM core.entities e WHERE e.entity_id = NEW.parent_organization_id;

                IF v_parent_world IS DISTINCT FROM v_own_world THEN
                    RAISE EXCEPTION
                        'Organization % belongs to world %, but parent organization % '
                        'belongs to world %',
                        NEW.organization_id, v_own_world, NEW.parent_organization_id, v_parent_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.headquarters_location_id IS NOT NULL THEN
                SELECT e.world_id INTO v_hq_world
                FROM core.entities e WHERE e.entity_id = NEW.headquarters_location_id;

                IF v_hq_world IS DISTINCT FROM v_own_world THEN
                    RAISE EXCEPTION
                        'Organization % belongs to world %, but headquarters location % '
                        'belongs to world %',
                        NEW.organization_id, v_own_world, NEW.headquarters_location_id, v_hq_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.founded_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_founded_world, v_founded_sort_key
                FROM core.world_times WHERE world_time_id = NEW.founded_world_time_id;

                IF v_founded_world IS DISTINCT FROM v_own_world THEN
                    RAISE EXCEPTION
                        'Organization % belongs to world %, but founded_world_time_id % '
                        'belongs to world %',
                        NEW.organization_id, v_own_world, NEW.founded_world_time_id, v_founded_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.dissolved_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_dissolved_world, v_dissolved_sort_key
                FROM core.world_times WHERE world_time_id = NEW.dissolved_world_time_id;

                IF v_dissolved_world IS DISTINCT FROM v_own_world THEN
                    RAISE EXCEPTION
                        'Organization % belongs to world %, but dissolved_world_time_id % '
                        'belongs to world %',
                        NEW.organization_id, v_own_world, NEW.dissolved_world_time_id,
                        v_dissolved_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;

                IF v_dissolved_sort_key <= v_founded_sort_key THEN
                    RAISE EXCEPTION
                        'Organization % dissolved_world_time_id must be strictly after '
                        'founded_world_time_id', NEW.organization_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_organization_world() IS
        'Same-world guard for world.organizations: parent_organization_id, '
        'headquarters_location_id, founded_world_time_id, and '
        'dissolved_world_time_id, when set, must belong to the organization''s '
        'own world; dissolved must be strictly after founded (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_organizations_enforce_world
        BEFORE INSERT OR UPDATE ON world.organizations
        FOR EACH ROW EXECUTE FUNCTION world.enforce_organization_world();
    """)

    # ==========================================================================
    # 8. world.businesses / world.governments / world.military_units /
    #    world.political_factions (CTI leaves needing no extra trigger)
    # ==========================================================================
    _organization_subtype(
        "businesses",
        "business_id",
        """business_type       TEXT,
            operating_status    TEXT NOT NULL DEFAULT 'operating',
            reputation          SMALLINT,
            CONSTRAINT ck_businesses_operating_status CHECK (
                operating_status IN ('operating', 'closed', 'bankrupt', 'relocated')
            ),
            CONSTRAINT ck_businesses_reputation_range CHECK (
                reputation IS NULL OR reputation BETWEEN -100 AND 100
            ),""",
        "A business organization engaged in trade, services, or production "
        "(docs/DOMAIN_MODEL.md §10.3). Locations/employees/owners are "
        "expressed through world.organizations.headquarters_location_id and "
        "the employment/ownership specialized relationships, not duplicated "
        "here; inventory/prices are deferred to Phase 9's item domain.",
    )
    _organization_subtype(
        "governments",
        "government_id",
        "government_form  TEXT,",
        "A government organization (docs/DOMAIN_MODEL.md §10.1). "
        "Jurisdiction/territorial control is expressed through the universal "
        "relationship model (relationship_type = control), per "
        "docs/PLAN.md's own example, not a typed column here; offices/"
        "leaders are organization_memberships, agencies are child "
        "organizations (parent_organization_id).",
    )
    _organization_subtype(
        "military_units",
        "military_unit_id",
        "unit_type  TEXT,",
        "A military organization — army, militia, mercenary company, or "
        "guard force. Not described in further detail by "
        "docs/architecture/DATABASE_MODEL.md §10.3's hierarchy beyond naming "
        "the table; deliberately minimal, same latitude character.npcs took "
        "in revision 017.",
    )
    _organization_subtype(
        "political_factions",
        "political_faction_id",
        "ideology  TEXT,",
        "A political faction. Not described in further detail by "
        "docs/architecture/DATABASE_MODEL.md §10.3's hierarchy beyond naming "
        "the table; deliberately minimal, same latitude character.npcs took "
        "in revision 017.",
    )

    # ==========================================================================
    # 9. world.religions (entity-rooted, separate CTI chain)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.religions (
            religion_id          UUID PRIMARY KEY
                                 REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            pantheon_structure    TEXT,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.religions IS
        'A belief system, theology, or doctrine (docs/DOMAIN_MODEL.md §10.5) — '
        'distinct from a religious organization (a church, temple, order, or '
        'cult that serves it, world.religious_organizations, below). '
        'pantheon_structure is illustrative free text (monotheistic, '
        'polytheistic, pantheistic, animistic, philosophical, ...). Holy sites '
        'and reverence are expressed through the universal relationship model '
        '(docs/PLAN.md''s own "religion reveres deity" example), not typed '
        'columns here; doctrines/rituals/sacred texts/symbols/traditions are '
        'descriptive lore carried by the inherited core.entities.summary and '
        'core.entity_names, with no exit criterion requiring structured '
        'columns for them yet.';
    """)
    op.execute("""
        CREATE TRIGGER tr_religions_set_updated_at
        BEFORE UPDATE ON world.religions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_religions_enforce_subtype
        AFTER INSERT OR UPDATE ON world.religions
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('religion_id');
    """)

    # ==========================================================================
    # 10. world.religious_organizations (CTI leaf needing its own trigger)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.religious_organizations (
            religious_organization_id  UUID PRIMARY KEY
                                       REFERENCES world.organizations(organization_id)
                                       ON DELETE CASCADE,
            religion_id                 UUID NOT NULL
                                       REFERENCES world.religions(religion_id) ON DELETE RESTRICT,
            created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.religious_organizations IS
        'An organization affiliated with a religion — a church, temple, order, '
        'or cult (docs/DOMAIN_MODEL.md §10.6).';
    """)
    op.execute("""
        CREATE TRIGGER tr_religious_organizations_set_updated_at
        BEFORE UPDATE ON world.religious_organizations
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_religious_organizations_enforce_subtype
        AFTER INSERT OR UPDATE ON world.religious_organizations
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('religious_organization_id');
    """)
    op.execute(
        "CREATE INDEX ix_religious_organizations_religion_id "
        "ON world.religious_organizations (religion_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_religious_organization_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world      UUID;
            v_religion_world UUID;
        BEGIN
            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.religious_organization_id;

            SELECT world_id INTO v_religion_world
            FROM core.entities WHERE entity_id = NEW.religion_id;

            IF v_religion_world IS DISTINCT FROM v_own_world THEN
                RAISE EXCEPTION
                    'Religious organization % belongs to world %, but religion % '
                    'belongs to world %',
                    NEW.religious_organization_id, v_own_world, NEW.religion_id, v_religion_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_religious_organization_world() IS
        'Same-world guard for world.religious_organizations.religion_id '
        '(conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_religious_organizations_enforce_world
        BEFORE INSERT OR UPDATE ON world.religious_organizations
        FOR EACH ROW EXECUTE FUNCTION world.enforce_religious_organization_world();
    """)

    # ==========================================================================
    # 11. character.character_religious_affiliations
    # ==========================================================================
    op.execute("""
        CREATE TABLE character.character_religious_affiliations (
            character_religious_affiliation_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_id                          UUID NOT NULL
                                                  REFERENCES character.characters(character_id)
                                                  ON DELETE CASCADE,
            religion_id                            UUID NOT NULL
                                                  REFERENCES world.religions(religion_id)
                                                  ON DELETE CASCADE,
            devotion                               core.percentage_0_100,
            belief_status                          TEXT NOT NULL DEFAULT 'believer',
            practice                               TEXT,
            interpretation                         TEXT,
            conflicts                              TEXT,
            public_display                         BOOLEAN NOT NULL DEFAULT true,
            created_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_character_religious_affiliations_character_religion UNIQUE (
                character_id, religion_id
            ),
            CONSTRAINT ck_character_religious_affiliations_belief_status CHECK (
                belief_status IN ('believer', 'skeptic', 'apostate', 'convert', 'other')
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_religious_affiliations IS
        'A character''s personal relationship with a religion — devotion, '
        'belief status, practice, interpretation, conflicts, public display '
        '(docs/DOMAIN_MODEL.md §10.7). Kept separate from organizational rank '
        '(world.organization_memberships) and employment '
        '(world.employment_relationships) — clergy office and organizational '
        'rank remain organization memberships, not this table.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_religious_affiliations_set_updated_at
        BEFORE UPDATE ON character.character_religious_affiliations
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_character_religious_affiliations_character_id "
        "ON character.character_religious_affiliations (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_religious_affiliations_religion_id "
        "ON character.character_religious_affiliations (religion_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_character_religious_affiliation_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_character_world  UUID;
            v_religion_world   UUID;
        BEGIN
            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            SELECT world_id INTO v_religion_world
            FROM core.entities WHERE entity_id = NEW.religion_id;

            IF v_religion_world IS DISTINCT FROM v_character_world THEN
                RAISE EXCEPTION
                    'Character % belongs to world %, but religion % belongs to world %',
                    NEW.character_id, v_character_world, NEW.religion_id, v_religion_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_character_religious_affiliation_world() IS
        'Same-world guard for character.character_religious_affiliations '
        '(conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_religious_affiliations_enforce_world
        BEFORE INSERT OR UPDATE ON character.character_religious_affiliations
        FOR EACH ROW EXECUTE FUNCTION character.enforce_character_religious_affiliation_world();
    """)

    # ==========================================================================
    # 12. world.organization_memberships (CTI leaf of world.relationships,
    #     ADR 0010-shaped exclusion constraint)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.organization_memberships (
            relationship_id                UUID PRIMARY KEY
                                           REFERENCES world.relationships(relationship_id)
                                           ON DELETE CASCADE,
            organization_id                 UUID NOT NULL
                                           REFERENCES world.organizations(organization_id)
                                           ON DELETE CASCADE,
            member_entity_id                 UUID NOT NULL
                                           REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            role                             TEXT,
            rank                             TEXT,
            is_public                        BOOLEAN NOT NULL DEFAULT true,
            effective_from_world_time_id     UUID NOT NULL
                                           REFERENCES core.world_times(world_time_id)
                                           ON DELETE RESTRICT,
            effective_to_world_time_id       UUID
                                           REFERENCES core.world_times(world_time_id)
                                           ON DELETE RESTRICT,
            membership_period                INT8RANGE NOT NULL,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_organization_memberships_open_ended_agrees CHECK (
                (effective_to_world_time_id IS NULL) = (upper_inf(membership_period))
            ),
            CONSTRAINT ck_organization_memberships_lower_bound_finite CHECK (
                NOT lower_inf(membership_period)
            ),
            CONSTRAINT ck_organization_memberships_period_not_empty CHECK (
                NOT isempty(membership_period)
            ),
            CONSTRAINT ex_organization_memberships_no_overlap
                EXCLUDE USING gist (
                    organization_id WITH =,
                    member_entity_id WITH =,
                    membership_period WITH &&
                )
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.organization_memberships IS
        'A specialized relationship: an entity''s membership in an organization '
        '— role, rank, public/secret, joining and leaving, multiple memberships '
        'over time (docs/DOMAIN_MODEL.md §10.2). Rejoining creates a new row '
        '(a new world.relationships parent) rather than reopening an old one, '
        'the same pattern campaign.party_memberships uses; the exclusion '
        'constraint rejects overlapping stints for the same (organization, '
        'member), concurrency-safe in a way an application check is not '
        '(ADR 0010).';
    """)
    op.execute("""
        CREATE TRIGGER tr_organization_memberships_set_updated_at
        BEFORE UPDATE ON world.organization_memberships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_organization_memberships_organization_id "
        "ON world.organization_memberships (organization_id);"
    )
    op.execute(
        "CREATE INDEX ix_organization_memberships_member_entity_id "
        "ON world.organization_memberships (member_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_organization_memberships_effective_from_world_time_id "
        "ON world.organization_memberships (effective_from_world_time_id);"
    )
    op.execute(
        "CREATE INDEX ix_organization_memberships_effective_to_world_time_id "
        "ON world.organization_memberships (effective_to_world_time_id) "
        "WHERE effective_to_world_time_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.sync_organization_membership_period()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_relationship_world  UUID;
            v_org_world           UUID;
            v_member_world        UUID;
            v_from_world          UUID;
            v_from_sort_key       BIGINT;
            v_to_world            UUID;
            v_to_sort_key         BIGINT;
        BEGIN
            SELECT world_id INTO v_relationship_world
            FROM world.relationships WHERE relationship_id = NEW.relationship_id;

            SELECT e.world_id INTO v_org_world
            FROM core.entities e WHERE e.entity_id = NEW.organization_id;

            IF v_org_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Relationship % belongs to world %, but organization % belongs to world %',
                    NEW.relationship_id, v_relationship_world, NEW.organization_id, v_org_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id INTO v_member_world
            FROM core.entities WHERE entity_id = NEW.member_entity_id;

            IF v_member_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Relationship % belongs to world %, but member % belongs to world %',
                    NEW.relationship_id, v_relationship_world, NEW.member_entity_id, v_member_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id, sort_key INTO v_from_world, v_from_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_from_world_time_id;

            IF v_from_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Start world time % belongs to world %, but relationship % belongs '
                    'to world %',
                    NEW.effective_from_world_time_id, v_from_world, NEW.relationship_id,
                    v_relationship_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.effective_to_world_time_id IS NULL THEN
                NEW.membership_period := int8range(v_from_sort_key, NULL, '[)');
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_to_world, v_to_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_to_world_time_id;

            IF v_to_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'End world time % belongs to world %, but relationship % belongs '
                    'to world %',
                    NEW.effective_to_world_time_id, v_to_world, NEW.relationship_id,
                    v_relationship_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_to_sort_key <= v_from_sort_key THEN
                RAISE EXCEPTION
                    'Membership % effective_to_world_time_id must be strictly after '
                    'effective_from_world_time_id', NEW.relationship_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.membership_period := int8range(v_from_sort_key, v_to_sort_key, '[)');
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.sync_organization_membership_period() IS
        'Validates organization_id/member_entity_id/effective_from/to world '
        'agreement against the parent relationship''s world, then derives '
        'membership_period from the endpoints'' sort_key values — the same '
        'contract campaign.sync_party_membership_period() enforces (ADR 0010).';
    """)
    op.execute("""
        CREATE TRIGGER tr_organization_memberships_sync_period
        BEFORE INSERT OR UPDATE ON world.organization_memberships
        FOR EACH ROW EXECUTE FUNCTION world.sync_organization_membership_period();
    """)

    # ==========================================================================
    # 13. world.employment_relationships / world.ownership_relationships
    #     (CTI leaves of world.relationships with their own entity references)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.employment_relationships (
            relationship_id               UUID PRIMARY KEY
                                          REFERENCES world.relationships(relationship_id)
                                          ON DELETE CASCADE,
            employer_entity_id             UUID NOT NULL
                                          REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            employee_entity_id             UUID NOT NULL
                                          REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            job_title                       TEXT,
            effective_from_world_time_id    UUID
                                          REFERENCES core.world_times(world_time_id)
                                          ON DELETE RESTRICT,
            effective_to_world_time_id      UUID
                                          REFERENCES core.world_times(world_time_id)
                                          ON DELETE RESTRICT,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_employment_relationships_not_self CHECK (
                employer_entity_id IS DISTINCT FROM employee_entity_id
            ),
            CONSTRAINT ck_employment_relationships_end_requires_start CHECK (
                effective_to_world_time_id IS NULL OR effective_from_world_time_id IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.employment_relationships IS
        'A specialized relationship: employer and employee '
        '(docs/architecture/DATABASE_MODEL.md §10.2). Currentness follows '
        'conventions §12.4''s "effective_to_world_time_id IS NULL" pattern — the '
        'one pattern per domain the convention requires, chosen over a separate '
        'is_current column so contradictory current/end-dated combinations are '
        'structurally impossible rather than merely guarded. No ADR 0010 '
        'exclusion constraint — see this revision''s docstring scoping note.';
    """)
    op.execute("""
        CREATE TRIGGER tr_employment_relationships_set_updated_at
        BEFORE UPDATE ON world.employment_relationships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_employment_relationships_employer_entity_id "
        "ON world.employment_relationships (employer_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_employment_relationships_employee_entity_id "
        "ON world.employment_relationships (employee_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_employment_relationships_effective_from_world_time_id "
        "ON world.employment_relationships (effective_from_world_time_id) "
        "WHERE effective_from_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_employment_relationships_effective_to_world_time_id "
        "ON world.employment_relationships (effective_to_world_time_id) "
        "WHERE effective_to_world_time_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_employment_relationship_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_relationship_world  UUID;
            v_employer_world      UUID;
            v_employee_world      UUID;
            v_start_world         UUID;
            v_start_sort_key      BIGINT;
            v_end_world           UUID;
            v_end_sort_key        BIGINT;
        BEGIN
            SELECT world_id INTO v_relationship_world
            FROM world.relationships WHERE relationship_id = NEW.relationship_id;

            SELECT world_id INTO v_employer_world
            FROM core.entities WHERE entity_id = NEW.employer_entity_id;

            IF v_employer_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Relationship % belongs to world %, but employer % belongs to world %',
                    NEW.relationship_id, v_relationship_world, NEW.employer_entity_id,
                    v_employer_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id INTO v_employee_world
            FROM core.entities WHERE entity_id = NEW.employee_entity_id;

            IF v_employee_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Relationship % belongs to world %, but employee % belongs to world %',
                    NEW.relationship_id, v_relationship_world, NEW.employee_entity_id,
                    v_employee_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.effective_from_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_start_world, v_start_sort_key
                FROM core.world_times WHERE world_time_id = NEW.effective_from_world_time_id;

                IF v_start_world IS DISTINCT FROM v_relationship_world THEN
                    RAISE EXCEPTION
                        'Relationship % belongs to world %, but effective_from_world_time_id '
                        '% belongs to world %',
                        NEW.relationship_id, v_relationship_world,
                        NEW.effective_from_world_time_id, v_start_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.effective_to_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_end_world, v_end_sort_key
                FROM core.world_times WHERE world_time_id = NEW.effective_to_world_time_id;

                IF v_end_world IS DISTINCT FROM v_relationship_world THEN
                    RAISE EXCEPTION
                        'Relationship % belongs to world %, but effective_to_world_time_id % '
                        'belongs to world %',
                        NEW.relationship_id, v_relationship_world,
                        NEW.effective_to_world_time_id, v_end_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;

                IF v_start_sort_key IS NOT NULL AND v_end_sort_key <= v_start_sort_key THEN
                    RAISE EXCEPTION
                        'Employment relationship % effective_to_world_time_id must be '
                        'strictly after effective_from_world_time_id', NEW.relationship_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_employment_relationship_world() IS
        'Same-world guard for world.employment_relationships (conventions §9.5), '
        'plus: effective_from_world_time_id/effective_to_world_time_id, when set, '
        'must belong to the relationship''s own world, and an end must be '
        'strictly after the start (conventions §12.3) — the end-without-a-start '
        'case itself is rejected by ck_employment_relationships_end_requires_start '
        'before this trigger''s ordering check would even run.';
    """)
    op.execute("""
        CREATE TRIGGER tr_employment_relationships_enforce_world
        BEFORE INSERT OR UPDATE ON world.employment_relationships
        FOR EACH ROW EXECUTE FUNCTION world.enforce_employment_relationship_world();
    """)

    op.execute("""
        CREATE TABLE world.ownership_relationships (
            relationship_id     UUID PRIMARY KEY
                                REFERENCES world.relationships(relationship_id) ON DELETE CASCADE,
            owner_entity_id      UUID NOT NULL
                                REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            owned_entity_id      UUID NOT NULL
                                REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            ownership_share      core.percentage_0_100,
            is_public            BOOLEAN NOT NULL DEFAULT true,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_ownership_relationships_not_self CHECK (
                owner_entity_id IS DISTINCT FROM owned_entity_id
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.ownership_relationships IS
        'A specialized relationship: an entity owning another non-item entity '
        '— a business, a building, another organization '
        '(docs/architecture/DATABASE_MODEL.md §10.2). Item ownership stays with '
        'the future Phase 9 item domain (campaign.item_ownership) rather than '
        'this table.';
    """)
    op.execute("""
        CREATE TRIGGER tr_ownership_relationships_set_updated_at
        BEFORE UPDATE ON world.ownership_relationships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_ownership_relationships_owner_entity_id "
        "ON world.ownership_relationships (owner_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_ownership_relationships_owned_entity_id "
        "ON world.ownership_relationships (owned_entity_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_ownership_relationship_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_relationship_world  UUID;
            v_owner_world         UUID;
            v_owned_world         UUID;
        BEGIN
            SELECT world_id INTO v_relationship_world
            FROM world.relationships WHERE relationship_id = NEW.relationship_id;

            SELECT world_id INTO v_owner_world
            FROM core.entities WHERE entity_id = NEW.owner_entity_id;

            IF v_owner_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Relationship % belongs to world %, but owner % belongs to world %',
                    NEW.relationship_id, v_relationship_world, NEW.owner_entity_id, v_owner_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id INTO v_owned_world
            FROM core.entities WHERE entity_id = NEW.owned_entity_id;

            IF v_owned_world IS DISTINCT FROM v_relationship_world THEN
                RAISE EXCEPTION
                    'Relationship % belongs to world %, but owned entity % belongs to world %',
                    NEW.relationship_id, v_relationship_world, NEW.owned_entity_id, v_owned_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_ownership_relationship_world() IS
        'Same-world guard for world.ownership_relationships (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_ownership_relationships_enforce_world
        BEFORE INSERT OR UPDATE ON world.ownership_relationships
        FOR EACH ROW EXECUTE FUNCTION world.enforce_ownership_relationship_world();
    """)

    # ==========================================================================
    # 14. world.family_relationships / world.political_relationships
    #     (CTI leaves with no additional entity reference to validate)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.family_relationships (
            relationship_id    UUID PRIMARY KEY
                               REFERENCES world.relationships(relationship_id) ON DELETE CASCADE,
            family_unit_name    TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.family_relationships IS
        'A specialized relationship: family ties '
        '(docs/architecture/DATABASE_MODEL.md §10.2). Participants (parent/'
        'child, sibling, spouse, ...) are expressed through '
        'world.relationship_participants'' typed roles, not duplicated here; '
        'family_unit_name is the one genuinely typed addition (e.g. a shared '
        'house name) beyond that generic shape.';
    """)
    op.execute("""
        CREATE TRIGGER tr_family_relationships_set_updated_at
        BEFORE UPDATE ON world.family_relationships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    op.execute("""
        CREATE TABLE world.political_relationships (
            relationship_id  UUID PRIMARY KEY
                             REFERENCES world.relationships(relationship_id) ON DELETE CASCADE,
            is_active         BOOLEAN NOT NULL DEFAULT true,
            treaty_terms      TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.political_relationships IS
        'A specialized relationship: political control, alliance, or rivalry '
        '(docs/architecture/DATABASE_MODEL.md §10.2). The kind of political '
        'relationship is world.relationships.relationship_type_id (alliance/'
        'rivalry/war/control/...); is_active/treaty_terms are the typed '
        'additions beyond that generic shape.';
    """)
    op.execute("""
        CREATE TRIGGER tr_political_relationships_set_updated_at
        BEFORE UPDATE ON world.political_relationships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 15. campaign.organization_statuses / campaign.organization_state
    # ==========================================================================
    _lookup_table(
        "campaign",
        "organization_statuses",
        "organization_status_id",
        "Timeline-scoped organization operational status — active, "
        "dissolved, dormant, banned, underground, unknown.",
    )
    for sort_order, (code, display_name) in enumerate(ORGANIZATION_STATUSES):
        op.execute(f"""
            INSERT INTO campaign.organization_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute("""
        CREATE TABLE campaign.organization_state (
            organization_state_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                UUID NOT NULL
                                      REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            organization_id             UUID NOT NULL
                                      REFERENCES world.organizations(organization_id)
                                      ON DELETE CASCADE,
            organization_status_id      UUID NOT NULL
                                      REFERENCES campaign.organization_statuses
                                          (organization_status_id)
                                      ON DELETE RESTRICT,
            last_event_id                UUID
                                      REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_organization_state_timeline_organization UNIQUE (
                timeline_id, organization_id
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.organization_state IS
        'Tracks an organization''s current operational status for a timeline '
        '(docs/architecture/DATABASE_MODEL.md §17) — can diverge after a '
        'branch and evolve from events, unlike the stable world.organizations '
        'definition row. One current row per (timeline, organization).';
    """)
    op.execute("""
        CREATE TRIGGER tr_organization_state_set_updated_at
        BEFORE UPDATE ON campaign.organization_state
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_organization_state_timeline_id "
        "ON campaign.organization_state (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_organization_state_organization_id "
        "ON campaign.organization_state (organization_id);"
    )
    op.execute(
        "CREATE INDEX ix_organization_state_organization_status_id "
        "ON campaign.organization_state (organization_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_organization_state_last_event_id "
        "ON campaign.organization_state (last_event_id) "
        "WHERE last_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_organization_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world      UUID;
            v_organization_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_organization_world
            FROM core.entities WHERE entity_id = NEW.organization_id;

            IF v_organization_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but organization % belongs to world %',
                    NEW.timeline_id, v_timeline_world, NEW.organization_id, v_organization_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_organization_state_world() IS
        'Same-world guard for campaign.organization_state (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_organization_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.organization_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_organization_state_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_organization_state_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.organization_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 16. campaign.relationship_statuses / campaign.relationship_state
    # ==========================================================================
    _lookup_table(
        "campaign",
        "relationship_statuses",
        "relationship_status_id",
        "Timeline-scoped relationship status — active, ended, broken, estranged, dormant, unknown.",
    )
    for sort_order, (code, display_name) in enumerate(RELATIONSHIP_STATUSES):
        op.execute(f"""
            INSERT INTO campaign.relationship_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute(f"""
        CREATE TABLE campaign.relationship_state (
            relationship_state_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                    UUID NOT NULL
                                          REFERENCES campaign.timelines(timeline_id)
                                          ON DELETE CASCADE,
            relationship_id                 UUID NOT NULL
                                          REFERENCES world.relationships(relationship_id)
                                          ON DELETE CASCADE,
            perspective_holder_entity_id     UUID
                                          REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            relationship_status_id           UUID NOT NULL
                                          REFERENCES campaign.relationship_statuses
                                              (relationship_status_id)
                                          ON DELETE RESTRICT,
            affinity                         SMALLINT,
            trust                            SMALLINT,
            respect                          SMALLINT,
            fear                             SMALLINT,
            obligation                       SMALLINT,
            emotional_tone                   TEXT,
            private_interpretation           TEXT,
            last_event_id                     UUID
                                          REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            {_affinity_checks("relationship_state")}
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.relationship_state IS
        'Tracks a relationship''s current status for a timeline, optionally '
        'scoped to one perspective holder (docs/architecture/DATABASE_MODEL.md '
        '§17) — same perspective_holder_entity_id NULL/set convention as '
        'campaign.quest_state''s party_id: NULL is the shared/objective status, '
        'set is that one participant''s current subjective reaction (affinity, '
        'trust, respect, fear, obligation, emotional tone). This is the row '
        'events update — see docs/PLAN.md''s "NPC and faction reactions can '
        'evolve from events" exit criterion — unlike the stable, authored '
        'world.relationship_perspectives baseline. One current row per '
        '(timeline, relationship[, perspective holder]) — see the partial '
        'unique indexes below.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.relationship_state.perspective_holder_entity_id IS
        'NULL for the relationship''s shared/objective status; set for one '
        'participant''s own current subjective reaction — same convention as '
        'campaign.quest_state.party_id.';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_state_set_updated_at
        BEFORE UPDATE ON campaign.relationship_state
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_relationship_state_timeline_id "
        "ON campaign.relationship_state (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationship_state_relationship_id "
        "ON campaign.relationship_state (relationship_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationship_state_perspective_holder_entity_id "
        "ON campaign.relationship_state (perspective_holder_entity_id) "
        "WHERE perspective_holder_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_relationship_state_relationship_status_id "
        "ON campaign.relationship_state (relationship_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationship_state_last_event_id "
        "ON campaign.relationship_state (last_event_id) "
        "WHERE last_event_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_relationship_state_timeline_relationship_no_holder
        ON campaign.relationship_state (timeline_id, relationship_id)
        WHERE perspective_holder_entity_id IS NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_relationship_state_timeline_relationship_holder
        ON campaign.relationship_state (
            timeline_id, relationship_id, perspective_holder_entity_id
        )
        WHERE perspective_holder_entity_id IS NOT NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_relationship_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world      UUID;
            v_relationship_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_relationship_world
            FROM world.relationships WHERE relationship_id = NEW.relationship_id;

            IF v_relationship_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but relationship % belongs to world %',
                    NEW.timeline_id, v_timeline_world, NEW.relationship_id, v_relationship_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.perspective_holder_entity_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM world.relationship_participants
                   WHERE relationship_id = NEW.relationship_id
                     AND entity_id = NEW.perspective_holder_entity_id
               )
            THEN
                RAISE EXCEPTION
                    'perspective_holder_entity_id % is not a participant in relationship %',
                    NEW.perspective_holder_entity_id, NEW.relationship_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_relationship_state_world() IS
        'Same-world guard for campaign.relationship_state (conventions §9.5), '
        'plus: perspective_holder_entity_id, when set, must be a participant '
        'in the relationship.';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.relationship_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_relationship_state_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_state_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.relationship_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)
    op.execute("""
        CREATE TRIGGER tr_relationship_state_enforce_immutable
        BEFORE UPDATE ON campaign.relationship_state
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('timeline_id');
    """)

    # ==========================================================================
    # 17. narrative.event_types: relationship/organization seed rows
    # ==========================================================================
    for sort_order, (code, display_name) in enumerate(NEW_EVENT_TYPES, start=102):
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 18. narrative.event_effects.target_relationship_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE narrative.event_effects
        ADD COLUMN target_relationship_id UUID
            REFERENCES world.relationships(relationship_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_effects.target_relationship_id IS
        'The relationship this event changed, when it has one — the seventh '
        'target_* column in the at-most-one-of-N pattern (revision 057, last '
        'extended by revision 073).';
    """)
    op.execute("""
        ALTER TABLE narrative.event_effects
        DROP CONSTRAINT ck_event_effects_at_most_one_target;
    """)
    op.execute("""
        ALTER TABLE narrative.event_effects
        ADD CONSTRAINT ck_event_effects_at_most_one_target CHECK (
            num_nonnulls(
                target_entity_id, target_area_connection_id, target_area_feature_id,
                target_area_hazard_id, target_area_interactable_id, target_quest_objective_id,
                target_relationship_id
            ) <= 1
        );
    """)
    op.execute(
        "CREATE INDEX ix_event_effects_target_relationship_id "
        "ON narrative.event_effects (target_relationship_id) "
        "WHERE target_relationship_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_effect_target_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_world    UUID;
            v_target_world   UUID;
        BEGIN
            SELECT world_id INTO v_event_world
            FROM core.entities WHERE entity_id = NEW.event_id;

            IF NEW.target_entity_id IS NOT NULL THEN
                SELECT world_id INTO v_target_world
                FROM core.entities WHERE entity_id = NEW.target_entity_id;
            ELSIF NEW.target_area_connection_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_connections ac
                JOIN core.entities e ON e.entity_id = ac.from_dungeon_area_id
                WHERE ac.area_connection_id = NEW.target_area_connection_id;
            ELSIF NEW.target_area_feature_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_features af
                JOIN core.entities e ON e.entity_id = af.dungeon_area_id
                WHERE af.area_feature_id = NEW.target_area_feature_id;
            ELSIF NEW.target_area_hazard_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_hazards ah
                JOIN core.entities e ON e.entity_id = ah.dungeon_area_id
                WHERE ah.area_hazard_id = NEW.target_area_hazard_id;
            ELSIF NEW.target_area_interactable_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_interactables ai
                JOIN core.entities e ON e.entity_id = ai.dungeon_area_id
                WHERE ai.area_interactable_id = NEW.target_area_interactable_id;
            ELSIF NEW.target_quest_objective_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM narrative.quest_objectives qo
                JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
                JOIN narrative.quests q ON q.quest_id = qs.quest_id
                JOIN core.entities e ON e.entity_id = q.quest_id
                WHERE qo.quest_objective_id = NEW.target_quest_objective_id;
            ELSIF NEW.target_relationship_id IS NOT NULL THEN
                SELECT world_id INTO v_target_world
                FROM world.relationships WHERE relationship_id = NEW.target_relationship_id;
            ELSE
                RETURN NEW;
            END IF;

            IF v_target_world IS DISTINCT FROM v_event_world THEN
                RAISE EXCEPTION
                    'Event effect target belongs to world %, but event % belongs to world %',
                    v_target_world, NEW.event_id, v_event_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_effect_target_world() IS
        'World-agreement guard for narrative.event_effects: whichever target_* '
        'column is set must belong to the same world as the event '
        '(conventions §9.5). Extended by revision 074 to cover '
        'target_quest_objective_id, and by revision 076 to cover '
        'target_relationship_id.';
    """)

    # ==========================================================================
    # 19. interaction.consequences.resulting_relationship_state_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE interaction.consequences
        ADD COLUMN resulting_relationship_state_id UUID
            REFERENCES campaign.relationship_state(relationship_state_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.consequences.resulting_relationship_state_id IS
        'The relationship-state row a relationship_change consequence produced, '
        'when it has one. Closes revision 061''s own documented placeholder '
        '("relationship_change ... consequence types have no FK target at all '
        'yet ... Phase 7/8 domains do not exist") for its relationship half.';
    """)
    op.execute(
        "CREATE INDEX ix_consequences_resulting_relationship_state_id "
        "ON interaction.consequences (resulting_relationship_state_id) "
        "WHERE resulting_relationship_state_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_consequence_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_timeline        UUID;
            v_event_timeline              UUID;
            v_discovery_timeline          UUID;
            v_objective_state_timeline    UUID;
            v_relationship_state_timeline UUID;
        BEGIN
            SELECT timeline_id INTO v_interaction_timeline
            FROM interaction.interactions WHERE interaction_id = NEW.interaction_id;

            IF NEW.resulting_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_event_timeline
                FROM narrative.events WHERE event_id = NEW.resulting_event_id;

                IF v_event_timeline IS DISTINCT FROM v_interaction_timeline THEN
                    RAISE EXCEPTION
                        'Consequence % resulting_event_id % belongs to timeline %, but the '
                        'interaction belongs to timeline %',
                        NEW.consequence_id, NEW.resulting_event_id, v_event_timeline,
                        v_interaction_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.resulting_party_discovery_id IS NOT NULL THEN
                SELECT timeline_id INTO v_discovery_timeline
                FROM knowledge.party_discoveries
                WHERE party_discovery_id = NEW.resulting_party_discovery_id;

                IF v_discovery_timeline IS DISTINCT FROM v_interaction_timeline THEN
                    RAISE EXCEPTION
                        'Consequence % resulting_party_discovery_id % belongs to timeline %, '
                        'but the interaction belongs to timeline %',
                        NEW.consequence_id, NEW.resulting_party_discovery_id, v_discovery_timeline,
                        v_interaction_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.resulting_quest_objective_state_id IS NOT NULL THEN
                SELECT timeline_id INTO v_objective_state_timeline
                FROM campaign.objective_state
                WHERE objective_state_id = NEW.resulting_quest_objective_state_id;

                IF v_objective_state_timeline IS DISTINCT FROM v_interaction_timeline THEN
                    RAISE EXCEPTION
                        'Consequence % resulting_quest_objective_state_id % belongs to timeline '
                        '%, but the interaction belongs to timeline %',
                        NEW.consequence_id, NEW.resulting_quest_objective_state_id,
                        v_objective_state_timeline, v_interaction_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.resulting_relationship_state_id IS NOT NULL THEN
                SELECT timeline_id INTO v_relationship_state_timeline
                FROM campaign.relationship_state
                WHERE relationship_state_id = NEW.resulting_relationship_state_id;

                IF v_relationship_state_timeline IS DISTINCT FROM v_interaction_timeline THEN
                    RAISE EXCEPTION
                        'Consequence % resulting_relationship_state_id % belongs to timeline '
                        '%, but the interaction belongs to timeline %',
                        NEW.consequence_id, NEW.resulting_relationship_state_id,
                        v_relationship_state_timeline, v_interaction_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_consequence_world() IS
        'Guards interaction.consequences: resulting_event_id/'
        'resulting_party_discovery_id/resulting_quest_objective_state_id/'
        'resulting_relationship_state_id (when set) must belong to the same '
        'timeline as the interaction (conventions §9.5). Extended by revision 074 '
        'to cover resulting_quest_objective_state_id, and by revision 076 to '
        'cover resulting_relationship_state_id.';
    """)
    op.execute("""
        COMMENT ON TABLE interaction.consequences IS
        'A proposed or resolved outcome of an interaction — observations, '
        'events, state changes, discoveries, quest changes, or relationship '
        'changes (docs/DOMAIN_MODEL.md §16.6). Interaction-level, not '
        'action-level. quest_change gained a typed FK target in revision 073 '
        '(resulting_quest_objective_state_id); relationship_change gained one '
        'in revision 076 (resulting_relationship_state_id, above).';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        COMMENT ON TABLE interaction.consequences IS
        'A proposed or resolved outcome of an interaction — observations, '
        'events, state changes, discoveries, quest changes, or relationship '
        'changes (docs/DOMAIN_MODEL.md §16.6). Interaction-level, not '
        'action-level. relationship_change has no typed FK target yet '
        '(Phase 8''s domain does not exist); quest_change gained one in '
        'revision 073 (resulting_quest_objective_state_id, below).';
    """)
    op.execute(
        "ALTER TABLE interaction.consequences "
        "DROP COLUMN IF EXISTS resulting_relationship_state_id;"
    )

    op.execute("""
        ALTER TABLE narrative.event_effects
        DROP CONSTRAINT IF EXISTS ck_event_effects_at_most_one_target;
    """)
    op.execute("""
        ALTER TABLE narrative.event_effects
        ADD CONSTRAINT ck_event_effects_at_most_one_target CHECK (
            num_nonnulls(
                target_entity_id, target_area_connection_id, target_area_feature_id,
                target_area_hazard_id, target_area_interactable_id, target_quest_objective_id
            ) <= 1
        );
    """)
    op.execute("ALTER TABLE narrative.event_effects DROP COLUMN IF EXISTS target_relationship_id;")

    # Restore interaction.enforce_consequence_world() to its exact revision-074
    # body (quest-objective branch, no relationship branch).
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_consequence_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_timeline       UUID;
            v_event_timeline             UUID;
            v_discovery_timeline         UUID;
            v_objective_state_timeline   UUID;
        BEGIN
            SELECT timeline_id INTO v_interaction_timeline
            FROM interaction.interactions WHERE interaction_id = NEW.interaction_id;

            IF NEW.resulting_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_event_timeline
                FROM narrative.events WHERE event_id = NEW.resulting_event_id;

                IF v_event_timeline IS DISTINCT FROM v_interaction_timeline THEN
                    RAISE EXCEPTION
                        'Consequence % resulting_event_id % belongs to timeline %, but the '
                        'interaction belongs to timeline %',
                        NEW.consequence_id, NEW.resulting_event_id, v_event_timeline,
                        v_interaction_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.resulting_party_discovery_id IS NOT NULL THEN
                SELECT timeline_id INTO v_discovery_timeline
                FROM knowledge.party_discoveries
                WHERE party_discovery_id = NEW.resulting_party_discovery_id;

                IF v_discovery_timeline IS DISTINCT FROM v_interaction_timeline THEN
                    RAISE EXCEPTION
                        'Consequence % resulting_party_discovery_id % belongs to timeline %, '
                        'but the interaction belongs to timeline %',
                        NEW.consequence_id, NEW.resulting_party_discovery_id, v_discovery_timeline,
                        v_interaction_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.resulting_quest_objective_state_id IS NOT NULL THEN
                SELECT timeline_id INTO v_objective_state_timeline
                FROM campaign.objective_state
                WHERE objective_state_id = NEW.resulting_quest_objective_state_id;

                IF v_objective_state_timeline IS DISTINCT FROM v_interaction_timeline THEN
                    RAISE EXCEPTION
                        'Consequence % resulting_quest_objective_state_id % belongs to timeline '
                        '%, but the interaction belongs to timeline %',
                        NEW.consequence_id, NEW.resulting_quest_objective_state_id,
                        v_objective_state_timeline, v_interaction_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_consequence_world() IS
        'Guards interaction.consequences: resulting_event_id/'
        'resulting_party_discovery_id/resulting_quest_objective_state_id (when set) '
        'must belong to the same timeline as the interaction (conventions §9.5). '
        'Extended by revision 074 to cover resulting_quest_objective_state_id.';
    """)

    # Restore narrative.enforce_event_effect_target_world() to its exact
    # revision-074 body (quest-objective branch, no relationship branch).
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_effect_target_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_world    UUID;
            v_target_world   UUID;
        BEGIN
            SELECT world_id INTO v_event_world
            FROM core.entities WHERE entity_id = NEW.event_id;

            IF NEW.target_entity_id IS NOT NULL THEN
                SELECT world_id INTO v_target_world
                FROM core.entities WHERE entity_id = NEW.target_entity_id;
            ELSIF NEW.target_area_connection_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_connections ac
                JOIN core.entities e ON e.entity_id = ac.from_dungeon_area_id
                WHERE ac.area_connection_id = NEW.target_area_connection_id;
            ELSIF NEW.target_area_feature_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_features af
                JOIN core.entities e ON e.entity_id = af.dungeon_area_id
                WHERE af.area_feature_id = NEW.target_area_feature_id;
            ELSIF NEW.target_area_hazard_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_hazards ah
                JOIN core.entities e ON e.entity_id = ah.dungeon_area_id
                WHERE ah.area_hazard_id = NEW.target_area_hazard_id;
            ELSIF NEW.target_area_interactable_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM world.area_interactables ai
                JOIN core.entities e ON e.entity_id = ai.dungeon_area_id
                WHERE ai.area_interactable_id = NEW.target_area_interactable_id;
            ELSIF NEW.target_quest_objective_id IS NOT NULL THEN
                SELECT e.world_id INTO v_target_world
                FROM narrative.quest_objectives qo
                JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
                JOIN narrative.quests q ON q.quest_id = qs.quest_id
                JOIN core.entities e ON e.entity_id = q.quest_id
                WHERE qo.quest_objective_id = NEW.target_quest_objective_id;
            ELSE
                RETURN NEW;
            END IF;

            IF v_target_world IS DISTINCT FROM v_event_world THEN
                RAISE EXCEPTION
                    'Event effect target belongs to world %, but event % belongs to world %',
                    v_target_world, NEW.event_id, v_event_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_effect_target_world() IS
        'World-agreement guard for narrative.event_effects: whichever target_* '
        'column is set must belong to the same world as the event '
        '(conventions §9.5). Extended by revision 074 to cover '
        'target_quest_objective_id.';
    """)

    op.execute(
        "DELETE FROM narrative.event_types WHERE code IN "
        "('relationship_changed', 'organization_status_changed');"
    )

    op.execute("DROP TABLE IF EXISTS campaign.relationship_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_relationship_state_world();")
    op.execute("DROP TABLE IF EXISTS campaign.relationship_statuses;")

    op.execute("DROP TABLE IF EXISTS campaign.organization_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_organization_state_world();")
    op.execute("DROP TABLE IF EXISTS campaign.organization_statuses;")

    op.execute("DROP TABLE IF EXISTS world.political_relationships;")
    op.execute("DROP TABLE IF EXISTS world.family_relationships;")

    op.execute("DROP TABLE IF EXISTS world.ownership_relationships;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_ownership_relationship_world();")

    op.execute("DROP TABLE IF EXISTS world.employment_relationships;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_employment_relationship_world();")

    op.execute("DROP TABLE IF EXISTS world.organization_memberships;")
    op.execute("DROP FUNCTION IF EXISTS world.sync_organization_membership_period();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_religious_affiliations_enforce_world "
        "ON character.character_religious_affiliations;"
    )
    op.execute("DROP TABLE IF EXISTS character.character_religious_affiliations;")
    op.execute("DROP FUNCTION IF EXISTS character.enforce_character_religious_affiliation_world();")

    op.execute("DROP TABLE IF EXISTS world.religious_organizations;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_religious_organization_world();")

    op.execute("DROP TABLE IF EXISTS world.religions;")

    op.execute("DROP TABLE IF EXISTS world.political_factions;")
    op.execute("DROP TABLE IF EXISTS world.military_units;")
    op.execute("DROP TABLE IF EXISTS world.governments;")
    op.execute("DROP TABLE IF EXISTS world.businesses;")

    op.execute("DROP TABLE IF EXISTS world.organizations;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_organization_world();")

    op.execute("DROP TABLE IF EXISTS world.organization_types;")

    op.execute("DROP TABLE IF EXISTS world.relationship_perspectives;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_relationship_perspective_participant();")

    op.execute("DROP TABLE IF EXISTS world.relationship_participants;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_relationship_participant_world();")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_relationship_participant_removal();")

    op.execute("DROP TABLE IF EXISTS world.relationships;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_relationship_validity();")

    op.execute("DROP TABLE IF EXISTS world.relationship_participant_roles;")
    op.execute("DROP TABLE IF EXISTS world.relationship_types;")

    op.execute(
        "DELETE FROM core.entity_types WHERE code IN "
        "('business', 'government', 'religious_organization', 'military_unit', "
        "'political_faction');"
    )
    op.execute("DELETE FROM core.entity_types WHERE code = 'organization';")
    op.execute("DELETE FROM core.entity_types WHERE code = 'religion';")
