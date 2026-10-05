"""Add the organization-hierarchy cycle guard

Revision ID: 113_organization_cycle_guard
Revises: 112_actor_idempotent_requests
Create Date: 2026-10-04 12:00:00.000000

Purpose:
    Phase 15.1 (docs/adr/0015-typed-world-content-authoring.md). Reassigning an
    organization's parent becomes a user action in the portal.
    `world.organizations.parent_organization_id` has only a self-parent CHECK
    (`ck_organizations_parent_not_self`, revision 076): an A -> B -> A cycle, or
    any longer one, is accepted. Location containment already has this guard
    (revisions 044/049/054); this revision gives the organization hierarchy the
    same one.

Forward migration:
    1. Pre-flight: if any organization hierarchy already contains a cycle, raise
       (naming the offending ids) rather than installing a guard over corrupt
       data. A clean database is the expected case.
    2. `world.enforce_organization_no_cycle()`, modelled on
       `world.enforce_location_no_cycle()` (revision 054): takes the world's
       advisory lock `world.organizations.hierarchy:<world>` (so concurrent
       reparents in one world serialize), then walks the proposed parent's
       ancestry with a recursive `CYCLE` query. It raises
       `integrity_constraint_violation` if the organization is among its own
       ancestors, if the walk finds an already-corrupt cycle, or if the chain
       exceeds 10,000 ancestors without completing.
    3. `tr_organizations_enforce_no_cycle`, BEFORE INSERT OR UPDATE OF
       parent_organization_id.

Rollback:
    Supported. Drops the trigger, then the function.

Data implications:
    None. No rows are read for change or mutated; the pre-flight is read-only.
    Rolling back mutates nothing, so DATABASE_CONVENTIONS §25.7 deferred-trigger
    draining is not needed.

Locking considerations:
    Function and trigger creation take a brief SHARE ROW EXCLUSIVE lock on
    `world.organizations`.

See: database/migrations/versions/054_location_cycle_detection_complete.py
     src/dnd_ai/commands/organizations.py (pre-checks under the same advisory key)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "113_organization_cycle_guard"
down_revision = "112_actor_idempotent_requests"
branch_labels = None
depends_on = None

_DEPTH_BOUND = 10000


def upgrade() -> None:
    """Apply the migration."""
    op.execute(f"""
        DO $$
        DECLARE
            v_offenders TEXT;
        BEGIN
            WITH RECURSIVE walk AS (
                SELECT o.organization_id AS start_id, o.organization_id AS node_id,
                       o.parent_organization_id AS next_id, 1 AS depth
                FROM world.organizations o
                WHERE o.parent_organization_id IS NOT NULL
                UNION ALL
                SELECT w.start_id, p.organization_id, p.parent_organization_id, w.depth + 1
                FROM walk w
                JOIN world.organizations p ON p.organization_id = w.next_id
                WHERE w.depth < {_DEPTH_BOUND}
            )
            SELECT string_agg(DISTINCT start_id::text, ', ')
            INTO v_offenders
            FROM walk
            WHERE next_id = start_id;

            IF v_offenders IS NOT NULL THEN
                RAISE EXCEPTION
                    'Cannot install the organization hierarchy cycle guard: these '
                    'organizations are already part of a parent cycle: %', v_offenders
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)
    op.execute(f"""
        CREATE OR REPLACE FUNCTION world.enforce_organization_no_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world             UUID;
            v_parent_world          UUID;
            v_scope                 UUID;
            v_found_target          BOOLEAN;
            v_found_existing_cycle  BOOLEAN;
            v_max_depth             INTEGER;
        BEGIN
            IF NEW.parent_organization_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.organization_id;

            SELECT world_id INTO v_parent_world
            FROM core.entities WHERE entity_id = NEW.parent_organization_id;

            -- Serialize hierarchy changes per world before inspecting the
            -- hierarchy; both worlds, in a fixed order, so a (rejected)
            -- cross-world write cannot deadlock a legitimate one.
            FOR v_scope IN
                SELECT DISTINCT w FROM unnest(ARRAY[v_own_world, v_parent_world]) AS w
                WHERE w IS NOT NULL
                ORDER BY w
            LOOP
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('world.organizations.hierarchy:' || v_scope::text, 0)
                );
            END LOOP;

            WITH RECURSIVE ancestry AS (
                SELECT o.organization_id, o.parent_organization_id, 1 AS depth
                FROM world.organizations o
                WHERE o.organization_id = NEW.parent_organization_id
                UNION ALL
                SELECT o.organization_id, o.parent_organization_id, a.depth + 1
                FROM world.organizations o
                JOIN ancestry a ON o.organization_id = a.parent_organization_id
                WHERE a.depth < {_DEPTH_BOUND}
            )
            CYCLE organization_id SET is_cycle USING path
            SELECT
                bool_or(organization_id = NEW.organization_id),
                bool_or(is_cycle),
                max(depth)
            INTO v_found_target, v_found_existing_cycle, v_max_depth
            FROM ancestry;

            IF v_found_target THEN
                RAISE EXCEPTION
                    'Organization % cannot be parented under %: % is already an ancestor '
                    'of itself through that chain, which would create a hierarchy cycle',
                    NEW.organization_id, NEW.parent_organization_id, NEW.organization_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_found_existing_cycle THEN
                RAISE EXCEPTION
                    'Organization %''s proposed parent chain (starting at %) already '
                    'contains a pre-existing hierarchy cycle unrelated to this update; '
                    'refusing to modify the hierarchy until that corruption is repaired',
                    NEW.organization_id, NEW.parent_organization_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_max_depth >= {_DEPTH_BOUND} THEN
                RAISE EXCEPTION
                    'Organization %''s proposed parent chain (starting at %) exceeds % '
                    'ancestors without completing; cannot prove the hierarchy is acyclic '
                    'this deep, refusing rather than assuming it is',
                    NEW.organization_id, NEW.parent_organization_id, {_DEPTH_BOUND}
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_organization_no_cycle() IS
        'Walks parent_organization_id ancestry from the proposed parent and rejects the '
        'write if NEW.organization_id is among its ancestors (a cycle of any length this '
        'write would create), if the walk finds a pre-existing cycle (CYCLE clause), or if '
        'it exceeds its depth safety bound without completing. Serializes hierarchy '
        'changes per world with the advisory lock world.organizations.hierarchy:<world>, '
        'the same key the organization commands take before their own pre-check. '
        'Mirrors world.enforce_location_no_cycle().';
    """)
    op.execute("""
        CREATE TRIGGER tr_organizations_enforce_no_cycle
        BEFORE INSERT OR UPDATE OF parent_organization_id ON world.organizations
        FOR EACH ROW EXECUTE FUNCTION world.enforce_organization_no_cycle();
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP TRIGGER IF EXISTS tr_organizations_enforce_no_cycle ON world.organizations;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_organization_no_cycle();")
