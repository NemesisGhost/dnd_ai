"""Phase 7 correction pass: party knowledge, scope-guard extensions, quest
objective metadata, missing knowledge type codes, knowledge_versions
immutability, and an advance_objective() concurrency fix

Revision ID: 074_phase7_correction_pass
Revises: 073_quest_and_knowledge_domain
Create Date: 2026-08-07 12:00:00.000000

Purpose:
    A review of PR #17 (Phase 7) found six production defects revision 073's
    own verification loop missed:

    1. docs/PLAN.md §15 and docs/DOMAIN_MODEL.md §15.4 name campaign.
       party_knowledge as the party's own current effective belief, distinct
       from knowledge.party_discoveries (an acquisition record with no
       belief/confidence/interpretation columns at all). Revision 073 built
       everything else the Phase 5/Phase 7 knowledge-domain boundary named
       but not this table, and the exit-criterion test written against it
       exercised an unrelated NPC's entity_knowledge row instead of party
       belief. This revision builds campaign.party_knowledge.
    2. narrative.enforce_event_effect_target_world() (revision 057) and
       interaction.enforce_consequence_world() (revision 061) were not
       extended when revision 073 added target_quest_objective_id/
       resulting_quest_objective_state_id — both columns accepted a
       cross-world/cross-timeline reference silently.
    3. knowledge.enforce_information_transfer_world() (revision 073) only
       checked world agreement, not timeline agreement, for
       source_entity_knowledge_id/caused_by_interaction_id/caused_by_event_id,
       and never validated occurred_at_world_time_id at all.
       knowledge.enforce_public_knowledge_world() (revision 073) never
       validated known_since_world_time_id.
    4. src/dnd_ai/commands/quests.py's advance_objective() locked the
       campaign.objective_state row only when one already existed
       (_lock_objective_state's SELECT ... FOR UPDATE has nothing to lock
       before the first row is inserted) — two concurrent first
       transitions for the same (timeline, objective[, party]) scope could
       both observe "no state" and race into ux_objective_state_timeline_
       objective_no_party, the same class of gap Phase 6's correction pass
       (revision 067) found and fixed in resolve_check().
    5. docs/PLAN.md §14.1 names completion-rule metadata and visibility
       policies as two things quest objectives support, separate from
       completion_mode (automatic vs. GM-confirmed) and requirement_level
       (required/optional/hidden) — revision 073 built only the latter two.
       docs/PLAN.md §15.1 names ten required knowledge_types seed codes;
       revision 073 seeded six of them plus the pre-existing claim, missing
       fact/prophecy/misconception/doctrine.
    6. knowledge.knowledge_versions is documented as append-only (revision
       073's own table comment) but nothing enforced it — a version already
       cited by knowledge.entity_knowledge.knowledge_version_id could be
       rewritten or reparented to a different knowledge_item_id, silently
       invalidating enforce_entity_knowledge_version_item()'s invariant
       after the fact rather than at the time it would matter.

Forward migration:
    - campaign.party_knowledge, with campaign.enforce_party_knowledge_world()
      and campaign.enforce_party_knowledge_version_item(); reuses the
      existing campaign.enforce_state_event_timeline() (revision 066)
      unchanged for its last_event_id column.
    - narrative.enforce_event_effect_target_world(): CREATE OR REPLACE
      adding a target_quest_objective_id branch.
    - interaction.enforce_consequence_world(): CREATE OR REPLACE adding a
      resulting_quest_objective_state_id timeline check.
    - knowledge.enforce_information_transfer_world(): CREATE OR REPLACE
      adding source/caused-by-interaction/caused-by-event timeline checks
      and an occurred_at_world_time_id world check.
    - knowledge.enforce_public_knowledge_world(): CREATE OR REPLACE adding
      a known_since_world_time_id world check.
    - narrative.quest_objectives.completion_rule (JSONB, nullable) and
      .visibility_policy (TEXT, NOT NULL DEFAULT 'visible').
    - knowledge.knowledge_types: four missing seed rows (fact, prophecy,
      misconception, doctrine) — docs/PLAN.md §15.1's exact list.
    - knowledge.enforce_knowledge_version_immutable(): BEFORE UPDATE OR
      DELETE trigger on knowledge.knowledge_versions rejecting both
      unconditionally.
    - src/dnd_ai/commands/quests.py: advance_objective() now locks the
      parent narrative.quest_objectives row (always exists) before
      touching campaign.objective_state at all.

Rollback:
    Supported. Restores narrative.enforce_event_effect_target_world(),
    interaction.enforce_consequence_world(), knowledge.
    enforce_information_transfer_world(), and knowledge.
    enforce_public_knowledge_world() to their exact pre-this-revision
    bodies (057/061 originals for the first two, 073 originals for the
    last two) — none of the restored bodies reference any column this
    revision added, so a later downgrade of 073 itself (which does remove
    target_quest_objective_id/resulting_quest_objective_state_id) leaves no
    dangling reference. Drops the knowledge_versions immutability trigger/
    function, the four new knowledge_types rows, the two new quest_
    objectives columns, and campaign.party_knowledge with its two
    functions.

Data implications:
    Seeds four lookup rows. No existing narrative.quest_objectives row is
    affected by the two new columns (JSONB defaults to NULL,
    visibility_policy defaults to 'visible'). No existing knowledge_versions
    row is affected by the new immutability trigger — it only rejects
    UPDATE/DELETE from this point forward.

Locking considerations:
    Two ADD COLUMN statements against narrative.quest_objectives — both
    metadata-only (no default requiring a rewrite: JSONB NULL default,
    TEXT constant default). Every other statement creates a new, empty
    object or replaces a function body (CREATE OR REPLACE takes no lock
    beyond the brief one needed to swap the function definition).

See: docs/PLAN.md §14.1 (quest objectives), §15.1 (knowledge types), §15.4
     (party knowledge)
     docs/DOMAIN_MODEL.md §15.4 (party knowledge)
     docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency), §13.4
     (causality)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "074_phase7_correction_pass"
down_revision = "073_quest_and_knowledge_domain"
branch_labels = None
depends_on = None

NEW_KNOWLEDGE_TYPES = [
    ("fact", "Fact"),
    ("prophecy", "Prophecy"),
    ("misconception", "Misconception"),
    ("doctrine", "Doctrine"),
]


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. campaign.party_knowledge
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.party_knowledge (
            party_knowledge_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id           UUID NOT NULL
                                  REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            party_id               UUID NOT NULL
                                  REFERENCES campaign.parties(party_id) ON DELETE CASCADE,
            knowledge_item_id        UUID NOT NULL
                                  REFERENCES knowledge.knowledge_items(knowledge_item_id)
                                  ON DELETE CASCADE,
            knowledge_version_id       UUID
                                  REFERENCES knowledge.knowledge_versions(knowledge_version_id)
                                  ON DELETE SET NULL,
            awareness_level               TEXT NOT NULL DEFAULT 'aware',
            confidence                      core.percentage_0_100,
            interpretation                    TEXT,
            willing_to_share                    BOOLEAN NOT NULL DEFAULT true,
            last_event_id                         UUID
                                  REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_party_knowledge_awareness_level CHECK (
                awareness_level IN ('aware', 'rumored', 'suspected')
            ),
            CONSTRAINT ux_party_knowledge_current
                UNIQUE (timeline_id, party_id, knowledge_item_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.party_knowledge IS
        'The party''s own current effective belief about a knowledge item on a '
        'timeline (docs/DOMAIN_MODEL.md §15.4, docs/PLAN.md §15) — distinct from '
        'knowledge.party_discoveries, which records only when/how the party '
        'acquired the item and carries no belief/confidence/interpretation of its '
        'own. Does not imply every party member shares this understanding unless '
        'the application explicitly promotes it to individual '
        'knowledge.entity_knowledge rows. A false belief is valid game data and is '
        'never overwritten merely because the canonical truth is known elsewhere — '
        'same rule as knowledge.entity_knowledge (revision 041). One row per '
        '(timeline, party, knowledge item).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_knowledge.knowledge_version_id IS
        'The specific (possibly distorted) version the party heard, when it was a '
        'distorted retelling rather than the canonical statement — same role as '
        'knowledge.entity_knowledge.knowledge_version_id.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_knowledge_set_updated_at
        BEFORE UPDATE ON campaign.party_knowledge
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_party_knowledge_timeline_id ON campaign.party_knowledge (timeline_id);"
    )
    op.execute("CREATE INDEX ix_party_knowledge_party_id ON campaign.party_knowledge (party_id);")
    op.execute(
        "CREATE INDEX ix_party_knowledge_knowledge_item_id "
        "ON campaign.party_knowledge (knowledge_item_id);"
    )
    op.execute(
        "CREATE INDEX ix_party_knowledge_knowledge_version_id "
        "ON campaign.party_knowledge (knowledge_version_id) "
        "WHERE knowledge_version_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_party_knowledge_last_event_id ON campaign.party_knowledge (last_event_id) "
        "WHERE last_event_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_party_knowledge_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_party_world     UUID;
            v_item_world      UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_party_world
            FROM campaign.parties WHERE party_id = NEW.party_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            IF v_party_world IS DISTINCT FROM v_timeline_world
               OR v_item_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Party knowledge mixes worlds: timeline % (world %), party % '
                    '(world %), knowledge item % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.party_id, v_party_world,
                    NEW.knowledge_item_id, v_item_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_party_knowledge_world() IS
        'World-agreement guard for campaign.party_knowledge: timeline, party, and '
        'knowledge item must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_knowledge_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.party_knowledge
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_party_knowledge_world();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_party_knowledge_version_item()
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
                    'Party knowledge row''s knowledge_version_id % belongs to knowledge item '
                    '%, but the row itself cites knowledge item %',
                    NEW.knowledge_version_id, v_version_item, NEW.knowledge_item_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_party_knowledge_version_item() IS
        'Guards campaign.party_knowledge: knowledge_version_id, when set, must '
        'belong to the same knowledge_item_id the row itself cites — same '
        'invariant as knowledge.enforce_entity_knowledge_version_item().';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_knowledge_enforce_version_item
        BEFORE INSERT OR UPDATE ON campaign.party_knowledge
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_party_knowledge_version_item();
    """)
    op.execute("""
        CREATE TRIGGER tr_party_knowledge_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.party_knowledge
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)

    # ==========================================================================
    # 2. narrative.enforce_event_effect_target_world(): add target_quest_objective_id
    # ==========================================================================
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

    # ==========================================================================
    # 3. interaction.enforce_consequence_world(): add resulting_quest_objective_state_id
    # ==========================================================================
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

    # ==========================================================================
    # 4. knowledge.enforce_information_transfer_world(): add timeline/world-time checks
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_information_transfer_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world        UUID;
            v_source_world          UUID;
            v_source_timeline       UUID;
            v_recipient_world       UUID;
            v_interaction_timeline  UUID;
            v_event_timeline        UUID;
            v_world_time_world      UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT e.world_id, ek.timeline_id INTO v_source_world, v_source_timeline
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

            IF v_source_timeline IS DISTINCT FROM NEW.timeline_id THEN
                RAISE EXCEPTION
                    'Information transfer % source_entity_knowledge_id % belongs to timeline '
                    '%, but the transfer belongs to timeline %',
                    NEW.information_transfer_id, NEW.source_entity_knowledge_id, v_source_timeline,
                    NEW.timeline_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.caused_by_interaction_id IS NOT NULL THEN
                SELECT timeline_id INTO v_interaction_timeline
                FROM interaction.interactions WHERE interaction_id = NEW.caused_by_interaction_id;

                IF v_interaction_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Information transfer % caused_by_interaction_id % belongs to timeline '
                        '%, but the transfer belongs to timeline %',
                        NEW.information_transfer_id, NEW.caused_by_interaction_id,
                        v_interaction_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.caused_by_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_event_timeline
                FROM narrative.events WHERE event_id = NEW.caused_by_event_id;

                IF v_event_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Information transfer % caused_by_event_id % belongs to timeline %, '
                        'but the transfer belongs to timeline %',
                        NEW.information_transfer_id, NEW.caused_by_event_id, v_event_timeline,
                        NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.occurred_at_world_time_id IS NOT NULL THEN
                SELECT world_id INTO v_world_time_world
                FROM core.world_times WHERE world_time_id = NEW.occurred_at_world_time_id;

                IF v_world_time_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Information transfer % occurred_at_world_time_id % belongs to world '
                        '%, but timeline % belongs to world %',
                        NEW.information_transfer_id, NEW.occurred_at_world_time_id,
                        v_world_time_world, NEW.timeline_id, v_timeline_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_information_transfer_world() IS
        'World- and timeline-agreement guard for knowledge.information_transfers: '
        'timeline/source/recipient must share a world; source_entity_knowledge_id, '
        'caused_by_interaction_id, and caused_by_event_id (each when applicable) '
        'must share the transfer''s own timeline; occurred_at_world_time_id (when '
        'set) must share the timeline''s world. Extended by revision 074 — the '
        'original only checked world agreement.';
    """)

    # ==========================================================================
    # 5. knowledge.enforce_public_knowledge_world(): add known_since_world_time_id
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_public_knowledge_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world      UUID;
            v_item_world          UUID;
            v_location_world      UUID;
            v_known_since_world   UUID;
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

            IF NEW.known_since_world_time_id IS NOT NULL THEN
                SELECT world_id INTO v_known_since_world
                FROM core.world_times WHERE world_time_id = NEW.known_since_world_time_id;

                IF v_known_since_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Public knowledge % known_since_world_time_id % belongs to world %, '
                        'but timeline % belongs to world %',
                        NEW.public_knowledge_id, NEW.known_since_world_time_id, v_known_since_world,
                        NEW.timeline_id, v_timeline_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_public_knowledge_world() IS
        'World-agreement guard for knowledge.public_knowledge: timeline, knowledge '
        'item, location, and known_since_world_time_id (when set) must all belong '
        'to the same world. Extended by revision 074 to cover '
        'known_since_world_time_id — the original left it unchecked.';
    """)

    # ==========================================================================
    # 6. narrative.quest_objectives: completion_rule + visibility_policy
    # ==========================================================================
    op.execute("""
        ALTER TABLE narrative.quest_objectives
        ADD COLUMN completion_rule JSONB,
        ADD COLUMN visibility_policy TEXT NOT NULL DEFAULT 'visible';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.quest_objectives.completion_rule IS
        'Structured completion-rule metadata (docs/PLAN.md §14.1) — e.g. '
        '{"rule": "quantity_threshold", "threshold": 3} — distinct from '
        'completion_mode (automatic vs. GM-confirmed, i.e. who decides) and from '
        'quantity_required (a single scalar). NULL when the objective''s '
        'completion condition needs no structured metadata beyond its type and '
        'target.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.quest_objectives.visibility_policy IS
        'Whether and when this objective is shown to players (docs/PLAN.md §14.1) '
        '— distinct from requirement_level=''hidden'' (whether the objective is '
        'mandatory for quest completion, not whether players can see it). An '
        'inferred, illustrative vocabulary — docs/PLAN.md does not enumerate '
        'policy values, only the concept.';
    """)
    op.execute("""
        ALTER TABLE narrative.quest_objectives
        ADD CONSTRAINT ck_quest_objectives_visibility_policy CHECK (
            visibility_policy IN (
                'visible', 'hidden_until_active', 'hidden_until_discovered', 'gm_only'
            )
        );
    """)

    # ==========================================================================
    # 7. knowledge.knowledge_types: missing required seed codes
    # ==========================================================================
    for sort_order, (code, display_name) in enumerate(NEW_KNOWLEDGE_TYPES, start=100):
        op.execute(f"""
            INSERT INTO knowledge.knowledge_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 8. knowledge.knowledge_versions: append-only enforcement
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_knowledge_version_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'knowledge.knowledge_versions is append-only (conventions §10.3) — % is '
                'not permitted on knowledge_version_id %; a distorted retelling is a new '
                'version, not an edit of an existing one',
                TG_OP, OLD.knowledge_version_id
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_knowledge_version_immutable() IS
        'Rejects any UPDATE or DELETE on knowledge.knowledge_versions unconditionally '
        '— prevents rewriting or reparenting (to a different knowledge_item_id) a '
        'version that knowledge.entity_knowledge.knowledge_version_id or '
        'campaign.party_knowledge.knowledge_version_id may already cite, which would '
        'otherwise invalidate enforce_entity_knowledge_version_item()''s/'
        'enforce_party_knowledge_version_item()''s invariant after the fact.';
    """)
    op.execute("""
        CREATE TRIGGER tr_knowledge_versions_immutable
        BEFORE UPDATE OR DELETE ON knowledge.knowledge_versions
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_knowledge_version_immutable();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_knowledge_versions_immutable ON knowledge.knowledge_versions;"
    )
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_knowledge_version_immutable();")

    op.execute(
        "DELETE FROM knowledge.knowledge_types WHERE code IN "
        "('fact', 'prophecy', 'misconception', 'doctrine');"
    )

    op.execute("""
        ALTER TABLE narrative.quest_objectives
        DROP CONSTRAINT IF EXISTS ck_quest_objectives_visibility_policy,
        DROP COLUMN IF EXISTS visibility_policy,
        DROP COLUMN IF EXISTS completion_rule;
    """)

    # Restore knowledge.enforce_public_knowledge_world() to its revision-073 body.
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

    # Restore knowledge.enforce_information_transfer_world() to its revision-073 body.
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

    # Restore interaction.enforce_consequence_world() to its revision-061 body.
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

    # Restore narrative.enforce_event_effect_target_world() to its revision-057 body.
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

    op.execute(
        "DROP TRIGGER IF EXISTS tr_party_knowledge_enforce_event_timeline "
        "ON campaign.party_knowledge;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS tr_party_knowledge_enforce_version_item ON campaign.party_knowledge;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_party_knowledge_version_item();")
    op.execute(
        "DROP TRIGGER IF EXISTS tr_party_knowledge_enforce_world ON campaign.party_knowledge;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_party_knowledge_world();")
    op.execute("DROP TABLE IF EXISTS campaign.party_knowledge;")
