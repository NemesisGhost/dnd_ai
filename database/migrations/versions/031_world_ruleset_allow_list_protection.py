"""Complete world-ruleset allow-list protection

Revision ID: 031_world_ruleset_full_protect
Revises: 030_parent_scope_immutable
Create Date: 2026-08-02 22:00:00.000000

Purpose:
    Corrective revision (PHASE4_REMAINING_ISSUES.md §1). Revision 027's
    rules.enforce_world_ruleset_still_in_use() rejected removing or
    repointing a world_rulesets association while it was a world's default
    or a campaign was pinned to one of its versions, but left four more
    revision-029 dependency categories unprotected: a character's species, a
    character build's ruleset version, an applied character condition, and a
    tracked character resource can all reference content from a ruleset a
    world still allows only because that world_rulesets row exists — nothing
    stopped removing (or repointing) the row itself out from under them.

    The function also unconditionally `RETURN OLD`, which is correct for
    DELETE but silently discards the row's new values on a permitted UPDATE
    (a BEFORE UPDATE trigger's return value becomes the row actually
    written) — a repoint that passed every check would still not take
    effect. Fixed to `RETURN NEW` on UPDATE, `RETURN OLD` on DELETE.

Forward migration:
    - rules.enforce_world_ruleset_still_in_use() replaced: adds the species/
      build/condition/resource checks and fixes the DELETE-vs-UPDATE return
      value. The trigger itself (revision 027) is unchanged.

Rollback:
    Supported. Restores revision 027's original function body verbatim.

Data implications:
    Creates no rows. Existing world_rulesets associations are unaffected;
    this only changes what a future DELETE/UPDATE against the table checks.

Locking considerations:
    CREATE OR REPLACE FUNCTION does not lock or rewrite rules.world_rulesets.

See: PHASE4_REMAINING_ISSUES.md §1
     database/migrations/versions/027_world_ruleset_single_default.py
     database/migrations/versions/029_character_state_corrections.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "031_world_ruleset_full_protect"
down_revision = "030_parent_scope_immutable"
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
            v_is_default     BOOLEAN;
            v_campaign_uses  BOOLEAN;
            v_species_uses   BOOLEAN;
            v_build_uses     BOOLEAN;
            v_condition_uses BOOLEAN;
            v_resource_uses  BOOLEAN;
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
        'applied condition, or a tracked resource in that world still depends on it. '
        'Returns NEW on a permitted UPDATE and OLD on a permitted DELETE.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_world_ruleset_still_in_use()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_default    BOOLEAN;
            v_campaign_uses BOOLEAN;
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

            RETURN OLD;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_world_ruleset_still_in_use() IS
        'Rejects removing (or repointing) a world_rulesets association while the world''s '
        'default_ruleset_id or a campaign in that world still depends on it.';
    """)
