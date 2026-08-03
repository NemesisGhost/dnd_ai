"""Enforce the world's ruleset allow-list for character languages

Revision ID: 037_character_language_ruleset
Revises: 036_remaining_rules_immutable
Create Date: 2026-08-02 23:30:00.000000

Purpose:
    Corrective revision (PHASE4_REMAINING_ISSUES.md §1, second post-closeout
    review). Revision 029 checked every other rule-content association a
    character or its timeline state can hold (species, build ruleset
    version, applied condition, tracked resource) against the character's
    world-level `rules.world_rulesets` allow-list, and revision 031 taught
    the reverse guard (`rules.enforce_world_ruleset_still_in_use()`) to
    reject removing or repointing an allow-list association those categories
    still depend on. `character.character_languages` was left out of both:
    a character could acquire a language from a ruleset family its world
    never allowed, and an allow-list association could be removed or
    repointed out from under a character still using a language from it.

Forward migration:
    - `character.enforce_character_language_ruleset_allowed()`: a new
      `BEFORE INSERT OR UPDATE` trigger on `character.character_languages`,
      shaped exactly like revision 029's
      `character.enforce_character_species_ruleset_allowed()` — resolve the
      character's world and the language's ruleset version, then call the
      shared `rules.ruleset_allowed_for_world()` helper. That helper already
      takes the concurrency-safe `FOR SHARE` lock on the specific
      `rules.world_rulesets` row (revision 035), so this new check inherits
      the same race protection as every other category with no new locking
      code of its own.
    - `rules.enforce_world_ruleset_still_in_use()` (revision 031, unchanged
      since): adds a `character.character_languages` usage check alongside
      the existing five, using the same shape (join through
      `core.entities`/`rules.languages`/`rules.ruleset_versions` to the
      candidate `(world_id, ruleset_id)` row) and the same
      `RAISE EXCEPTION ... USING ERRCODE = 'integrity_constraint_violation'`
      pattern. This closes the DELETE/UPDATE side of the race for languages
      exactly as revision 031 did for the other five categories, and — because
      it is the same trigger revision 035 already made concurrency-safe by
      having every check on this side rely on the row lock the DELETE/UPDATE
      itself takes — needs no further locking changes either.

    One character may still know languages from multiple ruleset families,
    as long as every family in play is allowed by the world (unchanged from
    revision 019's original "pure association" design) — this only rejects a
    family the world does not allow at all.

    Also updates `character.character_languages`'s table comment to describe
    the new enforcement (`tables.py`'s SQLAlchemy metadata comment was
    updated to match) — `alembic check` compares table comments, so leaving
    the live comment at its revision-019 text would show up as undeclared
    drift the next time autogenerate runs.

Rollback:
    Supported. Drops the new trigger and function, restores
    `rules.enforce_world_ruleset_still_in_use()` to revision 031's exact
    body (the six-check version, without the languages check added here),
    and restores the table comment to its revision-019 text.

Data implications:
    Creates no rows. No `character.character_languages` rows exist outside
    test fixtures to re-validate.

Locking considerations:
    Adding a trigger function does not lock or rewrite
    `character.character_languages`. The `CREATE OR REPLACE FUNCTION` for
    `rules.enforce_world_ruleset_still_in_use()` does not lock or rewrite
    `rules.world_rulesets` either — only a future DELETE/UPDATE against it
    will evaluate the new check, at which point it already holds the
    exclusive row lock that check needs.

See: PHASE4_REMAINING_ISSUES.md §1
     database/migrations/versions/019_character_shared_data.py
     database/migrations/versions/029_character_state_corrections.py
     database/migrations/versions/031_world_ruleset_allow_list_protection.py
     database/migrations/versions/035_world_ruleset_concurrency_safety.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "037_character_language_ruleset"
down_revision = "036_remaining_rules_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. A character's languages must be drawn from a ruleset its world allows
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_character_language_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world            UUID;
            v_language_version UUID;
        BEGIN
            SELECT world_id INTO v_world FROM core.entities WHERE entity_id = NEW.character_id;

            SELECT ruleset_version_id INTO v_language_version
            FROM rules.languages WHERE language_id = NEW.language_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_language_version) THEN
                RAISE EXCEPTION
                    'Language %''s ruleset is not allowed for world % (character %''s world)',
                    NEW.language_id, v_world, NEW.character_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_character_language_ruleset_allowed() IS
        'Keeps a character''s known languages drawn from ruleset families its own '
        'world allows. Relies on rules.ruleset_allowed_for_world()''s FOR SHARE lock '
        '(revision 035) for concurrency safety against a concurrent allow-list removal '
        'or repoint.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_languages_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON character.character_languages
        FOR EACH ROW EXECUTE FUNCTION character.enforce_character_language_ruleset_allowed();
    """)
    op.execute("""
        COMMENT ON TABLE character.character_languages IS
        'Languages a character knows. Pure association — a character may know '
        'languages from more than one ruleset''s content, as long as every ruleset '
        'family in play is one the character''s world allows (rules.world_rulesets); '
        'enforced by trigger (revision 037), same as species/build/condition/resource.';
    """)

    # ==========================================================================
    # 2. Removing/repointing an allow-list association must respect languages too
    # ==========================================================================
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

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_languages_enforce_ruleset_allowed "
        "ON character.character_languages;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_character_language_ruleset_allowed();")
    op.execute("""
        COMMENT ON TABLE character.character_languages IS
        'Languages a character knows. Pure association — a character may know '
        'languages from more than one ruleset''s content.';
    """)
