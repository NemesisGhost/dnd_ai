"""Narrative events domain: events, participants, locations, causes, effects, observations

Revision ID: 057_narrative_events
Revises: 056_dungeon_area_child_lock
Create Date: 2026-08-05 12:00:00.000000

Purpose:
    Phase 6 ("Events and interactions", docs/PLAN.md §23) delivers events as
    first-class entities — the dependency root for the rest of the phase:
    interactions will reference events (increment 2), campaign.timelines.
    branch_event_id references events (revision 058), and the five Phase-5
    campaign.*_state tables gain an event-provenance column (revision 060).
    This revision builds narrative.events and its five satellite tables per
    docs/PLAN.md §13.1, docs/architecture/DATABASE_MODEL.md §12, and
    docs/DOMAIN_MODEL.md §13 — nothing downstream yet.

    narrative.events is entity-rooted (docs/DATABASE_CONVENTIONS.md §14.1:
    "Events are world entities and reuse the entity UUID"), following the same
    "build the marker row" pattern as every other CTI subtype in this schema:
    it does NOT duplicate core.entities.canonical_name/summary/source_id/
    created_by_user_id, which it inherits for free. "Title" and "summary"
    (docs/DOMAIN_MODEL.md §13.1) map onto canonical_name/summary; "source"
    maps onto core.entities.source_id; "database recording time" maps onto
    core.entities.created_at. Only genuinely event-specific columns are added
    here: timeline/campaign/session scope, type, status, effective world
    time, and free-form details.

Forward migration:
    - core.entity_types row: event (root type, required_subtype_table =
      'narrative.events', required_subtype_pk_column = 'event_id')
    - narrative.event_statuses (lookup: draft, recorded, voided, corrected —
      docs/ENTITY_LIFECYCLE.md §15's exact vocabulary), seeded
    - narrative.event_types (lookup: an illustrative, extensible starter set
      covering docs/PLAN.md §13.3's promotion examples), seeded
    - narrative.event_participant_roles (lookup: the exact
      docs/DOMAIN_MODEL.md §13.2 list — actor, target, witness, victim,
      beneficiary, organizer, location_controller), seeded
    - narrative.events, with narrative.enforce_event_consistency() validating
      the event's own world against timeline_id/world_time_id, and campaign_id/
      session_id chain consistency when set
    - narrative.event_participants, with narrative.enforce_event_participant_world()
    - narrative.event_locations, with narrative.enforce_event_location_world()
    - narrative.event_causes, with a self-cause CHECK and an either-cause CHECK
      (cause_event_id or cause_description)
    - narrative.event_effects, with narrative.enforce_event_effect_target_world()
    - narrative.event_observations, with narrative.enforce_event_observation_world()

Rollback:
    Supported. Drops all six domain tables, their seven trigger functions, the
    three lookups (with seed rows), and the event entity_types row.

Data implications:
    Seeds three small lookups. No event rows.

Locking considerations:
    None. All tables are new and empty.

Deliberate scoping decisions:
    - No corrected_by_event_id/supersession column on narrative.events.
      docs/ENTITY_LIFECYCLE.md §15's "corrected" status exists as a value, but
      the correction-linkage mechanism is not required by any Phase 6 exit
      criterion — add it if/when a CorrectEvent command is actually built.
    - narrative.event_causes.cause_description is a free-text placeholder for
      interaction/decision/condition causes, the same pattern Phase 5 used for
      knowledge.entity_knowledge.learned_source (revision 041) — a real
      cause_interaction_id FK arrives once interaction.interactions exists
      (Phase 6 increment 2), not invented ahead of that table.
    - narrative.event_effects reuses knowledge.knowledge_items' exact
      "at-most-one-of-five-typed-target" pattern (target_entity_id plus one
      column per dungeon-domain non-entity target) rather than inventing a
      different shape for the same underlying problem.
    - narrative.event_locations.event_location_role is TEXT + CHECK, not a
      lookup table — a small fixed vocabulary (occurred_at, affected), same
      reasoning as knowledge_items.sensitivity (revision 041).
    - narrative.event_participants/_locations/_causes/_observations are
      append-only (created_at only, no updated_at); narrative.events and
      narrative.event_effects are mutable (status/application_status can
      transition after creation) and get the standard updated_at trigger.

See: docs/PLAN.md §13 (event implementation)
     docs/architecture/DATABASE_MODEL.md §12 (events and effects)
     docs/DOMAIN_MODEL.md §13 (event domain)
     docs/DATABASE_CONVENTIONS.md §14 (event conventions)
     docs/ENTITY_LIFECYCLE.md §15 (event entity lifecycle)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "057_narrative_events"
down_revision = "056_dungeon_area_child_lock"
branch_labels = None
depends_on = None

EVENT_STATUSES = [
    ("draft", "Draft"),
    ("recorded", "Recorded"),
    ("voided", "Voided"),
    ("corrected", "Corrected"),
]

EVENT_TYPES = [
    ("character_death", "Character Death"),
    ("character_revival", "Character Revival"),
    ("location_destroyed", "Location Destroyed"),
    ("location_discovered", "Location Discovered"),
    ("item_created", "Item Created"),
    ("item_destroyed", "Item Destroyed"),
    ("item_acquired", "Item Acquired"),
    ("hazard_triggered", "Hazard Triggered"),
    ("hazard_disarmed", "Hazard Disarmed"),
    ("mechanism_activated", "Mechanism Activated"),
    ("faction_status_change", "Faction Status Change"),
    ("npc_rescued", "NPC Rescued"),
    ("npc_captured", "NPC Captured"),
    ("relationship_change", "Relationship Change"),
    ("knowledge_revealed", "Knowledge Revealed"),
    ("quest_stage_completed", "Quest Stage Completed"),
    ("quest_failed", "Quest Failed"),
    ("session_narrative", "Session Narrative"),
    ("administrative_correction", "Administrative Correction"),
    ("other", "Other"),
]

EVENT_PARTICIPANT_ROLES = [
    ("actor", "Actor"),
    ("target", "Target"),
    ("witness", "Witness"),
    ("victim", "Victim"),
    ("beneficiary", "Beneficiary"),
    ("organizer", "Organizer"),
    ("location_controller", "Location Controller"),
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

    # narrative schema already exists (001_bootstrap.py) — nothing to create here.

    # ==========================================================================
    # 1. core.entity_types row
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, required_subtype_table, required_subtype_pk_column)
        VALUES ('event', 'Event', 'narrative.events', 'event_id')
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. Lookups
    # ==========================================================================
    _lookup_table(
        "narrative",
        "event_statuses",
        "event_status_id",
        "Lifecycle status of a recorded event (draft, recorded, voided, "
        "corrected) — docs/ENTITY_LIFECYCLE.md §15.",
    )
    for sort_order, (code, display_name) in enumerate(EVENT_STATUSES):
        op.execute(f"""
            INSERT INTO narrative.event_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    _lookup_table(
        "narrative",
        "event_types",
        "event_type_id",
        "The kind of occurrence an event represents. An illustrative, "
        "extensible starter set (docs/PLAN.md §13.3), not an exhaustive "
        "taxonomy.",
    )
    for sort_order, (code, display_name) in enumerate(EVENT_TYPES):
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    _lookup_table(
        "narrative",
        "event_participant_roles",
        "event_participant_role_id",
        "How an entity relates to an event it participated in — docs/DOMAIN_MODEL.md §13.2.",
    )
    for sort_order, (code, display_name) in enumerate(EVENT_PARTICIPANT_ROLES):
        op.execute(f"""
            INSERT INTO narrative.event_participant_roles (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 3. narrative.events
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.events (
            event_id           UUID PRIMARY KEY
                               REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            timeline_id         UUID NOT NULL
                               REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            campaign_id          UUID
                               REFERENCES campaign.campaigns(campaign_id) ON DELETE SET NULL,
            session_id            UUID
                               REFERENCES campaign.sessions(session_id) ON DELETE SET NULL,
            event_type_id          UUID NOT NULL
                               REFERENCES narrative.event_types(event_type_id) ON DELETE RESTRICT,
            event_status_id          UUID NOT NULL
                               REFERENCES narrative.event_statuses(event_status_id)
                               ON DELETE RESTRICT,
            world_time_id              UUID NOT NULL
                               REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            details                     TEXT,
            created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.events IS
        'A significant occurrence in a timeline (docs/DOMAIN_MODEL.md §13.1). '
        'Entity-rooted like any other important world object — title, summary, '
        'source and recording time are inherited from core.entities rather than '
        'duplicated here. May reference a campaign and session when produced '
        'during play.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.events.world_time_id IS
        'The effective world time (or approximate period, via core.world_times''s '
        'own label/precision support) at which this event occurred. Distinct '
        'from created_at, which is when it was recorded in the database.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.events.details IS
        'Long-form narrative text. core.entities.canonical_name/summary cover '
        'the event''s title and short summary.';
    """)
    op.execute("""
        CREATE TRIGGER tr_events_set_updated_at
        BEFORE UPDATE ON narrative.events
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_events_timeline_id ON narrative.events (timeline_id);")
    op.execute(
        "CREATE INDEX ix_events_campaign_id ON narrative.events (campaign_id) "
        "WHERE campaign_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_events_session_id ON narrative.events (session_id) "
        "WHERE session_id IS NOT NULL;"
    )
    op.execute("CREATE INDEX ix_events_event_type_id ON narrative.events (event_type_id);")
    op.execute("CREATE INDEX ix_events_event_status_id ON narrative.events (event_status_id);")
    op.execute("CREATE INDEX ix_events_world_time_id ON narrative.events (world_time_id);")
    op.execute("""
        CREATE TRIGGER tr_events_enforce_subtype
        AFTER INSERT OR UPDATE ON narrative.events
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('event_id');
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_consistency()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world           UUID;
            v_timeline_world      UUID;
            v_world_time_world    UUID;
            v_campaign_timeline   UUID;
            v_session_campaign    UUID;
        BEGIN
            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.event_id;

            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            IF v_own_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Event % belongs to world %, but timeline % belongs to world %',
                    NEW.event_id, v_own_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id INTO v_world_time_world
            FROM core.world_times WHERE world_time_id = NEW.world_time_id;

            IF v_world_time_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Event % world time belongs to world %, but timeline % belongs to world %',
                    NEW.event_id, v_world_time_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.campaign_id IS NOT NULL THEN
                SELECT timeline_id INTO v_campaign_timeline
                FROM campaign.campaigns WHERE campaign_id = NEW.campaign_id;

                IF v_campaign_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Event % campaign % belongs to timeline %, but the event belongs to '
                        'timeline %',
                        NEW.event_id, NEW.campaign_id, v_campaign_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.session_id IS NOT NULL THEN
                SELECT campaign_id INTO v_session_campaign
                FROM campaign.sessions WHERE session_id = NEW.session_id;

                IF NEW.campaign_id IS NULL OR v_session_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION
                        'Event % session % belongs to campaign %, but the event''s campaign_id '
                        'is %',
                        NEW.event_id, NEW.session_id, v_session_campaign, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_consistency() IS
        'Guards narrative.events: the event''s own world must match its timeline '
        'and world time, and campaign_id/session_id (when set) must form a '
        'consistent timeline -> campaign -> session chain (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_events_enforce_consistency
        BEFORE INSERT OR UPDATE ON narrative.events
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_consistency();
    """)

    # ==========================================================================
    # 4. narrative.event_participants
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.event_participants (
            event_participant_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id                 UUID NOT NULL
                                    REFERENCES narrative.events(event_id) ON DELETE CASCADE,
            participant_entity_id      UUID NOT NULL
                                    REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            participant_role_id          UUID NOT NULL
                                    REFERENCES narrative.event_participant_roles
                                    (event_participant_role_id) ON DELETE RESTRICT,
            notes                          TEXT,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_event_participants_event_entity_role
                UNIQUE (event_id, participant_entity_id, participant_role_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_participants IS
        'Relates an entity to an event with a role — actor, target, witness, '
        'victim, beneficiary, organizer, location_controller '
        '(docs/DOMAIN_MODEL.md §13.2). Append-only.';
    """)
    op.execute(
        "CREATE INDEX ix_event_participants_event_id ON narrative.event_participants (event_id);"
    )
    op.execute(
        "CREATE INDEX ix_event_participants_participant_entity_id "
        "ON narrative.event_participants (participant_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_event_participants_participant_role_id "
        "ON narrative.event_participants (participant_role_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_participant_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_world        UUID;
            v_participant_world  UUID;
        BEGIN
            SELECT world_id INTO v_event_world
            FROM core.entities WHERE entity_id = NEW.event_id;

            SELECT world_id INTO v_participant_world
            FROM core.entities WHERE entity_id = NEW.participant_entity_id;

            IF v_participant_world IS DISTINCT FROM v_event_world THEN
                RAISE EXCEPTION
                    'Event participant % belongs to world %, but event % belongs to world %',
                    NEW.participant_entity_id, v_participant_world, NEW.event_id, v_event_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_participant_world() IS
        'World-agreement guard for narrative.event_participants: the '
        'participant must belong to the event''s world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_participants_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.event_participants
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_participant_world();
    """)

    # ==========================================================================
    # 5. narrative.event_locations
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.event_locations (
            event_location_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id               UUID NOT NULL
                                  REFERENCES narrative.events(event_id) ON DELETE CASCADE,
            location_id              UUID NOT NULL
                                  REFERENCES world.locations(location_id) ON DELETE CASCADE,
            event_location_role        TEXT NOT NULL DEFAULT 'occurred_at',
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_event_locations_role
                CHECK (event_location_role IN ('occurred_at', 'affected')),
            CONSTRAINT ux_event_locations_event_location_role
                UNIQUE (event_id, location_id, event_location_role)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_locations IS
        'Identifies where an event occurred or what locations it affected '
        '(docs/DOMAIN_MODEL.md §13.3). Append-only.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_locations.event_location_role IS
        'occurred_at (where the event took place) or affected (a location the '
        'event changed without being the site of the event). Fixed small '
        'vocabulary, not a lookup — same reasoning as knowledge_items.sensitivity '
        '(revision 041).';
    """)
    op.execute("CREATE INDEX ix_event_locations_event_id ON narrative.event_locations (event_id);")
    op.execute(
        "CREATE INDEX ix_event_locations_location_id ON narrative.event_locations (location_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_location_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_world     UUID;
            v_location_world  UUID;
        BEGIN
            SELECT world_id INTO v_event_world
            FROM core.entities WHERE entity_id = NEW.event_id;

            SELECT world_id INTO v_location_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            IF v_location_world IS DISTINCT FROM v_event_world THEN
                RAISE EXCEPTION
                    'Event location % belongs to world %, but event % belongs to world %',
                    NEW.location_id, v_location_world, NEW.event_id, v_event_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_location_world() IS
        'World-agreement guard for narrative.event_locations: the location '
        'must belong to the event''s world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_locations_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.event_locations
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_location_world();
    """)

    # ==========================================================================
    # 6. narrative.event_causes
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.event_causes (
            event_cause_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id             UUID NOT NULL
                                REFERENCES narrative.events(event_id) ON DELETE CASCADE,
            cause_event_id          UUID
                                REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            cause_description         TEXT,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_event_causes_has_cause
                CHECK (cause_event_id IS NOT NULL OR cause_description IS NOT NULL),
            CONSTRAINT ck_event_causes_no_self_cause
                CHECK (cause_event_id IS DISTINCT FROM event_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_causes IS
        'Links an event to a prior event, or a free-text decision/condition, '
        'that caused it (docs/DOMAIN_MODEL.md §13.4). Append-only.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_causes.cause_description IS
        'Free-text placeholder for interaction/decision/condition causes until '
        'interaction.interactions exists (Phase 6 increment 2) to reference '
        'instead — same pattern as knowledge.entity_knowledge.learned_source '
        '(revision 041).';
    """)
    op.execute("CREATE INDEX ix_event_causes_event_id ON narrative.event_causes (event_id);")
    op.execute(
        "CREATE INDEX ix_event_causes_cause_event_id ON narrative.event_causes (cause_event_id) "
        "WHERE cause_event_id IS NOT NULL;"
    )

    # ==========================================================================
    # 7. narrative.event_effects
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.event_effects (
            event_effect_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id                         UUID NOT NULL
                                            REFERENCES narrative.events(event_id) ON DELETE CASCADE,
            target_entity_id                   UUID
                                            REFERENCES core.entities(entity_id) ON DELETE SET NULL,
            target_area_connection_id            UUID
                                            REFERENCES world.area_connections(area_connection_id)
                                            ON DELETE SET NULL,
            target_area_feature_id                 UUID
                                            REFERENCES world.area_features(area_feature_id)
                                            ON DELETE SET NULL,
            target_area_hazard_id                    UUID
                                            REFERENCES world.area_hazards(area_hazard_id)
                                            ON DELETE SET NULL,
            target_area_interactable_id                UUID
                                            REFERENCES world.area_interactables
                                            (area_interactable_id) ON DELETE SET NULL,
            target_component                             TEXT NOT NULL,
            previous_value                                 JSONB,
            new_value                                        JSONB,
            effective_world_time_id                            UUID
                                            REFERENCES core.world_times(world_time_id)
                                            ON DELETE SET NULL,
            application_status                                   TEXT NOT NULL DEFAULT 'applied',
            created_at                                             TIMESTAMPTZ NOT NULL
                                            DEFAULT now(),
            updated_at                                               TIMESTAMPTZ NOT NULL
                                            DEFAULT now(),
            CONSTRAINT ck_event_effects_at_most_one_target CHECK (
                num_nonnulls(
                    target_entity_id, target_area_connection_id, target_area_feature_id,
                    target_area_hazard_id, target_area_interactable_id
                ) <= 1
            ),
            CONSTRAINT ck_event_effects_application_status CHECK (
                application_status IN ('pending', 'applied', 'failed', 'skipped')
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_effects IS
        'A change caused by an event: target, affected component, old/new '
        'value, effective time, application status (docs/DOMAIN_MODEL.md '
        '§13.5). Common effects should also update the corresponding typed '
        'state table in the same transaction (conventions §14.4).';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_effects.target_entity_id IS
        'The core.entities row this effect changed, when it has one. At most '
        'one target_* column is set — same pattern as '
        'knowledge.knowledge_items.subject_entity_id (revision 041).';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_effects.target_component IS
        'Machine-readable path to the affected field, e.g. "hit_points_current" '
        'or "hazard_status_id".';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_effects_set_updated_at
        BEFORE UPDATE ON narrative.event_effects
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_event_effects_event_id ON narrative.event_effects (event_id);")
    op.execute(
        "CREATE INDEX ix_event_effects_target_entity_id "
        "ON narrative.event_effects (target_entity_id) WHERE target_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_event_effects_target_area_connection_id "
        "ON narrative.event_effects (target_area_connection_id) "
        "WHERE target_area_connection_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_event_effects_target_area_feature_id "
        "ON narrative.event_effects (target_area_feature_id) "
        "WHERE target_area_feature_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_event_effects_target_area_hazard_id "
        "ON narrative.event_effects (target_area_hazard_id) "
        "WHERE target_area_hazard_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_event_effects_target_area_interactable_id "
        "ON narrative.event_effects (target_area_interactable_id) "
        "WHERE target_area_interactable_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_event_effects_effective_world_time_id "
        "ON narrative.event_effects (effective_world_time_id) "
        "WHERE effective_world_time_id IS NOT NULL;"
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
        '(conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_effects_enforce_target_world
        BEFORE INSERT OR UPDATE ON narrative.event_effects
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_effect_target_world();
    """)

    # ==========================================================================
    # 8. narrative.event_observations
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.event_observations (
            event_observation_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id                  UUID NOT NULL
                                    REFERENCES narrative.events(event_id) ON DELETE CASCADE,
            observer_entity_id           UUID NOT NULL
                                    REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            observation_text                TEXT NOT NULL,
            observed_at_world_time_id          UUID
                                    REFERENCES core.world_times(world_time_id) ON DELETE SET NULL,
            created_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_event_observations_text_length
                CHECK (char_length(observation_text) BETWEEN 1 AND 5000)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_observations IS
        'What an observer perceived about an event, distinct from its '
        'objective facts (docs/DOMAIN_MODEL.md §13.6). Append-only.';
    """)
    op.execute(
        "CREATE INDEX ix_event_observations_event_id ON narrative.event_observations (event_id);"
    )
    op.execute(
        "CREATE INDEX ix_event_observations_observer_entity_id "
        "ON narrative.event_observations (observer_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_event_observations_observed_at_world_time_id "
        "ON narrative.event_observations (observed_at_world_time_id) "
        "WHERE observed_at_world_time_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_observation_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_world      UUID;
            v_observer_world   UUID;
        BEGIN
            SELECT world_id INTO v_event_world
            FROM core.entities WHERE entity_id = NEW.event_id;

            SELECT world_id INTO v_observer_world
            FROM core.entities WHERE entity_id = NEW.observer_entity_id;

            IF v_observer_world IS DISTINCT FROM v_event_world THEN
                RAISE EXCEPTION
                    'Event observer % belongs to world %, but event % belongs to world %',
                    NEW.observer_entity_id, v_observer_world, NEW.event_id, v_event_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_observation_world() IS
        'World-agreement guard for narrative.event_observations: the observer '
        'must belong to the event''s world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_observations_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.event_observations
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_observation_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS narrative.event_observations;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_observation_world();")

    op.execute("DROP TABLE IF EXISTS narrative.event_effects;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_effect_target_world();")

    op.execute("DROP TABLE IF EXISTS narrative.event_causes;")

    op.execute("DROP TABLE IF EXISTS narrative.event_locations;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_location_world();")

    op.execute("DROP TABLE IF EXISTS narrative.event_participants;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_participant_world();")

    op.execute("DROP TABLE IF EXISTS narrative.events;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_consistency();")

    op.execute("DROP TABLE IF EXISTS narrative.event_participant_roles;")
    op.execute("DROP TABLE IF EXISTS narrative.event_types;")
    op.execute("DROP TABLE IF EXISTS narrative.event_statuses;")

    op.execute("DELETE FROM core.entity_types WHERE code = 'event';")
