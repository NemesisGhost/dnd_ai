"""Integration domain: external systems, external identifiers,
synchronization jobs, synchronization state, and delivery attempts.

Revision ID: 079_integration_domain
Revises: 078_encounter_domain
Create Date: 2026-08-09 18:00:00.000000

Purpose:
    Phase 9 ("Items, inventory, encounters, and Foundry integration
    contracts", docs/PLAN.md §23) delivers the database model for external
    identifiers and synchronization state
    (docs/architecture/DATABASE_MODEL.md §19). This is the third and final
    increment of the phase — item domain (revision 077) and encounters
    (revision 078) came first. Per the 2026-08-09 replan recorded in
    PLAN.md's Phase 9 entry, this increment builds the schema and command-
    layer contract an adapter (FoundryVTT, Discord, or otherwise) will call
    once a live API exists (Phase 10) — it does not stand up that API or
    deploy anything to AWS.

    The `integration` schema itself already existed (seeded, with default
    privileges wired, by revision 001) — this is the first revision to
    populate it.

    External IDs must never replace internal UUID identity
    (DATABASE_MODEL.md §19) — every table below anchors on entity_id/
    encounter_id, never the external system's own identifier alone.
    integration.external_systems is world-scoped (one row per external
    system connection a world has — a specific Foundry world, a specific
    Discord guild), the same way world.organizations or narrative.events
    ultimately trace back to one world; external_identifiers/.sync_jobs/.
    sync_state inherit their world indirectly through it.

    integration.sync_jobs and .sync_state target at most one of
    target_entity_id/target_encounter_id — the same "at-most-one-typed-
    target" shape narrative.event_effects/knowledge.knowledge_items/
    interaction.targets/narrative.quest_objectives/narrative.
    encounter_turns' combat_action_id established, extended here because a
    sync unit of work can be about either an entity (a character, an item
    instance) or an encounter (not entity-rooted, per revision 078).
    integration.sync_state additionally requires exactly one (never zero) —
    unlike a job, a *current sync state* row must always be about something.

    integration.sync_jobs.payload_jsonb holds the request payload used for
    both replay and idempotency-conflict comparison — an explicitly
    acceptable JSONB use per conventions §5.7 ("external API payload
    snapshot").

    integration.sync_jobs.external_operation_id (added in review, before
    this PR merged — see docs/PHASE9_VERIFICATION.md's correction-pass
    note) is a stable idempotency key an inbound job's external system
    supplies, unique per external_system_id
    (ux_sync_jobs_system_operation). The command layer
    (dnd_ai.commands.integration.apply_foundry_combat_sync()) uses a
    session-scoped Postgres advisory lock keyed on
    (external_system_id, external_operation_id) to fully serialize
    concurrent submissions of the same operation — by the time a second
    concurrent caller acquires the lock, the first has already reached a
    terminal sync_jobs.status and the second replays that result instead
    of re-executing the domain command. The unique index is the database-
    level backstop for that invariant, not the primary mechanism.
    resulting_encounter_turn_id lets a replay reconstruct the original
    ResolveCombatTurnResult (combat_action_id via the turn row, HP change
    via narrative.event_effects keyed off resulting_event_id) without
    re-running resolve_combat_turn().

    Second correction, before this PR merged (docs/PHASE9_VERIFICATION.md's
    "atomic completion" note): the two partial unique indexes on
    integration.sync_state — one per target column — are designed to be
    the target of an `INSERT ... ON CONFLICT (...) WHERE ... DO UPDATE`
    upsert from the command layer, not a SELECT-then-INSERT. Two different
    external_operation_ids racing to complete for the same target (the
    advisory lock above only serializes same-operation-id callers, not
    different ones) rely on Postgres serializing the two upserts at the
    row level through these indexes — whichever conflicts, blocks on the
    other's row lock, and applies its own update once free. This is why
    both indexes stayed partial UNIQUE indexes rather than being merged
    into one general-purpose index or loosened: the upsert's conflict
    target must exactly match one specific index (columns and predicate)
    per PostgreSQL's inference rules, and a target-scoped partial index is
    exactly what makes that inference unambiguous per target type.

    Third correction, before this PR merged (docs/PHASE9_VERIFICATION.md's
    "single-connection" note): no schema change, but worth recording here
    since it changes how the command layer's advisory lock interacts with
    connection pooling. The second correction's claim/work/fail steps each
    opened their own connection via engine.begin() while the advisory-lock
    connection sat idle for the whole call — under a small connection pool,
    a caller waiting on the lock could exhaust the pool's remaining
    connections and leave the lock holder itself unable to obtain one for
    its own steps, a self-inflicted deadlock. apply_foundry_combat_sync()
    now runs all three steps as sequential transactions on the same
    connection that holds the lock, so one call never needs more than a
    single pooled connection for its entire duration. The same pass
    hardened lock release: if pg_advisory_unlock()'s result can't confirm
    the lock was actually released (or the unlock statement itself raises),
    the connection is invalidated rather than returned to the pool, so a
    still-held session-scoped lock can never be silently inherited by a
    future caller.

Forward migration:
    - integration.external_systems (world-scoped), with
      integration.enforce_external_system_world() — trivial (world_id is
      its own column, no cross-table check needed), included only for
      symmetry-of-pattern; see deliberate scoping decisions
    - integration.external_identifiers, with
      integration.enforce_external_identifier_world()
    - integration.sync_jobs, with integration.enforce_sync_job_world();
      external_operation_id + resulting_encounter_turn_id +
      ux_sync_jobs_system_operation added in the same correction pass that
      added the docstring paragraph above
    - integration.sync_state, with integration.enforce_sync_state_world()
    - integration.delivery_attempts (child of sync_jobs, no world check of
      its own needed — it has no reference beyond sync_job_id)

Rollback:
    Supported. Drops everything created here in FK-dependency order.

Data implications:
    Creates no rows.

Locking considerations:
    Every statement creates a new, empty object.

Deliberate scoping decisions:
    - integration.external_systems has no enforce_*_world() trigger in
      practice (world_id is a plain column with a normal FK, not derived
      through any other reference), so no world-agreement function is
      actually created for it — listed above only to make explicit that it
      was considered and found unnecessary, not overlooked.
    - external_kind (external_identifiers) and job_type (sync_jobs) are
      free TEXT with only a length guard, not a CHECK-constrained closed
      set — unlike action_kind/rarity/identification_level elsewhere in
      this project, the vocabulary genuinely varies per external system
      (Foundry's actor/scene/journal/token is not Discord's or MCP's), so a
      single shared enum would either be wrong for most systems or need to
      keep growing. A per-system_type lookup table would be the more
      correct long-term shape but has no concrete caller yet (conventions
      §33.1) — revisit once a second real external_system_type is actually
      integrated.
    - No entity-rooted "external system" concept and no CTI — external
      systems are configuration/connection records, not world entities
      with discoverable in-fiction identity.
    - sync_state's one-current-row-per-target invariant is enforced with
      two partial unique indexes (one per target column), the same shape
      campaign.relationship_state used for its nullable
      perspective_holder_entity_id dimension (revision 076), rather than a
      single expression index — partial indexes read more directly here
      given the CHECK already guarantees exactly one target is set.
    - external_operation_id has no CHECK-constrained format (unlike
      lookup codes elsewhere) — it is an opaque identifier the external
      system chooses, not a code this platform defines.
    - Replaying an operation id whose prior sync_jobs row is still
      'failed' (or, in the crash-recovery case, stuck 'in_progress' with
      no other transaction currently holding its advisory lock) is treated
      as a retry of the same job row — a new integration.delivery_attempts
      row with an incremented attempt_number, not a new sync_jobs row —
      but only when the replay's canonical payload matches the payload
      originally recorded for that operation id exactly. The payload-
      equality check (dnd_ai.commands.integration.
      ConflictingSyncPayloadError) runs unconditionally, before status is
      even consulted, so it applies to a 'failed' row exactly as it does to
      a 'completed' one: every payload mismatch under a reused operation id
      is a conflict, full stop, never a silent retry with new arguments.
      Only a same-payload retry of a job that never actually succeeded
      reaches delivery_attempts's incremented attempt_number (its own
      table comment already says so).

See: docs/PLAN.md Phase 9 (items, inventory, encounters, Foundry integration
     contracts)
     docs/architecture/DATABASE_MODEL.md §19 (security, audit and
     integration)
     docs/architecture/SYSTEM_ARCHITECTURE.md §15 (integration architecture)
     docs/DATABASE_CONVENTIONS.md §5.7 (JSONB), §9.5 (same-world
     consistency)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "079_integration_domain"
down_revision = "078_encounter_domain"
branch_labels = None
depends_on = None

EXTERNAL_SYSTEM_TYPES = ("foundry", "discord", "mcp", "other")
SYNC_JOB_DIRECTIONS = ("inbound", "outbound")
SYNC_JOB_STATUSES = ("pending", "in_progress", "completed", "failed")
SYNC_STATUSES = ("unsynced", "synced", "conflict", "stale")


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. integration.external_systems
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE integration.external_systems (
            external_system_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id                UUID NOT NULL
                                   REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            system_type               TEXT NOT NULL,
            display_name                 TEXT NOT NULL,
            external_reference              TEXT,
            is_active                          BOOLEAN NOT NULL DEFAULT true,
            created_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_external_systems_system_type CHECK (
                system_type IN {EXTERNAL_SYSTEM_TYPES}
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE integration.external_systems IS
        'A configured external system connection for a world — a specific '
        'Foundry world, a specific Discord guild (docs/architecture/'
        'DATABASE_MODEL.md §19). external_reference is that system''s own '
        'identifier for the connection (a Foundry world ID, a Discord guild '
        'ID), free-text since it varies by system_type.';
    """)
    op.execute("""
        CREATE TRIGGER tr_external_systems_set_updated_at
        BEFORE UPDATE ON integration.external_systems
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_external_systems_world_id ON integration.external_systems (world_id);"
    )
    op.execute(
        "CREATE INDEX ix_external_systems_system_type "
        "ON integration.external_systems (system_type);"
    )

    # ==========================================================================
    # 2. integration.external_identifiers
    # ==========================================================================
    op.execute("""
        CREATE TABLE integration.external_identifiers (
            external_identifier_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            external_system_id         UUID NOT NULL
                                      REFERENCES integration.external_systems(external_system_id)
                                      ON DELETE CASCADE,
            entity_id                    UUID NOT NULL
                                      REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            external_kind                  TEXT NOT NULL,
            external_id                      TEXT NOT NULL,
            last_synced_at                     TIMESTAMPTZ,
            created_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_external_identifiers_system_kind_external UNIQUE (
                external_system_id, external_kind, external_id
            ),
            CONSTRAINT ck_external_identifiers_kind_length
                CHECK (char_length(external_kind) BETWEEN 1 AND 100),
            CONSTRAINT ck_external_identifiers_external_id_length
                CHECK (char_length(external_id) BETWEEN 1 AND 500)
        );
    """)
    op.execute("""
        COMMENT ON TABLE integration.external_identifiers IS
        'Maps an internal entity to its representation in an external '
        'system — a Foundry actor/scene/journal/token, a Discord user/'
        'channel (docs/architecture/SYSTEM_ARCHITECTURE.md §15.1). External '
        'IDs must never replace internal UUID identity '
        '(docs/architecture/DATABASE_MODEL.md §19) — every other domain '
        'table continues to reference entity_id, never external_id. One '
        'entity may have several rows here (e.g. both an ''actor'' and a '
        '''token'' mapping in the same system).';
    """)
    op.execute("""
        COMMENT ON COLUMN integration.external_identifiers.external_kind IS
        'The external system''s own category for this mapping (actor, '
        'scene, journal, token, ...) — free text, not a CHECK-constrained '
        'set, since the vocabulary varies per system_type (see this '
        'revision''s docstring).';
    """)
    op.execute("""
        CREATE TRIGGER tr_external_identifiers_set_updated_at
        BEFORE UPDATE ON integration.external_identifiers
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_external_identifiers_external_system_id "
        "ON integration.external_identifiers (external_system_id);"
    )
    op.execute(
        "CREATE INDEX ix_external_identifiers_entity_id "
        "ON integration.external_identifiers (entity_id);"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION integration.enforce_external_identifier_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_system_world  UUID;
            v_entity_world  UUID;
        BEGIN
            SELECT world_id INTO v_system_world
            FROM integration.external_systems WHERE external_system_id = NEW.external_system_id;

            SELECT world_id INTO v_entity_world
            FROM core.entities WHERE entity_id = NEW.entity_id;

            IF v_entity_world IS DISTINCT FROM v_system_world THEN
                RAISE EXCEPTION
                    'External system % belongs to world %, but entity % belongs to world %',
                    NEW.external_system_id, v_system_world, NEW.entity_id, v_entity_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION integration.enforce_external_identifier_world() IS
        'Same-world guard for integration.external_identifiers (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_external_identifiers_enforce_world
        BEFORE INSERT OR UPDATE ON integration.external_identifiers
        FOR EACH ROW EXECUTE FUNCTION integration.enforce_external_identifier_world();
    """)

    # ==========================================================================
    # 3. integration.sync_jobs
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE integration.sync_jobs (
            sync_job_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            external_system_id      UUID NOT NULL
                                   REFERENCES integration.external_systems(external_system_id)
                                   ON DELETE CASCADE,
            direction                  TEXT NOT NULL,
            job_type                     TEXT NOT NULL,
            target_entity_id                UUID
                                   REFERENCES core.entities(entity_id) ON DELETE SET NULL,
            target_encounter_id                UUID
                                   REFERENCES narrative.encounters(encounter_id)
                                   ON DELETE SET NULL,
            status                                TEXT NOT NULL DEFAULT 'pending',
            payload_jsonb                           JSONB,
            error_message                             TEXT,
            resulting_event_id                          UUID
                                   REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            resulting_encounter_turn_id                    UUID
                                   REFERENCES narrative.encounter_turns(encounter_turn_id)
                                   ON DELETE SET NULL,
            external_operation_id                             TEXT,
            created_at                                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sync_jobs_direction CHECK (direction IN {SYNC_JOB_DIRECTIONS}),
            CONSTRAINT ck_sync_jobs_status CHECK (status IN {SYNC_JOB_STATUSES}),
            CONSTRAINT ck_sync_jobs_job_type_length CHECK (char_length(job_type) BETWEEN 1 AND 100),
            CONSTRAINT ck_sync_jobs_at_most_one_target CHECK (
                num_nonnulls(target_entity_id, target_encounter_id) <= 1
            ),
            CONSTRAINT ck_sync_jobs_external_operation_id_length CHECK (
                external_operation_id IS NULL
                OR char_length(external_operation_id) BETWEEN 1 AND 500
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE integration.sync_jobs IS
        'One unit of synchronization work between an external system and '
        'the platform — inbound (a Foundry combat action submitted) or '
        'outbound (pushing updated HP back to Foundry), per '
        'docs/architecture/DATABASE_MODEL.md §19. At most one of '
        'target_entity_id/target_encounter_id is set; a job with neither '
        'is valid (e.g. an initial connection handshake with no single '
        'subject yet).';
    """)
    op.execute("""
        COMMENT ON COLUMN integration.sync_jobs.payload_jsonb IS
        'The request payload used for both replay and idempotency-conflict '
        'comparison — an explicitly acceptable JSONB use (conventions '
        '§5.7). For inbound jobs with an external_operation_id, this is '
        'the canonicalized set of command arguments (not only the raw '
        'external payload) so a replay with a different payload under the '
        'same operation id can be detected. Never the sole record of a '
        'state change: a job that mutates persistent state does so '
        'through the normal command layer (rule 6), which records its own '
        'causal event; resulting_event_id links back to that event when '
        'there was one.';
    """)
    op.execute("""
        COMMENT ON COLUMN integration.sync_jobs.resulting_encounter_turn_id IS
        'The narrative.encounter_turns row this job produced, when it '
        'produced one — lets a replayed job (same external_system_id, '
        'external_operation_id) reconstruct its original result '
        '(combat_action_id via the turn, HP change via '
        'narrative.event_effects keyed off resulting_event_id) without '
        're-executing the domain command.';
    """)
    op.execute("""
        COMMENT ON COLUMN integration.sync_jobs.external_operation_id IS
        'A stable idempotency key the external system supplies for an '
        'inbound job (e.g. a Foundry combat-turn operation id) — unique '
        'per external_system_id (ux_sync_jobs_system_operation, below), so '
        'redelivering the same operation is detected as a replay rather '
        'than re-applied. NULL for job types with no external-supplied '
        'operation identity (e.g. outbound jobs this platform itself '
        'initiates).';
    """)
    op.execute("""
        CREATE TRIGGER tr_sync_jobs_set_updated_at
        BEFORE UPDATE ON integration.sync_jobs
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_sync_jobs_external_system_id ON integration.sync_jobs (external_system_id);"
    )
    op.execute("CREATE INDEX ix_sync_jobs_status ON integration.sync_jobs (status);")
    op.execute(
        "CREATE INDEX ix_sync_jobs_target_entity_id ON integration.sync_jobs (target_entity_id) "
        "WHERE target_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_sync_jobs_target_encounter_id "
        "ON integration.sync_jobs (target_encounter_id) WHERE target_encounter_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_sync_jobs_resulting_event_id ON integration.sync_jobs (resulting_event_id) "
        "WHERE resulting_event_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_sync_jobs_resulting_encounter_turn_id "
        "ON integration.sync_jobs (resulting_encounter_turn_id) "
        "WHERE resulting_encounter_turn_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_sync_jobs_system_operation
        ON integration.sync_jobs (external_system_id, external_operation_id)
        WHERE external_operation_id IS NOT NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION integration.enforce_sync_job_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_system_world     UUID;
            v_entity_world     UUID;
            v_encounter_world  UUID;
        BEGIN
            SELECT world_id INTO v_system_world
            FROM integration.external_systems WHERE external_system_id = NEW.external_system_id;

            IF NEW.target_entity_id IS NOT NULL THEN
                SELECT world_id INTO v_entity_world
                FROM core.entities WHERE entity_id = NEW.target_entity_id;

                IF v_entity_world IS DISTINCT FROM v_system_world THEN
                    RAISE EXCEPTION
                        'Sync job % belongs to world %, but target_entity_id % belongs to world %',
                        NEW.sync_job_id, v_system_world, NEW.target_entity_id, v_entity_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.target_encounter_id IS NOT NULL THEN
                SELECT t.world_id INTO v_encounter_world
                FROM narrative.encounters e
                JOIN campaign.timelines t ON t.timeline_id = e.timeline_id
                WHERE e.encounter_id = NEW.target_encounter_id;

                IF v_encounter_world IS DISTINCT FROM v_system_world THEN
                    RAISE EXCEPTION
                        'Sync job % belongs to world %, but target_encounter_id % belongs to '
                        'world %',
                        NEW.sync_job_id, v_system_world, NEW.target_encounter_id, v_encounter_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION integration.enforce_sync_job_world() IS
        'Same-world guard for integration.sync_jobs: whichever target_* '
        'column is set must belong to the same world as the external '
        'system (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_sync_jobs_enforce_world
        BEFORE INSERT OR UPDATE ON integration.sync_jobs
        FOR EACH ROW EXECUTE FUNCTION integration.enforce_sync_job_world();
    """)

    # ==========================================================================
    # 4. integration.sync_state
    # ==========================================================================
    op.execute(f"""
        CREATE TABLE integration.sync_state (
            sync_state_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            external_system_id      UUID NOT NULL
                                   REFERENCES integration.external_systems(external_system_id)
                                   ON DELETE CASCADE,
            target_entity_id           UUID
                                   REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            target_encounter_id           UUID
                                   REFERENCES narrative.encounters(encounter_id) ON DELETE CASCADE,
            last_sync_job_id                 UUID
                                   REFERENCES integration.sync_jobs(sync_job_id) ON DELETE SET NULL,
            last_synced_at                     TIMESTAMPTZ,
            sync_status                           TEXT NOT NULL DEFAULT 'unsynced',
            created_at                               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sync_state_status CHECK (sync_status IN {SYNC_STATUSES}),
            CONSTRAINT ck_sync_state_exactly_one_target CHECK (
                num_nonnulls(target_entity_id, target_encounter_id) = 1
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE integration.sync_state IS
        'Current synchronization status for one target (an entity or an '
        'encounter) against one external system — distinct from '
        'integration.sync_jobs, which logs each individual unit of work '
        '(docs/architecture/DATABASE_MODEL.md §19). Exactly one of '
        'target_entity_id/target_encounter_id is set, unlike sync_jobs '
        'where neither may be set — a current sync-state row must always '
        'be about something. One current row per (external system, '
        'target) — see the partial unique indexes below.';
    """)
    op.execute("""
        CREATE TRIGGER tr_sync_state_set_updated_at
        BEFORE UPDATE ON integration.sync_state
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_sync_state_external_system_id ON integration.sync_state (external_system_id);"
    )
    op.execute(
        "CREATE INDEX ix_sync_state_target_entity_id ON integration.sync_state (target_entity_id) "
        "WHERE target_entity_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_sync_state_target_encounter_id "
        "ON integration.sync_state (target_encounter_id) WHERE target_encounter_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_sync_state_last_sync_job_id ON integration.sync_state (last_sync_job_id) "
        "WHERE last_sync_job_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_sync_state_system_entity
        ON integration.sync_state (external_system_id, target_entity_id)
        WHERE target_entity_id IS NOT NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_sync_state_system_encounter
        ON integration.sync_state (external_system_id, target_encounter_id)
        WHERE target_encounter_id IS NOT NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION integration.enforce_sync_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_system_world     UUID;
            v_entity_world     UUID;
            v_encounter_world  UUID;
        BEGIN
            SELECT world_id INTO v_system_world
            FROM integration.external_systems WHERE external_system_id = NEW.external_system_id;

            IF NEW.target_entity_id IS NOT NULL THEN
                SELECT world_id INTO v_entity_world
                FROM core.entities WHERE entity_id = NEW.target_entity_id;

                IF v_entity_world IS DISTINCT FROM v_system_world THEN
                    RAISE EXCEPTION
                        'Sync state % belongs to world %, but target_entity_id % belongs to world %',
                        NEW.sync_state_id, v_system_world, NEW.target_entity_id, v_entity_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.target_encounter_id IS NOT NULL THEN
                SELECT t.world_id INTO v_encounter_world
                FROM narrative.encounters e
                JOIN campaign.timelines t ON t.timeline_id = e.timeline_id
                WHERE e.encounter_id = NEW.target_encounter_id;

                IF v_encounter_world IS DISTINCT FROM v_system_world THEN
                    RAISE EXCEPTION
                        'Sync state % belongs to world %, but target_encounter_id % belongs to '
                        'world %',
                        NEW.sync_state_id, v_system_world, NEW.target_encounter_id,
                        v_encounter_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION integration.enforce_sync_state_world() IS
        'Same-world guard for integration.sync_state: whichever target_* '
        'column is set must belong to the same world as the external '
        'system (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_sync_state_enforce_world
        BEFORE INSERT OR UPDATE ON integration.sync_state
        FOR EACH ROW EXECUTE FUNCTION integration.enforce_sync_state_world();
    """)

    # ==========================================================================
    # 5. integration.delivery_attempts (child of sync_jobs)
    # ==========================================================================
    op.execute("""
        CREATE TABLE integration.delivery_attempts (
            delivery_attempt_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sync_job_id              UUID NOT NULL
                                    REFERENCES integration.sync_jobs(sync_job_id) ON DELETE CASCADE,
            attempt_number              core.nonnegative_integer NOT NULL DEFAULT 1,
            attempted_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            succeeded                        BOOLEAN NOT NULL,
            response_summary                   TEXT,
            CONSTRAINT ux_delivery_attempts_job_attempt UNIQUE (sync_job_id, attempt_number)
        );
    """)
    op.execute("""
        COMMENT ON TABLE integration.delivery_attempts IS
        'One retry attempt for a sync job — timestamp, success, and a '
        'short response summary (docs/architecture/DATABASE_MODEL.md §19). '
        'Append-only; a sync job that fails and is retried gets a second '
        'row with attempt_number incremented, not an update to the first.';
    """)
    op.execute(
        "CREATE INDEX ix_delivery_attempts_sync_job_id "
        "ON integration.delivery_attempts (sync_job_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS integration.delivery_attempts;")

    op.execute("DROP TABLE IF EXISTS integration.sync_state;")
    op.execute("DROP FUNCTION IF EXISTS integration.enforce_sync_state_world();")

    op.execute("DROP TABLE IF EXISTS integration.sync_jobs;")
    op.execute("DROP FUNCTION IF EXISTS integration.enforce_sync_job_world();")

    op.execute("DROP TABLE IF EXISTS integration.external_identifiers;")
    op.execute("DROP FUNCTION IF EXISTS integration.enforce_external_identifier_world();")

    op.execute("DROP TABLE IF EXISTS integration.external_systems;")
