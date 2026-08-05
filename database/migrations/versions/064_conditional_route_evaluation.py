"""Conditional-route evaluation: structured check requirements, target-scoped checks

Revision ID: 064_conditional_route_evaluation
Revises: 063_knowledge_source_provenance
Create Date: 2026-08-05 19:00:00.000000

Purpose:
    Closes the Phase 6 first-time obligation docs/PLAN.md names: "Wire up
    conditional-route evaluation. world.area_connections.is_conditional/
    condition_description (revision 047) record that a route is conditional
    and what the condition is, but nothing evaluates it — a party attempting
    to traverse a conditional route needs a check resolution against the
    interaction model this phase builds. Quest-gated conditions additionally
    need Phase 7's quest state; a route conditioned purely on interaction/
    check outcome (not quest progress) can be fully wired here."

    "Fully wired" does NOT mean a trigger that mutates
    campaign.area_connection_state on a successful check result — rule 6
    (CLAUDE.md §5) requires state changes to go through a causal event
    committed atomically by the command layer, and no command layer exists
    yet (Phase 6 increment 5's job). A bare state-mutating trigger here would
    silently violate that rule the moment it fired. What this revision
    delivers instead is everything a command CAN use to resolve a
    check-gated route correctly once it exists:

    1. A structured, machine-checkable check requirement on
       world.area_connections (required_check_kind/ability_id/skill_id/
       difficulty) alongside the existing free-text condition_description —
       which remains for conditions that are not simply "pass this check"
       (quest-gated, state-gated, or otherwise; Phase 7's problem).
    2. interaction.check_requests.target_id, closing a real modeling gap
       from revision 061: nothing previously said which of an action's
       (possibly several) targets a given check actually resolves.
    3. world.conditional_route_requirement_satisfied(), a pure read-only SQL
       function — no mutation, so it cannot violate rule 6 — that a future
       command calls to decide whether a specific check result actually
       satisfies a specific conditional route's requirement.

Forward migration:
    - world.area_connections: required_check_kind, required_ability_id,
      required_skill_id, required_difficulty (all nullable), with CHECKs
      tying them to is_conditional and to each other (mirroring
      interaction.check_requests' own kind/ability/skill exclusivity), and
      world.enforce_area_connection_check_requirement_ruleset() reusing
      rules.ruleset_allowed_for_world() (revision 035)
    - interaction.check_requests.target_id (nullable FK to
      interaction.targets), with
      interaction.enforce_check_request_target_action() ensuring the target
      belongs to the same action as the check request
    - world.conditional_route_requirement_satisfied(p_area_connection_id,
      p_check_result_id) RETURNS BOOLEAN

Rollback:
    Supported. Drops the function, the new check_requests column/trigger,
    and the new area_connections columns/triggers.

Data implications:
    None — all new columns are nullable with no default; existing rows are
    unaffected.

Locking considerations:
    ALTER TABLE ADD COLUMN with no default on both tables: brief
    metadata-only locks, no table rewrite.

See: docs/PLAN.md Phase 6 (first-time obligations)
     docs/architecture/DATABASE_MODEL.md §9.2 (dungeon structures), §16
     (interaction and resolution model), §27 (Phase 6 reconciliation notes)
     CLAUDE.md §5 rule 6 (state changes need a causal event)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "064_conditional_route_evaluation"
down_revision = "063_knowledge_source_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. world.area_connections: structured check requirement
    # ==========================================================================
    op.execute("""
        ALTER TABLE world.area_connections
        ADD COLUMN required_check_kind TEXT,
        ADD COLUMN required_ability_id UUID
            REFERENCES rules.abilities(ability_id) ON DELETE RESTRICT,
        ADD COLUMN required_skill_id UUID
            REFERENCES rules.skills(skill_id) ON DELETE RESTRICT,
        ADD COLUMN required_difficulty core.nonnegative_integer;
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.is_conditional IS
        'True for a conditional route (docs/PLAN.md §9.2) — traversable only when '
        'some condition holds. required_check_kind (revision 064), when set, makes '
        'a check-gated condition machine-evaluable; quest-gated or state-gated '
        'conditions still rely on condition_description alone (Phase 7).';
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.required_check_kind IS
        'When set, the machine-checkable form of this route''s condition: '
        'ability_check, skill_check, or saving_throw. NULL for a conditional '
        'route whose condition is not simply "pass a check" (quest-gated, '
        'state-gated, ...) — condition_description remains the source of truth '
        'for those. See world.conditional_route_requirement_satisfied().';
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.required_skill_id IS
        'Set only for required_check_kind = skill_check — see '
        'ck_area_connections_check_requirement_reference.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.required_ability_id IS
        'Set for required_check_kind IN (ability_check, saving_throw). NULL for '
        'skill_check, where the governing ability is reached through '
        'required_skill_id -> rules.skills.ability_id instead.';
    """)
    op.execute("""
        ALTER TABLE world.area_connections
        ADD CONSTRAINT ck_area_connections_check_requirement_kind CHECK (
            required_check_kind IS NULL
            OR required_check_kind IN ('ability_check', 'skill_check', 'saving_throw')
        ),
        ADD CONSTRAINT ck_area_connections_check_requirement_reference CHECK (
            (required_check_kind IS NULL
                AND required_ability_id IS NULL
                AND required_skill_id IS NULL
                AND required_difficulty IS NULL)
            OR
            (required_check_kind = 'skill_check'
                AND required_skill_id IS NOT NULL
                AND required_ability_id IS NULL
                AND required_difficulty IS NOT NULL)
            OR
            (required_check_kind IN ('ability_check', 'saving_throw')
                AND required_ability_id IS NOT NULL
                AND required_skill_id IS NULL
                AND required_difficulty IS NOT NULL)
        ),
        ADD CONSTRAINT ck_area_connections_check_requirement_conditional CHECK (
            required_check_kind IS NULL OR is_conditional
        );
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_area_connection_check_requirement_ruleset()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world            UUID;
            v_ruleset_version  UUID;
        BEGIN
            IF NEW.required_ability_id IS NULL AND NEW.required_skill_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT e.world_id INTO v_world
            FROM world.dungeon_areas da
            JOIN core.entities e ON e.entity_id = da.dungeon_area_id
            WHERE da.dungeon_area_id = NEW.from_dungeon_area_id;

            IF NEW.required_skill_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_ruleset_version
                FROM rules.skills WHERE skill_id = NEW.required_skill_id;
            ELSE
                SELECT ruleset_version_id INTO v_ruleset_version
                FROM rules.abilities WHERE ability_id = NEW.required_ability_id;
            END IF;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_ruleset_version) THEN
                RAISE EXCEPTION
                    'Area connection %''s required ability/skill ruleset is not allowed '
                    'for world %',
                    NEW.area_connection_id, v_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_area_connection_check_requirement_ruleset() IS
        'Keeps a conditional route''s required ability/skill drawn from a ruleset '
        'family the route''s own world allows, reusing '
        'rules.ruleset_allowed_for_world() (revision 035) — same pattern as '
        'interaction.enforce_check_request_ruleset_allowed() (revision 061).';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_connections_enforce_check_requirement_ruleset
        BEFORE INSERT OR UPDATE ON world.area_connections
        FOR EACH ROW EXECUTE FUNCTION world.enforce_area_connection_check_requirement_ruleset();
    """)
    op.execute(
        "CREATE INDEX ix_area_connections_required_ability_id "
        "ON world.area_connections (required_ability_id) "
        "WHERE required_ability_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_area_connections_required_skill_id "
        "ON world.area_connections (required_skill_id) "
        "WHERE required_skill_id IS NOT NULL;"
    )

    # ==========================================================================
    # 2. interaction.check_requests.target_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE interaction.check_requests
        ADD COLUMN target_id UUID REFERENCES interaction.targets(target_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN interaction.check_requests.target_id IS
        'The specific target (of the same action) this check resolves, when the '
        'check is about a specific target rather than the action in the '
        'abstract. NULL when there is no single relevant target. Must belong to '
        'the same action_id as this check request — enforced by '
        'interaction.enforce_check_request_target_action().';
    """)
    op.execute(
        "CREATE INDEX ix_check_requests_target_id ON interaction.check_requests (target_id) "
        "WHERE target_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_check_request_target_action()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_target_action  UUID;
        BEGIN
            IF NEW.target_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT action_id INTO v_target_action
            FROM interaction.targets WHERE target_id = NEW.target_id;

            IF v_target_action IS DISTINCT FROM NEW.action_id THEN
                RAISE EXCEPTION
                    'Check request %''s target % belongs to action %, but the check '
                    'request belongs to action %',
                    NEW.check_request_id, NEW.target_id, v_target_action, NEW.action_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_check_request_target_action() IS
        'Guards interaction.check_requests.target_id: when set, the target must '
        'belong to the same action as the check request itself.';
    """)
    op.execute("""
        CREATE TRIGGER tr_check_requests_enforce_target_action
        BEFORE INSERT OR UPDATE ON interaction.check_requests
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_check_request_target_action();
    """)

    # ==========================================================================
    # 3. world.conditional_route_requirement_satisfied() — pure evaluation
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION world.conditional_route_requirement_satisfied(
            p_area_connection_id UUID, p_check_result_id UUID
        )
        RETURNS BOOLEAN
        LANGUAGE sql
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM interaction.check_results cres
                JOIN interaction.check_requests creq
                    ON creq.check_request_id = cres.check_request_id
                JOIN interaction.targets tgt ON tgt.target_id = creq.target_id
                JOIN world.area_connections ac
                    ON ac.area_connection_id = tgt.target_area_connection_id
                WHERE cres.check_result_id = p_check_result_id
                  AND ac.area_connection_id = p_area_connection_id
                  AND ac.is_conditional
                  AND ac.required_check_kind IS NOT NULL
                  AND ac.required_check_kind = creq.check_kind
                  AND ac.required_ability_id IS NOT DISTINCT FROM creq.ability_id
                  AND ac.required_skill_id IS NOT DISTINCT FROM creq.skill_id
                  AND creq.difficulty >= ac.required_difficulty
                  AND cres.degree_of_success IN ('success', 'critical_success')
            );
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.conditional_route_requirement_satisfied(UUID, UUID) IS
        'True when the given check result was for a check that targeted the '
        'given conditional route, matched its required_check_kind/ability_id/'
        'skill_id, met or exceeded its required_difficulty, and succeeded. Pure '
        'read-only decision helper — deliberately does not update '
        'campaign.area_connection_state itself (rule 6: state changes need a '
        'causal event, which only the command layer that calls this can '
        'provide). See this revision''s docstring.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP FUNCTION IF EXISTS world.conditional_route_requirement_satisfied(UUID, UUID);")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_check_requests_enforce_target_action "
        "ON interaction.check_requests;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_check_request_target_action();")
    op.execute("ALTER TABLE interaction.check_requests DROP COLUMN IF EXISTS target_id;")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_area_connections_enforce_check_requirement_ruleset "
        "ON world.area_connections;"
    )
    op.execute("DROP FUNCTION IF EXISTS world.enforce_area_connection_check_requirement_ruleset();")
    op.execute("""
        ALTER TABLE world.area_connections
        DROP CONSTRAINT IF EXISTS ck_area_connections_check_requirement_conditional,
        DROP CONSTRAINT IF EXISTS ck_area_connections_check_requirement_reference,
        DROP CONSTRAINT IF EXISTS ck_area_connections_check_requirement_kind;
    """)
    op.execute("""
        ALTER TABLE world.area_connections
        DROP COLUMN IF EXISTS required_difficulty,
        DROP COLUMN IF EXISTS required_skill_id,
        DROP COLUMN IF EXISTS required_ability_id,
        DROP COLUMN IF EXISTS required_check_kind;
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.is_conditional IS
        'True for a conditional route (docs/PLAN.md §9.2) — traversable only when '
        'some condition holds. Descriptive only: evaluating the condition requires '
        'interaction/check resolution (Phase 6) or quest state (Phase 7), neither '
        'of which exists yet. See PLAN.md Phase 6''s first-time obligations.';
    """)
