"""Timeline-specific active character builds

Revision ID: 028_build_timeline_state
Revises: 027_world_ruleset_default
Create Date: 2026-08-02 20:30:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review). character.character_builds
    .is_current (revision 020) was a single global flag per character —
    "the" build a sheet is assembled from by default — enforced by a partial
    unique index over character_id. That cannot represent a character who
    plays differently in two timelines at once (a common branch scenario:
    the same character re-leveled or re-optioned after a divergence), since
    both timelines would be forced to agree on which build is "current."

    Active-build selection moves to campaign.character_state, which is
    already the one-row-per-(timeline, character) current-state table
    (revision 021) — the natural home for "which build applies right now, on
    this timeline," alongside current HP and the rest of that table's
    current-state columns. character.character_builds keeps only its
    original job: a reusable, versioned mechanical snapshot pinned to a
    ruleset version. is_current and its partial unique index are dropped
    outright rather than redefined, since "the current build" is no longer a
    meaningful global concept once selection is timeline-scoped.

Forward migration:
    - campaign.character_state.character_build_id (nullable — a character
      may exist on a timeline with no build selected yet)
    - campaign.enforce_character_state_build_character(), a trigger keeping
      the selected build's character_id in agreement with the state row's
      character_id
    - Drop character.character_builds.is_current and
      ux_character_builds_one_current_per_character

Rollback:
    Supported. Restores is_current (defaulted false, since there is no
    longer a per-timeline value to fall back to) and its partial unique
    index; drops the new column and trigger.

Data implications:
    Creates no rows. campaign.character_state is empty outside test
    fixtures, which roll back.

Locking considerations:
    ADD COLUMN ... NULL is metadata-only.

See: docs/architecture/DATABASE_MODEL.md §7.4 (character builds), §17
     (typed timeline state)
     database/migrations/versions/020_character_builds.py
     database/migrations/versions/021_character_timeline_state.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "028_build_timeline_state"
down_revision = "027_world_ruleset_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("DROP INDEX IF EXISTS character.ux_character_builds_one_current_per_character;")
    op.execute("ALTER TABLE character.character_builds DROP COLUMN IF EXISTS is_current;")
    op.execute("""
        COMMENT ON TABLE character.character_builds IS
        'A versioned mechanical snapshot of a character, pinned to one ruleset version. '
        'Ability scores, class levels, proficiencies, features, and spellcasting all '
        'belong to a build, not directly to the character, so re-leveling or rebuilding '
        'does not erase the prior build''s history. Which build is active on a given '
        'timeline is timeline state (campaign.character_state.character_build_id), not a '
        'property of the build itself — a character may use different builds on '
        'different timelines after a branch.';
    """)

    op.execute("""
        ALTER TABLE campaign.character_state
        ADD COLUMN character_build_id UUID
        REFERENCES character.character_builds(character_build_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_state.character_build_id IS
        'The build this character sheet is currently assembled from on this timeline. '
        'NULL if no build has been selected yet. Must belong to this same character '
        '(enforced by trigger) — different timelines may select different builds for '
        'the same character after a branch.';
    """)
    op.execute(
        "CREATE INDEX ix_character_state_character_build_id "
        "ON campaign.character_state (character_build_id) WHERE character_build_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_character_state_build_character()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_build_character UUID;
        BEGIN
            IF NEW.character_build_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT character_id INTO v_build_character
            FROM character.character_builds WHERE character_build_id = NEW.character_build_id;

            IF v_build_character IS DISTINCT FROM NEW.character_id THEN
                RAISE EXCEPTION
                    'Build % belongs to character %, but this state row is for character %',
                    NEW.character_build_id, v_build_character, NEW.character_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_character_state_build_character() IS
        'Keeps campaign.character_state.character_build_id pointed at a build belonging '
        'to the same character as the state row.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_state_enforce_build_character
        BEFORE INSERT OR UPDATE ON campaign.character_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_character_state_build_character();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_state_enforce_build_character "
        "ON campaign.character_state;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_character_state_build_character();")
    op.execute("ALTER TABLE campaign.character_state DROP COLUMN IF EXISTS character_build_id;")

    op.execute(
        "ALTER TABLE character.character_builds ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT FALSE;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_character_builds_one_current_per_character
        ON character.character_builds (character_id)
        WHERE is_current;
    """)
    op.execute("""
        COMMENT ON TABLE character.character_builds IS
        'A versioned mechanical snapshot of a character, pinned to one ruleset version. '
        'Ability scores, class levels, proficiencies, features, and spellcasting all '
        'belong to a build, not directly to the character, so re-leveling or rebuilding '
        'does not erase the prior build''s history.';
    """)
