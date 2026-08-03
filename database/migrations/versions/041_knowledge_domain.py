"""Knowledge domain (pulled forward from Phase 7): knowledge items, entity knowledge, discoveries

Revision ID: 041_knowledge_domain
Revises: 040_dungeon_timeline_state
Create Date: 2026-08-02 18:45:00.000000

Purpose:
    Phase 5 lists "discovery records" as a deliverable and requires "hidden
    connections remain distinct from party knowledge" as an exit criterion
    (docs/PLAN.md §23, Phase 5), but the documented shape of discovery
    (knowledge.party_discoveries in docs/architecture/DATABASE_MODEL.md §15;
    Discovery's definition in docs/DOMAIN_MODEL.md §15.5) ties it to
    knowledge.knowledge_items, and the implementation order in
    DATABASE_MODEL.md §23 places "Knowledge and discovery" after locations,
    interactions/events, and quests. Rather than build a smaller,
    differently-shaped Phase-5-only discovery table now and risk a second,
    incompatible one appearing in Phase 7, this revision pulls the minimum
    slice of the knowledge domain forward: knowledge items, entity knowledge,
    and party discoveries — using their documented shape from
    DATABASE_MODEL.md §15 and DOMAIN_MODEL.md §15 — rather than a Phase 7
    knowledge domain built from scratch. This was a deliberate choice made
    with the user rather than a default; docs/architecture/DATABASE_MODEL.md
    §25 records the fuller reconciliation-note treatment.

    Full-domain apparatus this revision deliberately does NOT build —
    genuinely Phase 7's job, not needed to satisfy any Phase 5 exit
    criterion: knowledge.knowledge_versions (rumor mutation/distortion),
    knowledge.information_transfers (communication between knowers),
    knowledge.expertise_domains / character_expertise, and
    knowledge.public_knowledge (location/region-wide public knowledge, as
    opposed to a specific knower or party). knowledge.entity_knowledge here
    references a bare knowledge_item_id, not a knowledge_version_id — there
    is nothing to version yet.

    A knowledge item's "subject" (docs/DOMAIN_MODEL.md §15.1: "subject
    entities") is simplified from the documented plural association to a
    single nullable typed reference directly on knowledge.knowledge_items:
    most subjects are core.entities (an NPC, a location, an organization),
    but dungeon-domain connections/features/hazards/interactables are NOT
    entities (revision 039's docstring) and need their own reference columns
    to be a discovery subject at all. At most one subject is set — Phase 7
    should promote this to a proper knowledge.knowledge_item_subjects
    junction table if a knowledge item genuinely needs more than one subject.

Forward migration:
    - core.entity_types row: knowledge_item (root type, required_subtype_table
      = 'knowledge.knowledge_items')
    - knowledge.knowledge_types (lookup: claim, belief, secret, rumor, memory,
      instruction, theory), seeded
    - knowledge.truth_statuses (lookup: true, false, partially_true, disputed,
      unknown, no_objective_truth — the exact vocabulary in
      docs/DATABASE_CONVENTIONS.md §15.2), seeded
    - knowledge.knowledge_items, with an at-most-one-subject CHECK and
      knowledge.enforce_knowledge_item_subject_world()
    - knowledge.entity_knowledge, with knowledge.enforce_entity_knowledge_world()
    - knowledge.party_discoveries, with an exactly-one-recipient CHECK,
      partial unique indexes for party vs. entity recipients, and
      knowledge.enforce_party_discovery_world()

Rollback:
    Supported. Drops the three domain tables, their trigger functions, the
    two lookups (with seed rows), and the knowledge_item entity_types row.

Data implications:
    Seeds two small lookups and one entity_types row. No knowledge rows.

Locking considerations:
    None. All tables are new and empty.

See: docs/PLAN.md Phase 5 (discovery records), Phase 7 (knowledge items,
     entity knowledge, discoveries, information transfer)
     docs/architecture/DATABASE_MODEL.md §15 (knowledge model), §9.3
     (discovery versus existence), §25 (reconciliation notes)
     docs/DOMAIN_MODEL.md §15 (knowledge domain)
     docs/DATABASE_CONVENTIONS.md §15 (knowledge and visibility conventions)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "041_knowledge_domain"
down_revision = "040_dungeon_timeline_state"
branch_labels = None
depends_on = None

KNOWLEDGE_TYPES = [
    ("claim", "Claim"),
    ("belief", "Belief"),
    ("secret", "Secret"),
    ("rumor", "Rumor"),
    ("memory", "Memory"),
    ("instruction", "Instruction"),
    ("theory", "Theory"),
]

TRUTH_STATUSES = [
    ("true", "True"),
    ("false", "False"),
    ("partially_true", "Partially True"),
    ("disputed", "Disputed"),
    ("unknown", "Unknown"),
    ("no_objective_truth", "No Objective Truth"),
]


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


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.entity_types row
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types (code, display_name, required_subtype_table)
        VALUES ('knowledge_item', 'Knowledge Item', 'knowledge.knowledge_items')
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. Lookups
    # ==========================================================================
    _lookup_table(
        "knowledge",
        "knowledge_types",
        "knowledge_type_id",
        "The kind of claim a knowledge item represents (claim, belief, secret, "
        "rumor, memory, instruction, theory) — docs/DOMAIN_MODEL.md §15.1.",
    )
    for sort_order, (code, display_name) in enumerate(KNOWLEDGE_TYPES):
        op.execute(f"""
            INSERT INTO knowledge.knowledge_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    _lookup_table(
        "knowledge",
        "truth_statuses",
        "truth_status_id",
        "How a knowledge item relates to canonical truth (true, false, partially "
        "true, disputed, unknown, no objective truth) — "
        "docs/DATABASE_CONVENTIONS.md §15.2.",
    )
    for sort_order, (code, display_name) in enumerate(TRUTH_STATUSES):
        op.execute(f"""
            INSERT INTO knowledge.truth_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 3. knowledge.knowledge_items
    # ==========================================================================
    op.execute("""
        CREATE TABLE knowledge.knowledge_items (
            knowledge_item_id             UUID PRIMARY KEY
                                          REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            knowledge_type_id             UUID NOT NULL
                                          REFERENCES knowledge.knowledge_types(knowledge_type_id)
                                          ON DELETE RESTRICT,
            truth_status_id                UUID NOT NULL
                                          REFERENCES knowledge.truth_statuses(truth_status_id)
                                          ON DELETE RESTRICT,
            canonical_statement             TEXT NOT NULL,
            sensitivity                     TEXT NOT NULL DEFAULT 'public',
            subject_entity_id               UUID
                                          REFERENCES core.entities(entity_id) ON DELETE SET NULL,
            subject_area_connection_id      UUID
                                          REFERENCES world.area_connections(area_connection_id)
                                          ON DELETE SET NULL,
            subject_area_feature_id         UUID
                                          REFERENCES world.area_features(area_feature_id)
                                          ON DELETE SET NULL,
            subject_area_hazard_id          UUID
                                          REFERENCES world.area_hazards(area_hazard_id)
                                          ON DELETE SET NULL,
            subject_area_interactable_id    UUID
                                          REFERENCES world.area_interactables(area_interactable_id)
                                          ON DELETE SET NULL,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_knowledge_items_statement_length
                CHECK (char_length(canonical_statement) BETWEEN 1 AND 5000),
            CONSTRAINT ck_knowledge_items_sensitivity CHECK (
                sensitivity IN ('public', 'restricted', 'secret', 'dangerous')
            ),
            CONSTRAINT ck_knowledge_items_at_most_one_subject CHECK (
                num_nonnulls(
                    subject_entity_id, subject_area_connection_id, subject_area_feature_id,
                    subject_area_hazard_id, subject_area_interactable_id
                ) <= 1
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.knowledge_items IS
        'A specific claim, belief, secret, rumor, memory, instruction, or theory '
        '(docs/DOMAIN_MODEL.md §15.1). Entity-rooted like any other important world '
        'object. subject_* columns are a deliberately simplified single-subject '
        'reference — see this revision''s docstring.';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.knowledge_items.sensitivity IS
        'A fixed, universal classification (public, restricted, secret, dangerous), '
        'not a lookup — same reasoning as character.characters.size_category (Phase 4).';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.knowledge_items.subject_entity_id IS
        'The core.entities row this knowledge is about (an NPC, a location, an '
        'organization, ...), when it has one. At most one subject_* column is set.';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.knowledge_items.subject_area_connection_id IS
        'The area connection this knowledge is about (e.g. "a secret door exists '
        'here"), when it has one. Connections are not entities (revision 039), so '
        'this direct reference exists alongside subject_entity_id rather than through it.';
    """)
    op.execute("""
        CREATE TRIGGER tr_knowledge_items_set_updated_at
        BEFORE UPDATE ON knowledge.knowledge_items
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_knowledge_items_knowledge_type_id "
        "ON knowledge.knowledge_items (knowledge_type_id);"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_items_truth_status_id "
        "ON knowledge.knowledge_items (truth_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_items_subject_entity_id "
        "ON knowledge.knowledge_items (subject_entity_id) WHERE subject_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_items_subject_area_connection_id "
        "ON knowledge.knowledge_items (subject_area_connection_id) "
        "WHERE subject_area_connection_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_items_subject_area_feature_id "
        "ON knowledge.knowledge_items (subject_area_feature_id) "
        "WHERE subject_area_feature_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_items_subject_area_hazard_id "
        "ON knowledge.knowledge_items (subject_area_hazard_id) "
        "WHERE subject_area_hazard_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_items_subject_area_interactable_id "
        "ON knowledge.knowledge_items (subject_area_interactable_id) "
        "WHERE subject_area_interactable_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_knowledge_items_enforce_subtype
        AFTER INSERT OR UPDATE ON knowledge.knowledge_items
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('knowledge_item_id');
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_knowledge_item_subject_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world      UUID;
            v_subject_world  UUID;
        BEGIN
            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            IF NEW.subject_entity_id IS NOT NULL THEN
                SELECT world_id INTO v_subject_world
                FROM core.entities WHERE entity_id = NEW.subject_entity_id;
            ELSIF NEW.subject_area_connection_id IS NOT NULL THEN
                SELECT e.world_id INTO v_subject_world
                FROM world.area_connections ac
                JOIN core.entities e ON e.entity_id = ac.from_dungeon_area_id
                WHERE ac.area_connection_id = NEW.subject_area_connection_id;
            ELSIF NEW.subject_area_feature_id IS NOT NULL THEN
                SELECT e.world_id INTO v_subject_world
                FROM world.area_features af
                JOIN core.entities e ON e.entity_id = af.dungeon_area_id
                WHERE af.area_feature_id = NEW.subject_area_feature_id;
            ELSIF NEW.subject_area_hazard_id IS NOT NULL THEN
                SELECT e.world_id INTO v_subject_world
                FROM world.area_hazards ah
                JOIN core.entities e ON e.entity_id = ah.dungeon_area_id
                WHERE ah.area_hazard_id = NEW.subject_area_hazard_id;
            ELSIF NEW.subject_area_interactable_id IS NOT NULL THEN
                SELECT e.world_id INTO v_subject_world
                FROM world.area_interactables ai
                JOIN core.entities e ON e.entity_id = ai.dungeon_area_id
                WHERE ai.area_interactable_id = NEW.subject_area_interactable_id;
            ELSE
                RETURN NEW;
            END IF;

            IF v_subject_world IS DISTINCT FROM v_own_world THEN
                RAISE EXCEPTION
                    'Knowledge item % belongs to world %, but its subject belongs to world %',
                    NEW.knowledge_item_id, v_own_world, v_subject_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_knowledge_item_subject_world() IS
        'Guards knowledge.knowledge_items: whichever subject_* column is set must '
        'belong to the same world as the knowledge item itself (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_knowledge_items_enforce_subject_world
        BEFORE INSERT OR UPDATE ON knowledge.knowledge_items
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_knowledge_item_subject_world();
    """)

    # ==========================================================================
    # 4. knowledge.entity_knowledge
    # ==========================================================================
    op.execute("""
        CREATE TABLE knowledge.entity_knowledge (
            entity_knowledge_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                UUID NOT NULL
                                      REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            knowledge_item_id           UUID NOT NULL
                                      REFERENCES knowledge.knowledge_items(knowledge_item_id)
                                      ON DELETE CASCADE,
            knower_entity_id            UUID NOT NULL
                                      REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            awareness_level             TEXT NOT NULL DEFAULT 'aware',
            confidence                  core.percentage_0_100,
            interpretation               TEXT,
            learned_source               TEXT,
            learned_at_world_time_id     UUID
                                      REFERENCES core.world_times(world_time_id)
                                      ON DELETE SET NULL,
            willing_to_share              BOOLEAN NOT NULL DEFAULT true,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_entity_knowledge_awareness_level CHECK (
                awareness_level IN ('aware', 'rumored', 'suspected')
            ),
            CONSTRAINT ux_entity_knowledge_current
                UNIQUE (timeline_id, knowledge_item_id, knower_entity_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.entity_knowledge IS
        'What a knower believes about a knowledge item on a timeline: awareness, '
        'confidence, interpretation, source, sharing willingness '
        '(docs/DOMAIN_MODEL.md §15.3). A false belief is valid game data and is never '
        'overwritten merely because the canonical truth is known elsewhere. One row '
        'per (timeline, knowledge item, knower) — see revision 021''s docstring on '
        'event linkage, which applies unchanged here.';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.entity_knowledge.learned_source IS
        'Free-text placeholder for how this was learned until interaction/event '
        'records exist (Phase 6) to reference instead.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_knowledge_set_updated_at
        BEFORE UPDATE ON knowledge.entity_knowledge
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_entity_knowledge_knowledge_item_id "
        "ON knowledge.entity_knowledge (knowledge_item_id);"
    )
    op.execute(
        "CREATE INDEX ix_entity_knowledge_knower_entity_id "
        "ON knowledge.entity_knowledge (knower_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_entity_knowledge_learned_at_world_time_id "
        "ON knowledge.entity_knowledge (learned_at_world_time_id) "
        "WHERE learned_at_world_time_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_entity_knowledge_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_item_world      UUID;
            v_knower_world    UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            SELECT world_id INTO v_knower_world
            FROM core.entities WHERE entity_id = NEW.knower_entity_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_knower_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Entity knowledge row mixes worlds: timeline % (world %), '
                    'knowledge item % (world %), knower % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.knowledge_item_id, v_item_world,
                    NEW.knower_entity_id, v_knower_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_entity_knowledge_world() IS
        'World-agreement guard for knowledge.entity_knowledge: timeline, knowledge '
        'item, and knower must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_knowledge_enforce_world
        BEFORE INSERT OR UPDATE ON knowledge.entity_knowledge
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_entity_knowledge_world();
    """)

    # ==========================================================================
    # 5. knowledge.party_discoveries
    # ==========================================================================
    op.execute("""
        CREATE TABLE knowledge.party_discoveries (
            party_discovery_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                    UUID NOT NULL
                                          REFERENCES campaign.timelines(timeline_id)
                                          ON DELETE CASCADE,
            knowledge_item_id               UUID NOT NULL
                                          REFERENCES knowledge.knowledge_items(knowledge_item_id)
                                          ON DELETE CASCADE,
            party_id                        UUID
                                          REFERENCES campaign.parties(party_id) ON DELETE CASCADE,
            knower_entity_id                 UUID
                                          REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            discovered_at_world_time_id      UUID
                                          REFERENCES core.world_times(world_time_id)
                                          ON DELETE SET NULL,
            discovery_method                  TEXT,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_party_discoveries_exactly_one_recipient CHECK (
                num_nonnulls(party_id, knower_entity_id) = 1
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.party_discoveries IS
        'The discovery record: when and how a party or individual knower learned a '
        'knowledge item (docs/architecture/DATABASE_MODEL.md §15). Recipient is '
        'exactly one of party_id (party-level discovery) or knower_entity_id '
        '(individual character, NPC, or organization discovery) — public/regional '
        'discovery (knowledge.public_knowledge) is deferred to Phase 7.';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.party_discoveries.discovery_method IS
        'Free-text placeholder for how this was discovered until interaction/event '
        'records exist (Phase 6) to reference instead.';
    """)
    op.execute(
        "CREATE INDEX ix_party_discoveries_knowledge_item_id "
        "ON knowledge.party_discoveries (knowledge_item_id);"
    )
    op.execute(
        "CREATE INDEX ix_party_discoveries_party_id "
        "ON knowledge.party_discoveries (party_id) WHERE party_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_party_discoveries_knower_entity_id "
        "ON knowledge.party_discoveries (knower_entity_id) WHERE knower_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_party_discoveries_discovered_at_world_time_id "
        "ON knowledge.party_discoveries (discovered_at_world_time_id) "
        "WHERE discovered_at_world_time_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_party_discoveries_party
        ON knowledge.party_discoveries (timeline_id, knowledge_item_id, party_id)
        WHERE party_id IS NOT NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_party_discoveries_knower
        ON knowledge.party_discoveries (timeline_id, knowledge_item_id, knower_entity_id)
        WHERE knower_entity_id IS NOT NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_party_discovery_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world    UUID;
            v_item_world        UUID;
            v_recipient_world   UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            IF NEW.party_id IS NULL AND NEW.knower_entity_id IS NULL THEN
                -- Malformed (no recipient at all) — let
                -- ck_party_discoveries_exactly_one_recipient reject it with a
                -- clearer error instead of this trigger reporting a spurious
                -- "recipient world NULL" mismatch.
                RETURN NEW;
            END IF;

            IF NEW.party_id IS NOT NULL THEN
                SELECT world_id INTO v_recipient_world
                FROM campaign.parties WHERE party_id = NEW.party_id;
            ELSE
                SELECT world_id INTO v_recipient_world
                FROM core.entities WHERE entity_id = NEW.knower_entity_id;
            END IF;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_recipient_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Party discovery mixes worlds: timeline % (world %), knowledge item % '
                    '(world %), recipient world %',
                    NEW.timeline_id, v_timeline_world, NEW.knowledge_item_id, v_item_world,
                    v_recipient_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_party_discovery_world() IS
        'World-agreement guard for knowledge.party_discoveries: timeline, knowledge '
        'item, and recipient (party or knower entity) must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_discoveries_enforce_world
        BEFORE INSERT OR UPDATE ON knowledge.party_discoveries
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_party_discovery_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS knowledge.party_discoveries;")
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_party_discovery_world();")

    op.execute("DROP TABLE IF EXISTS knowledge.entity_knowledge;")
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_entity_knowledge_world();")

    op.execute("DROP TABLE IF EXISTS knowledge.knowledge_items;")
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_knowledge_item_subject_world();")

    op.execute("DROP TABLE IF EXISTS knowledge.truth_statuses;")
    op.execute("DROP TABLE IF EXISTS knowledge.knowledge_types;")

    op.execute("DELETE FROM core.entity_types WHERE code = 'knowledge_item';")
