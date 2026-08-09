"""Encounter domain: encounters, participants, rounds, turns, and combat
actions.

Revision ID: 078_encounter_domain
Revises: 077_item_domain
Create Date: 2026-08-09 15:00:00.000000

Purpose:
    Phase 9 ("Items, inventory, encounters, and Foundry integration contracts",
    docs/PLAN.md §23) delivers encounters (docs/architecture/DATABASE_MODEL.md
    §13). This is the second increment of the phase — item domain (revision
    077) came first; Foundry identifiers/sync records follow in revision 079.

    narrative.encounters is not entity-rooted — the same reasoning
    DATABASE_MODEL.md §16.1 gives for interaction.interactions (revision
    061): a structural, high-volume-ish session record with no independent
    canonical identity of its own beyond its participants, timeline, and
    outcome. It sits in the `narrative` schema rather than `interaction`
    because DATABASE_MODEL.md §13 places it there explicitly and because,
    unlike a single interaction, an encounter is the thing narrative.events
    are promoted *from* (its own resulting_event_id, mirroring
    interaction.interactions.resulting_event_id) rather than a peer of
    interaction.interactions. encounter_participants/_rounds/_turns follow
    interaction.interactions' plain-TEXT-status-with-CHECK convention
    (status, side, outcome, action_kind below) rather than the lookup-table
    convention narrative.events itself uses for event_status_id — encounters
    are structurally much closer to interactions (high-volume, session-
    scoped) than to the permanent-history events table.

    FoundryVTT may remain the detailed tactical authority during live combat
    (DATABASE_MODEL.md §13); this domain captures synchronized state and
    meaningful outcomes, not every tactical decision. Current HP and
    conditions are NOT duplicated here — they already exist as timeline
    state (campaign.character_state.current_hit_points,
    campaign.character_conditions, both Phase 4) and resource consumption
    already exists as campaign.character_resources (Phase 4). Encounter-
    driven commands update those existing tables through events (rule 6),
    the same way every other domain in this project updates typed state —
    building parallel HP/condition/resource columns on encounter_turns would
    be exactly the "campaign-owned copy of persistent world/character state"
    anti-pattern docs/DATABASE_CONVENTIONS.md §34 warns against.

    interaction.combat_actions is a sibling of interaction.check_requests
    (both children of interaction.actions, revision 061) rather than a new
    root — an attack roll is mechanically an ability check against a target's
    AC and is already representable as check_kind = 'ability_check' on the
    existing check_requests/check_results pair; no new check_kind or roll
    machinery is added here. combat_actions instead captures the combat-
    specific semantics check_requests has no room for: what kind of action
    (attack/cast_spell/dodge/...), what item or spell was used, whether it
    hit, and its damage/condition outcome.

    Forward-reference closed: narrative.event_causes gains cause_encounter_id
    (a fourth cause type alongside cause_event_id/cause_interaction_id/
    cause_description, extending revision 062's num_nonnulls CHECK to
    require exactly one of four instead of three) — a mid-combat event (a
    character killed, an item destroyed) can now cite the encounter that
    produced it, the same way revision 062 let events cite the interaction
    that produced them.

Forward migration:
    - narrative.encounters (not entity-rooted), with
      narrative.enforce_encounter_world()
    - narrative.encounter_participants, with
      narrative.enforce_encounter_participant_world()
    - narrative.encounter_rounds
    - interaction.combat_actions (child of interaction.actions), with
      interaction.enforce_combat_action_world()
    - narrative.encounter_turns, with
      narrative.enforce_encounter_turn_participant_round()
    - narrative.event_types: one new seed row, combat_damage_dealt
    - narrative.event_causes.cause_encounter_id, with
      narrative.enforce_event_cause_encounter_world() (mirrors revision
      062's enforce_event_cause_interaction_world())

Rollback:
    Supported. Drops everything created here in FK-dependency order, then
    the event_types seed addition and the extended CHECK/column.

Data implications:
    Seeds one narrative.event_types row. No encounter, participant, round,
    turn, or combat_action rows.

Locking considerations:
    One ALTER TABLE against narrative.event_causes (ADD COLUMN, metadata-
    only) plus a CHECK constraint replacement — both cheap against the
    table's current near-empty size. Every other statement creates a new,
    empty object.

Deliberate scoping decisions:
    - No entity_types/CTI row is added for encounters — see the not-entity-
      rooted reasoning above.
    - encounter_turns does not enforce one-turn-per-participant-per-round
      via a database CHECK beyond the natural UNIQUE(encounter_round_id,
      participant_id); a character with multiple attacks (Extra Attack,
      bonus-action spells) is recorded as multiple interaction.actions/
      combat_actions referenced from other narrative context, not multiple
      encounter_turns rows — the turn row marks whose initiative slot is
      active, not a log of every action taken during it.
    - combat_actions.item_instance_id/.spell_id have no CHECK forcing
      exactly one or none — a natural attack (fists, claws) sets neither,
      an unarmed strike with a held weapon sets item_instance_id, a spell
      sets spell_id; both being set (a weapon that also functions as a
      spellcasting focus for the same action) is left un-forbidden rather
      than modeled with a speculative exclusivity rule no exit criterion
      requires.
    - encounter_rounds carries no world_time_id of its own — rounds are
      tactical sub-steps of the encounter's single narrative moment
      (encounters.world_time_id), the same way interaction.actions carry no
      world_time_id independent of their parent interaction.

See: docs/PLAN.md Phase 9 (items, inventory, encounters, Foundry integration contracts)
     docs/architecture/DATABASE_MODEL.md §13 (encounters and combat)
     docs/DOMAIN_MODEL.md §17 (encounter domain)
     docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency), §34
     (anti-patterns)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "078_encounter_domain"
down_revision = "077_item_domain"
branch_labels = None
depends_on = None

ENCOUNTER_STATUSES = ("pending", "active", "completed", "aborted")
ENCOUNTER_PARTICIPANT_SIDES = ("party", "ally", "enemy", "neutral")
ENCOUNTER_PARTICIPANT_OUTCOMES = ("defeated", "escaped", "surrendered", "captured")
COMBAT_ACTION_KINDS = (
    "attack",
    "cast_spell",
    "dodge",
    "dash",
    "disengage",
    "help",
    "hide",
    "ready",
    "use_item",
    "other",
)


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. narrative.encounters (not entity-rooted — see docstring)
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE narrative.encounters (
            encounter_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id          UUID NOT NULL
                                REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            campaign_id            UUID
                                REFERENCES campaign.campaigns(campaign_id) ON DELETE SET NULL,
            session_id                UUID
                                REFERENCES campaign.sessions(session_id) ON DELETE SET NULL,
            location_id                  UUID
                                REFERENCES world.locations(location_id) ON DELETE SET NULL,
            world_time_id                  UUID NOT NULL
                                REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            status                            TEXT NOT NULL DEFAULT 'pending',
            current_round                        core.nonnegative_integer NOT NULL DEFAULT 0,
            summary                                TEXT,
            resulting_event_id                       UUID
                                REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_encounters_status CHECK (status IN {ENCOUNTER_STATUSES})
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.encounters IS
        'A combat or tactical encounter (docs/DOMAIN_MODEL.md §17.1) — not '
        'entity-rooted, a structural session record like '
        'interaction.interactions (revision 061), distinct from '
        'narrative.events. FoundryVTT may remain the detailed tactical '
        'authority during live combat; this table captures synchronized '
        'state and meaningful outcomes (docs/architecture/DATABASE_MODEL.md '
        '§13), not every tactical decision.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.encounters.resulting_event_id IS
        'The event this encounter produced, when its outcome was '
        'significant enough to promote — mirrors '
        'interaction.interactions.resulting_event_id. Individual mid-'
        'combat events (a character killed) cite the encounter directly '
        'via narrative.event_causes.cause_encounter_id instead.';
    """)
    op.execute("""
        CREATE TRIGGER tr_encounters_set_updated_at
        BEFORE UPDATE ON narrative.encounters
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_encounters_timeline_id ON narrative.encounters (timeline_id);")
    op.execute(
        "CREATE INDEX ix_encounters_campaign_id ON narrative.encounters (campaign_id) "
        "WHERE campaign_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_encounters_session_id ON narrative.encounters (session_id) "
        "WHERE session_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_encounters_location_id ON narrative.encounters (location_id) "
        "WHERE location_id IS NOT NULL;"
    )
    op.execute("CREATE INDEX ix_encounters_world_time_id ON narrative.encounters (world_time_id);")
    op.execute(
        "CREATE INDEX ix_encounters_resulting_event_id ON narrative.encounters (resulting_event_id) "
        "WHERE resulting_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_encounter_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world    UUID;
            v_location_world    UUID;
            v_world_time_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            IF NEW.location_id IS NOT NULL THEN
                SELECT world_id INTO v_location_world
                FROM core.entities WHERE entity_id = NEW.location_id;

                IF v_location_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Encounter % belongs to world %, but location_id % belongs to world %',
                        NEW.encounter_id, v_timeline_world, NEW.location_id, v_location_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            SELECT world_id INTO v_world_time_world
            FROM core.world_times WHERE world_time_id = NEW.world_time_id;

            IF v_world_time_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Encounter % belongs to world %, but world_time_id % belongs to world %',
                    NEW.encounter_id, v_timeline_world, NEW.world_time_id, v_world_time_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_encounter_world() IS
        'Same-world guard for narrative.encounters: location_id and '
        'world_time_id, when set, must belong to the same world as the '
        'timeline (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_encounters_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.encounters
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_encounter_world();
    """)

    # ==========================================================================
    # 2. narrative.encounter_participants
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE narrative.encounter_participants (
            encounter_participant_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            encounter_id                 UUID NOT NULL
                                        REFERENCES narrative.encounters(encounter_id)
                                        ON DELETE CASCADE,
            participant_entity_id          UUID NOT NULL
                                        REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            side                              TEXT NOT NULL DEFAULT 'party',
            initiative                          INTEGER,
            outcome                                TEXT,
            created_at                               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_encounter_participants_encounter_entity UNIQUE (
                encounter_id, participant_entity_id
            ),
            CONSTRAINT ck_encounter_participants_side CHECK (
                side IN {ENCOUNTER_PARTICIPANT_SIDES}
            ),
            CONSTRAINT ck_encounter_participants_outcome CHECK (
                outcome IS NULL OR outcome IN {ENCOUNTER_PARTICIPANT_OUTCOMES}
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.encounter_participants IS
        'An entity taking part in an encounter (docs/DOMAIN_MODEL.md §17.2) '
        '— side, initiative, and outcome (defeated/escaped/surrendered/'
        'captured) once resolved. outcome NULL means still in progress or '
        'the encounter ended without a tracked individual outcome for this '
        'participant.';
    """)
    op.execute("""
        CREATE TRIGGER tr_encounter_participants_set_updated_at
        BEFORE UPDATE ON narrative.encounter_participants
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_encounter_participants_encounter_id "
        "ON narrative.encounter_participants (encounter_id);"
    )
    op.execute(
        "CREATE INDEX ix_encounter_participants_participant_entity_id "
        "ON narrative.encounter_participants (participant_entity_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_encounter_participant_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_encounter_world    UUID;
            v_participant_world  UUID;
        BEGIN
            SELECT t.world_id INTO v_encounter_world
            FROM narrative.encounters e
            JOIN campaign.timelines t ON t.timeline_id = e.timeline_id
            WHERE e.encounter_id = NEW.encounter_id;

            SELECT world_id INTO v_participant_world
            FROM core.entities WHERE entity_id = NEW.participant_entity_id;

            IF v_participant_world IS DISTINCT FROM v_encounter_world THEN
                RAISE EXCEPTION
                    'Encounter % belongs to world %, but participant % belongs to world %',
                    NEW.encounter_id, v_encounter_world, NEW.participant_entity_id,
                    v_participant_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_encounter_participant_world() IS
        'Same-world guard for narrative.encounter_participants (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_encounter_participants_enforce_world
        BEFORE INSERT OR UPDATE ON narrative.encounter_participants
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_encounter_participant_world();
    """)

    # ==========================================================================
    # 3. narrative.encounter_rounds
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.encounter_rounds (
            encounter_round_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            encounter_id           UUID NOT NULL
                                  REFERENCES narrative.encounters(encounter_id) ON DELETE CASCADE,
            round_number             core.nonnegative_integer NOT NULL,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_encounter_rounds_encounter_round UNIQUE (encounter_id, round_number)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.encounter_rounds IS
        'One round of an encounter (docs/DOMAIN_MODEL.md §17). Carries no '
        'world_time_id of its own — a tactical sub-step of the encounter''s '
        'single narrative moment (narrative.encounters.world_time_id), the '
        'same way interaction.actions carry no world_time_id independent of '
        'their parent interaction. Append-only.';
    """)
    op.execute(
        "CREATE INDEX ix_encounter_rounds_encounter_id "
        "ON narrative.encounter_rounds (encounter_id);"
    )

    # ==========================================================================
    # 4. interaction.combat_actions (child of interaction.actions)
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE interaction.combat_actions (
            combat_action_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            action_id                UUID NOT NULL
                                    REFERENCES interaction.actions(action_id) ON DELETE CASCADE,
            target_id                   UUID
                                    REFERENCES interaction.targets(target_id) ON DELETE SET NULL,
            action_kind                    TEXT NOT NULL,
            item_instance_id                  UUID
                                    REFERENCES world.item_instances(item_instance_id)
                                    ON DELETE SET NULL,
            spell_id                             UUID
                                    REFERENCES rules.spells(spell_id) ON DELETE SET NULL,
            hit                                     BOOLEAN,
            damage_amount                             core.nonnegative_integer,
            damage_type_id                               UUID
                                    REFERENCES rules.damage_types(damage_type_id)
                                    ON DELETE RESTRICT,
            resulting_condition_id                          UUID
                                    REFERENCES rules.conditions(condition_id) ON DELETE RESTRICT,
            created_at                                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_combat_actions_action_kind CHECK (action_kind IN {COMBAT_ACTION_KINDS})
        );
    """)
    op.execute("""
        COMMENT ON TABLE interaction.combat_actions IS
        'Combat-specific detail for an action (docs/DOMAIN_MODEL.md §17), a '
        'sibling of interaction.check_requests under interaction.actions — '
        'an attack roll is already representable as check_kind = '
        '''ability_check'' on check_requests/check_results (revision 061); '
        'this table adds what those cannot: action kind, item/spell used, '
        'hit/miss, and damage/condition outcome. Append-only.';
    """)
    op.execute(
        "CREATE INDEX ix_combat_actions_action_id ON interaction.combat_actions (action_id);"
    )
    op.execute(
        "CREATE INDEX ix_combat_actions_target_id ON interaction.combat_actions (target_id) "
        "WHERE target_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_combat_actions_item_instance_id "
        "ON interaction.combat_actions (item_instance_id) WHERE item_instance_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_combat_actions_spell_id ON interaction.combat_actions (spell_id) "
        "WHERE spell_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_combat_actions_damage_type_id "
        "ON interaction.combat_actions (damage_type_id) WHERE damage_type_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_combat_actions_resulting_condition_id "
        "ON interaction.combat_actions (resulting_condition_id) "
        "WHERE resulting_condition_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_combat_action_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_action_world  UUID;
            v_item_world    UUID;
        BEGIN
            IF NEW.item_instance_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT t.world_id INTO v_action_world
            FROM interaction.actions a
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
            JOIN campaign.timelines t ON t.timeline_id = i.timeline_id
            WHERE a.action_id = NEW.action_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            IF v_item_world IS DISTINCT FROM v_action_world THEN
                RAISE EXCEPTION
                    'Combat action % belongs to world %, but item_instance_id % belongs to '
                    'world %',
                    NEW.combat_action_id, v_action_world, NEW.item_instance_id, v_item_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_combat_action_world() IS
        'Same-world guard for interaction.combat_actions.item_instance_id '
        '(conventions §9.5). spell_id is not world-scoped (ruleset content) '
        'and target_id''s world agreement is already enforced by '
        'interaction.enforce_target_world() (revision 061), so neither '
        'needs a second check here.';
    """)
    op.execute("""
        CREATE TRIGGER tr_combat_actions_enforce_world
        BEFORE INSERT OR UPDATE ON interaction.combat_actions
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_combat_action_world();
    """)

    # ==========================================================================
    # 5. narrative.encounter_turns
    # ==========================================================================
    op.execute("""
        CREATE TABLE narrative.encounter_turns (
            encounter_turn_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            encounter_round_id    UUID NOT NULL
                                 REFERENCES narrative.encounter_rounds(encounter_round_id)
                                 ON DELETE CASCADE,
            participant_id           UUID NOT NULL
                                 REFERENCES narrative.encounter_participants
                                     (encounter_participant_id)
                                 ON DELETE CASCADE,
            turn_order                 core.nonnegative_integer NOT NULL,
            combat_action_id             UUID
                                 REFERENCES interaction.combat_actions(combat_action_id)
                                 ON DELETE SET NULL,
            notes                         TEXT,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_encounter_turns_round_participant UNIQUE (
                encounter_round_id, participant_id
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.encounter_turns IS
        'One participant''s turn within an encounter round '
        '(docs/architecture/DATABASE_MODEL.md §13) — initiative order used, '
        'and the combat_action (if any) that resolved it. Marks whose '
        'initiative slot is active, not a full log of every action taken — '
        'see this revision''s docstring on why a character with multiple '
        'attacks does not get multiple turn rows. Append-only.';
    """)
    op.execute(
        "CREATE INDEX ix_encounter_turns_encounter_round_id "
        "ON narrative.encounter_turns (encounter_round_id);"
    )
    op.execute(
        "CREATE INDEX ix_encounter_turns_participant_id "
        "ON narrative.encounter_turns (participant_id);"
    )
    op.execute(
        "CREATE INDEX ix_encounter_turns_combat_action_id "
        "ON narrative.encounter_turns (combat_action_id) WHERE combat_action_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_encounter_turn_participant_round()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_round_encounter        UUID;
            v_participant_encounter  UUID;
        BEGIN
            SELECT encounter_id INTO v_round_encounter
            FROM narrative.encounter_rounds WHERE encounter_round_id = NEW.encounter_round_id;

            SELECT encounter_id INTO v_participant_encounter
            FROM narrative.encounter_participants
            WHERE encounter_participant_id = NEW.participant_id;

            IF v_participant_encounter IS DISTINCT FROM v_round_encounter THEN
                RAISE EXCEPTION
                    'Encounter turn %''s round belongs to encounter %, but participant % '
                    'belongs to encounter %',
                    NEW.encounter_turn_id, v_round_encounter, NEW.participant_id,
                    v_participant_encounter
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_encounter_turn_participant_round() IS
        'Keeps a turn''s participant scoped to the same encounter as its round.';
    """)
    op.execute("""
        CREATE TRIGGER tr_encounter_turns_enforce_participant_round
        BEFORE INSERT OR UPDATE ON narrative.encounter_turns
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_encounter_turn_participant_round();
    """)

    # ==========================================================================
    # 6. narrative.event_types: combat_damage_dealt
    # ==========================================================================
    op.execute("""
        INSERT INTO narrative.event_types (code, display_name, sort_order)
        VALUES ('combat_damage_dealt', 'Combat Damage Dealt', 112)
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 7. narrative.event_causes.cause_encounter_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE narrative.event_causes
        ADD COLUMN cause_encounter_id UUID
            REFERENCES narrative.encounters(encounter_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_causes.cause_encounter_id IS
        'The encounter that caused this event, e.g. a character killed '
        'mid-combat — a fourth alternative alongside cause_event_id/'
        'cause_interaction_id/cause_description (conventions §9.4), closing '
        'this revision''s own forward reference.';
    """)
    op.execute(
        "CREATE INDEX ix_event_causes_cause_encounter_id "
        "ON narrative.event_causes (cause_encounter_id) WHERE cause_encounter_id IS NOT NULL;"
    )

    op.execute("ALTER TABLE narrative.event_causes DROP CONSTRAINT ck_event_causes_has_cause;")
    op.execute("""
        ALTER TABLE narrative.event_causes
        ADD CONSTRAINT ck_event_causes_has_cause CHECK (
            num_nonnulls(
                cause_event_id, cause_interaction_id, cause_encounter_id, cause_description
            ) = 1
        );
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_cause_encounter_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_timeline      UUID;
            v_encounter_timeline  UUID;
        BEGIN
            IF NEW.cause_encounter_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT timeline_id INTO v_event_timeline
            FROM narrative.events WHERE event_id = NEW.event_id;

            SELECT timeline_id INTO v_encounter_timeline
            FROM narrative.encounters WHERE encounter_id = NEW.cause_encounter_id;

            IF v_encounter_timeline IS DISTINCT FROM v_event_timeline THEN
                RAISE EXCEPTION
                    'Event cause %''s encounter % belongs to timeline %, but event % '
                    'belongs to timeline %',
                    NEW.event_cause_id, NEW.cause_encounter_id, v_encounter_timeline,
                    NEW.event_id, v_event_timeline
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_cause_encounter_world() IS
        'Guards narrative.event_causes: cause_encounter_id, when set, must '
        'belong to the same timeline as the event it caused (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_causes_enforce_encounter_world
        BEFORE INSERT OR UPDATE ON narrative.event_causes
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_cause_encounter_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_event_causes_enforce_encounter_world ON narrative.event_causes;"
    )
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_cause_encounter_world();")

    op.execute(
        "ALTER TABLE narrative.event_causes DROP CONSTRAINT IF EXISTS ck_event_causes_has_cause;"
    )
    op.execute("""
        ALTER TABLE narrative.event_causes
        ADD CONSTRAINT ck_event_causes_has_cause CHECK (
            num_nonnulls(cause_event_id, cause_interaction_id, cause_description) = 1
        );
    """)
    op.execute("ALTER TABLE narrative.event_causes DROP COLUMN IF EXISTS cause_encounter_id;")

    op.execute("DELETE FROM narrative.event_types WHERE code = 'combat_damage_dealt';")

    op.execute("DROP TABLE IF EXISTS narrative.encounter_turns;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_encounter_turn_participant_round();")

    op.execute("DROP TABLE IF EXISTS interaction.combat_actions;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_combat_action_world();")

    op.execute("DROP TABLE IF EXISTS narrative.encounter_rounds;")

    op.execute("DROP TABLE IF EXISTS narrative.encounter_participants;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_encounter_participant_world();")

    op.execute("DROP TABLE IF EXISTS narrative.encounters;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_encounter_world();")
