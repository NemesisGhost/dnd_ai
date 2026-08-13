"""Encounter campaign/session ownership consistency

Revision ID: 081_encounter_session_scope
Revises: 080_security_identity_and_access
Create Date: 2026-08-13 12:00:00.000000

Purpose:
    Corrective revision. `narrative.encounters.campaign_id`/`.session_id`
    are both nullable foreign keys (revision 078) — a normal foreign key
    only proves a referenced `campaign.campaigns`/`campaign.sessions` row
    exists, never that it belongs to the *other* column's value.
    `narrative.enforce_encounter_world()` (revision 078) validates only
    same-world agreement (`location_id`/`world_time_id` against the
    timeline); it never checked `campaign_id` against `timeline_id`, or
    `session_id` against `campaign_id`. A caller authorized for campaign A
    (in world W) could therefore create an encounter naming campaign A but
    a `session_id` belonging to campaign B — also in world W, so the
    same-world guard never fires — producing a durable, silently accepted
    (HTTP 201) cross-campaign session linkage.

    This is exactly the gap `narrative.events` (revision 057,
    `enforce_event_consistency()`) and `interaction.interactions`
    (revision 061, `enforce_interaction_consistency()`) already closed for
    their own identically-shaped `campaign_id`/`session_id` pair —
    `narrative.encounters` is the one sibling table in this family that
    was missed. This revision brings it to parity, reusing the exact same
    two rules those functions already establish:

    1. `campaign_id`, when set, must belong to the encounter's own
       `timeline_id` (via `campaign.campaigns.timeline_id`).
    2. `session_id`, when set, must belong to `campaign_id` (via
       `campaign.sessions.campaign_id`) — and `campaign_id` must actually
       be set: a session always belongs to exactly one campaign
       (`campaign.sessions.campaign_id NOT NULL`, revision 011), so
       `campaign_id IS NULL` can never be the campaign a real session
       belongs to. `src/dnd_ai/commands/encounters.py`'s
       `_validate_session_campaign()`/`SessionNotInCampaignError` apply
       the identical rule in application code, ahead of this trigger,
       returning a fixed 404 for the normal case a request hits this;
       this migration is defense in depth for anything that reaches
       `narrative.encounters` outside that command (a future command,
       direct administrative SQL, or a bug in the application check).

    Reparenting: this revision does *not* need to make
    `narrative.encounters.campaign_id`/`.timeline_id` immutable to stay
    correct. `narrative.enforce_encounter_world()` is a `BEFORE INSERT OR
    UPDATE` trigger on `narrative.encounters` itself, so a direct UPDATE
    of either column re-validates immediately, at that UPDATE — unlike
    the "parent row's own scope changes out from under an already-valid
    *child* row that never re-validates" class of gap revisions 030/075/
    080 closed elsewhere (e.g. security.resource_grants scoping through
    campaign.sessions/narrative.events without either of those tables'
    own row changing). The two parent columns this revision's checks
    depend on are already immutable — `campaign.campaigns.timeline_id`
    (revision 030) and `campaign.sessions.campaign_id` (revision 080) —
    so neither a session's owning campaign nor a campaign's owning
    timeline can move out from under an already-valid encounter after the
    fact. No new reverse-mutation guard is added; this is a deliberate
    scoping decision, not an oversight (conventions §9.5's own "constraint
    triggers" + "command validation" combination is already satisfied by
    the trigger extended here plus campaign.sessions/campaign.campaigns'
    existing immutability).

    Concurrency: like every other same-world/same-scope guard in this
    project, this is a plain `BEFORE INSERT OR UPDATE` row trigger, not a
    constraint trigger needing `DEFERRABLE` semantics — it only reads
    already-committed rows in *other* tables (`campaign.campaigns`,
    `campaign.sessions`) that this revision's own reparenting analysis
    above shows cannot change in a way that would invalidate the check
    after the fact, so there is no ordering/timing window a deferred check
    would need to close.

    Sibling review (no additional gap found, so no further change made):
    `location_id`/`world_time_id` (same-world, `enforce_encounter_world()`
    itself) and `encounter_participants.participant_entity_id` (same-world,
    `enforce_encounter_participant_world()`) were already validated by
    revision 078's own triggers. `resulting_event_id` points at a
    `narrative.events` row created by `end_encounter()`/`_insert_event_row()`
    using the *encounter's own* `world_id`/`timeline_id`/`campaign_id`/
    `session_id`, which `enforce_event_consistency()` (revision 057)
    already validates independently on that row's own insert — a foreign-
    campaign `session_id` supplied to `end_encounter()`'s request body is
    already rejected there today (as a generic, non-disclosing 500, since
    no application-level pre-check exists for that path); no `narrative.
    encounters`-side change is needed for it to stay rejected, and adding a
    third, cross-endpoint fixed-404 pre-check for it is out of scope for
    this revision without a demonstrated case of it returning 200/201.

Forward migration:
    - A pre-flight audit (anonymous DO block): counts existing
      narrative.encounters rows that already violate either rule above and
      RAISEs, refusing to proceed, if any exist — this project has no live
      deployment yet (docs/PLAN.md "Current status"), so every real
      environment is expected to have zero, but the audit runs
      unconditionally rather than assuming that.
    - narrative.enforce_encounter_world(): CREATE OR REPLACE, extended
      with the two checks above. The existing BEFORE INSERT OR UPDATE
      trigger on narrative.encounters already points at this function by
      name, so no trigger changes are needed.

Rollback:
    Supported. CREATE OR REPLACE FUNCTION back to revision 078's original
    body (same-world checks only).

Data implications:
    None beyond the pre-flight audit — no row is modified. If the audit
    finds violations, the migration fails outright rather than silently
    reinterpreting or discarding existing data.

Locking considerations:
    CREATE OR REPLACE FUNCTION does not lock or rewrite narrative.
    encounters; the audit is a read-only SELECT.

SQLAlchemy metadata / architecture docs:
    src/dnd_ai/persistence/tables/encounters.py declares no CHECK
    constraints or triggers (see that module's own note — alembic check
    only compares tables/columns/comments, never trigger bodies), so no
    change is needed there. docs/architecture/DATABASE_MODEL.md §13 gained
    one sentence noting this invariant.

See: docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency)
     docs/architecture/DATABASE_MODEL.md §13 (encounters and combat)
     database/migrations/versions/057_narrative_events.py
     (narrative.enforce_event_consistency(), the precedent this revision
     mirrors)
     database/migrations/versions/061_interaction_domain.py
     (interaction.enforce_interaction_consistency(), the same precedent
     for interaction.interactions)
     database/migrations/versions/078_encounter_domain.py
     (narrative.enforce_encounter_world()'s original, same-world-only body)
     database/migrations/versions/030_parent_scope_immutability.py,
     database/migrations/versions/080_security_identity_and_access.py
     (campaign.campaigns.timeline_id and campaign.sessions.campaign_id
     immutability, why no new reverse-mutation guard is needed here)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "081_encounter_session_scope"
down_revision = "080_security_identity_and_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        DO $$
        DECLARE
            v_violations INTEGER;
        BEGIN
            SELECT count(*) INTO v_violations
            FROM narrative.encounters e
            WHERE (
                e.campaign_id IS NOT NULL
                AND (
                    SELECT c.timeline_id FROM campaign.campaigns c
                    WHERE c.campaign_id = e.campaign_id
                ) IS DISTINCT FROM e.timeline_id
            )
            OR (
                e.session_id IS NOT NULL
                AND (
                    e.campaign_id IS NULL
                    OR (
                        SELECT s.campaign_id FROM campaign.sessions s
                        WHERE s.session_id = e.session_id
                    ) IS DISTINCT FROM e.campaign_id
                )
            );

            IF v_violations > 0 THEN
                RAISE EXCEPTION
                    'narrative.encounters has % row(s) violating the campaign/timeline or '
                    'session/campaign ownership invariant this migration enables — resolve '
                    'them before upgrading to revision 081',
                    v_violations
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_encounter_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world    UUID;
            v_location_world    UUID;
            v_world_time_world  UUID;
            v_campaign_timeline UUID;
            v_session_campaign  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            IF NEW.location_id IS NOT NULL THEN
                SELECT world_id INTO v_location_world
                FROM core.entities WHERE entity_id = NEW.location_id;

                IF v_location_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Encounter % belongs to world %, but location_id % belongs to world %',
                        NEW.encounter_id, v_timeline_world, NEW.location_id, v_location_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            SELECT world_id INTO v_world_time_world
            FROM core.world_times WHERE world_time_id = NEW.world_time_id;

            IF v_world_time_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Encounter % belongs to world %, but world_time_id % belongs to world %',
                    NEW.encounter_id, v_timeline_world, NEW.world_time_id, v_world_time_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.campaign_id IS NOT NULL THEN
                SELECT timeline_id INTO v_campaign_timeline
                FROM campaign.campaigns WHERE campaign_id = NEW.campaign_id;

                IF v_campaign_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Encounter % campaign % belongs to timeline %, but the encounter '
                        'belongs to timeline %',
                        NEW.encounter_id, NEW.campaign_id, v_campaign_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.session_id IS NOT NULL THEN
                SELECT campaign_id INTO v_session_campaign
                FROM campaign.sessions WHERE session_id = NEW.session_id;

                IF NEW.campaign_id IS NULL OR v_session_campaign IS DISTINCT FROM NEW.campaign_id
                THEN
                    RAISE EXCEPTION
                        'Encounter % session % belongs to campaign %, but the encounter''s '
                        'campaign_id is %',
                        NEW.encounter_id, NEW.session_id, v_session_campaign, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_encounter_world() IS
        'Consistency guard for narrative.encounters: location_id and world_time_id, '
        'when set, must belong to the same world as the timeline (conventions §9.5); '
        'campaign_id, when set, must belong to the encounter''s own timeline; and '
        'session_id, when set, must belong to campaign_id — the same timeline -> '
        'campaign -> session chain narrative.enforce_event_consistency() (revision 057) '
        'and interaction.enforce_interaction_consistency() (revision 061) already '
        'require (revision 081).';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_encounter_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world    UUID;
            v_location_world    UUID;
            v_world_time_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            IF NEW.location_id IS NOT NULL THEN
                SELECT world_id INTO v_location_world
                FROM core.entities WHERE entity_id = NEW.location_id;

                IF v_location_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Encounter % belongs to world %, but location_id % belongs to world %',
                        NEW.encounter_id, v_timeline_world, NEW.location_id, v_location_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            SELECT world_id INTO v_world_time_world
            FROM core.world_times WHERE world_time_id = NEW.world_time_id;

            IF v_world_time_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Encounter % belongs to world %, but world_time_id % belongs to world %',
                    NEW.encounter_id, v_timeline_world, NEW.world_time_id, v_world_time_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_encounter_world() IS
        'Same-world guard for narrative.encounters: location_id and '
        'world_time_id, when set, must belong to the same world as the '
        'timeline (conventions §9.5).';
    """)
