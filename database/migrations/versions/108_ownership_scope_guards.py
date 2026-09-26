"""Ownership-scope database-boundary guards: membership identity
immutability and final-owner retention for established active scopes.

Revision ID: 108_ownership_scope_guards
Revises: 107_world_ownership_scope
Create Date: 2026-09-26 09:00:00.000000

Purpose:
    Correction pass on `107_world_ownership_scope` (ADR 0014). That
    revision's own `dnd_ai.commands.ownership` module docstring already
    claimed "ownership_scope_id is immutable for a membership row" and
    relied on the command layer alone to keep at least one active owner —
    but neither claim was ever enforced at the database boundary. Direct
    SQL (or a future command with a bug) could revoke every owner of a
    scope that already has one, or reparent a `security.
    ownership_scope_memberships` row to a different scope or user entirely,
    and nothing in the schema itself would object.

    This revision closes both gaps using patterns already established
    elsewhere in this codebase rather than inventing new ones:

    - Membership identity immutability reuses `core.
      enforce_immutable_columns()` (revision `030_parent_scope_immutable`)
      exactly as every other "this column is identity, not configuration"
      column in this schema already does — no new trigger function.
    - Final-owner retention mirrors `security.
      campaign_has_access_manager()`/`.assert_campaign_retains_access_
      manager()`'s shape (revision `080_security_identity_and_access`)
      precisely: a `STABLE` pure-read predicate function, a `void`
      assert-and-raise function that takes a `FOR UPDATE` row lock on the
      parent (`security.ownership_scopes`, not `campaign.campaigns`) before
      evaluating, and a `DEFERRABLE INITIALLY DEFERRED` constraint trigger
      on the membership table so a normal "revoke old owner, add new
      owner" transfer within one transaction is checked once against the
      final state, not rejected on a momentarily owner-less intermediate
      one.

    Deliberately gated the same way campaign's own check is gated —
    **only** an ownership scope whose own `lifecycle_status_id` resolves to
    `active` must retain an owner; an archived scope may freely end its
    last owner. And because the constraint trigger lives on `security.
    ownership_scope_memberships` and fires only on `UPDATE`/`DELETE` of an
    *existing* row, it can never fire for a scope that has zero membership
    rows at all — the exact shape `107_world_ownership_scope`'s own legacy
    scope ("Legacy Self-Hosted Worlds (unclaimed)") is left in immediately
    after a populated upgrade. That scope remains a legitimate, explicit,
    non-authorizing "unclaimed" state this revision does not touch or
    require anyone to guess an owner for — `scripts/claim_legacy_
    ownership_scope.py`/`dnd_ai.commands.ownership.
    claim_unclaimed_ownership_scope` (a companion application-layer
    correction, not part of this migration) remains the only sanctioned
    way to give it its first owner.

    `dnd_ai.commands.ownership.remove_ownership_scope_member`'s own
    advisory-lock-and-count check (unchanged by this revision) continues to
    exist alongside this trigger, not instead of it — it exists so an
    ordinary call fails with a specific, catchable `LastActiveOwnerError`
    before ever reaching this trigger's generic integrity-constraint
    violation, exactly the relationship `dnd_ai.commands.campaigns.
    create_campaign` already has with `security.
    assert_campaign_retains_access_manager()`.

Forward migration:
    - `core.enforce_immutable_columns('ownership_scope_id', 'user_id')`
      attached (`BEFORE UPDATE`) to `security.ownership_scope_memberships`
      — a membership's owning scope and underlying user are identity, not
      configuration, exactly like every column `030_parent_scope_
      immutable` already protects elsewhere. `user_id` is included
      alongside `ownership_scope_id`: swapping which user a membership row
      names is the same class of "reparent" this revision's own docstring
      and the task that produced it both call out, even though the
      original design note in `107_world_ownership_scope` only mentioned
      `ownership_scope_id`.
    - `security.ownership_scope_has_active_owner(UUID)` — `STABLE` SQL
      predicate, mirroring `campaign_has_access_manager(UUID)`'s shape.
    - `security.assert_ownership_scope_retains_owner(UUID)` — `plpgsql`
      assert-and-raise, mirroring `assert_campaign_retains_access_
      manager(UUID)`'s shape, including its `FOR UPDATE` parent-row lock
      for concurrency-safety (two concurrent transactions each removing a
      *different* owning membership of the same scope cannot both
      independently observe "someone else still has it" and both commit).
    - `security.enforce_ownership_scope_memberships_retain_owner()` —
      trigger function, `AFTER UPDATE OR DELETE` only (an `INSERT` can only
      ever add an owner, never remove one, so it needs no check — matching
      `080`'s identical choice for `security.campaign_memberships`'s own
      trigger), with the same "check `OLD`'s scope, and `NEW`'s scope too
      when it differs" shape as a defense-in-depth measure even though the
      immutability trigger above makes that branch unreachable in
      practice — matching `080`'s own documented "(defense in depth;
      campaign_id is immutable per section 16)" precedent for the
      identical situation.
    - `CREATE CONSTRAINT TRIGGER tr_ownership_scope_memberships_retain_owner
      ... DEFERRABLE INITIALLY DEFERRED`, attached to `security.
      ownership_scope_memberships`.

Rollback:
    Supported. Drops the constraint trigger, both new functions, and the
    immutable-columns trigger, in that order. Does not drop `core.
    enforce_immutable_columns()` itself — that function is shared
    infrastructure owned by `030_parent_scope_immutable`, not this
    revision.

Data implications:
    Creates no rows and rewrites no existing row. A populated database
    already satisfying the invariant (every existing active scope with
    membership history already has an active owner — true by construction,
    since `dnd_ai.commands.ownership.create_ownership_scope`/
    `claim_unclaimed_ownership_scope` are the only ways such a row is ever
    created) upgrades with nothing to reconcile. The one known exception —
    `107`'s own legacy scope — has zero membership rows and is therefore
    outside this trigger's domain entirely, as explained above.

Locking considerations:
    Adding triggers does not rewrite either table. Both new functions are
    pure additions.

See: docs/adr/0014-world-ownership-scope.md
     docs/architecture/DATABASE_MODEL.md §19.9
     database/migrations/versions/030_parent_scope_immutability.py
     (core.enforce_immutable_columns(), reused unchanged)
     database/migrations/versions/080_security_identity_and_access.py
     (security.campaign_has_access_manager()/.assert_campaign_retains_
     access_manager(), the shape this revision mirrors)
     src/dnd_ai/commands/ownership.py (the application-layer half of this
     correction pass — authorization policy and the narrow
     claim_unclaimed_ownership_scope bootstrap path)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "108_ownership_scope_guards"
down_revision = "107_world_ownership_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. Membership identity immutability — reuses core.
    #    enforce_immutable_columns() (030_parent_scope_immutable) unchanged.
    # ==========================================================================
    op.execute("""
        CREATE TRIGGER tr_ownership_scope_memberships_enforce_immutable
        BEFORE UPDATE ON security.ownership_scope_memberships
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns(
            'ownership_scope_id', 'user_id'
        );
    """)

    # ==========================================================================
    # 2. Final-owner retention for established active scopes
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION security.ownership_scope_has_active_owner(
            p_ownership_scope_id UUID
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM security.ownership_scope_memberships osm
                JOIN security.ownership_scope_roles r
                    ON r.ownership_scope_role_id = osm.ownership_scope_role_id
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = osm.membership_status_id
                WHERE osm.ownership_scope_id = p_ownership_scope_id
                  AND osm.ended_at IS NULL
                  AND ms.code = 'active'
                  AND ms.is_active
                  AND r.code = 'owner'
                  AND r.is_active
            );
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.ownership_scope_has_active_owner(UUID) IS
        'Whether p_ownership_scope_id currently has at least one open '
        '(ended_at IS NULL), active-status, owner-role membership — both the '
        'membership_statuses and ownership_scope_roles lookup rows must also be '
        'is_active, the same rule security.campaign_has_access_manager() applies to '
        'its own lookups (ADR 0014, docs/architecture/DATABASE_MODEL.md §19.9). Pure '
        'read — callers needing the enforcement side (locking plus RAISE) use '
        'security.assert_ownership_scope_retains_owner().';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.assert_ownership_scope_retains_owner(
            p_ownership_scope_id UUID
        )
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_status TEXT;
        BEGIN
            IF p_ownership_scope_id IS NULL THEN
                RETURN;
            END IF;

            -- Serializes concurrent removals of different owning memberships of
            -- the same scope against each other (see this revision's docstring).
            PERFORM 1 FROM security.ownership_scopes
            WHERE ownership_scope_id = p_ownership_scope_id FOR UPDATE;

            SELECT ls.code INTO v_status
            FROM security.ownership_scopes os
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = os.lifecycle_status_id
            WHERE os.ownership_scope_id = p_ownership_scope_id;

            IF v_status IS DISTINCT FROM 'active' THEN
                RETURN;
            END IF;

            IF NOT security.ownership_scope_has_active_owner(p_ownership_scope_id) THEN
                RAISE EXCEPTION
                    'Ownership scope % would be left with no active owner — an active '
                    'ownership scope that already has membership history must retain at '
                    'least one (ADR 0014, docs/architecture/DATABASE_MODEL.md §19.9)',
                    p_ownership_scope_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.assert_ownership_scope_retains_owner(UUID) IS
        'Locks security.ownership_scopes for p_ownership_scope_id (FOR UPDATE, '
        'concurrency-safety — see this revision''s docstring), then raises unless it '
        'is not active or security.ownership_scope_has_active_owner() is true. Called '
        'only from a DEFERRABLE INITIALLY DEFERRED constraint trigger, so it evaluates '
        'the fully-committed-within-the-transaction final state, not a momentarily '
        'incomplete one.';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_ownership_scope_memberships_retain_owner()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                PERFORM security.assert_ownership_scope_retains_owner(OLD.ownership_scope_id);
            END IF;

            IF TG_OP = 'UPDATE' AND NEW.ownership_scope_id IS DISTINCT FROM OLD.ownership_scope_id THEN
                PERFORM security.assert_ownership_scope_retains_owner(NEW.ownership_scope_id);
            END IF;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_ownership_scope_memberships_retain_owner() IS
        'Guard for security.ownership_scope_memberships: any UPDATE or DELETE that '
        'would leave an already-established active ownership scope with zero active '
        'owners is rejected at commit (ADR 0014). The NEW-scope branch is defense in '
        'depth only — ownership_scope_id is immutable on this table (see this '
        'revision''s own immutability trigger), so that branch can never actually '
        'fire, mirroring security.enforce_campaign_memberships_retain_access_manager()''s '
        'identical documented precedent for campaign_id.';
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_ownership_scope_memberships_retain_owner
        AFTER UPDATE OR DELETE ON security.ownership_scope_memberships
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_ownership_scope_memberships_retain_owner();
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute(
        "DROP TRIGGER IF EXISTS tr_ownership_scope_memberships_retain_owner "
        "ON security.ownership_scope_memberships;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS security.enforce_ownership_scope_memberships_retain_owner();"
    )
    op.execute("DROP FUNCTION IF EXISTS security.assert_ownership_scope_retains_owner(UUID);")
    op.execute("DROP FUNCTION IF EXISTS security.ownership_scope_has_active_owner(UUID);")
    op.execute(
        "DROP TRIGGER IF EXISTS tr_ownership_scope_memberships_enforce_immutable "
        "ON security.ownership_scope_memberships;"
    )
