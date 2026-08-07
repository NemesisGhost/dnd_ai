"""Interaction domain: interactions, actions, targets, checks, consequences, external messages

Revision ID: 061_interaction_domain
Revises: 060_state_event_provenance
Create Date: 2026-08-05 16:00:00.000000

Purpose:
    Phase 6 increment 2 (docs/PLAN.md §16, docs/architecture/DATABASE_MODEL.md
    §16, docs/DOMAIN_MODEL.md §16): the other half of Phase 6's table list.
    An interaction is a structured attempt by one or more actors to affect or
    examine the world (searching, movement, lockpicking, conversation,
    attacks, spellcasting, resting, travel, using an item, activating a
    mechanism, reading an inscription); not every interaction creates a
    narrative.events row, but Discord/Foundry/AI actions must create or
    reference an interaction record rather than writing directly to arbitrary
    tables (conventions §16.2, DATABASE_MODEL.md §16).

    Unlike narrative.events, interactions are NOT entity-rooted. The same
    reasoning DATABASE_MODEL.md §9 gives for world.area_connections/
    area_features/area_hazards/area_interactables applies here: interactions
    are high-volume structural/log records with no independent canonical
    identity of their own (no source, no canon status, nothing else needs to
    reference "the interaction" the way branch_event_id references "the
    event") — narrative.events is the entity-rooted record of what became
    historically significant; interaction.interactions is the log of what was
    attempted, most of which never rises to that level (conventions §14.5,
    event granularity).

Forward migration:
    - interaction.interaction_types (lookup: move, search, persuade, attack,
      cast_spell, use_item, activate_mechanism, pick_lock, rest, travel,
      read_inscription, converse, other), seeded
    - interaction.interactions, scoped to timeline/campaign/session like
      narrative.events, with interaction.enforce_interaction_consistency()
    - interaction.actions ("an individual operation within an interaction" —
      DOMAIN_MODEL.md §16.2; a complex interaction may contain several,
      ordered by sequence_number, each with its own actor), with
      interaction.enforce_action_actor_world()
    - interaction.targets (belongs to an action, not the interaction —
      DOMAIN_MODEL.md §16.3 ties it there explicitly), reusing the
      knowledge_items/event_effects single-typed-target pattern plus a
      free-text target_description for abstract objectives, with
      interaction.enforce_target_world()
    - interaction.check_requests (belongs to an action — resolving whether a
      specific action succeeds), referencing rules.abilities/rules.skills
      properly rather than free text, validated against the interaction's
      world's ruleset allow-list via the existing
      rules.ruleset_allowed_for_world() helper (revision 035), with
      interaction.enforce_check_request_actor_world()
    - interaction.check_results (one per check_requests row)
    - interaction.consequences ("a proposed or resolved outcome of an
      interaction" — interaction-level per DOMAIN_MODEL.md §16.6, not
      action-level), with interaction.enforce_consequence_world()
    - interaction.external_messages (the Discord/Foundry message or command
      that originated an interaction)

Rollback:
    Supported. Drops all seven domain tables, their trigger functions, and
    the interaction_types lookup (with seed rows).

Data implications:
    Seeds one small lookup. No interaction rows.

Locking considerations:
    None. All tables are new and empty.

Deliberate scoping decisions:
    - interaction.check_requests validates ability_id/skill_id against
      rules.ruleset_allowed_for_world() (the insert-side check only, same as
      revision 037's first half for character_languages) but does NOT yet add
      a check_requests usage clause to
      rules.enforce_world_ruleset_still_in_use() (the reverse DELETE/UPDATE
      guard, revision 031/037's second half) — the same two-sided contract
      every other ruleset-scoped category eventually got, added over several
      revisions rather than all at once (see revision 037's own docstring for
      that history). Recorded here as a known, non-blocking gap per §23.1's
      proportionality policy rather than left silent.
    - interaction.consequences.resulting_event_id and
      .resulting_party_discovery_id are both nullable with no CHECK tying
      their presence to consequence_type — a "proposed" consequence
      legitimately has neither yet, and a CHECK cannot express "eventually
      set once resolved." quest_change/relationship_change consequence types
      have no FK target at all yet, since narrative.quests and the
      relationship domain (Phase 7/8) do not exist — consequence_type is
      recorded as a free classification either way; the typed reference is
      added when those domains land, the same placeholder pattern used
      throughout this schema for forward references.
    - interaction.actions.actor_entity_id has no "must be a character"
      constraint — core.entities FK per conventions §9.4, same latitude
      narrative.event_participants gives its participant_entity_id.

See: docs/PLAN.md §16 (interaction and resolution implementation)
     docs/architecture/DATABASE_MODEL.md §16 (interaction and resolution model)
     docs/DOMAIN_MODEL.md §16 (interaction domain)
     docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "061_interaction_domain"
down_revision = "060_state_event_provenance"
branch_labels = None
depends_on = None

INTERACTION_TYPES = [
    ("move", "Move"),
    ("search", "Search"),
    ("persuade", "Persuade"),
    ("attack", "Attack"),
    ("cast_spell", "Cast Spell"),
    ("use_item", "Use Item"),
    ("activate_mechanism", "Activate Mechanism"),
    ("pick_lock", "Pick Lock"),
    ("rest", "Rest"),
    ("travel", "Travel"),
    ("read_inscription", "Read Inscription"),
    ("converse", "Converse"),
    ("other", "Other"),
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
    # 1. interaction.interaction_types
    # ==========================================================================
    _lookup_table(
        "interaction",
        "interaction_types",
        "interaction_type_id",
        "The kind of structured attempt to affect or examine the world "
        "(docs/DOMAIN_MODEL.md §16.1). Illustrative starter set, extensible.",
    )
    for sort_order, (code, display_name) in enumerate(INTERACTION_TYPES):
        op.execute(f"""
            INSERT INTO interaction.interaction_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 2. interaction.interactions
    # ==========================================================================
    op.execute("""
        CREATE TABLE interaction.interactions (
            interaction_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id            UUID NOT NULL
                                  REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            campaign_id              UUID
                                  REFERENCES campaign.campaigns(campaign_id) ON DELETE SET NULL,
            session_id                UUID
                                  REFERENCES campaign.sessions(session_id) ON DELETE SET NULL,
            interaction_type_id         UUID NOT NULL
                                  REFERENCES interaction.interaction_types(interaction_type_id)
                                  ON DELETE RESTRICT,
            world_time_id                 UUID NOT NULL
                                  REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            status                          TEXT NOT NULL DEFAULT 'initiated',
            summary                           TEXT,
            resulting_event_id                  UUID
                                  REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_interactions_status CHECK (
                status IN ('initiated', 'resolving', 'resolved', 'failed', 'cancelled')
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE interaction.interactions IS
        'A structured attempt by one or more actors to affect or examine the '
        'world (docs/DOMAIN_MODEL.md §16.1). Not entity-rooted — a high-volume '
        'log record, distinct from narrative.events (this revision''s docstring). '
        'May reference a campaign and session when produced during play.';
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.interactions.resulting_event_id IS
        'The event this interaction produced, when its outcome was significant '
        'enough to promote (conventions §14.5) — most interactions have none.';
    """)
    op.execute("""
        CREATE TRIGGER tr_interactions_set_updated_at
        BEFORE UPDATE ON interaction.interactions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_interactions_timeline_id ON interaction.interactions (timeline_id);"
    )
    op.execute(
        "CREATE INDEX ix_interactions_campaign_id ON interaction.interactions (campaign_id) "
        "WHERE campaign_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_interactions_session_id ON interaction.interactions (session_id) "
        "WHERE session_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_interactions_interaction_type_id "
        "ON interaction.interactions (interaction_type_id);"
    )
    op.execute(
        "CREATE INDEX ix_interactions_world_time_id ON interaction.interactions (world_time_id);"
    )
    op.execute(
        "CREATE INDEX ix_interactions_resulting_event_id "
        "ON interaction.interactions (resulting_event_id) WHERE resulting_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_interaction_consistency()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world     UUID;
            v_world_time_world   UUID;
            v_campaign_timeline  UUID;
            v_session_campaign   UUID;
            v_event_timeline     UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_world_time_world
            FROM core.world_times WHERE world_time_id = NEW.world_time_id;

            IF v_world_time_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Interaction % world time belongs to world %, but timeline % belongs to '
                    'world %',
                    NEW.interaction_id, v_world_time_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.campaign_id IS NOT NULL THEN
                SELECT timeline_id INTO v_campaign_timeline
                FROM campaign.campaigns WHERE campaign_id = NEW.campaign_id;

                IF v_campaign_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Interaction % campaign % belongs to timeline %, but the interaction '
                        'belongs to timeline %',
                        NEW.interaction_id, NEW.campaign_id, v_campaign_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.session_id IS NOT NULL THEN
                SELECT campaign_id INTO v_session_campaign
                FROM campaign.sessions WHERE session_id = NEW.session_id;

                IF NEW.campaign_id IS NULL OR v_session_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION
                        'Interaction % session % belongs to campaign %, but the interaction''s '
                        'campaign_id is %',
                        NEW.interaction_id, NEW.session_id, v_session_campaign, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.resulting_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_event_timeline
                FROM narrative.events WHERE event_id = NEW.resulting_event_id;

                IF v_event_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Interaction % resulting_event_id % belongs to timeline %, but the '
                        'interaction belongs to timeline %',
                        NEW.interaction_id, NEW.resulting_event_id, v_event_timeline,
                        NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_interaction_consistency() IS
        'Guards interaction.interactions: world_time_id must match the timeline''s '
        'world; campaign_id/session_id (when set) must form a consistent timeline '
        '-> campaign -> session chain; resulting_event_id (when set) must belong to '
        'the same timeline (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_interactions_enforce_consistency
        BEFORE INSERT OR UPDATE ON interaction.interactions
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_interaction_consistency();
    """)

    # ==========================================================================
    # 3. interaction.actions
    # ==========================================================================
    op.execute("""
        CREATE TABLE interaction.actions (
            action_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            interaction_id         UUID NOT NULL
                                  REFERENCES interaction.interactions(interaction_id)
                                  ON DELETE CASCADE,
            actor_entity_id           UUID NOT NULL
                                  REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            sequence_number             core.nonnegative_integer NOT NULL DEFAULT 0,
            description                   TEXT,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_actions_interaction_sequence UNIQUE (interaction_id, sequence_number)
        );
    """)
    op.execute("""
        COMMENT ON TABLE interaction.actions IS
        'An individual operation within an interaction (docs/DOMAIN_MODEL.md '
        '§16.2). A complex interaction may contain several, ordered by '
        'sequence_number, each with its own actor. Append-only.';
    """)
    op.execute("CREATE INDEX ix_actions_interaction_id ON interaction.actions (interaction_id);")
    op.execute("CREATE INDEX ix_actions_actor_entity_id ON interaction.actions (actor_entity_id);")
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_action_actor_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_world  UUID;
            v_actor_world        UUID;
        BEGIN
            SELECT t.world_id INTO v_interaction_world
            FROM interaction.interactions i
            JOIN campaign.timelines t ON t.timeline_id = i.timeline_id
            WHERE i.interaction_id = NEW.interaction_id;

            SELECT world_id INTO v_actor_world
            FROM core.entities WHERE entity_id = NEW.actor_entity_id;

            IF v_actor_world IS DISTINCT FROM v_interaction_world THEN
                RAISE EXCEPTION
                    'Action actor % belongs to world %, but interaction % belongs to world %',
                    NEW.actor_entity_id, v_actor_world, NEW.interaction_id, v_interaction_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_action_actor_world() IS
        'World-agreement guard for interaction.actions: the actor must belong to '
        'the interaction''s world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_actions_enforce_actor_world
        BEFORE INSERT OR UPDATE ON interaction.actions
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_action_actor_world();
    """)

    # ==========================================================================
    # 4. interaction.targets
    # ==========================================================================
    op.execute("""
        CREATE TABLE interaction.targets (
            target_id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            action_id                       UUID NOT NULL
                                           REFERENCES interaction.actions(action_id)
                                           ON DELETE CASCADE,
            target_entity_id                  UUID
                                           REFERENCES core.entities(entity_id) ON DELETE SET NULL,
            target_area_connection_id           UUID
                                           REFERENCES world.area_connections(area_connection_id)
                                           ON DELETE SET NULL,
            target_area_feature_id                UUID
                                           REFERENCES world.area_features(area_feature_id)
                                           ON DELETE SET NULL,
            target_area_hazard_id                   UUID
                                           REFERENCES world.area_hazards(area_hazard_id)
                                           ON DELETE SET NULL,
            target_area_interactable_id               UUID
                                           REFERENCES world.area_interactables
                                           (area_interactable_id) ON DELETE SET NULL,
            target_component                            TEXT,
            target_description                            TEXT,
            created_at                                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_targets_at_most_one_typed_target CHECK (
                num_nonnulls(
                    target_entity_id, target_area_connection_id, target_area_feature_id,
                    target_area_hazard_id, target_area_interactable_id
                ) <= 1
            ),
            CONSTRAINT ck_targets_identifies_something CHECK (
                num_nonnulls(
                    target_entity_id, target_area_connection_id, target_area_feature_id,
                    target_area_hazard_id, target_area_interactable_id
                ) >= 1
                OR target_description IS NOT NULL
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE interaction.targets IS
        'Identifies entities, components, areas, or abstract objectives '
        'affected by an action (docs/DOMAIN_MODEL.md §16.3). A typed target '
        '(at most one) or a free-text target_description (for abstract '
        'objectives with no typed reference) must be present. Append-only.';
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.targets.target_description IS
        'Free-text description for abstract objectives with no typed '
        'target_* reference, e.g. "the far wall" or "anyone listening".';
    """)
    op.execute("CREATE INDEX ix_targets_action_id ON interaction.targets (action_id);")
    op.execute(
        "CREATE INDEX ix_targets_target_entity_id ON interaction.targets (target_entity_id) "
        "WHERE target_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_targets_target_area_connection_id "
        "ON interaction.targets (target_area_connection_id) "
        "WHERE target_area_connection_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_targets_target_area_feature_id "
        "ON interaction.targets (target_area_feature_id) "
        "WHERE target_area_feature_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_targets_target_area_hazard_id "
        "ON interaction.targets (target_area_hazard_id) "
        "WHERE target_area_hazard_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_targets_target_area_interactable_id "
        "ON interaction.targets (target_area_interactable_id) "
        "WHERE target_area_interactable_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_target_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_action_world   UUID;
            v_target_world   UUID;
        BEGIN
            SELECT t.world_id INTO v_action_world
            FROM interaction.actions a
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
            JOIN campaign.timelines t ON t.timeline_id = i.timeline_id
            WHERE a.action_id = NEW.action_id;

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

            IF v_target_world IS DISTINCT FROM v_action_world THEN
                RAISE EXCEPTION
                    'Target belongs to world %, but action % belongs to world %',
                    v_target_world, NEW.action_id, v_action_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_target_world() IS
        'World-agreement guard for interaction.targets: whichever target_* '
        'column is set must belong to the same world as the action''s '
        'interaction (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_targets_enforce_world
        BEFORE INSERT OR UPDATE ON interaction.targets
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_target_world();
    """)

    # ==========================================================================
    # 5. interaction.check_requests
    # ==========================================================================
    op.execute("""
        CREATE TABLE interaction.check_requests (
            check_request_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            action_id                    UUID NOT NULL
                                        REFERENCES interaction.actions(action_id)
                                        ON DELETE CASCADE,
            actor_entity_id                 UUID NOT NULL
                                        REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            check_kind                        TEXT NOT NULL,
            ability_id                          UUID
                                        REFERENCES rules.abilities(ability_id) ON DELETE RESTRICT,
            skill_id                              UUID
                                        REFERENCES rules.skills(skill_id) ON DELETE RESTRICT,
            difficulty                              core.nonnegative_integer NOT NULL,
            advantage_state                           TEXT NOT NULL DEFAULT 'normal',
            modifiers                                   JSONB,
            stakes                                        TEXT,
            created_at                                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_check_requests_kind CHECK (
                check_kind IN ('ability_check', 'skill_check', 'saving_throw')
            ),
            CONSTRAINT ck_check_requests_kind_reference CHECK (
                (check_kind = 'skill_check' AND skill_id IS NOT NULL AND ability_id IS NULL)
                OR
                (check_kind IN ('ability_check', 'saving_throw')
                    AND ability_id IS NOT NULL AND skill_id IS NULL)
            ),
            CONSTRAINT ck_check_requests_advantage_state CHECK (
                advantage_state IN ('normal', 'advantage', 'disadvantage')
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE interaction.check_requests IS
        'A required rules resolution for an action: actor, ability or skill, '
        'difficulty, advantage/disadvantage, modifiers, stakes '
        '(docs/DOMAIN_MODEL.md §16.4). Append-only.';
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.check_requests.ability_id IS
        'Set for ability_check/saving_throw. NULL for skill_check, where the '
        'governing ability is reached through skill_id -> rules.skills.ability_id '
        'instead of being duplicated here.';
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.check_requests.skill_id IS
        'Set only for skill_check — see ck_check_requests_kind_reference.';
    """)
    op.execute(
        "CREATE INDEX ix_check_requests_action_id ON interaction.check_requests (action_id);"
    )
    op.execute(
        "CREATE INDEX ix_check_requests_actor_entity_id "
        "ON interaction.check_requests (actor_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_check_requests_ability_id ON interaction.check_requests (ability_id) "
        "WHERE ability_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_check_requests_skill_id ON interaction.check_requests (skill_id) "
        "WHERE skill_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_check_request_actor_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_action_world  UUID;
            v_actor_world   UUID;
        BEGIN
            SELECT t.world_id INTO v_action_world
            FROM interaction.actions a
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
            JOIN campaign.timelines t ON t.timeline_id = i.timeline_id
            WHERE a.action_id = NEW.action_id;

            SELECT world_id INTO v_actor_world
            FROM core.entities WHERE entity_id = NEW.actor_entity_id;

            IF v_actor_world IS DISTINCT FROM v_action_world THEN
                RAISE EXCEPTION
                    'Check request actor % belongs to world %, but action % belongs to world %',
                    NEW.actor_entity_id, v_actor_world, NEW.action_id, v_action_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_check_request_actor_world() IS
        'World-agreement guard for interaction.check_requests: the actor must '
        'belong to the same world as the action being resolved.';
    """)
    op.execute("""
        CREATE TRIGGER tr_check_requests_enforce_actor_world
        BEFORE INSERT OR UPDATE ON interaction.check_requests
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_check_request_actor_world();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_check_request_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_action_world     UUID;
            v_ruleset_version  UUID;
        BEGIN
            -- Only when there is an ability/skill to check. Neither set (or
            -- both set) is rejected by ck_check_requests_kind_reference, and
            -- that constraint should be the thing that reports it — a BEFORE
            -- trigger runs first, so looking one up here would mask the
            -- clearer error with a confusing "ruleset not allowed" message.
            IF NEW.ability_id IS NULL AND NEW.skill_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT t.world_id INTO v_action_world
            FROM interaction.actions a
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
            JOIN campaign.timelines t ON t.timeline_id = i.timeline_id
            WHERE a.action_id = NEW.action_id;

            IF NEW.skill_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_ruleset_version
                FROM rules.skills WHERE skill_id = NEW.skill_id;
            ELSE
                SELECT ruleset_version_id INTO v_ruleset_version
                FROM rules.abilities WHERE ability_id = NEW.ability_id;
            END IF;

            IF NOT rules.ruleset_allowed_for_world(v_action_world, v_ruleset_version) THEN
                RAISE EXCEPTION
                    'Check request %''s ability/skill ruleset is not allowed for world % '
                    '(action %''s world)',
                    NEW.check_request_id, v_action_world, NEW.action_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_check_request_ruleset_allowed() IS
        'Keeps a check request''s ability/skill drawn from a ruleset family the '
        'action''s world allows, reusing rules.ruleset_allowed_for_world() '
        '(revision 035) for the same concurrency-safe allow-list check every '
        'other ruleset-scoped category uses. Insert-side only for now — see this '
        'revision''s docstring on the deferred reverse guard.';
    """)
    op.execute("""
        CREATE TRIGGER tr_check_requests_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON interaction.check_requests
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_check_request_ruleset_allowed();
    """)

    # ==========================================================================
    # 6. interaction.check_results
    # ==========================================================================
    op.execute("""
        CREATE TABLE interaction.check_results (
            check_result_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            check_request_id           UUID NOT NULL
                                      REFERENCES interaction.check_requests(check_request_id)
                                      ON DELETE CASCADE,
            roll                          core.nonnegative_integer,
            total_modifier                  INTEGER,
            total                              INTEGER,
            degree_of_success                    TEXT NOT NULL,
            is_visible_to_players                  BOOLEAN NOT NULL DEFAULT true,
            external_system_source                   TEXT,
            created_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_check_results_one_per_request UNIQUE (check_request_id),
            CONSTRAINT ck_check_results_degree_of_success CHECK (
                degree_of_success IN
                    ('critical_success', 'success', 'failure', 'critical_failure')
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE interaction.check_results IS
        'The resolved roll, modifiers, total, degree of success, visibility, '
        'and external system source for a check request '
        '(docs/DOMAIN_MODEL.md §16.5). At most one per check_request_id — a '
        're-roll is a new check_requests row, not a mutation here. Append-only.';
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.check_results.is_visible_to_players IS
        'False for a roll the GM makes secretly (e.g. a passive check the '
        'party is not meant to know happened).';
    """)
    op.execute(
        "CREATE INDEX ix_check_results_check_request_id "
        "ON interaction.check_results (check_request_id);"
    )

    # ==========================================================================
    # 7. interaction.consequences
    # ==========================================================================
    op.execute("""
        CREATE TABLE interaction.consequences (
            consequence_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            interaction_id                    UUID NOT NULL
                                             REFERENCES interaction.interactions(interaction_id)
                                             ON DELETE CASCADE,
            consequence_type                     TEXT NOT NULL,
            status                                  TEXT NOT NULL DEFAULT 'proposed',
            resulting_event_id                        UUID
                                             REFERENCES narrative.events(event_id)
                                             ON DELETE SET NULL,
            resulting_party_discovery_id                UUID
                                             REFERENCES knowledge.party_discoveries
                                             (party_discovery_id) ON DELETE SET NULL,
            description                                   TEXT,
            created_at                                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_consequences_type CHECK (
                consequence_type IN (
                    'observation', 'event', 'state_change', 'discovery',
                    'quest_change', 'relationship_change'
                )
            ),
            CONSTRAINT ck_consequences_status CHECK (
                status IN ('proposed', 'resolved', 'rejected')
            )
        );
    """)
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
        "CREATE INDEX ix_consequences_interaction_id ON interaction.consequences (interaction_id);"
    )
    op.execute(
        "CREATE INDEX ix_consequences_resulting_event_id "
        "ON interaction.consequences (resulting_event_id) WHERE resulting_event_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_consequences_resulting_party_discovery_id "
        "ON interaction.consequences (resulting_party_discovery_id) "
        "WHERE resulting_party_discovery_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_consequences_set_updated_at
        BEFORE UPDATE ON interaction.consequences
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_consequence_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_timeline  UUID;
            v_event_timeline        UUID;
            v_discovery_timeline    UUID;
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

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_consequence_world() IS
        'Guards interaction.consequences: resulting_event_id/'
        'resulting_party_discovery_id (when set) must belong to the same '
        'timeline as the interaction (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_consequences_enforce_world
        BEFORE INSERT OR UPDATE ON interaction.consequences
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_consequence_world();
    """)

    # ==========================================================================
    # 8. interaction.external_messages
    # ==========================================================================
    op.execute("""
        CREATE TABLE interaction.external_messages (
            external_message_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            interaction_id           UUID NOT NULL
                                    REFERENCES interaction.interactions(interaction_id)
                                    ON DELETE CASCADE,
            source_system               TEXT NOT NULL,
            external_id                    TEXT NOT NULL,
            raw_payload                       JSONB,
            received_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_external_messages_source_system CHECK (
                source_system IN ('discord', 'foundry', 'other')
            ),
            CONSTRAINT ux_external_messages_source_external_id UNIQUE (source_system, external_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE interaction.external_messages IS
        'The Discord/Foundry message or command that originated an '
        'interaction, so external actions create or reference interaction '
        'records rather than writing directly to arbitrary tables '
        '(docs/architecture/DATABASE_MODEL.md §16, conventions §16.2). '
        'Unique per (source_system, external_id) so re-delivery cannot '
        'double-ingest the same external message.';
    """)
    op.execute(
        "CREATE INDEX ix_external_messages_interaction_id "
        "ON interaction.external_messages (interaction_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS interaction.external_messages;")

    op.execute("DROP TABLE IF EXISTS interaction.consequences;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_consequence_world();")

    op.execute("DROP TABLE IF EXISTS interaction.check_results;")

    op.execute("DROP TABLE IF EXISTS interaction.check_requests;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_check_request_ruleset_allowed();")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_check_request_actor_world();")

    op.execute("DROP TABLE IF EXISTS interaction.targets;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_target_world();")

    op.execute("DROP TABLE IF EXISTS interaction.actions;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_action_actor_world();")

    op.execute("DROP TABLE IF EXISTS interaction.interactions;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_interaction_consistency();")

    op.execute("DROP TABLE IF EXISTS interaction.interaction_types;")
