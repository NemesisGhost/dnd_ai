"""Quest and knowledge domain: story arcs, quests, stages, objectives, outcomes,
quest/objective state, knowledge temporal validity, versions, expertise,
information transfers, public knowledge

Revision ID: 073_quest_and_knowledge_domain
Revises: 072_interaction_lifecycle_gaps
Create Date: 2026-08-06 22:00:00.000000

Purpose:
    Phase 7 ("Quests and knowledge", docs/PLAN.md §23) delivers the quest
    domain in full and closes the knowledge-domain gaps Phase 5's pulled-
    forward slice (revision 041) explicitly deferred here: temporal validity
    on knowledge.knowledge_items, knowledge.knowledge_versions,
    knowledge.information_transfers, knowledge.expertise_domains/
    .character_expertise, and knowledge.public_knowledge — see
    docs/architecture/DATABASE_MODEL.md §15's "Explicit Phase 5 / Phase 7
    boundary" note.

    knowledge.knowledge_items/.entity_knowledge/.party_discoveries are NOT
    rebuilt here — Phase 5 already delivered them and Phase 6 revision 063
    already gave entity_knowledge/party_discoveries real interaction/event
    provenance. This revision only extends knowledge_items (temporal
    validity) and entity_knowledge (an optional knowledge_version_id, closing
    revision 041's own "nothing to version yet" placeholder now that
    knowledge_versions exists).

    Quest tables follow docs/architecture/DATABASE_MODEL.md §14's erDiagram
    exactly: narrative.quests is the one entity-rooted table in this domain
    (the diagram's only `CORE_ENTITIES ||--|| ... : is` relationship here);
    narrative.story_arcs is a standalone world-scoped definition row, not an
    entity — same reasoning DATABASE_MODEL.md §9/§16 gives for
    world.area_connections/interaction.interactions not being entities: it
    groups quests but carries no independent canonical identity of its own
    (no source, no discoverable/branchable history).

    Quest objective targets reuse the knowledge_items/event_effects/
    interaction.targets "at-most-one-of-five" typed-target pattern exactly.
    world.locations and knowledge.knowledge_items are both entity-rooted
    (their own primary key IS core.entities.entity_id), so "reach a
    location" and "discover knowledge" objectives are both expressible
    through target_entity_id alone — no separate target_location_id/
    target_knowledge_item_id column is needed, unlike the dungeon-domain
    connection/feature/hazard/interactable targets, which are not entities.

    Two documented forward-reference placeholders are closed:
    narrative.event_effects gains target_quest_objective_id (closing this
    revision's own new need — objective advancement is an event effect like
    any other typed-state change, conventions §14.4), and
    interaction.consequences gains resulting_quest_objective_state_id,
    closing revision 061's own docstring note ("quest_change ... consequence
    types have no FK target at all yet ... Phase 7/8 domains don't exist").

Forward migration:
    - core.entity_types row: quest (required_subtype_table =
      'narrative.quests', required_subtype_pk_column = 'quest_id')
    - narrative.story_arcs (not entity-rooted; world-scoped definition row)
    - narrative.quests (entity-rooted), with
      narrative.enforce_quest_story_arc_world()
    - narrative.quest_stages
    - narrative.objective_types (lookup: reach_location, acquire_item,
      defeat_entity, protect_entity, activate_mechanism, discover_knowledge,
      persuade_npc, survive_condition, complete_before_deadline, other —
      docs/DOMAIN_MODEL.md §14.4's exact list plus an other fallback), seeded
    - narrative.quest_objectives, with an at-most-one-target CHECK and
      narrative.enforce_quest_objective_target_world()
    - narrative.objective_dependencies, with a no-self-dependency CHECK and
      narrative.enforce_objective_dependency_world()
    - narrative.quest_participants, with
      narrative.enforce_quest_participant_world()
    - narrative.quest_outcomes
    - narrative.quest_rewards, with narrative.enforce_quest_reward_world()
    - campaign.quest_statuses (lookup: unavailable, available, active,
      suspended, completed, failed, abandoned — docs/ENTITY_LIFECYCLE.md
      §16's exact progression list), seeded
    - campaign.quest_state, with campaign.enforce_quest_state_world() and
      the shared campaign.enforce_state_event_timeline() (revision 066)
    - campaign.objective_statuses (lookup: hidden, available, active,
      completed, failed, skipped, superseded — docs/DOMAIN_MODEL.md §14.7's
      exact list), seeded
    - campaign.objective_state, with campaign.enforce_objective_state_world()
      and the shared campaign.enforce_state_event_timeline()
    - knowledge.knowledge_items: effective_from_world_time_id/
      effective_to_world_time_id (both nullable — see "Deliberate scoping
      decisions"), a derived validity_period INT8RANGE, and
      knowledge.enforce_knowledge_item_validity() (ADR 0010 shape, without
      an EXCLUDE constraint — a single row has nothing to overlap against,
      same reasoning as campaign.sessions, ADR 0010's "Verification status")
    - knowledge.knowledge_versions
    - knowledge.entity_knowledge.knowledge_version_id (nullable FK to
      knowledge.knowledge_versions), with
      knowledge.enforce_entity_knowledge_version_item()
    - knowledge.expertise_domains (lookup: an illustrative, extensible
      starter set), seeded
    - knowledge.character_expertise
    - knowledge.information_transfers, with
      knowledge.enforce_information_transfer_world()
    - knowledge.public_knowledge, with knowledge.enforce_public_knowledge_world()
    - narrative.event_effects.target_quest_objective_id (extends the
      at-most-one-target CHECK to six columns)
    - narrative.event_types: two new seed rows, objective_completed and
      objective_failed (the existing quest_stage_completed/quest_failed
      rows are stage-level; these are the finer-grained objective-level
      equivalents this revision's command layer produces)
    - interaction.consequences.resulting_quest_objective_state_id

Rollback:
    Supported. Drops everything created here in FK-dependency order, then
    the two entity_types/event_types seed additions and the two extended
    columns on pre-existing tables.

Data implications:
    Seeds four small lookups (~35 rows total) and two event_types rows. No
    quest, knowledge-version, expertise, transfer, or public-knowledge rows.
    The two new columns on knowledge.knowledge_items default to NULL for
    every existing row; the two new columns on narrative.event_effects and
    interaction.consequences do too.

Locking considerations:
    Two ADD COLUMN statements against knowledge.knowledge_items,
    narrative.event_effects, knowledge.entity_knowledge, and
    interaction.consequences — all metadata-only (no default, no rewrite).
    Every other statement creates a new, empty object.

Deliberate scoping decisions:
    - knowledge.knowledge_items.effective_from_world_time_id is nullable,
      not the finite-start-required column ADR 0010 describes for a
      *tracked* interval. Not every claim has a known validity window ("the
      king is corrupt" has no meaningful start); ck_knowledge_items_validity_
      requires_start still enforces that IF a validity window is tracked at
      all, its start must be finite (effective_to set with effective_from
      NULL is rejected) — the ADR's contract applies in full once a caller
      opts in, it is just not mandatory for every row.
    - narrative.quest_participants.participant_role and
      narrative.quest_rewards.reward_type are inferred, illustrative fixed
      vocabularies — docs/architecture/DATABASE_MODEL.md §14 does not name
      either table's shape beyond listing them, unlike quest objective types
      (docs/DOMAIN_MODEL.md §14.4) or objective dependency types (§14.5),
      which quote the platform's own documented lists directly.
    - No cascading "all required objectives complete -> quest completes"
      trigger or command. docs/PLAN.md's Phase 7 exit criteria name
      objective-level advancement only ("dungeon events can advance or fail
      quest objectives"); quest-level completion policy (how stage
      sequencing/optionality/mutual-exclusion combine) is real design work
      with no exit criterion forcing a specific answer yet, and building it
      ahead of a concrete caller would guess at that answer. campaign.
      quest_state exists and is fully written by application code (or a
      later command) the same way campaign.character_state started as a
      snapshot table in Phase 4 before anything automated wrote to it.
    - knowledge.knowledge_versions carries no link back to
      knowledge.information_transfers. docs/DOMAIN_MODEL.md §15.2 describes
      versions as a standalone "changed or distorted form," not as a
      byproduct with mandatory transfer provenance; a version can originate
      from an information transfer (via a future column, once a concrete
      command needs it) or from GM authoring directly.

See: docs/PLAN.md Phase 7 (quests and knowledge)
     docs/architecture/DATABASE_MODEL.md §14 (quest and story model),
     §15 (knowledge model), §17 (typed timeline state)
     docs/DOMAIN_MODEL.md §14 (narrative and quest domain), §15 (knowledge domain)
     docs/DATABASE_CONVENTIONS.md §12 (temporal conventions), §13 (timeline-state
     conventions), §14.4 (event effects)
     docs/ENTITY_LIFECYCLE.md §16 (quest lifecycle), §17 (knowledge lifecycle)
     docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "073_quest_and_knowledge_domain"
down_revision = "072_interaction_lifecycle_gaps"
branch_labels = None
depends_on = None

OBJECTIVE_TYPES = [
    ("reach_location", "Reach Location"),
    ("acquire_item", "Acquire Item"),
    ("defeat_entity", "Defeat Entity"),
    ("protect_entity", "Protect Entity"),
    ("activate_mechanism", "Activate Mechanism"),
    ("discover_knowledge", "Discover Knowledge"),
    ("persuade_npc", "Persuade NPC"),
    ("survive_condition", "Survive Condition"),
    ("complete_before_deadline", "Complete Before Deadline"),
    ("other", "Other"),
]

QUEST_STATUSES = [
    ("unavailable", "Unavailable"),
    ("available", "Available"),
    ("active", "Active"),
    ("suspended", "Suspended"),
    ("completed", "Completed"),
    ("failed", "Failed"),
    ("abandoned", "Abandoned"),
]

OBJECTIVE_STATUSES = [
    ("hidden", "Hidden"),
    ("available", "Available"),
    ("active", "Active"),
    ("completed", "Completed"),
    ("failed", "Failed"),
    ("skipped", "Skipped"),
    ("superseded", "Superseded"),
]

EXPERTISE_DOMAINS = [
    ("arcana", "Arcana"),
    ("history", "History"),
    ("religion", "Religion"),
    ("nature", "Nature"),
    ("investigation", "Investigation"),
    ("medicine", "Medicine"),
    ("survival", "Survival"),
    ("persuasion", "Persuasion"),
    ("deception", "Deception"),
    ("insight", "Insight"),
    ("engineering", "Engineering"),
    ("other", "Other"),
]

NEW_EVENT_TYPES = [
    ("objective_completed", "Objective Completed"),
    ("objective_failed", "Objective Failed"),
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
        INSERT INTO core.entity_types
            (code, display_name, required_subtype_table, required_subtype_pk_column)
        VALUES ('quest', 'Quest', 'narrative.quests', 'quest_id')
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. narrative.story_arcs (not entity-rooted — see docstring)
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.story_arcs (
            story_arc_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id      UUID NOT NULL REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            description   TEXT,
            status        TEXT NOT NULL DEFAULT 'active',
            source_id     UUID REFERENCES core.sources(source_id) ON DELETE SET NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_story_arcs_name_length CHECK (char_length(name) BETWEEN 1 AND 500),
            CONSTRAINT ck_story_arcs_status CHECK (status IN ('active', 'complete', 'abandoned'))
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.story_arcs IS
        'Groups related quests, events, themes, and outcomes (docs/DOMAIN_MODEL.md '
        '§14.1). Not entity-rooted — a world-scoped grouping record with no '
        'independent canonical identity, same reasoning as world.area_connections '
        '(revision 039) and interaction.interactions (revision 061).';
    """)
    op.execute("""
        CREATE TRIGGER tr_story_arcs_set_updated_at
        BEFORE UPDATE ON narrative.story_arcs
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_story_arcs_world_id ON narrative.story_arcs (world_id);")
    op.execute(
        "CREATE INDEX ix_story_arcs_source_id ON narrative.story_arcs (source_id) "
        "WHERE source_id IS NOT NULL;"
    )

    # ==========================================================================
    # 3. narrative.quests (entity-rooted)
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.quests (
            quest_id      UUID PRIMARY KEY REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            story_arc_id  UUID REFERENCES narrative.story_arcs(story_arc_id) ON DELETE SET NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.quests IS
        'A structured narrative challenge or objective set (docs/DOMAIN_MODEL.md '
        '§14.2). Entity-rooted — title, summary, canon status, and source are '
        'inherited from core.entities rather than duplicated here. A quest may be '
        'persistent world content while its active progress is scoped to a '
        'timeline/campaign/party (campaign.quest_state, below).';
    """)
    op.execute("""
        CREATE TRIGGER tr_quests_set_updated_at
        BEFORE UPDATE ON narrative.quests
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_quests_story_arc_id ON narrative.quests (story_arc_id) "
        "WHERE story_arc_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_quests_enforce_subtype
        AFTER INSERT OR UPDATE ON narrative.quests
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('quest_id');
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_quest_story_arc_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world    UUID;
            v_arc_world    UUID;
        BEGIN
            IF NEW.story_arc_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_own_world FROM core.entities WHERE entity_id = NEW.quest_id;
            SELECT world_id INTO v_arc_world
            FROM narrative.story_arcs WHERE story_arc_id = NEW.story_arc_id;

            IF v_arc_world IS DISTINCT FROM v_own_world THEN
                RAISE EXCEPTION
                    'Quest % belongs to world %, but story arc % belongs to world %',
                    NEW.quest_id, v_own_world, NEW.story_arc_id, v_arc_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_quest_story_arc_world() IS
        'World-agreement guard for narrative.quests: story_arc_id, when set, must '
        'belong to the quest''s own world (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_quests_enforce_story_arc_world
        BEFORE INSERT OR UPDATE ON narrative.quests
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_quest_story_arc_world();
    """)

    # ==========================================================================
    # 4. narrative.quest_stages
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.quest_stages (
            quest_stage_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            quest_id         UUID NOT NULL
                             REFERENCES narrative.quests(quest_id) ON DELETE CASCADE,
            name             TEXT NOT NULL,
            description      TEXT,
            sequence_number  core.nonnegative_integer NOT NULL DEFAULT 0,
            stage_type       TEXT NOT NULL DEFAULT 'sequential',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_quest_stages_name_length CHECK (char_length(name) BETWEEN 1 AND 500),
            CONSTRAINT ck_quest_stages_stage_type CHECK (
                stage_type IN ('sequential', 'optional', 'conditional', 'mutually_exclusive')
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.quest_stages IS
        'Groups objectives into a phase (docs/DOMAIN_MODEL.md §14.3). sequence_number '
        'orders stages within a quest; not unique, since mutually_exclusive stages '
        '(alternative branches) may legitimately share a position.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.quest_stages.stage_type IS
        'sequential, optional, conditional, or mutually_exclusive '
        '(docs/DOMAIN_MODEL.md §14.3) — fixed small vocabulary, not a lookup, same '
        'reasoning as knowledge_items.sensitivity (revision 041).';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_stages_set_updated_at
        BEFORE UPDATE ON narrative.quest_stages
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_quest_stages_quest_id ON narrative.quest_stages (quest_id);")

    # ==========================================================================
    # 5. narrative.objective_types (lookup)
    # ==========================================================================
    _lookup_table(
        "narrative",
        "objective_types",
        "objective_type_id",
        "The kind of completion/failure condition a quest objective defines "
        "(docs/DOMAIN_MODEL.md §14.4).",
    )
    for sort_order, (code, display_name) in enumerate(OBJECTIVE_TYPES):
        op.execute(f"""
            INSERT INTO narrative.objective_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 6. narrative.quest_objectives
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.quest_objectives (
            quest_objective_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            quest_stage_id                 UUID NOT NULL
                                          REFERENCES narrative.quest_stages(quest_stage_id)
                                          ON DELETE CASCADE,
            objective_type_id               UUID NOT NULL
                                          REFERENCES narrative.objective_types(objective_type_id)
                                          ON DELETE RESTRICT,
            name                             TEXT NOT NULL,
            description                       TEXT,
            requirement_level                  TEXT NOT NULL DEFAULT 'required',
            completion_mode                      TEXT NOT NULL DEFAULT 'automatic',
            target_entity_id                       UUID
                                          REFERENCES core.entities(entity_id) ON DELETE SET NULL,
            target_area_connection_id                UUID
                                          REFERENCES world.area_connections(area_connection_id)
                                          ON DELETE SET NULL,
            target_area_feature_id                     UUID
                                          REFERENCES world.area_features(area_feature_id)
                                          ON DELETE SET NULL,
            target_area_hazard_id                        UUID
                                          REFERENCES world.area_hazards(area_hazard_id)
                                          ON DELETE SET NULL,
            target_area_interactable_id                    UUID
                                          REFERENCES world.area_interactables
                                          (area_interactable_id) ON DELETE SET NULL,
            quantity_required                                INTEGER,
            created_at                                         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                           TIMESTAMPTZ NOT NULL
                                          DEFAULT now(),
            CONSTRAINT ck_quest_objectives_name_length
                CHECK (char_length(name) BETWEEN 1 AND 500),
            CONSTRAINT ck_quest_objectives_requirement_level CHECK (
                requirement_level IN ('required', 'optional', 'hidden')
            ),
            CONSTRAINT ck_quest_objectives_completion_mode CHECK (
                completion_mode IN ('automatic', 'gm_confirmed')
            ),
            CONSTRAINT ck_quest_objectives_quantity_required_positive
                CHECK (quantity_required IS NULL OR quantity_required > 0),
            CONSTRAINT ck_quest_objectives_at_most_one_target CHECK (
                num_nonnulls(
                    target_entity_id, target_area_connection_id, target_area_feature_id,
                    target_area_hazard_id, target_area_interactable_id
                ) <= 1
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.quest_objectives IS
        'Defines a completion or failure condition (docs/DOMAIN_MODEL.md §14.4). '
        'target_* columns reuse the knowledge_items/event_effects at-most-one-typed- '
        'target pattern; world.locations and knowledge.knowledge_items are both '
        'entity-rooted, so target_entity_id alone covers "reach a location" and '
        '"discover knowledge" objectives.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.quest_objectives.requirement_level IS
        'required, optional, or hidden (docs/DOMAIN_MODEL.md §14.4).';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.quest_objectives.quantity_required IS
        'For objectives counted in units, e.g. "activate three pylons" '
        '(docs/DOMAIN_MODEL.md §14). NULL for objectives with no quantity.';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_objectives_set_updated_at
        BEFORE UPDATE ON narrative.quest_objectives
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_quest_objectives_quest_stage_id "
        "ON narrative.quest_objectives (quest_stage_id);"
    )
    op.execute(
        "CREATE INDEX ix_quest_objectives_objective_type_id "
        "ON narrative.quest_objectives (objective_type_id);"
    )
    for column in (
        "target_entity_id",
        "target_area_connection_id",
        "target_area_feature_id",
        "target_area_hazard_id",
        "target_area_interactable_id",
    ):
        op.execute(
            f"CREATE INDEX ix_quest_objectives_{column} ON narrative.quest_objectives ({column}) "
            f"WHERE {column} IS NOT NULL;"
        )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_quest_objective_target_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world      UUID;
            v_target_world   UUID;
        BEGIN
            SELECT e.world_id INTO v_own_world
            FROM narrative.quest_stages qs
            JOIN narrative.quests q ON q.quest_id = qs.quest_id
            JOIN core.entities e ON e.entity_id = q.quest_id
            WHERE qs.quest_stage_id = NEW.quest_stage_id;

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
            ELSE
                RETURN NEW;
            END IF;

            IF v_target_world IS DISTINCT FROM v_own_world THEN
                RAISE EXCEPTION
                    'Quest objective % belongs to world %, but its target belongs to world %',
                    NEW.quest_objective_id, v_own_world, v_target_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_quest_objective_target_world() IS
        'World-agreement guard for narrative.quest_objectives: whichever target_* '
        'column is set must belong to the same world as the objective''s own quest '
        '(conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_objectives_enforce_target_world
        BEFORE INSERT OR UPDATE ON narrative.quest_objectives
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_quest_objective_target_world();
    """)

    # ==========================================================================
    # 7. narrative.objective_dependencies
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.objective_dependencies (
            objective_dependency_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            objective_id             UUID NOT NULL
                                     REFERENCES narrative.quest_objectives(quest_objective_id)
                                     ON DELETE CASCADE,
            depends_on_objective_id  UUID NOT NULL
                                     REFERENCES narrative.quest_objectives(quest_objective_id)
                                     ON DELETE CASCADE,
            dependency_type          TEXT NOT NULL,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_objective_dependencies_type CHECK (
                dependency_type IN ('prerequisite', 'blocking', 'exclusion', 'branching')
            ),
            CONSTRAINT ck_objective_dependencies_no_self
                CHECK (objective_id IS DISTINCT FROM depends_on_objective_id),
            CONSTRAINT ux_objective_dependencies_edge
                UNIQUE (objective_id, depends_on_objective_id, dependency_type)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.objective_dependencies IS
        'Prerequisite, blocking, exclusion, or branching relationships between '
        'objectives (docs/DOMAIN_MODEL.md §14.5). Append-only.';
    """)
    op.execute(
        "CREATE INDEX ix_objective_dependencies_objective_id "
        "ON narrative.objective_dependencies (objective_id);"
    )
    op.execute(
        "CREATE INDEX ix_objective_dependencies_depends_on_objective_id "
        "ON narrative.objective_dependencies (depends_on_objective_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_objective_dependency_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_objective_world   UUID;
            v_depends_on_world  UUID;
        BEGIN
            SELECT e.world_id INTO v_objective_world
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            JOIN narrative.quests q ON q.quest_id = qs.quest_id
            JOIN core.entities e ON e.entity_id = q.quest_id
            WHERE qo.quest_objective_id = NEW.objective_id;

            SELECT e.world_id INTO v_depends_on_world
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            JOIN narrative.quests q ON q.quest_id = qs.quest_id
            JOIN core.entities e ON e.entity_id = q.quest_id
            WHERE qo.quest_objective_id = NEW.depends_on_objective_id;

            IF v_depends_on_world IS DISTINCT FROM v_objective_world THEN
                RAISE EXCEPTION
                    'Objective dependency % (world %) depends on objective % (world %)',
                    NEW.objective_id, v_objective_world, NEW.depends_on_objective_id,
                    v_depends_on_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_objective_dependency_world() IS
        'World-agreement guard for narrative.objective_dependencies: both objectives '
        'must belong to the same world (conventions §9.5). Not restricted to the '
        'same quest — cross-quest dependencies are not ruled out by the domain model.';
    """)
    op.execute("""
        CREATE TRIGGER tr_objective_dependencies_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.objective_dependencies
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_objective_dependency_world();
    """)

    # ==========================================================================
    # 8. narrative.quest_participants
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.quest_participants (
            quest_participant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            quest_id              UUID NOT NULL
                                  REFERENCES narrative.quests(quest_id) ON DELETE CASCADE,
            participant_entity_id  UUID NOT NULL
                                  REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            participant_role        TEXT NOT NULL DEFAULT 'involved',
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_quest_participants_role CHECK (
                participant_role IN ('quest_giver', 'ally', 'antagonist', 'involved')
            ),
            CONSTRAINT ux_quest_participants_quest_entity_role
                UNIQUE (quest_id, participant_entity_id, participant_role)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.quest_participants IS
        'Relates an entity (NPC, character) to a quest with a role. Not described '
        'in detail by docs/DOMAIN_MODEL.md §14 beyond naming the table — '
        'participant_role''s vocabulary is an inferred, illustrative default, same '
        'latitude the platform already takes for narrative.event_locations.'
        'event_location_role (revision 057).';
    """)
    op.execute(
        "CREATE INDEX ix_quest_participants_quest_id ON narrative.quest_participants (quest_id);"
    )
    op.execute(
        "CREATE INDEX ix_quest_participants_participant_entity_id "
        "ON narrative.quest_participants (participant_entity_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_quest_participant_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_quest_world        UUID;
            v_participant_world  UUID;
        BEGIN
            SELECT world_id INTO v_quest_world FROM core.entities WHERE entity_id = NEW.quest_id;
            SELECT world_id INTO v_participant_world
            FROM core.entities WHERE entity_id = NEW.participant_entity_id;

            IF v_participant_world IS DISTINCT FROM v_quest_world THEN
                RAISE EXCEPTION
                    'Quest participant % belongs to world %, but quest % belongs to world %',
                    NEW.participant_entity_id, v_participant_world, NEW.quest_id, v_quest_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_quest_participant_world() IS
        'World-agreement guard for narrative.quest_participants: the participant '
        'must belong to the quest''s world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_participants_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.quest_participants
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_quest_participant_world();
    """)

    # ==========================================================================
    # 9. narrative.quest_outcomes
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.quest_outcomes (
            quest_outcome_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            quest_id          UUID NOT NULL
                              REFERENCES narrative.quests(quest_id) ON DELETE CASCADE,
            code              TEXT NOT NULL,
            name              TEXT NOT NULL,
            description       TEXT,
            outcome_category  TEXT NOT NULL DEFAULT 'success',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_quest_outcomes_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_quest_outcomes_name_length CHECK (char_length(name) BETWEEN 1 AND 500),
            CONSTRAINT ck_quest_outcomes_category CHECK (
                outcome_category IN ('success', 'partial_success', 'failure', 'neutral')
            ),
            CONSTRAINT ux_quest_outcomes_quest_code UNIQUE (quest_id, code)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.quest_outcomes IS
        'Defines a meaningful resolution and its downstream effects '
        '(docs/DOMAIN_MODEL.md §14.8). code is quest-scoped (unique per quest, not '
        'globally), unlike a lookup table''s code — each quest''s outcomes are its '
        'own narrative vocabulary.';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_outcomes_set_updated_at
        BEFORE UPDATE ON narrative.quest_outcomes
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_quest_outcomes_quest_id ON narrative.quest_outcomes (quest_id);")

    # ==========================================================================
    # 10. narrative.quest_rewards
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.quest_rewards (
            quest_reward_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            quest_outcome_id          UUID NOT NULL
                                      REFERENCES narrative.quest_outcomes(quest_outcome_id)
                                      ON DELETE CASCADE,
            reward_type               TEXT NOT NULL,
            description               TEXT NOT NULL,
            reward_knowledge_item_id  UUID
                                      REFERENCES knowledge.knowledge_items(knowledge_item_id)
                                      ON DELETE SET NULL,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_quest_rewards_type CHECK (
                reward_type IN ('item', 'currency', 'reputation', 'knowledge', 'other')
            ),
            CONSTRAINT ck_quest_rewards_description_length
                CHECK (char_length(description) BETWEEN 1 AND 2000)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.quest_rewards IS
        'A reward granted by a specific quest outcome. item/currency rewards have '
        'no typed target yet (Phase 9''s item domain does not exist); '
        'reward_knowledge_item_id is the one typed reward this phase can express.';
    """)
    op.execute(
        "CREATE INDEX ix_quest_rewards_quest_outcome_id ON narrative.quest_rewards (quest_outcome_id);"
    )
    op.execute(
        "CREATE INDEX ix_quest_rewards_reward_knowledge_item_id "
        "ON narrative.quest_rewards (reward_knowledge_item_id) "
        "WHERE reward_knowledge_item_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_quest_reward_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_quest_world      UUID;
            v_knowledge_world  UUID;
        BEGIN
            IF NEW.reward_knowledge_item_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT e.world_id INTO v_quest_world
            FROM narrative.quest_outcomes qo
            JOIN core.entities e ON e.entity_id = qo.quest_id
            WHERE qo.quest_outcome_id = NEW.quest_outcome_id;

            SELECT world_id INTO v_knowledge_world
            FROM core.entities WHERE entity_id = NEW.reward_knowledge_item_id;

            IF v_knowledge_world IS DISTINCT FROM v_quest_world THEN
                RAISE EXCEPTION
                    'Quest reward''s knowledge item % belongs to world %, but its quest '
                    'belongs to world %',
                    NEW.reward_knowledge_item_id, v_knowledge_world, v_quest_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_quest_reward_world() IS
        'World-agreement guard for narrative.quest_rewards: reward_knowledge_item_id, '
        'when set, must belong to the same world as the reward''s quest.';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_rewards_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.quest_rewards
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_quest_reward_world();
    """)

    # ==========================================================================
    # 11. campaign.quest_statuses + campaign.quest_state
    # ==========================================================================
    _lookup_table(
        "campaign",
        "quest_statuses",
        "quest_status_id",
        "Timeline-scoped quest progression (docs/ENTITY_LIFECYCLE.md §16): "
        "unavailable, available, active, suspended, completed, failed, abandoned.",
    )
    for sort_order, (code, display_name) in enumerate(QUEST_STATUSES):
        op.execute(f"""
            INSERT INTO campaign.quest_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute("""
        CREATE TABLE campaign.quest_state (
            quest_state_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id       UUID NOT NULL
                              REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            quest_id           UUID NOT NULL
                              REFERENCES narrative.quests(quest_id) ON DELETE CASCADE,
            party_id             UUID REFERENCES campaign.parties(party_id) ON DELETE CASCADE,
            quest_status_id        UUID NOT NULL
                              REFERENCES campaign.quest_statuses(quest_status_id)
                              ON DELETE RESTRICT,
            last_event_id             UUID
                              REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.quest_state IS
        'Tracks active quest progress for a timeline, optionally scoped to one '
        'party (docs/DOMAIN_MODEL.md §14.6). party_id NULL means timeline/campaign- '
        'wide tracking rather than any one party''s; party_id set means this row '
        'tracks that specific party''s progress. One current row per '
        '(timeline, quest[, party]) — see the partial unique indexes below.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.quest_state.party_id IS
        'NULL for timeline/campaign-wide progress; set for a party pursuing this '
        'quest independently of any other party on the same timeline.';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_state_set_updated_at
        BEFORE UPDATE ON campaign.quest_state
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_quest_state_timeline_id ON campaign.quest_state (timeline_id);")
    op.execute("CREATE INDEX ix_quest_state_quest_id ON campaign.quest_state (quest_id);")
    op.execute(
        "CREATE INDEX ix_quest_state_party_id ON campaign.quest_state (party_id) "
        "WHERE party_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_quest_state_quest_status_id ON campaign.quest_state (quest_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_quest_state_last_event_id ON campaign.quest_state (last_event_id) "
        "WHERE last_event_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_quest_state_timeline_quest_no_party
        ON campaign.quest_state (timeline_id, quest_id) WHERE party_id IS NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_quest_state_timeline_quest_party
        ON campaign.quest_state (timeline_id, quest_id, party_id) WHERE party_id IS NOT NULL;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_quest_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_quest_world     UUID;
            v_party_world     UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_quest_world
            FROM core.entities WHERE entity_id = NEW.quest_id;

            IF v_quest_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Quest state timeline % (world %) does not match quest % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.quest_id, v_quest_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.party_id IS NOT NULL THEN
                SELECT world_id INTO v_party_world
                FROM campaign.parties WHERE party_id = NEW.party_id;

                IF v_party_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Quest state timeline % (world %) does not match party % (world %)',
                        NEW.timeline_id, v_timeline_world, NEW.party_id, v_party_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_quest_state_world() IS
        'World-agreement guard for campaign.quest_state: timeline, quest, and party '
        '(when set) must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.quest_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_quest_state_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_quest_state_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.quest_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 12. campaign.objective_statuses + campaign.objective_state
    # ==========================================================================
    _lookup_table(
        "campaign",
        "objective_statuses",
        "objective_status_id",
        "Timeline-scoped objective progression (docs/DOMAIN_MODEL.md §14.7): "
        "hidden, available, active, completed, failed, skipped, superseded.",
    )
    for sort_order, (code, display_name) in enumerate(OBJECTIVE_STATUSES):
        op.execute(f"""
            INSERT INTO campaign.objective_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute("""
        CREATE TABLE campaign.objective_state (
            objective_state_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id          UUID NOT NULL
                                 REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            quest_objective_id    UUID NOT NULL
                                 REFERENCES narrative.quest_objectives(quest_objective_id)
                                 ON DELETE CASCADE,
            party_id                UUID REFERENCES campaign.parties(party_id) ON DELETE CASCADE,
            objective_status_id       UUID NOT NULL
                                 REFERENCES campaign.objective_statuses(objective_status_id)
                                 ON DELETE RESTRICT,
            last_event_id                UUID
                                 REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.objective_state IS
        'Tracks one quest objective''s current status for a timeline, optionally '
        'scoped to one party — same party_id NULL/set convention as '
        'campaign.quest_state above. Transitions must reference a triggering event '
        'or GM decision (docs/DOMAIN_MODEL.md §14.7); last_event_id is the causal '
        'reference (conventions §13.4). One current row per '
        '(timeline, objective[, party]).';
    """)
    op.execute("""
        CREATE TRIGGER tr_objective_state_set_updated_at
        BEFORE UPDATE ON campaign.objective_state
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_objective_state_timeline_id ON campaign.objective_state (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_objective_state_quest_objective_id "
        "ON campaign.objective_state (quest_objective_id);"
    )
    op.execute(
        "CREATE INDEX ix_objective_state_party_id ON campaign.objective_state (party_id) "
        "WHERE party_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_objective_state_objective_status_id "
        "ON campaign.objective_state (objective_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_objective_state_last_event_id ON campaign.objective_state (last_event_id) "
        "WHERE last_event_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_objective_state_timeline_objective_no_party
        ON campaign.objective_state (timeline_id, quest_objective_id) WHERE party_id IS NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_objective_state_timeline_objective_party
        ON campaign.objective_state (timeline_id, quest_objective_id, party_id)
        WHERE party_id IS NOT NULL;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_objective_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world   UUID;
            v_objective_world  UUID;
            v_party_world      UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT e.world_id INTO v_objective_world
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            JOIN narrative.quests q ON q.quest_id = qs.quest_id
            JOIN core.entities e ON e.entity_id = q.quest_id
            WHERE qo.quest_objective_id = NEW.quest_objective_id;

            IF v_objective_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Objective state timeline % (world %) does not match objective % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.quest_objective_id, v_objective_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.party_id IS NOT NULL THEN
                SELECT world_id INTO v_party_world
                FROM campaign.parties WHERE party_id = NEW.party_id;

                IF v_party_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Objective state timeline % (world %) does not match party % (world %)',
                        NEW.timeline_id, v_timeline_world, NEW.party_id, v_party_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_objective_state_world() IS
        'World-agreement guard for campaign.objective_state: timeline, objective, '
        'and party (when set) must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_objective_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.objective_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_objective_state_world();
    """)
    op.execute("""
        CREATE TRIGGER tr_objective_state_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.objective_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 13. knowledge.knowledge_items: temporal validity
    # ==========================================================================
    op.execute("""
        ALTER TABLE knowledge.knowledge_items
        ADD COLUMN effective_from_world_time_id UUID
            REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
        ADD COLUMN effective_to_world_time_id UUID
            REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
        ADD COLUMN validity_period INT8RANGE;
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.knowledge_items.effective_from_world_time_id IS
        'When this claim became true in the fictional world, if tracked (ADR 0010). '
        'NULL means no validity window is tracked for this item at all — most claims '
        '("the king is corrupt") have no meaningful start.';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.knowledge_items.effective_to_world_time_id IS
        'When this claim stopped being true, if known. NULL with '
        'effective_from_world_time_id set means still current. Must be NULL if '
        'effective_from_world_time_id is NULL (ck_knowledge_items_validity_requires_start).';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.knowledge_items.validity_period IS
        'Database-derived INT8RANGE over the two world-time columns'' sort_key '
        'values (ADR 0010), half-open [from, to). NULL when no validity window is '
        'tracked. No EXCLUDE constraint: a knowledge item has exactly one validity '
        'row, so there is nothing for it to overlap.';
    """)
    op.execute("""
        ALTER TABLE knowledge.knowledge_items
        ADD CONSTRAINT ck_knowledge_items_validity_requires_start CHECK (
            effective_from_world_time_id IS NOT NULL OR effective_to_world_time_id IS NULL
        );
    """)
    op.execute(
        "CREATE INDEX ix_knowledge_items_effective_from_world_time_id "
        "ON knowledge.knowledge_items (effective_from_world_time_id) "
        "WHERE effective_from_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_items_effective_to_world_time_id "
        "ON knowledge.knowledge_items (effective_to_world_time_id) "
        "WHERE effective_to_world_time_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_knowledge_item_validity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world     UUID;
            v_from_world    UUID;
            v_from_sort     BIGINT;
            v_to_world      UUID;
            v_to_sort       BIGINT;
        BEGIN
            IF NEW.effective_from_world_time_id IS NULL THEN
                NEW.validity_period := NULL;
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            SELECT world_id, sort_key INTO v_from_world, v_from_sort
            FROM core.world_times WHERE world_time_id = NEW.effective_from_world_time_id;

            IF v_from_world IS DISTINCT FROM v_own_world THEN
                RAISE EXCEPTION
                    'Knowledge item % belongs to world %, but effective_from_world_time_id '
                    '% belongs to world %',
                    NEW.knowledge_item_id, v_own_world, NEW.effective_from_world_time_id,
                    v_from_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.effective_to_world_time_id IS NULL THEN
                NEW.validity_period := int8range(v_from_sort, NULL);
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_to_world, v_to_sort
            FROM core.world_times WHERE world_time_id = NEW.effective_to_world_time_id;

            IF v_to_world IS DISTINCT FROM v_own_world THEN
                RAISE EXCEPTION
                    'Knowledge item % belongs to world %, but effective_to_world_time_id % '
                    'belongs to world %',
                    NEW.knowledge_item_id, v_own_world, NEW.effective_to_world_time_id, v_to_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_to_sort <= v_from_sort THEN
                RAISE EXCEPTION
                    'Knowledge item % validity end (sort_key %) must be strictly after its '
                    'start (sort_key %)',
                    NEW.knowledge_item_id, v_to_sort, v_from_sort
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.validity_period := int8range(v_from_sort, v_to_sort);
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_knowledge_item_validity() IS
        'ADR 0010 endpoint-validation and range-derivation trigger for '
        'knowledge.knowledge_items: both endpoints (when set) must belong to the '
        'item''s own world, the end must be strictly after the start, and '
        'validity_period is overwritten from the endpoints'' sort_key values — '
        'callers never supply the range directly.';
    """)
    op.execute("""
        CREATE TRIGGER tr_knowledge_items_enforce_validity
        BEFORE INSERT OR UPDATE ON knowledge.knowledge_items
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_knowledge_item_validity();
    """)

    # ==========================================================================
    # 14. knowledge.knowledge_versions
    # ==========================================================================
    op.execute("""
        CREATE TABLE knowledge.knowledge_versions (
            knowledge_version_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            knowledge_item_id     UUID NOT NULL
                                  REFERENCES knowledge.knowledge_items(knowledge_item_id)
                                  ON DELETE CASCADE,
            version_statement     TEXT NOT NULL,
            distortion_type       TEXT NOT NULL DEFAULT 'embellishment',
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_knowledge_versions_statement_length
                CHECK (char_length(version_statement) BETWEEN 1 AND 5000),
            CONSTRAINT ck_knowledge_versions_distortion_type CHECK (
                distortion_type IN (
                    'embellishment', 'omission', 'exaggeration', 'fabrication',
                    'simplification', 'other'
                )
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.knowledge_versions IS
        'A changed or distorted form of a knowledge item, supporting rumor '
        'mutation and incomplete reports (docs/DOMAIN_MODEL.md §15.2). Append-only '
        '— a new distortion is a new version, not an edit of an existing one.';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.knowledge_versions.distortion_type IS
        'An inferred, illustrative starter vocabulary — docs/DOMAIN_MODEL.md §15.2 '
        'does not enumerate distortion kinds, only the concept.';
    """)
    op.execute(
        "CREATE INDEX ix_knowledge_versions_knowledge_item_id "
        "ON knowledge.knowledge_versions (knowledge_item_id);"
    )

    # ==========================================================================
    # 15. knowledge.entity_knowledge.knowledge_version_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE knowledge.entity_knowledge
        ADD COLUMN knowledge_version_id UUID
            REFERENCES knowledge.knowledge_versions(knowledge_version_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.entity_knowledge.knowledge_version_id IS
        'The specific (possibly distorted) version this knower heard, when it was a '
        'distorted retelling rather than the canonical statement. Closes revision '
        '041''s own documented placeholder ("references a bare knowledge_item_id, '
        'not a version, since nothing to version exists yet") now that '
        'knowledge.knowledge_versions exists. NULL is still the common case — most '
        'beliefs reference the item directly.';
    """)
    op.execute(
        "CREATE INDEX ix_entity_knowledge_knowledge_version_id "
        "ON knowledge.entity_knowledge (knowledge_version_id) "
        "WHERE knowledge_version_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_entity_knowledge_version_item()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_version_item  UUID;
        BEGIN
            IF NEW.knowledge_version_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT knowledge_item_id INTO v_version_item
            FROM knowledge.knowledge_versions WHERE knowledge_version_id = NEW.knowledge_version_id;

            IF v_version_item IS DISTINCT FROM NEW.knowledge_item_id THEN
                RAISE EXCEPTION
                    'Entity knowledge row''s knowledge_version_id % belongs to knowledge item '
                    '%, but the row itself cites knowledge item %',
                    NEW.knowledge_version_id, v_version_item, NEW.knowledge_item_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_entity_knowledge_version_item() IS
        'Guards knowledge.entity_knowledge: knowledge_version_id, when set, must '
        'belong to the same knowledge_item_id the row itself cites.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_knowledge_enforce_version_item
        BEFORE INSERT OR UPDATE ON knowledge.entity_knowledge
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_entity_knowledge_version_item();
    """)

    # ==========================================================================
    # 16. knowledge.expertise_domains (lookup)
    # ==========================================================================
    _lookup_table(
        "knowledge",
        "expertise_domains",
        "expertise_domain_id",
        "An illustrative, extensible starter set of fields a character can have "
        "expertise in (docs/architecture/DATABASE_MODEL.md §15).",
    )
    for sort_order, (code, display_name) in enumerate(EXPERTISE_DOMAINS):
        op.execute(f"""
            INSERT INTO knowledge.expertise_domains (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 17. knowledge.character_expertise
    # ==========================================================================
    op.execute("""
        CREATE TABLE knowledge.character_expertise (
            character_expertise_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_id             UUID NOT NULL
                                     REFERENCES character.characters(character_id) ON DELETE CASCADE,
            expertise_domain_id       UUID NOT NULL
                                     REFERENCES knowledge.expertise_domains(expertise_domain_id)
                                     ON DELETE RESTRICT,
            proficiency_level           TEXT NOT NULL DEFAULT 'trained',
            notes                         TEXT,
            created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_character_expertise_proficiency CHECK (
                proficiency_level IN ('untrained', 'trained', 'expert', 'master')
            ),
            CONSTRAINT ux_character_expertise_character_domain
                UNIQUE (character_id, expertise_domain_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.character_expertise IS
        'What fields a character has expertise in (docs/architecture/DATABASE_MODEL.md '
        '§15). Character-level, not timeline-scoped state — expertise is treated as '
        'a stable trait of the character definition, the same latitude '
        'character.characters.size_category (revision 017) already takes.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_expertise_set_updated_at
        BEFORE UPDATE ON knowledge.character_expertise
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_character_expertise_character_id "
        "ON knowledge.character_expertise (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_expertise_expertise_domain_id "
        "ON knowledge.character_expertise (expertise_domain_id);"
    )

    # ==========================================================================
    # 18. knowledge.information_transfers
    # ==========================================================================
    op.execute("""
        CREATE TABLE knowledge.information_transfers (
            information_transfer_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                 UUID NOT NULL
                                       REFERENCES campaign.timelines(timeline_id)
                                       ON DELETE CASCADE,
            source_entity_knowledge_id   UUID NOT NULL
                                       REFERENCES knowledge.entity_knowledge(entity_knowledge_id)
                                       ON DELETE CASCADE,
            recipient_entity_id            UUID NOT NULL
                                       REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            modified_interpretation          TEXT,
            transfer_method                    TEXT NOT NULL DEFAULT 'dialogue',
            caused_by_interaction_id             UUID
                                       REFERENCES interaction.interactions(interaction_id)
                                       ON DELETE SET NULL,
            caused_by_event_id                     UUID
                                       REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            occurred_at_world_time_id                UUID
                                       REFERENCES core.world_times(world_time_id)
                                       ON DELETE SET NULL,
            created_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_information_transfers_method CHECK (
                transfer_method IN (
                    'dialogue', 'written_message', 'public_announcement', 'rumor',
                    'telepathy', 'magical_vision', 'other'
                )
            ),
            CONSTRAINT ck_information_transfers_at_most_one_cause CHECK (
                num_nonnulls(caused_by_interaction_id, caused_by_event_id) <= 1
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.information_transfers IS
        'Records communication between entities (docs/DOMAIN_MODEL.md §15.6): '
        'dialogue, written messages, public announcements, rumors, telepathy, '
        'magical visions. source_entity_knowledge_id identifies the source knower, '
        'their belief, and their interpretation together (knowledge.entity_knowledge '
        'already carries all three); modified_interpretation records what was '
        'actually conveyed, when it differs.';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.information_transfers.modified_interpretation IS
        'The interpretation actually conveyed to the recipient, when it differs '
        'from the source''s own entity_knowledge.interpretation — this is what '
        'supports rumor propagation and misinformation.';
    """)
    op.execute(
        "CREATE INDEX ix_information_transfers_timeline_id "
        "ON knowledge.information_transfers (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_information_transfers_source_entity_knowledge_id "
        "ON knowledge.information_transfers (source_entity_knowledge_id);"
    )
    op.execute(
        "CREATE INDEX ix_information_transfers_recipient_entity_id "
        "ON knowledge.information_transfers (recipient_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_information_transfers_caused_by_interaction_id "
        "ON knowledge.information_transfers (caused_by_interaction_id) "
        "WHERE caused_by_interaction_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_information_transfers_caused_by_event_id "
        "ON knowledge.information_transfers (caused_by_event_id) "
        "WHERE caused_by_event_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_information_transfers_occurred_at_world_time_id "
        "ON knowledge.information_transfers (occurred_at_world_time_id) "
        "WHERE occurred_at_world_time_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_information_transfer_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world   UUID;
            v_source_world     UUID;
            v_recipient_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT e.world_id INTO v_source_world
            FROM knowledge.entity_knowledge ek
            JOIN core.entities e ON e.entity_id = ek.knowledge_item_id
            WHERE ek.entity_knowledge_id = NEW.source_entity_knowledge_id;

            SELECT world_id INTO v_recipient_world
            FROM core.entities WHERE entity_id = NEW.recipient_entity_id;

            IF v_source_world IS DISTINCT FROM v_timeline_world
               OR v_recipient_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Information transfer mixes worlds: timeline % (world %), source '
                    'entity_knowledge % (world %), recipient % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.source_entity_knowledge_id,
                    v_source_world, NEW.recipient_entity_id, v_recipient_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_information_transfer_world() IS
        'World-agreement guard for knowledge.information_transfers: timeline, '
        'source knowledge, and recipient must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_information_transfers_enforce_world
        BEFORE INSERT OR UPDATE ON knowledge.information_transfers
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_information_transfer_world();
    """)

    # ==========================================================================
    # 19. knowledge.public_knowledge
    # ==========================================================================
    op.execute("""
        CREATE TABLE knowledge.public_knowledge (
            public_knowledge_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id               UUID NOT NULL
                                      REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            knowledge_item_id          UUID NOT NULL
                                      REFERENCES knowledge.knowledge_items(knowledge_item_id)
                                      ON DELETE CASCADE,
            location_id                  UUID NOT NULL
                                      REFERENCES world.locations(location_id) ON DELETE CASCADE,
            awareness_level                TEXT NOT NULL DEFAULT 'aware',
            known_since_world_time_id        UUID
                                      REFERENCES core.world_times(world_time_id)
                                      ON DELETE SET NULL,
            created_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_public_knowledge_awareness CHECK (
                awareness_level IN ('aware', 'rumored', 'suspected')
            ),
            CONSTRAINT ux_public_knowledge_timeline_item_location
                UNIQUE (timeline_id, knowledge_item_id, location_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE knowledge.public_knowledge IS
        'What is known publicly within a location (a settlement, a region — regions '
        'are themselves locations via world.locations.parent_location_id, revision '
        '038) independent of any one knower or party (docs/architecture/DATABASE_MODEL.md '
        '§15). Distinct from knowledge.entity_knowledge (a specific knower''s belief) '
        'and knowledge.party_discoveries (a specific discovery event).';
    """)
    op.execute("""
        CREATE TRIGGER tr_public_knowledge_set_updated_at
        BEFORE UPDATE ON knowledge.public_knowledge
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_public_knowledge_timeline_id ON knowledge.public_knowledge (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_public_knowledge_knowledge_item_id "
        "ON knowledge.public_knowledge (knowledge_item_id);"
    )
    op.execute(
        "CREATE INDEX ix_public_knowledge_location_id ON knowledge.public_knowledge (location_id);"
    )
    op.execute(
        "CREATE INDEX ix_public_knowledge_known_since_world_time_id "
        "ON knowledge.public_knowledge (known_since_world_time_id) "
        "WHERE known_since_world_time_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_public_knowledge_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_item_world      UUID;
            v_location_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            SELECT world_id INTO v_location_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_location_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Public knowledge mixes worlds: timeline % (world %), knowledge item % '
                    '(world %), location % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.knowledge_item_id, v_item_world,
                    NEW.location_id, v_location_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_public_knowledge_world() IS
        'World-agreement guard for knowledge.public_knowledge: timeline, knowledge '
        'item, and location must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_public_knowledge_enforce_world
        BEFORE INSERT OR UPDATE ON knowledge.public_knowledge
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_public_knowledge_world();
    """)

    # ==========================================================================
    # 20. narrative.event_effects.target_quest_objective_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE narrative.event_effects
        ADD COLUMN target_quest_objective_id UUID
            REFERENCES narrative.quest_objectives(quest_objective_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_effects.target_quest_objective_id IS
        'The quest objective this event advanced or failed, when it has one — the '
        'sixth target_* column in the at-most-one-of-N pattern (revision 057).';
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
                target_area_hazard_id, target_area_interactable_id, target_quest_objective_id
            ) <= 1
        );
    """)
    op.execute(
        "CREATE INDEX ix_event_effects_target_quest_objective_id "
        "ON narrative.event_effects (target_quest_objective_id) "
        "WHERE target_quest_objective_id IS NOT NULL;"
    )

    # ==========================================================================
    # 21. narrative.event_types: objective-level seed rows
    # ==========================================================================
    for sort_order, (code, display_name) in enumerate(NEW_EVENT_TYPES, start=100):
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 22. interaction.consequences.resulting_quest_objective_state_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE interaction.consequences
        ADD COLUMN resulting_quest_objective_state_id UUID
            REFERENCES campaign.objective_state(objective_state_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.consequences.resulting_quest_objective_state_id IS
        'The objective-state row a quest_change consequence produced, when it has '
        'one. Closes revision 061''s own documented placeholder ("quest_change ... '
        'consequence types have no FK target at all yet ... Phase 7/8 domains do '
        'not exist") for its quest half; relationship_change remains Phase 8''s job.';
    """)
    op.execute(
        "CREATE INDEX ix_consequences_resulting_quest_objective_state_id "
        "ON interaction.consequences (resulting_quest_objective_state_id) "
        "WHERE resulting_quest_objective_state_id IS NOT NULL;"
    )
    op.execute("""
        COMMENT ON TABLE interaction.consequences IS
        'A proposed or resolved outcome of an interaction — observations, events, '
        'state changes, discoveries, quest changes, or relationship changes '
        '(docs/DOMAIN_MODEL.md §16.6). Interaction-level, not action-level. '
        'relationship_change has no typed FK target yet (Phase 8''s domain does '
        'not exist); quest_change gained one in revision 073 '
        '(resulting_quest_objective_state_id, below).';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        COMMENT ON TABLE interaction.consequences IS
        'A proposed or resolved outcome of an interaction — observations, '
        'events, state changes, discoveries, quest changes, or relationship '
        'changes (docs/DOMAIN_MODEL.md §16.6). Interaction-level, not '
        'action-level. quest_change/relationship_change have no typed FK '
        'target yet (Phase 7/8 domains do not exist) — see this revision''s '
        'docstring.';
    """)
    op.execute(
        "ALTER TABLE interaction.consequences "
        "DROP COLUMN IF EXISTS resulting_quest_objective_state_id;"
    )

    op.execute(
        "DELETE FROM narrative.event_types WHERE code IN "
        "('objective_completed', 'objective_failed');"
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
                target_area_hazard_id, target_area_interactable_id
            ) <= 1
        );
    """)
    op.execute(
        "ALTER TABLE narrative.event_effects DROP COLUMN IF EXISTS target_quest_objective_id;"
    )

    op.execute("DROP TABLE IF EXISTS knowledge.public_knowledge;")
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_public_knowledge_world();")

    op.execute("DROP TABLE IF EXISTS knowledge.information_transfers;")
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_information_transfer_world();")

    op.execute("DROP TABLE IF EXISTS knowledge.character_expertise;")
    op.execute("DROP TABLE IF EXISTS knowledge.expertise_domains;")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_entity_knowledge_enforce_version_item "
        "ON knowledge.entity_knowledge;"
    )
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_entity_knowledge_version_item();")
    op.execute("ALTER TABLE knowledge.entity_knowledge DROP COLUMN IF EXISTS knowledge_version_id;")

    op.execute("DROP TABLE IF EXISTS knowledge.knowledge_versions;")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_knowledge_items_enforce_validity ON knowledge.knowledge_items;"
    )
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_knowledge_item_validity();")
    op.execute("""
        ALTER TABLE knowledge.knowledge_items
        DROP CONSTRAINT IF EXISTS ck_knowledge_items_validity_requires_start,
        DROP COLUMN IF EXISTS validity_period,
        DROP COLUMN IF EXISTS effective_to_world_time_id,
        DROP COLUMN IF EXISTS effective_from_world_time_id;
    """)

    op.execute("DROP TABLE IF EXISTS campaign.objective_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_objective_state_world();")
    op.execute("DROP TABLE IF EXISTS campaign.objective_statuses;")

    op.execute("DROP TABLE IF EXISTS campaign.quest_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_quest_state_world();")
    op.execute("DROP TABLE IF EXISTS campaign.quest_statuses;")

    op.execute("DROP TABLE IF EXISTS narrative.quest_rewards;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_quest_reward_world();")

    op.execute("DROP TABLE IF EXISTS narrative.quest_outcomes;")

    op.execute("DROP TABLE IF EXISTS narrative.quest_participants;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_quest_participant_world();")

    op.execute("DROP TABLE IF EXISTS narrative.objective_dependencies;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_objective_dependency_world();")

    op.execute("DROP TABLE IF EXISTS narrative.quest_objectives;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_quest_objective_target_world();")

    op.execute("DROP TABLE IF EXISTS narrative.objective_types;")

    op.execute("DROP TABLE IF EXISTS narrative.quest_stages;")

    op.execute("DROP TABLE IF EXISTS narrative.quests;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_quest_story_arc_world();")

    op.execute("DROP TABLE IF EXISTS narrative.story_arcs;")

    op.execute("DELETE FROM core.entity_types WHERE code = 'quest';")
