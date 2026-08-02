"""Concurrency-safe world-ruleset allow-list enforcement

Revision ID: 035_world_ruleset_concurrency
Revises: 034_ruleset_family_neutral
Create Date: 2026-08-02 23:00:00.000000

Purpose:
    Corrective revision (PHASE4_REMAINING_ISSUES.md §1, post-closeout review).
    Revisions 029 and 031 correctly reject a `rules.world_rulesets` deletion
    or repoint *while a dependent row already exists*, and correctly reject
    *creating* a dependent whose ruleset is not currently allowed — but
    within one transaction each. At the project's `READ COMMITTED` isolation
    level, nothing stopped these two checks from interleaving across two
    concurrent transactions:

      T1 (creating a dependent): checks `rules.world_rulesets` still has the
        association -> sees it -> proceeds to insert the dependent.
      T2 (deleting the association): checks no dependent references it yet
        -> sees none (T1 hasn't committed) -> proceeds to delete.
      Both commit. Final state: a dependent referencing a ruleset the world
      no longer allows — exactly the invariant these triggers exist to
      prevent, just not against each other.

    This affects every dependency category revision 031 enumerated (world
    default, campaign, character species, character build, applied
    condition, tracked resource), because all six ultimately gate on reading
    `rules.world_rulesets` without taking a lock that conflicts with the
    delete/repoint side's implicit row lock.

Forward migration:
    Every check that reads a `rules.world_rulesets` row as its "is this
    ruleset allowed for this world" gate now takes a `SELECT ... FOR SHARE`
    on that exact `(world_id, ruleset_id)` row before deciding, so it holds
    a lock for the rest of its transaction that a concurrent DELETE/UPDATE
    on the same row (which needs an exclusive lock, acquired automatically
    by the DELETE/UPDATE statement itself before revision 031's trigger even
    runs) must wait behind. Whichever transaction's lock request arrives
    second blocks until the first commits or rolls back, then re-evaluates
    against the now-final committed state — not a stale snapshot — which is
    exactly what closes the race: the loser either sees the row already gone
    (dependent creation correctly rejected) or sees the dependent that
    already committed (deletion/repoint correctly rejected).

    - `rules.ruleset_allowed_for_world()` (revision 029): rewritten from a
      pure `STABLE SQL` boolean check to `PL/pgSQL`, taking the `FOR SHARE`
      lock explicitly. Used by species, build, condition, and resource
      checks (revision 029) — fixing it here fixes all four at once.
    - `core.enforce_world_default_ruleset_allowed()` (revision 016): same
      fix for `core.worlds.default_ruleset_id`.
    - `campaign.enforce_campaign_ruleset_allowed()` (revision 024): same fix
      for `campaign.campaigns.ruleset_version_id`.

    Locking order (why this cannot deadlock): every one of the four call
    sites locks at most one row, always the single `rules.world_rulesets`
    row identified by its own primary key `(world_id, ruleset_id)`, and never
    acquires any other lock first. A transaction that already holds this
    lock never waits on a second lock to finish its check. Two transactions
    can therefore only ever contend for the *same* single row, never a
    chain of rows acquired in different orders across transactions — the
    structural precondition for a deadlock (a cycle of waiters) cannot
    arise. Any future dependency category added to this invariant must keep
    this shape: resolve identifiers first (no locks), then take exactly one
    `FOR SHARE` lock on the one `rules.world_rulesets` row being checked,
    with no lock ever taken before it.

    `FOR SHARE` (not `FOR UPDATE`) is deliberate: many concurrent dependency
    creations checking the same allowed ruleset must not block each other
    (shared locks are mutually compatible), only block a concurrent
    delete/repoint (which needs the exclusive lock a DELETE/UPDATE always
    takes).

Rollback:
    Supported. Restores each function's prior (revision 016/024/029) body,
    without the lock.

Data implications:
    Creates no rows.

Locking considerations:
    Adds a `FOR SHARE` row lock, held until the calling transaction ends, to
    every dependent-creation path this invariant covers. Contention is
    limited to the one `rules.world_rulesets` row in play and is expected to
    be rare — allow-list membership changes are an infrequent administrative
    action, not routine play traffic.

See: PHASE4_REMAINING_ISSUES.md §1
     database/migrations/versions/016_close_ruleset_references.py
     database/migrations/versions/024_campaign_ruleset_version.py
     database/migrations/versions/029_character_state_corrections.py
     database/migrations/versions/031_world_ruleset_allow_list_protection.py
     tests/database/test_party_memberships.py (two-connection test pattern)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "035_world_ruleset_concurrency"
down_revision = "034_ruleset_family_neutral"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. rules.ruleset_allowed_for_world() — species, build, condition, resource
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION rules.ruleset_allowed_for_world(
            p_world_id UUID, p_ruleset_version_id UUID
        )
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_ruleset_id UUID;
            v_locked     UUID;
        BEGIN
            SELECT ruleset_id INTO v_ruleset_id
            FROM rules.ruleset_versions WHERE ruleset_version_id = p_ruleset_version_id;

            IF v_ruleset_id IS NULL THEN
                RETURN FALSE;
            END IF;

            -- Locks the one candidate world_rulesets row (its own primary
            -- key) so a concurrent DELETE/UPDATE of it must wait behind
            -- this transaction, and vice versa. See revision 035's
            -- docstring for why this closes the create/delete race and
            -- why it cannot deadlock.
            SELECT ruleset_id INTO v_locked
            FROM rules.world_rulesets
            WHERE world_id = p_world_id AND ruleset_id = v_ruleset_id
            FOR SHARE;

            RETURN FOUND;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.ruleset_allowed_for_world(UUID, UUID) IS
        'True when the given ruleset version''s ruleset family is one the given world '
        'allows (rules.world_rulesets). Takes a FOR SHARE lock on that world_rulesets '
        'row for the rest of the caller''s transaction, so a concurrent removal or '
        'repoint of the same association cannot race past this check (revision 035). '
        'Shared by the character/state world-allowance triggers below.';
    """)

    # ==========================================================================
    # 2. core.enforce_world_default_ruleset_allowed() — core.worlds.default_ruleset_id
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_world_default_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_locked UUID;
        BEGIN
            IF NEW.default_ruleset_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT ruleset_id INTO v_locked
            FROM rules.world_rulesets
            WHERE world_id = NEW.world_id AND ruleset_id = NEW.default_ruleset_id
            FOR SHARE;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Ruleset % is not an allowed ruleset for world % (add it to '
                    'rules.world_rulesets first)',
                    NEW.default_ruleset_id, NEW.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_world_default_ruleset_allowed() IS
        'Keeps core.worlds.default_ruleset_id one of the rulesets rules.world_rulesets '
        'says the world allows. Takes a FOR SHARE lock on that world_rulesets row for '
        'the rest of the caller''s transaction, closing the race with a concurrent '
        'removal or repoint of the same association (revision 035).';
    """)

    # ==========================================================================
    # 3. campaign.enforce_campaign_ruleset_allowed() — campaign.campaigns.ruleset_version_id
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_campaign_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world_id   UUID;
            v_ruleset_id UUID;
            v_locked     UUID;
        BEGIN
            SELECT world_id INTO v_world_id
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT ruleset_id INTO v_ruleset_id
            FROM rules.ruleset_versions WHERE ruleset_version_id = NEW.ruleset_version_id;

            SELECT ruleset_id INTO v_locked
            FROM rules.world_rulesets
            WHERE world_id = v_world_id AND ruleset_id = v_ruleset_id
            FOR SHARE;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Ruleset version % (ruleset %) is not allowed for world % (campaign '
                    '%''s world, via its timeline)',
                    NEW.ruleset_version_id, v_ruleset_id, v_world_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_campaign_ruleset_allowed() IS
        'Keeps a campaign''s pinned ruleset version''s ruleset family one of the rulesets '
        'its world allows. Takes a FOR SHARE lock on that world_rulesets row for the '
        'rest of the caller''s transaction, closing the race with a concurrent removal '
        'or repoint of the same association (revision 035).';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_campaign_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world_id   UUID;
            v_ruleset_id UUID;
            v_allowed    BOOLEAN;
        BEGIN
            SELECT world_id INTO v_world_id
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT ruleset_id INTO v_ruleset_id
            FROM rules.ruleset_versions WHERE ruleset_version_id = NEW.ruleset_version_id;

            SELECT EXISTS (
                SELECT 1 FROM rules.world_rulesets
                WHERE world_id = v_world_id AND ruleset_id = v_ruleset_id
            ) INTO v_allowed;

            IF NOT v_allowed THEN
                RAISE EXCEPTION
                    'Ruleset version % (ruleset %) is not allowed for world % (campaign '
                    '%''s world, via its timeline)',
                    NEW.ruleset_version_id, v_ruleset_id, v_world_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_campaign_ruleset_allowed() IS
        'Keeps a campaign''s pinned ruleset version''s ruleset family one of the rulesets '
        'its world allows.';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_world_default_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_allowed BOOLEAN;
        BEGIN
            IF NEW.default_ruleset_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM rules.world_rulesets
                WHERE world_id = NEW.world_id AND ruleset_id = NEW.default_ruleset_id
            ) INTO v_allowed;

            IF NOT v_allowed THEN
                RAISE EXCEPTION
                    'Ruleset % is not an allowed ruleset for world % (add it to '
                    'rules.world_rulesets first)',
                    NEW.default_ruleset_id, NEW.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_world_default_ruleset_allowed() IS
        'Keeps core.worlds.default_ruleset_id one of the rulesets rules.world_rulesets '
        'says the world allows.';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION rules.ruleset_allowed_for_world(
            p_world_id UUID, p_ruleset_version_id UUID
        )
        RETURNS BOOLEAN
        LANGUAGE sql
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM rules.ruleset_versions rv
                JOIN rules.world_rulesets wr ON wr.ruleset_id = rv.ruleset_id
                WHERE rv.ruleset_version_id = p_ruleset_version_id
                  AND wr.world_id = p_world_id
            );
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.ruleset_allowed_for_world(UUID, UUID) IS
        'True when the given ruleset version''s ruleset family is one the given world '
        'allows (rules.world_rulesets). Shared by the character/state world-allowance '
        'triggers below.';
    """)
