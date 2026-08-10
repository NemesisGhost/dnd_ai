"""Item domain: item definitions, item instances, containers, timeline
state (condition, ownership, possession, attunement), and per-knower
item identification.

Revision ID: 077_item_domain
Revises: 076_relationships_and_orgs
Create Date: 2026-08-09 12:00:00.000000

Purpose:
    Phase 9 ("Items, inventory, encounters, and Foundry integration contracts",
    docs/PLAN.md §23) delivers item definitions and instances plus
    inventory/ownership (docs/architecture/DATABASE_MODEL.md §11). This is
    the first increment (item domain only) — encounters/combat and Foundry
    identifiers/sync records follow in later revisions of this same phase,
    per docs/PHASE9_VERIFICATION.md.

    Definition versus instance versus state (rule 4/5): rules.item_definitions
    is the reusable mechanical concept (a generic longsword), ruleset-version-
    scoped exactly like rules.spells/.classes. world.item_instances is the
    particular object in the world (a named legendary sword) — entity-rooted,
    referencing its definition. campaign.item_state/.item_ownership/.
    inventory_entries are the CURRENT, timeline-scoped, event-driven view:
    condition/charges/equipped/quantity, current owner, and current
    possessor/location respectively. Historical values are recoverable from
    narrative.events/.event_effects, the same way organization/relationship
    history works (revision 076) — no separate item-history table.

    Ownership versus possession (docs/DOMAIN_MODEL.md §12.4) are deliberately
    two different tables: campaign.item_ownership (who legally owns it,
    nullable for unclaimed treasure) and campaign.inventory_entries (who/what
    currently has it — a holder, a container, or a location; at most one of
    the three, same "at-most-one-typed-target" shape narrative.event_effects/
    knowledge.knowledge_items/interaction.targets/narrative.quest_objectives
    established). A borrowed or stolen item has one row in each table that
    disagree on the entity — that disagreement IS the modeling.

    Items are entity-rooted (world.item_instances), so narrative.event_effects
    already covers "target an item" via its existing target_entity_id column
    — no new event_effects target column is needed this revision, unlike
    revision 076's relationship/quest additions.

    world.item_containers is a 1:1 extension of world.item_instances (not a
    second CTI leaf off core.entities) — a container is an item that can
    hold other items (a backpack, a chest), not a distinct entity subtype;
    marking one is exactly the "additive capability row" shape
    world.religious_organizations used for organizations, applied one level
    down.

    rules.item_categories is a plain global lookup (weapon, armor, ...), not
    ruleset-scoped — the category taxonomy itself is stable across rulesets
    the way docs/DATABASE_CONVENTIONS.md §11.3 distinguishes from rules-owned
    content; individual item_definitions rows remain ruleset-version-scoped
    and reference it.

Forward migration:
    - rules.item_categories (lookup), seeded
    - rules.item_definitions (ruleset-version-scoped, provenance columns per
      revision 025's shape), with ck_item_definitions_code_format and
      ck_item_definitions_rarity
    - world.item_instances (entity-rooted), with
      world.enforce_item_instance_ruleset_allowed() (reusing
      rules.ruleset_allowed_for_world() from revision 029, the same pattern
      character.enforce_character_species_ruleset_allowed() uses)
    - world.item_containers (1:1 extension of world.item_instances)
    - campaign.item_state, with campaign.enforce_item_state_world() and the
      shared campaign.enforce_state_event_timeline() (revision 066)
    - campaign.item_ownership, with campaign.enforce_item_ownership_world()
      and the shared campaign.enforce_state_event_timeline()
    - campaign.inventory_entries, with campaign.enforce_inventory_entry_world()
      and the shared campaign.enforce_state_event_timeline()
    - campaign.item_attunements, with campaign.enforce_item_attunement_world()
      (world agreement plus broken-after-attuned ordering, the same combined
      shape world.enforce_organization_world() used for founded/dissolved)
      and the shared campaign.enforce_state_event_timeline()
    - knowledge.item_identification, with
      knowledge.enforce_item_identification_world() and the shared
      campaign.enforce_state_event_timeline()
    - campaign.character_inventory (VIEW) — a character-centric read model
      over inventory_entries/item_ownership/item_state (conventions §22).
      Not declared in src/dnd_ai/persistence/tables/ — alembic autogenerate
      compares tables, not views, the same reason CHECK constraints and
      triggers are left out of that module.
    - narrative.event_types: two new seed rows, item_transferred and
      item_identified (item_acquired/item_destroyed already exist from
      revision 057 and are reused, not duplicated)

Rollback:
    Supported. Drops everything created here in FK-dependency order, then
    the two narrative.event_types seed additions.

Data implications:
    Seeds one small lookup (rules.item_categories, ~14 rows) and two
    event_types rows. No item definition, instance, or state rows.

Locking considerations:
    Every statement creates a new, empty object. No ALTER TABLE against an
    existing populated table.

Deliberate scoping decisions:
    - world.item_containers only guards the trivial direct self-reference
      (a container cannot list itself as its own contents) via a CHECK on
      campaign.inventory_entries; it does not walk the full containment
      chain for deeper cycles (item A inside item B inside item A). No exit
      criterion requires it, and world.locations' equivalent cycle detection
      (revision 054) took multiple corrective passes to get right for a
      structure that is walked far more often — building the same machinery
      speculatively here would be exactly the anti-pattern
      docs/DATABASE_CONVENTIONS.md §33.1 warns against. Revisit if a command
      needs to move items between containers programmatically and a cycle
      becomes reachable in practice.
    - rarity (rules.item_definitions) and identification_level
      (knowledge.item_identification) are plain TEXT with an inline CHECK,
      not lookup tables — both are small, closed, D&D-rules-fixed
      classifications, the same reasoning
      character.characters.size_category (Phase 4) and
      knowledge.knowledge_items.sensitivity (revision 041) already used.
    - rules.item_definitions.properties_jsonb holds category-specific
      mechanical stats (damage dice, AC bonus, ...) as JSONB — "ruleset-
      specific calculation details" is an explicitly acceptable JSONB use
      per conventions §5.7; the alternative (a column per possible mechanical
      property across every item category) is exactly the kind of unstable,
      category-varying structure §5.7 says JSONB is for.
    - base_cost_gp is a single nullable NUMERIC, not a structured currency
      breakdown (cp/sp/ep/gp/pp) or a treasure-hoard model. No exit
      criterion requires currency-of-account modeling yet; add it against a
      concrete caller rather than speculatively.
    - The "at most 3 attuned items per character" D&D rule is not enforced
      by campaign.item_attunements' schema — it is a player-facing rule
      about a character's total attunement count across many rows, not a
      single-row or single-table constraint, and belongs in the command
      layer once attunement commands exist (the same latitude
      world.organization_memberships took for its relationship_type check,
      revision 076). The schema does enforce the rule PostgreSQL can express
      cleanly at the row level: at most one active (unbroken) attunement per
      item per timeline, via a partial unique index — an item cannot be
      attuned to two creatures at once.

See: docs/PLAN.md Phase 9 (items, inventory, encounters, Foundry integration contracts)
     docs/architecture/DATABASE_MODEL.md §11 (item model)
     docs/DOMAIN_MODEL.md §12 (item domain)
     docs/DATABASE_CONVENTIONS.md §5.7 (JSONB), §9.5 (same-world consistency),
     §13 (timeline-state conventions), §22 (view conventions)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "077_item_domain"
down_revision = "076_relationships_and_orgs"
branch_labels = None
depends_on = None

ITEM_CATEGORIES = [
    ("weapon", "Weapon"),
    ("armor", "Armor"),
    ("shield", "Shield"),
    ("ammunition", "Ammunition"),
    ("potion", "Potion"),
    ("scroll", "Scroll"),
    ("ring", "Ring"),
    ("rod", "Rod"),
    ("staff", "Staff"),
    ("wand", "Wand"),
    ("wondrous_item", "Wondrous Item"),
    ("tool", "Tool"),
    ("gear", "Gear"),
    ("treasure", "Treasure"),
    ("other", "Other"),
]

ITEM_RARITIES = ("common", "uncommon", "rare", "very_rare", "legendary", "artifact", "varies")

IDENTIFICATION_LEVELS = ("unidentified", "partially_identified", "fully_identified")

NEW_EVENT_TYPES = [
    ("item_transferred", "Item Transferred"),
    ("item_identified", "Item Identified"),
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
    # 1. core.entity_types: item_instance
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, required_subtype_table, required_subtype_pk_column)
        VALUES ('item_instance', 'Item Instance', 'world.item_instances', 'item_instance_id')
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. rules.item_categories
    # ==========================================================================
    _lookup_table(
        "rules",
        "item_categories",
        "item_category_id",
        "The mechanical category of an item definition (docs/DOMAIN_MODEL.md "
        "§12.1) — weapon, armor, shield, ammunition, potion, scroll, ring, "
        "rod, staff, wand, wondrous_item, tool, gear, treasure, other. "
        "Global, not ruleset-scoped: the taxonomy itself is stable across "
        "rulesets even though individual item definitions are not.",
    )
    for sort_order, (code, display_name) in enumerate(ITEM_CATEGORIES):
        op.execute(f"""
            INSERT INTO rules.item_categories (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 3. rules.item_definitions
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE rules.item_definitions (
            item_definition_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ruleset_version_id    UUID NOT NULL
                                  REFERENCES rules.ruleset_versions(ruleset_version_id)
                                  ON DELETE CASCADE,
            item_category_id      UUID NOT NULL
                                  REFERENCES rules.item_categories(item_category_id)
                                  ON DELETE RESTRICT,
            code                  TEXT NOT NULL,
            display_name          TEXT NOT NULL,
            description           TEXT,
            rarity                TEXT NOT NULL DEFAULT 'common',
            requires_attunement   BOOLEAN NOT NULL DEFAULT false,
            weight                NUMERIC(8, 2),
            base_cost_gp          NUMERIC(12, 2),
            properties_jsonb      JSONB,
            source_id             UUID REFERENCES core.sources(source_id) ON DELETE SET NULL,
            canon_status_id       UUID NOT NULL
                                  REFERENCES core.canon_statuses(canon_status_id)
                                  ON DELETE RESTRICT
                                  DEFAULT rules.default_canon_status_id(),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_item_definitions_ruleset_version_code UNIQUE (ruleset_version_id, code),
            CONSTRAINT ck_item_definitions_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_item_definitions_rarity CHECK (
                rarity IN {ITEM_RARITIES}
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.item_definitions IS
        'A reusable mechanical item definition (docs/DOMAIN_MODEL.md §12.1) — '
        'a generic longsword, a healing potion, a spell scroll. '
        'world.item_instances (below) references this for a particular '
        'object in the world; definition and instance are deliberately '
        'never the same row (conventions §34).';
    """)
    op.execute("""
        COMMENT ON COLUMN rules.item_definitions.properties_jsonb IS
        'Category-specific mechanical stats (damage dice, AC bonus, charges, '
        '...) — ruleset-specific calculation detail, an explicitly '
        'acceptable JSONB use (conventions §5.7). NULL for items with no '
        'mechanical effect beyond their description.';
    """)
    op.execute("""
        COMMENT ON COLUMN rules.item_definitions.source_id IS
        'Where this definition came from — a rulebook, a homebrew document, an '
        'import. NULL is common for official content with no single authored '
        'source record yet.';
    """)
    op.execute("""
        COMMENT ON COLUMN rules.item_definitions.canon_status_id IS
        'How authoritative this definition is. Homebrew content uses the same '
        'column, typically starting at draft/proposed rather than canon '
        '(docs/architecture/DATABASE_MODEL.md §8).';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_definitions_set_updated_at
        BEFORE UPDATE ON rules.item_definitions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_item_definitions_ruleset_version_id "
        "ON rules.item_definitions (ruleset_version_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_definitions_item_category_id "
        "ON rules.item_definitions (item_category_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_definitions_source_id ON rules.item_definitions (source_id) "
        "WHERE source_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_item_definitions_canon_status_id "
        "ON rules.item_definitions (canon_status_id);"
    )
    op.execute("""
        CREATE TRIGGER tr_item_definitions_enforce_immutable
        BEFORE UPDATE ON rules.item_definitions
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('ruleset_version_id');
    """)

    # ==========================================================================
    # 4. world.item_instances (entity-rooted)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.item_instances (
            item_instance_id    UUID PRIMARY KEY
                                REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            item_definition_id  UUID NOT NULL
                                REFERENCES rules.item_definitions(item_definition_id)
                                ON DELETE RESTRICT,
            origin_notes        TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.item_instances IS
        'A particular object in the world (docs/DOMAIN_MODEL.md §12.2) — a '
        'named legendary sword, a specific healing potion in a chest. '
        'Entity-rooted: title, summary, canon status, and source are '
        'inherited from core.entities. item_definition_id is the reusable '
        'mechanical definition this is an example of. Current location, '
        'possessor, owner, condition, charges, and equipped state are '
        'timeline state (campaign.item_state/.item_ownership/.'
        'inventory_entries, below), not columns here — the same definition/'
        'state split world.organizations draws against campaign.'
        'organization_state.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.item_instances.origin_notes IS
        'Free-text provenance/lore for this specific instance (crafted by, '
        'found where, ...) — distinct from core.sources, which records where '
        'the definition''s rules text came from.';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_instances_set_updated_at
        BEFORE UPDATE ON world.item_instances
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_item_instances_enforce_subtype
        AFTER INSERT OR UPDATE ON world.item_instances
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('item_instance_id');
    """)
    op.execute(
        "CREATE INDEX ix_item_instances_item_definition_id "
        "ON world.item_instances (item_definition_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_item_instance_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world             UUID;
            v_definition_version UUID;
        BEGIN
            SELECT world_id INTO v_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            SELECT ruleset_version_id INTO v_definition_version
            FROM rules.item_definitions WHERE item_definition_id = NEW.item_definition_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_definition_version) THEN
                RAISE EXCEPTION
                    'Item definition %''s ruleset is not allowed for world % (item instance %''s world)',
                    NEW.item_definition_id, v_world, NEW.item_instance_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_item_instance_ruleset_allowed() IS
        'Keeps an item instance''s definition drawn from a ruleset its own '
        'world allows (conventions §9.5), reusing rules.ruleset_allowed_for_world() '
        'from revision 029 — the same pattern '
        'character.enforce_character_species_ruleset_allowed() uses.';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_instances_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON world.item_instances
        FOR EACH ROW EXECUTE FUNCTION world.enforce_item_instance_ruleset_allowed();
    """)

    # ==========================================================================
    # 5. world.item_containers (1:1 extension of world.item_instances)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.item_containers (
            container_id     UUID PRIMARY KEY
                             REFERENCES world.item_instances(item_instance_id) ON DELETE CASCADE,
            capacity_weight   NUMERIC(8, 2),
            capacity_items    core.nonnegative_integer,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.item_containers IS
        'Marks an item instance as capable of holding other items (a '
        'backpack, a quiver, a chest) — a 1:1 extension of '
        'world.item_instances, not every item is a container, and not a '
        'second core.entity_types subtype (docs/DOMAIN_MODEL.md §12). '
        'capacity_weight/capacity_items are optional mechanical limits. '
        'campaign.inventory_entries.container_id (below) references this '
        'table for items currently stored inside one.';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_containers_set_updated_at
        BEFORE UPDATE ON world.item_containers
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 6. campaign.item_state
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.item_state (
            item_state_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id          UUID NOT NULL
                                REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            item_instance_id      UUID NOT NULL
                                REFERENCES world.item_instances(item_instance_id) ON DELETE CASCADE,
            quantity               core.nonnegative_integer NOT NULL DEFAULT 1,
            condition_percentage    core.percentage_0_100,
            charges_current          core.nonnegative_integer,
            charges_maximum          core.nonnegative_integer,
            is_equipped                BOOLEAN NOT NULL DEFAULT false,
            is_destroyed                BOOLEAN NOT NULL DEFAULT false,
            last_event_id                 UUID
                                REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_item_state_timeline_item UNIQUE (timeline_id, item_instance_id),
            CONSTRAINT ck_item_state_charges_range CHECK (
                charges_current IS NULL OR charges_maximum IS NULL
                OR charges_current <= charges_maximum
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.item_state IS
        'Tracks an item instance''s current condition for a timeline '
        '(docs/architecture/DATABASE_MODEL.md §17) — quantity (for '
        'stackable items), condition, charges, equipped and destroyed '
        'status. Can diverge after a branch and evolve from events, unlike '
        'the stable world.item_instances definition row. One current row '
        'per (timeline, item instance).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.item_state.last_event_id IS
        'The event that produced this row''s current values, when there was one '
        '(conventions §13.4). NULL for administrative/import-driven changes with '
        'no causing event.';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_state_set_updated_at
        BEFORE UPDATE ON campaign.item_state
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_item_state_timeline_id ON campaign.item_state (timeline_id);")
    op.execute(
        "CREATE INDEX ix_item_state_item_instance_id ON campaign.item_state (item_instance_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_state_last_event_id ON campaign.item_state (last_event_id) "
        "WHERE last_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_item_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world UUID;
            v_item_world     UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but item instance % belongs to world %',
                    NEW.timeline_id, v_timeline_world, NEW.item_instance_id, v_item_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_item_state_world() IS
        'Same-world guard for campaign.item_state (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.item_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_item_state_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_item_state_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.item_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 7. campaign.item_ownership
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.item_ownership (
            item_ownership_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id           UUID NOT NULL
                                REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            item_instance_id       UUID NOT NULL
                                REFERENCES world.item_instances(item_instance_id) ON DELETE CASCADE,
            owner_entity_id          UUID
                                REFERENCES core.entities(entity_id) ON DELETE SET NULL,
            acquired_world_time_id    UUID
                                REFERENCES core.world_times(world_time_id) ON DELETE SET NULL,
            last_event_id               UUID
                                REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_item_ownership_timeline_item UNIQUE (timeline_id, item_instance_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.item_ownership IS
        'Tracks an item instance''s current legal owner for a timeline — '
        'distinct from who currently possesses it (campaign.'
        'inventory_entries, below), per docs/DOMAIN_MODEL.md §12.4. '
        'owner_entity_id NULL means unowned/unclaimed (loose treasure). One '
        'current row per (timeline, item instance).';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_ownership_set_updated_at
        BEFORE UPDATE ON campaign.item_ownership
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_item_ownership_timeline_id ON campaign.item_ownership (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_ownership_item_instance_id "
        "ON campaign.item_ownership (item_instance_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_ownership_owner_entity_id "
        "ON campaign.item_ownership (owner_entity_id) WHERE owner_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_item_ownership_acquired_world_time_id "
        "ON campaign.item_ownership (acquired_world_time_id) "
        "WHERE acquired_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_item_ownership_last_event_id ON campaign.item_ownership (last_event_id) "
        "WHERE last_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_item_ownership_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world UUID;
            v_item_world     UUID;
            v_owner_world    UUID;
            v_acquired_world UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but item instance % belongs to world %',
                    NEW.timeline_id, v_timeline_world, NEW.item_instance_id, v_item_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.owner_entity_id IS NOT NULL THEN
                SELECT world_id INTO v_owner_world
                FROM core.entities WHERE entity_id = NEW.owner_entity_id;

                IF v_owner_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Item ownership row belongs to world %, but owner_entity_id % '
                        'belongs to world %',
                        v_timeline_world, NEW.owner_entity_id, v_owner_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.acquired_world_time_id IS NOT NULL THEN
                SELECT world_id INTO v_acquired_world
                FROM core.world_times WHERE world_time_id = NEW.acquired_world_time_id;

                IF v_acquired_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Item ownership row belongs to world %, but acquired_world_time_id % '
                        'belongs to world %',
                        v_timeline_world, NEW.acquired_world_time_id, v_acquired_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_item_ownership_world() IS
        'Same-world guard for campaign.item_ownership: item instance, '
        'owner_entity_id, and acquired_world_time_id, when set, must all '
        'belong to the same world as the timeline (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_ownership_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.item_ownership
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_item_ownership_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_item_ownership_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.item_ownership
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 8. campaign.inventory_entries
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.inventory_entries (
            inventory_entry_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id            UUID NOT NULL
                                  REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            item_instance_id        UUID NOT NULL
                                  REFERENCES world.item_instances(item_instance_id) ON DELETE CASCADE,
            holder_entity_id          UUID
                                  REFERENCES core.entities(entity_id) ON DELETE SET NULL,
            container_id               UUID
                                  REFERENCES world.item_containers(container_id) ON DELETE SET NULL,
            location_id                  UUID
                                  REFERENCES world.locations(location_id) ON DELETE SET NULL,
            last_event_id                  UUID
                                  REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_inventory_entries_timeline_item UNIQUE (timeline_id, item_instance_id),
            CONSTRAINT ck_inventory_entries_at_most_one_place CHECK (
                num_nonnulls(holder_entity_id, container_id, location_id) <= 1
            ),
            CONSTRAINT ck_inventory_entries_container_not_self CHECK (
                container_id IS NULL OR container_id != item_instance_id
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.inventory_entries IS
        'Tracks who or what currently possesses an item instance for a '
        'timeline — distinct from who legally owns it (campaign.'
        'item_ownership, above), per docs/DOMAIN_MODEL.md §12.4. At most '
        'one of holder_entity_id (carried by a character/creature), '
        'container_id (stored inside another item), or location_id (lying '
        'at a place) is set; zero set means not yet placed. One current '
        'row per (timeline, item instance).';
    """)
    op.execute("""
        CREATE TRIGGER tr_inventory_entries_set_updated_at
        BEFORE UPDATE ON campaign.inventory_entries
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_inventory_entries_timeline_id ON campaign.inventory_entries (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_inventory_entries_item_instance_id "
        "ON campaign.inventory_entries (item_instance_id);"
    )
    op.execute(
        "CREATE INDEX ix_inventory_entries_holder_entity_id "
        "ON campaign.inventory_entries (holder_entity_id) WHERE holder_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_inventory_entries_container_id "
        "ON campaign.inventory_entries (container_id) WHERE container_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_inventory_entries_location_id "
        "ON campaign.inventory_entries (location_id) WHERE location_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_inventory_entries_last_event_id "
        "ON campaign.inventory_entries (last_event_id) WHERE last_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_inventory_entry_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_item_world      UUID;
            v_holder_world    UUID;
            v_container_world UUID;
            v_location_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but item instance % belongs to world %',
                    NEW.timeline_id, v_timeline_world, NEW.item_instance_id, v_item_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.holder_entity_id IS NOT NULL THEN
                SELECT world_id INTO v_holder_world
                FROM core.entities WHERE entity_id = NEW.holder_entity_id;

                IF v_holder_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Inventory entry belongs to world %, but holder_entity_id % '
                        'belongs to world %',
                        v_timeline_world, NEW.holder_entity_id, v_holder_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.container_id IS NOT NULL THEN
                SELECT e.world_id INTO v_container_world
                FROM world.item_containers ic
                JOIN core.entities e ON e.entity_id = ic.container_id
                WHERE ic.container_id = NEW.container_id;

                IF v_container_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Inventory entry belongs to world %, but container_id % '
                        'belongs to world %',
                        v_timeline_world, NEW.container_id, v_container_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.location_id IS NOT NULL THEN
                SELECT world_id INTO v_location_world
                FROM core.entities WHERE entity_id = NEW.location_id;

                IF v_location_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Inventory entry belongs to world %, but location_id % '
                        'belongs to world %',
                        v_timeline_world, NEW.location_id, v_location_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_inventory_entry_world() IS
        'Same-world guard for campaign.inventory_entries: item instance, and '
        'whichever of holder_entity_id/container_id/location_id is set, '
        'must all belong to the same world as the timeline (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_inventory_entries_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.inventory_entries
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_inventory_entry_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_inventory_entries_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.inventory_entries
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 9. campaign.item_attunements
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.item_attunements (
            item_attunement_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id            UUID NOT NULL
                                  REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            item_instance_id        UUID NOT NULL
                                  REFERENCES world.item_instances(item_instance_id) ON DELETE CASCADE,
            character_id              UUID NOT NULL
                                  REFERENCES character.characters(character_id) ON DELETE CASCADE,
            attuned_world_time_id       UUID
                                  REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            broken_world_time_id          UUID
                                  REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            last_event_id                    UUID
                                  REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_item_attunements_broken_requires_attuned CHECK (
                broken_world_time_id IS NULL OR attuned_world_time_id IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.item_attunements IS
        'A character''s attunement to an item instance on a timeline '
        '(docs/DOMAIN_MODEL.md §12.3). broken_world_time_id NULL means the '
        'attunement is still active. ux_item_attunements_active_per_item '
        '(below) enforces the D&D rule that only one creature may be '
        'attuned to a given item at a time; the "at most 3 items per '
        'character" rule is a command-layer concern (see this revision''s '
        'docstring).';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_attunements_set_updated_at
        BEFORE UPDATE ON campaign.item_attunements
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_item_attunements_timeline_id ON campaign.item_attunements (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_attunements_item_instance_id "
        "ON campaign.item_attunements (item_instance_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_attunements_character_id ON campaign.item_attunements (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_attunements_attuned_world_time_id "
        "ON campaign.item_attunements (attuned_world_time_id) "
        "WHERE attuned_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_item_attunements_broken_world_time_id "
        "ON campaign.item_attunements (broken_world_time_id) "
        "WHERE broken_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_item_attunements_last_event_id "
        "ON campaign.item_attunements (last_event_id) WHERE last_event_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_item_attunements_active_per_item
        ON campaign.item_attunements (timeline_id, item_instance_id)
        WHERE broken_world_time_id IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_item_attunement_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world       UUID;
            v_item_world           UUID;
            v_character_world      UUID;
            v_attuned_world        UUID;
            v_attuned_sort_key     BIGINT;
            v_broken_world         UUID;
            v_broken_sort_key      BIGINT;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but item instance % belongs to world %',
                    NEW.timeline_id, v_timeline_world, NEW.item_instance_id, v_item_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            IF v_character_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Item attunement belongs to world %, but character % belongs to world %',
                    v_timeline_world, NEW.character_id, v_character_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.attuned_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_attuned_world, v_attuned_sort_key
                FROM core.world_times WHERE world_time_id = NEW.attuned_world_time_id;

                IF v_attuned_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Item attunement belongs to world %, but attuned_world_time_id % '
                        'belongs to world %',
                        v_timeline_world, NEW.attuned_world_time_id, v_attuned_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.broken_world_time_id IS NOT NULL THEN
                SELECT world_id, sort_key INTO v_broken_world, v_broken_sort_key
                FROM core.world_times WHERE world_time_id = NEW.broken_world_time_id;

                IF v_broken_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Item attunement belongs to world %, but broken_world_time_id % '
                        'belongs to world %',
                        v_timeline_world, NEW.broken_world_time_id, v_broken_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;

                IF v_broken_sort_key <= v_attuned_sort_key THEN
                    RAISE EXCEPTION
                        'Item attunement % broken_world_time_id must be strictly after '
                        'attuned_world_time_id', NEW.item_attunement_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_item_attunement_world() IS
        'Same-world guard for campaign.item_attunements plus broken-after-'
        'attuned ordering (conventions §9.5, §12.3) — the same combined '
        'shape world.enforce_organization_world() used for founded/dissolved.';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_attunements_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.item_attunements
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_item_attunement_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_item_attunements_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.item_attunements
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 10. knowledge.item_identification
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE knowledge.item_identification (
            item_identification_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                 UUID NOT NULL
                                     REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            item_instance_id             UUID NOT NULL
                                     REFERENCES world.item_instances(item_instance_id)
                                     ON DELETE CASCADE,
            knower_entity_id               UUID NOT NULL
                                     REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            identification_level             TEXT NOT NULL DEFAULT 'unidentified',
            known_properties_jsonb             JSONB,
            identified_at_world_time_id          UUID
                                     REFERENCES core.world_times(world_time_id) ON DELETE SET NULL,
            last_event_id                          UUID
                                     REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_item_identification_timeline_item_knower UNIQUE (
                timeline_id, item_instance_id, knower_entity_id
            ),
            CONSTRAINT ck_item_identification_level CHECK (
                identification_level IN {IDENTIFICATION_LEVELS}
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.item_identification IS
        'What a knower currently knows about an item instance''s hidden '
        'properties, per timeline (docs/DOMAIN_MODEL.md §12.5) — different '
        'characters may know different properties of the same item. One '
        'row per (timeline, item instance, knower).';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.item_identification.known_properties_jsonb IS
        'Which of rules.item_definitions.properties_jsonb''s keys this '
        'knower currently knows, when identification is partial — ruleset-'
        'specific detail, an acceptable JSONB use (conventions §5.7). NULL '
        'is normal for unidentified or fully identified rows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_identification_set_updated_at
        BEFORE UPDATE ON knowledge.item_identification
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_item_identification_timeline_id "
        "ON knowledge.item_identification (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_identification_item_instance_id "
        "ON knowledge.item_identification (item_instance_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_identification_knower_entity_id "
        "ON knowledge.item_identification (knower_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_item_identification_identified_at_world_time_id "
        "ON knowledge.item_identification (identified_at_world_time_id) "
        "WHERE identified_at_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_item_identification_last_event_id "
        "ON knowledge.item_identification (last_event_id) WHERE last_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_item_identification_world()
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
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            SELECT world_id INTO v_knower_world
            FROM core.entities WHERE entity_id = NEW.knower_entity_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_knower_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Item identification row mixes worlds: timeline % (world %), '
                    'item instance % (world %), knower % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.item_instance_id, v_item_world,
                    NEW.knower_entity_id, v_knower_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_item_identification_world() IS
        'World-agreement guard for knowledge.item_identification: timeline, '
        'item instance, and knower must all belong to the same world '
        '(conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_item_identification_enforce_world
        BEFORE INSERT OR UPDATE ON knowledge.item_identification
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_item_identification_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_item_identification_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON knowledge.item_identification
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 11. campaign.character_inventory (VIEW — read model, not autogenerate-tracked)
    # ==========================================================================
    op.execute("""
        CREATE VIEW campaign.character_inventory AS
        SELECT
            ie.timeline_id,
            ie.holder_entity_id AS character_id,
            ii.item_instance_id,
            ii.item_definition_id,
            idf.code AS item_definition_code,
            idf.display_name AS item_display_name,
            ist.quantity,
            ist.condition_percentage,
            ist.is_equipped,
            ist.is_destroyed,
            io.owner_entity_id,
            (io.owner_entity_id IS NOT DISTINCT FROM ie.holder_entity_id) AS is_owned_by_holder
        FROM campaign.inventory_entries ie
        JOIN world.item_instances ii ON ii.item_instance_id = ie.item_instance_id
        JOIN rules.item_definitions idf ON idf.item_definition_id = ii.item_definition_id
        LEFT JOIN campaign.item_state ist
            ON ist.timeline_id = ie.timeline_id AND ist.item_instance_id = ie.item_instance_id
        LEFT JOIN campaign.item_ownership io
            ON io.timeline_id = ie.timeline_id AND io.item_instance_id = ie.item_instance_id
        WHERE ie.holder_entity_id IS NOT NULL;
    """)
    op.execute("""
        COMMENT ON VIEW campaign.character_inventory IS
        'Character-centric read model over campaign.inventory_entries/.'
        'item_ownership/.item_state (docs/PLAN.md §12.2) — every item '
        'currently held by a character or creature on a timeline, with its '
        'definition, condition, and whether the holder is also the owner. '
        'Derived, not authoritative (conventions §22) — write through '
        'inventory_entries/item_ownership/item_state instead.';
    """)

    # ==========================================================================
    # 12. narrative.event_types: item_transferred, item_identified
    # ==========================================================================
    for sort_order, (code, display_name) in enumerate(NEW_EVENT_TYPES, start=110):
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DELETE FROM narrative.event_types WHERE code IN ('item_transferred', 'item_identified');"
    )

    op.execute("DROP VIEW IF EXISTS campaign.character_inventory;")

    op.execute("DROP TABLE IF EXISTS knowledge.item_identification;")
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_item_identification_world();")

    op.execute("DROP TABLE IF EXISTS campaign.item_attunements;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_item_attunement_world();")

    op.execute("DROP TABLE IF EXISTS campaign.inventory_entries;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_inventory_entry_world();")

    op.execute("DROP TABLE IF EXISTS campaign.item_ownership;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_item_ownership_world();")

    op.execute("DROP TABLE IF EXISTS campaign.item_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_item_state_world();")

    op.execute("DROP TABLE IF EXISTS world.item_containers;")

    op.execute("DROP TABLE IF EXISTS world.item_instances;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_item_instance_ruleset_allowed();")

    op.execute("DROP TABLE IF EXISTS rules.item_definitions;")

    op.execute("DROP TABLE IF EXISTS rules.item_categories;")

    op.execute("DELETE FROM core.entity_types WHERE code = 'item_instance';")
