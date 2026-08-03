"""Character-location temporal integrity: adopt the ADR 0010 interval contract

Revision ID: 043_character_location_temporal
Revises: 042_close_phase4_location_refs
Create Date: 2026-08-03 09:00:00.000000

Purpose:
    Phase 5 exit review finding: campaign.character_location_history
    (revision 042) enforced same-world agreement but not the rest of the
    interval contract ADR 0010 and DATABASE_CONVENTIONS.md §12.3/§12.5
    require for any fictional-time validity period — the same contract
    campaign.party_memberships (revision 009) already implements. Revision
    042 predates this review and used a partial unique index ("at most one
    open row per timeline+character") as a shortcut; that index proves
    exactly one thing and silently allows everything else the full contract
    would catch: overlapping *closed* periods, a closed period overlapping
    the open one, a departure before or equal to its arrival, and a client
    supplying an internally inconsistent range.

    This revision replaces that shortcut with the proven pattern rather than
    inventing a second temporal convention, per the review's explicit
    instruction. Revisions 038-042 are not modified — this is forward-only,
    matching how Phase 4's corrections revisions (023-030) fixed earlier
    tables without editing the migrations that created them.

    Scope-bearing parent rows this table depends on
    (core.entities.world_id, core.world_times.world_id/sort_key,
    campaign.timelines.world_id) are already immutable as of revision 030,
    before world.locations existed to depend on them — so "a later mutation
    of a referenced scope-bearing row cannot invalidate existing history" is
    already guaranteed for this table without any new trigger here. Tests
    prove this holds for the location domain specifically.

Forward migration:
    - campaign.character_location_history.arrived_at_world_time_id: made
      NOT NULL (renamed in spirit to match effective_from — a history row
      needs a real interval endpoint to participate in range overlap)
    - campaign.character_location_history.location_period INT8RANGE,
      derived, never client-authoritative — same role as
      party_memberships.effective_period
    - campaign.character_location_history.updated_at, with the standard
      core.set_updated_at() trigger (existing tables get this at creation;
      this one is being brought up to that standard now)
    - Drops ux_character_location_history_one_open_per_character (revision
      042) — fully subsumed by the exclusion constraint below, since two
      open (unbounded upper) periods for the same (timeline, character)
      always overlap
    - CONSTRAINT ck_character_location_history_open_ended_agrees,
      _lower_bound_finite, _period_not_empty — identical shape to
      party_memberships' three CHECKs
    - CONSTRAINT ex_character_location_history_no_overlap — EXCLUDE USING
      gist (timeline_id, character_id, location_period WITH &&), the
      (timeline, character) analogue of party_memberships' (timeline, party,
      member) key
    - campaign.sync_character_location_period(), replacing
      campaign.enforce_character_location_history_world() (revision 042):
      validates character/timeline/location world agreement (042's own
      checks, carried forward unchanged), validates both world-time
      endpoints belong to that same world, requires departure strictly
      later than arrival, and derives location_period from the endpoints'
      sort_keys — never from client input

Rollback:
    Supported. Restores revision 042's exact shape: drops the new
    constraints, function, and trigger; recreates
    enforce_character_location_history_world() and its trigger; drops
    location_period and updated_at; restores the partial unique index; sets
    arrived_at_world_time_id back to nullable.

Data implications:
    No rows exist yet in campaign.character_location_history (no command
    layer writes to it). arrived_at_world_time_id can be set NOT NULL
    directly with no backfill.

Locking considerations:
    ADD COLUMN / ALTER COLUMN SET NOT NULL on an empty table does not
    rewrite it. Adding the GiST exclusion constraint would take an ACCESS
    EXCLUSIVE lock to build its index on a populated table; harmless here
    since the table is empty.

See: docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md
     docs/DATABASE_CONVENTIONS.md §12.3 (temporal validity), §12.5 (overlap prevention)
     database/migrations/versions/009_parties_and_memberships.py (the pattern reused here)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "043_character_location_temporal"
down_revision = "042_close_phase4_location_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. Retire the shortcut: partial unique index and the old trigger/function
    # ==========================================================================
    op.execute(
        "DROP INDEX IF EXISTS campaign.ux_character_location_history_one_open_per_character;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_location_history_enforce_world "
        "ON campaign.character_location_history;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_character_location_history_world();")

    # ==========================================================================
    # 2. Bring the table up to the ADR 0010 shape
    # ==========================================================================
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "ALTER COLUMN arrived_at_world_time_id SET NOT NULL;"
    )

    # Both world-time endpoints move from ON DELETE SET NULL (revision 042)
    # to ON DELETE RESTRICT, matching campaign.party_memberships' endpoints
    # exactly (both of which use RESTRICT, including the nullable one). SET
    # NULL is wrong for either column now: on arrived_at_world_time_id it
    # cannot fire at all once the column is NOT NULL (the DELETE would just
    # fail on the NOT NULL constraint instead of failing cleanly on the FK);
    # on departed_at_world_time_id it would silently reopen a closed period
    # (departed_at_world_time_id set NULL) while location_period stayed
    # frozen at its old bounded value — the sync trigger only runs on
    # INSERT/UPDATE of this row, not on a DELETE of the row it references, so
    # the derived range would be left stale and wrong.
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT character_location_history_arrived_at_world_time_id_fkey;"
    )
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT character_location_history_arrived_at_world_time_id_fkey
            FOREIGN KEY (arrived_at_world_time_id)
            REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT;
    """)
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT character_location_history_departed_at_world_time_id_fkey;"
    )
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT character_location_history_departed_at_world_time_id_fkey
            FOREIGN KEY (departed_at_world_time_id)
            REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT;
    """)

    op.execute(
        "ALTER TABLE campaign.character_location_history ADD COLUMN location_period INT8RANGE;"
    )
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();"
    )
    op.execute("""
        COMMENT ON COLUMN campaign.character_location_history.arrived_at_world_time_id IS
        'Required — the interval''s finite start (ADR 0010). Renamed in spirit to '
        'effective_from: every history row needs a real endpoint to participate in '
        'range overlap.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_location_history.location_period IS
        'Derived, never client-authoritative: an INT8RANGE over '
        'arrived_at_world_time_id/departed_at_world_time_id''s sort_key values, rebuilt '
        'by trigger on every INSERT and UPDATE — same role as '
        'campaign.party_memberships.effective_period (ADR 0010).';
    """)

    # arrived_at_world_time_id is NOT NULL now (step 2 above), so its partial
    # index from revision 042 (WHERE ... IS NOT NULL) is always-true and no
    # longer matches convention §19.4 (partial indexes are for nullable FKs).
    # Replaced with a plain index, matching departed_at_world_time_id's own
    # index style once that one is genuinely nullable-only.
    op.execute(
        "DROP INDEX IF EXISTS campaign.ix_character_location_history_arrived_at_world_time_id;"
    )
    op.execute(
        "CREATE INDEX ix_character_location_history_arrived_at_world_time_id "
        "ON campaign.character_location_history (arrived_at_world_time_id);"
    )

    # ==========================================================================
    # 3. The interval contract's CHECK constraints — identical shape to
    #    campaign.party_memberships (revision 009)
    # ==========================================================================
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT ck_character_location_history_open_ended_agrees
            CHECK (
                (departed_at_world_time_id IS NULL) = (upper_inf(location_period))
            );
    """)
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT ck_character_location_history_lower_bound_finite
            CHECK (NOT lower_inf(location_period));
    """)
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT ck_character_location_history_period_not_empty
            CHECK (NOT isempty(location_period));
    """)

    # ==========================================================================
    # 4. The rule this revision exists to enforce
    # ==========================================================================
    # btree_gist was installed by revision 009 and is left permanently
    # installed by design (see that revision's downgrade() note) — this is
    # a defensive IF NOT EXISTS, not a new dependency.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT ex_character_location_history_no_overlap
            EXCLUDE USING gist (
                timeline_id WITH =,
                character_id WITH =,
                location_period WITH &&
            );
    """)

    # ==========================================================================
    # 5. Endpoint validation and range derivation
    # ==========================================================================
    # Supersedes campaign.enforce_character_location_history_world() (revision
    # 042): carries forward its timeline/character/location world-agreement
    # checks unchanged, and adds the world-time endpoint and ordering checks
    # ADR 0010 requires. One trigger owns the whole contract, exactly as
    # campaign.sync_party_membership_period() does for memberships.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.sync_character_location_period()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world   UUID;
            v_character_world  UUID;
            v_location_world   UUID;
            v_from_world       UUID;
            v_from_sort_key    BIGINT;
            v_to_world         UUID;
            v_to_sort_key      BIGINT;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            IF v_character_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Character % belongs to world %, but timeline % belongs to world %',
                    NEW.character_id, v_character_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id INTO v_location_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            IF v_location_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Location % belongs to world %, but timeline % belongs to world %',
                    NEW.location_id, v_location_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id, sort_key INTO v_from_world, v_from_sort_key
            FROM core.world_times WHERE world_time_id = NEW.arrived_at_world_time_id;

            IF v_from_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Arrival world time % belongs to world %, but timeline % belongs to world %',
                    NEW.arrived_at_world_time_id, v_from_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.departed_at_world_time_id IS NULL THEN
                NEW.location_period := int8range(v_from_sort_key, NULL, '[)');
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_to_world, v_to_sort_key
            FROM core.world_times WHERE world_time_id = NEW.departed_at_world_time_id;

            IF v_to_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Departure world time % belongs to world %, but timeline % belongs to world %',
                    NEW.departed_at_world_time_id, v_to_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_to_sort_key <= v_from_sort_key THEN
                RAISE EXCEPTION
                    'Departure (sort_key %) must be later than arrival (sort_key %)',
                    v_to_sort_key, v_from_sort_key
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.location_period := int8range(v_from_sort_key, v_to_sort_key, '[)');
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.sync_character_location_period() IS
        'Owns the ADR 0010 interval contract for character-location history: validates '
        'that the character, location, and both world-time endpoints share the '
        'timeline''s world, that departure is strictly later than arrival, and then '
        'overwrites location_period from the endpoints'' sort_keys so the IDs and the '
        'range can never disagree. Supersedes revision 042''s '
        'enforce_character_location_history_world().';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_location_history_sync_period
        BEFORE INSERT OR UPDATE ON campaign.character_location_history
        FOR EACH ROW EXECUTE FUNCTION campaign.sync_character_location_period();
    """)

    # ==========================================================================
    # 6. updated_at, the same standard trigger every other mutable table uses
    # ==========================================================================
    op.execute("""
        CREATE TRIGGER tr_character_location_history_set_updated_at
        BEFORE UPDATE ON campaign.character_location_history
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)


def downgrade() -> None:
    """Revert the migration — restores revision 042's exact shape."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_location_history_set_updated_at "
        "ON campaign.character_location_history;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_location_history_sync_period "
        "ON campaign.character_location_history;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.sync_character_location_period();")

    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT IF EXISTS ex_character_location_history_no_overlap;"
    )
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT IF EXISTS ck_character_location_history_period_not_empty;"
    )
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT IF EXISTS ck_character_location_history_lower_bound_finite;"
    )
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT IF EXISTS ck_character_location_history_open_ended_agrees;"
    )

    op.execute("ALTER TABLE campaign.character_location_history DROP COLUMN IF EXISTS updated_at;")
    op.execute(
        "ALTER TABLE campaign.character_location_history DROP COLUMN IF EXISTS location_period;"
    )
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "ALTER COLUMN arrived_at_world_time_id DROP NOT NULL;"
    )

    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT character_location_history_departed_at_world_time_id_fkey;"
    )
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT character_location_history_departed_at_world_time_id_fkey
            FOREIGN KEY (departed_at_world_time_id)
            REFERENCES core.world_times(world_time_id) ON DELETE SET NULL;
    """)
    op.execute(
        "ALTER TABLE campaign.character_location_history "
        "DROP CONSTRAINT character_location_history_arrived_at_world_time_id_fkey;"
    )
    op.execute("""
        ALTER TABLE campaign.character_location_history
        ADD CONSTRAINT character_location_history_arrived_at_world_time_id_fkey
            FOREIGN KEY (arrived_at_world_time_id)
            REFERENCES core.world_times(world_time_id) ON DELETE SET NULL;
    """)

    op.execute(
        "DROP INDEX IF EXISTS campaign.ix_character_location_history_arrived_at_world_time_id;"
    )
    op.execute("""
        CREATE INDEX ix_character_location_history_arrived_at_world_time_id
        ON campaign.character_location_history (arrived_at_world_time_id)
        WHERE arrived_at_world_time_id IS NOT NULL;
    """)

    # Restore revision 042's function/trigger.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_character_location_history_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world   UUID;
            v_character_world  UUID;
            v_location_world   UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            SELECT world_id INTO v_location_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            IF v_character_world IS DISTINCT FROM v_timeline_world
               OR v_location_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Character location history row mixes worlds: timeline % (world %), '
                    'character % (world %), location % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.character_id, v_character_world,
                    NEW.location_id, v_location_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_character_location_history_world() IS
        'World-agreement guard for campaign.character_location_history: timeline, '
        'character, and location must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_location_history_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.character_location_history
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_character_location_history_world();
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_character_location_history_one_open_per_character
        ON campaign.character_location_history (timeline_id, character_id)
        WHERE departed_at_world_time_id IS NULL;
    """)
