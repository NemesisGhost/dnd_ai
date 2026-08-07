"""Close the ruleset allow-list reverse guard for check requests and conditional routes

Revision ID: 068_ruleset_check_route_guard
Revises: 067_interaction_structural_lock
Create Date: 2026-08-05 19:30:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review correction pass). Both
    interaction.check_requests (revision 061) and world.area_connections'
    required_ability_id/required_skill_id (revision 064) validate their
    ability/skill choice against rules.ruleset_allowed_for_world() on
    INSERT/UPDATE, but rules.enforce_world_ruleset_still_in_use() — the
    reverse guard that blocks removing or repointing a rules.world_rulesets
    association while something still depends on it — never gained a usage
    clause for either. Revision 061's own docstring named this explicitly as
    "a known, non-blocking gap"; this revision closes it, following the same
    two-sided pattern every other ruleset-scoped category already has
    (species, character builds, applied conditions, tracked resources,
    character languages — revisions 027/031/037).

Forward migration:
    - CREATE OR REPLACE on rules.enforce_world_ruleset_still_in_use(): adds
      two more EXISTS checks alongside the existing ones —
      interaction.check_requests (ability_id or skill_id, reached via
      action_id -> interaction.actions.interaction_id -> interaction.
      interactions.timeline_id -> campaign.timelines.world_id) and
      world.area_connections (required_ability_id or required_skill_id,
      reached via from_dungeon_area_id -> core.entities.world_id, the same
      join world.enforce_area_connection_check_requirement_ruleset() and
      narrative.enforce_event_effect_target_world() already use for
      area-connection-rooted world lookups).

Rollback:
    Supported. Reverts to the revision-037 version of the function (without
    either of these two checks), matching the same downgrade shape revision
    037 itself used to revert to revision 031's version.

Data implications:
    None — no existing rules.world_rulesets row is deleted or repointed by
    this migration.

Locking considerations:
    One CREATE OR REPLACE FUNCTION. No table rewrite; the function is
    already attached to rules.world_rulesets by existing triggers from
    revision 027.

See: docs/DATABASE_CONVENTIONS.md §21 (ruleset scoping)
     database/migrations/versions/037_character_language_ruleset_allowed.py
     (the most recent prior two-sided addition, same pattern)
     database/migrations/versions/061_interaction_domain.py (the
     "known, non-blocking gap" this revision closes)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "068_ruleset_check_route_guard"
down_revision = "067_interaction_structural_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_world_ruleset_still_in_use()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_default             BOOLEAN;
            v_campaign_uses          BOOLEAN;
            v_species_uses           BOOLEAN;
            v_build_uses              BOOLEAN;
            v_condition_uses          BOOLEAN;
            v_resource_uses           BOOLEAN;
            v_language_uses           BOOLEAN;
            v_check_request_uses      BOOLEAN;
            v_area_connection_uses    BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM core.worlds
                WHERE world_id = OLD.world_id AND default_ruleset_id = OLD.ruleset_id
            ) INTO v_is_default;

            IF v_is_default THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: it is '
                    'that world''s default (change the world''s default_ruleset_id first)',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM campaign.campaigns c
                JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = c.ruleset_version_id
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_campaign_uses;

            IF v_campaign_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one campaign in that world is still pinned to a version of it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM character.characters ch
                JOIN core.entities e ON e.entity_id = ch.character_id
                JOIN rules.species sp ON sp.species_id = ch.species_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = sp.ruleset_version_id
                WHERE e.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_species_uses;

            IF v_species_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one character in that world has a species from it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM character.character_builds cb
                JOIN core.entities e ON e.entity_id = cb.character_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = cb.ruleset_version_id
                WHERE e.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_build_uses;

            IF v_build_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one character build in that world is pinned to a version of it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM campaign.character_conditions cc
                JOIN campaign.timelines t ON t.timeline_id = cc.timeline_id
                JOIN rules.conditions co ON co.condition_id = cc.condition_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = co.ruleset_version_id
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_condition_uses;

            IF v_condition_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one applied character condition in that world uses it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM campaign.character_resources cr
                JOIN campaign.timelines t ON t.timeline_id = cr.timeline_id
                JOIN rules.resource_definitions rd
                    ON rd.resource_definition_id = cr.resource_definition_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = rd.ruleset_version_id
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_resource_uses;

            IF v_resource_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one tracked character resource in that world uses it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM character.character_languages cl
                JOIN core.entities e ON e.entity_id = cl.character_id
                JOIN rules.languages la ON la.language_id = cl.language_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = la.ruleset_version_id
                WHERE e.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_language_uses;

            IF v_language_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one character in that world has a language from it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM interaction.check_requests creq
                JOIN interaction.actions a ON a.action_id = creq.action_id
                JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
                JOIN campaign.timelines t ON t.timeline_id = i.timeline_id
                LEFT JOIN rules.abilities ab ON ab.ability_id = creq.ability_id
                LEFT JOIN rules.skills sk ON sk.skill_id = creq.skill_id
                JOIN rules.ruleset_versions rv
                    ON rv.ruleset_version_id = COALESCE(ab.ruleset_version_id, sk.ruleset_version_id)
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_check_request_uses;

            IF v_check_request_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one interaction check request in that world requires an '
                    'ability or skill from it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM world.area_connections ac
                JOIN core.entities e ON e.entity_id = ac.from_dungeon_area_id
                LEFT JOIN rules.abilities ab ON ab.ability_id = ac.required_ability_id
                LEFT JOIN rules.skills sk ON sk.skill_id = ac.required_skill_id
                JOIN rules.ruleset_versions rv
                    ON rv.ruleset_version_id = COALESCE(ab.ruleset_version_id, sk.ruleset_version_id)
                WHERE e.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_area_connection_uses;

            IF v_area_connection_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one conditional route in that world requires an ability or '
                    'skill from it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_world_ruleset_still_in_use() IS
        'Rejects removing (or repointing) a world_rulesets association while the world''s '
        'default_ruleset_id, a campaign, a character species, a character build, an '
        'applied condition, a tracked resource, a character language, an interaction '
        'check request, or a conditional route''s check requirement in that world still '
        'depends on it. Returns NEW on a permitted UPDATE and OLD on a permitted DELETE.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_world_ruleset_still_in_use()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_default     BOOLEAN;
            v_campaign_uses  BOOLEAN;
            v_species_uses   BOOLEAN;
            v_build_uses     BOOLEAN;
            v_condition_uses BOOLEAN;
            v_resource_uses  BOOLEAN;
            v_language_uses  BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM core.worlds
                WHERE world_id = OLD.world_id AND default_ruleset_id = OLD.ruleset_id
            ) INTO v_is_default;

            IF v_is_default THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: it is '
                    'that world''s default (change the world''s default_ruleset_id first)',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM campaign.campaigns c
                JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = c.ruleset_version_id
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_campaign_uses;

            IF v_campaign_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one campaign in that world is still pinned to a version of it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM character.characters ch
                JOIN core.entities e ON e.entity_id = ch.character_id
                JOIN rules.species sp ON sp.species_id = ch.species_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = sp.ruleset_version_id
                WHERE e.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_species_uses;

            IF v_species_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one character in that world has a species from it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM character.character_builds cb
                JOIN core.entities e ON e.entity_id = cb.character_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = cb.ruleset_version_id
                WHERE e.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_build_uses;

            IF v_build_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one character build in that world is pinned to a version of it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM campaign.character_conditions cc
                JOIN campaign.timelines t ON t.timeline_id = cc.timeline_id
                JOIN rules.conditions co ON co.condition_id = cc.condition_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = co.ruleset_version_id
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_condition_uses;

            IF v_condition_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one applied character condition in that world uses it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM campaign.character_resources cr
                JOIN campaign.timelines t ON t.timeline_id = cr.timeline_id
                JOIN rules.resource_definitions rd
                    ON rd.resource_definition_id = cr.resource_definition_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = rd.ruleset_version_id
                WHERE t.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_resource_uses;

            IF v_resource_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one tracked character resource in that world uses it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM character.character_languages cl
                JOIN core.entities e ON e.entity_id = cl.character_id
                JOIN rules.languages la ON la.language_id = cl.language_id
                JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = la.ruleset_version_id
                WHERE e.world_id = OLD.world_id AND rv.ruleset_id = OLD.ruleset_id
            ) INTO v_language_uses;

            IF v_language_uses THEN
                RAISE EXCEPTION
                    'Ruleset % cannot be removed from world %''s allowed rulesets: at '
                    'least one character in that world has a language from it',
                    OLD.ruleset_id, OLD.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_world_ruleset_still_in_use() IS
        'Rejects removing (or repointing) a world_rulesets association while the world''s '
        'default_ruleset_id, a campaign, a character species, a character build, an '
        'applied condition, a tracked resource, or a character language in that world '
        'still depends on it. Returns NEW on a permitted UPDATE and OLD on a permitted '
        'DELETE.';
    """)
