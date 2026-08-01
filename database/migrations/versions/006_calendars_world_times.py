"""Calendars, calendar months, world times, and the world default calendar

Revision ID: 006_calendars_world_times
Revises: 005_names_and_tags
Create Date: 2026-08-01 18:00:00.000000

Purpose:
    Completes the fictional-time half of Phase 2 (docs/PLAN.md §4.3):
    core.calendars, core.calendar_months, core.world_times, plus the
    world_time_precisions lookup they depend on.

    System time and world time must never be conflated (docs/DOMAIN_MODEL.md
    §6.3, conventions §4.7). Real-world timestamps stay TIMESTAMPTZ; fictional
    chronology is referenced through world_time_id and never stored as a
    TIMESTAMPTZ.

Forward migration:
    - core.world_time_precisions — lookup, seeded from DOMAIN_MODEL.md §6.2
    - core.calendars — a world's fictional time system
    - core.calendar_months — the months within a calendar, ordered
    - core.world_times — a point or approximate period in fictional chronology
    - core.worlds.default_calendar_id — deferred from revision 004 until the
      table it references existed

Rollback:
    Supported. Drops the default_calendar_id column first, then the tables in
    FK-dependency order.

Data implications:
    Seeds four precision values. No other rows created.

Locking considerations:
    Adds a nullable column to core.worlds. Nullable with no default, so no
    table rewrite — and the table is empty at this point regardless.

See: docs/DOMAIN_MODEL.md §6 (time domain)
     docs/DATABASE_CONVENTIONS.md §4.7 (world-time columns), §12 (temporal)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "006_calendars_world_times"
down_revision = "005_names_and_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.world_time_precisions
    # ==========================================================================
    op.execute("""
        CREATE TABLE core.world_time_precisions (
            world_time_precision_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code                     TEXT NOT NULL,
            display_name             TEXT NOT NULL,
            description              TEXT,
            sort_order               core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active                BOOLEAN NOT NULL DEFAULT true,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_world_time_precisions_code UNIQUE (code),
            CONSTRAINT ck_world_time_precisions_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.world_time_precisions IS
        'How precisely a world time is known — see docs/DOMAIN_MODEL.md §6.2.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.world_time_precisions.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_world_time_precisions_set_updated_at
        BEFORE UPDATE ON core.world_time_precisions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 2. core.calendars
    # ==========================================================================
    op.execute("""
        CREATE TABLE core.calendars (
            calendar_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id        UUID NOT NULL
                            REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            code            TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            description     TEXT,
            days_per_week   core.nonnegative_integer,
            epoch_label     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_calendars_world_code UNIQUE (world_id, code),
            CONSTRAINT ck_calendars_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_calendars_days_per_week_positive
                CHECK (days_per_week IS NULL OR days_per_week > 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.calendars IS
        'A fictional time system belonging to one world (docs/DOMAIN_MODEL.md §6.1). '
        'Worlds may define several — a common reckoning and an elvish one, say.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.calendars.epoch_label IS
        'What year zero is counted from, e.g. "Founding of the Republic".';
    """)
    op.execute("""
        CREATE TRIGGER tr_calendars_set_updated_at
        BEFORE UPDATE ON core.calendars
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_calendars_world_id ON core.calendars (world_id);")

    # ==========================================================================
    # 3. core.calendar_months
    # ==========================================================================
    op.execute("""
        CREATE TABLE core.calendar_months (
            calendar_month_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            calendar_id        UUID NOT NULL
                               REFERENCES core.calendars(calendar_id) ON DELETE CASCADE,
            month_number       core.nonnegative_integer NOT NULL,
            name               TEXT NOT NULL,
            day_count          core.nonnegative_integer NOT NULL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_calendar_months_calendar_number UNIQUE (calendar_id, month_number),
            CONSTRAINT ux_calendar_months_calendar_name UNIQUE (calendar_id, name),
            CONSTRAINT ck_calendar_months_number_positive CHECK (month_number > 0),
            CONSTRAINT ck_calendar_months_day_count_positive CHECK (day_count > 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.calendar_months IS
        'The months of a calendar, ordered by month_number. Both the ordinal and the '
        'name are unique within a calendar.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.calendar_months.month_number IS
        'Ordinal position within the year, starting at 1. Not a real-world month.';
    """)
    op.execute("""
        CREATE TRIGGER tr_calendar_months_set_updated_at
        BEFORE UPDATE ON core.calendar_months
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_calendar_months_calendar_id ON core.calendar_months (calendar_id);")

    # ==========================================================================
    # 4. core.world_times
    # ==========================================================================
    # `year` is a plain INTEGER, deliberately NOT core.nonnegative_integer:
    # fictional chronologies count backwards from an epoch as readily as
    # forwards, and "-300" is a perfectly ordinary year.
    #
    # sort_key is what makes fictional chronology orderable at all, and every
    # timeline and effective-state query will lean on it. It is NOT NULL on
    # purpose: a world time that cannot be ordered is useless to the queries
    # this platform is built around, so the caller is forced to decide where an
    # approximate or purely narrative moment sits. Computing it is
    # calendar-specific and belongs in the domain layer, which does not exist
    # yet — see docs/PLAN.md §19 (effective-state resolution).
    op.execute("""
        CREATE TABLE core.world_times (
            world_time_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id                 UUID NOT NULL
                                     REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            calendar_id              UUID
                                     REFERENCES core.calendars(calendar_id) ON DELETE RESTRICT,
            world_time_precision_id  UUID NOT NULL
                                     REFERENCES core.world_time_precisions(world_time_precision_id)
                                     ON DELETE RESTRICT,
            year                     INTEGER,
            month_number             core.nonnegative_integer,
            day                      core.nonnegative_integer,
            hour                     core.nonnegative_integer,
            minute                   core.nonnegative_integer,
            label                    TEXT,
            sort_key                 BIGINT NOT NULL,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- Precision cascades: a finer component is meaningless without the
            -- coarser one above it. Purely local, so expressible as CHECKs.
            CONSTRAINT ck_world_times_month_needs_year
                CHECK (month_number IS NULL OR year IS NOT NULL),
            CONSTRAINT ck_world_times_day_needs_month
                CHECK (day IS NULL OR month_number IS NOT NULL),
            CONSTRAINT ck_world_times_hour_needs_day
                CHECK (hour IS NULL OR day IS NOT NULL),
            CONSTRAINT ck_world_times_minute_needs_hour
                CHECK (minute IS NULL OR hour IS NOT NULL),

            -- A world time has to be *something*: either it sits on the calendar
            -- or it carries a narrative label.
            CONSTRAINT ck_world_times_year_or_label
                CHECK (year IS NOT NULL OR label IS NOT NULL),

            CONSTRAINT ck_world_times_month_range
                CHECK (month_number IS NULL OR month_number > 0),
            CONSTRAINT ck_world_times_day_range
                CHECK (day IS NULL OR day > 0),
            CONSTRAINT ck_world_times_hour_range CHECK (hour IS NULL OR hour < 24),
            CONSTRAINT ck_world_times_minute_range CHECK (minute IS NULL OR minute < 60)
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.world_times IS
        'A point or approximate period in fictional chronology (docs/DOMAIN_MODEL.md §6.2). '
        'Never a real-world timestamp — system time and world time must not be conflated '
        '(§6.3).';
    """)
    op.execute("""
        COMMENT ON COLUMN core.world_times.sort_key IS
        'Orderable position in fictional chronology. NOT NULL because a world time that '
        'cannot be ordered is useless to timeline and effective-state queries; the caller '
        'must decide where even an approximate or narrative moment sits. Computation is '
        'calendar-specific and belongs in the domain layer.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.world_times.year IS
        'Plain INTEGER, not a non-negative domain: fictional calendars count backwards '
        'from their epoch as readily as forwards.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.world_times.label IS
        'Relative narrative description, e.g. "shortly after the Sundering". Required when '
        'there is no calendar year.';
    """)
    op.execute("""
        CREATE TRIGGER tr_world_times_set_updated_at
        BEFORE UPDATE ON core.world_times
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_world_times_world_id ON core.world_times (world_id);")
    op.execute("CREATE INDEX ix_world_times_calendar_id ON core.world_times (calendar_id);")
    op.execute(
        "CREATE INDEX ix_world_times_world_time_precision_id "
        "ON core.world_times (world_time_precision_id);"
    )
    # The access pattern every timeline query uses: order within a world.
    op.execute("""
        CREATE INDEX ix_world_times_world_id_sort_key
        ON core.world_times (world_id, sort_key);
    """)

    # A calendar and the world times using it must belong to the same world.
    # Same class as DATABASE_MODEL.md §21 invariants 3-5. Not expressible as a
    # foreign key because calendar_id is nullable for narrative-only times.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_world_time_calendar_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_calendar_world UUID;
        BEGIN
            IF NEW.calendar_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_calendar_world
            FROM core.calendars WHERE calendar_id = NEW.calendar_id;

            IF v_calendar_world IS DISTINCT FROM NEW.world_id THEN
                RAISE EXCEPTION
                    'Calendar % belongs to world %, but the world time belongs to world %',
                    NEW.calendar_id, v_calendar_world, NEW.world_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_world_time_calendar_world() IS
        'Keeps a world time from referencing a calendar owned by a different world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_world_times_enforce_calendar_world
        BEFORE INSERT OR UPDATE ON core.world_times
        FOR EACH ROW EXECUTE FUNCTION core.enforce_world_time_calendar_world();
    """)

    # ==========================================================================
    # 5. core.worlds.default_calendar_id
    # ==========================================================================
    # Deferred from revision 004, which deliberately did not add this as an
    # unconstrained UUID before core.calendars existed.
    op.execute("""
        ALTER TABLE core.worlds
        ADD COLUMN default_calendar_id UUID
        REFERENCES core.calendars(calendar_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN core.worlds.default_calendar_id IS
        'The calendar to use when none is specified. Nullable: a world need not have '
        'defined one yet.';
    """)
    op.execute("CREATE INDEX ix_worlds_default_calendar_id ON core.worlds (default_calendar_id);")

    # ==========================================================================
    # 6. Seeds
    # ==========================================================================
    apply_seed(op, "core", "world_time_precisions")


def downgrade() -> None:
    """Revert the migration."""

    op.execute("ALTER TABLE core.worlds DROP COLUMN IF EXISTS default_calendar_id;")

    op.execute("DROP TABLE IF EXISTS core.world_times;")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_world_time_calendar_world();")
    op.execute("DROP TABLE IF EXISTS core.calendar_months;")
    op.execute("DROP TABLE IF EXISTS core.calendars;")
    op.execute("DROP TABLE IF EXISTS core.world_time_precisions;")
