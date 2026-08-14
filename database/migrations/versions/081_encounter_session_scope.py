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

    Reparenting — corrected (same still-unreleased revision; this branch
    has not merged to main, so this is amended in place rather than
    spawning a new revision number, the same "correction pass" convention
    Phase 7's revision 074 followed while still unmerged — see CLAUDE.md
    §2): the paragraph below (kept for the historical record of what was
    argued and why it was wrong) reasoned that `narrative.encounters.
    campaign_id` did not need to be immutable because
    `narrative.enforce_encounter_world()` re-validates on every UPDATE.
    That is true, but incomplete: it only re-validates the *encounter
    row's own* internal consistency (its `campaign_id` against its
    `timeline_id`, its `session_id` against its `campaign_id`) — it says
    nothing about rows in *other* tables that were already created
    *because of* the encounter's campaign at the time. Once `src/dnd_ai/
    commands/encounters.py`'s `resolve_combat_turn()`/`end_encounter()`
    stamp an `interaction.interactions` row or a `narrative.events` row
    (cited back via `narrative.event_causes.cause_encounter_id` or
    `narrative.encounters.resulting_event_id`) with the encounter's
    campaign at that moment, a later `UPDATE narrative.encounters SET
    campaign_id = ...` reparenting the encounter to a different,
    same-timeline campaign succeeds cleanly (this trigger has nothing to
    say about it) while those already-created rows keep pointing at the
    *old* campaign — exactly the "parent row's own scope changes out from
    under an already-valid child row that never re-validates" class of
    gap this paragraph explicitly (and, it turns out, wrongly) claimed
    did not apply here. It does apply — one hop further out, through
    `narrative.encounters` as an intermediate parent, rather than
    directly through `campaign.sessions`/`campaign.campaigns` the way
    revisions 030/075/080 closed it elsewhere. The fix is the same shape
    those revisions already established: make the column immutable
    (`Corrected forward migration` below), rather than build a
    transactional cascade-and-revalidate path for a change — reparenting
    an encounter already in play — that should not happen in the first
    place. See "Corrected forward migration" for why this needed a
    *bespoke* trigger rather than reusing `core.enforce_immutable_columns()`
    (revision 030/033) directly.

    Reparenting — corrected again (same still-unreleased revision): the
    first correction pass above made `campaign_id` immutable but left
    `timeline_id` mutable, reasoning (wrongly, in the now-superseded
    paragraph below) that campaign-owned encounters were adequately
    protected *indirectly* — `campaign_id`'s own immutability plus
    `enforce_encounter_world()`'s existing "campaign must belong to
    timeline" check together mean a campaign-owned encounter's
    `timeline_id` can never actually move without also changing
    `campaign_id` (which is blocked). That reasoning has a gap: it says
    nothing about a *campaign-less* encounter (`campaign_id IS NULL`),
    which has no campaign relationship to indirectly pin its timeline
    down. `enforce_encounter_world()` only re-validates same-world
    agreement — moving such an encounter to a *different timeline in the
    same world* passes every existing check cleanly, while the
    `interaction.interactions`/`narrative.events` rows its turns/
    completion already created stay on the *original* timeline. This is
    the exact same "parent row's own scope changes out from under an
    already-valid child row" shape the `campaign_id` fix above closes —
    just for the one column that fix didn't cover. `timeline_id` is now
    immutable too, merged into the *same* trigger/function as
    `campaign_id` (renamed `enforce_encounter_identity_immutable()` /
    `tr_encounters_identity_immutable`, from `enforce_encounter_
    campaign_immutable()`/`tr_encounters_campaign_immutable`) rather than
    a second, separate trigger: both columns are now identical in shape
    ("reject any change, full stop, including NULL <-> value for
    campaign_id") and both exist to protect the exact same class of
    already-created dependent rows, so one clearly-named "encounter
    identity is fixed at creation" guard covers both, instead of two
    near-duplicate ones a reader would have to notice enforce the same
    idea. The corrected pre-flight audit (below) is extended the same
    way: every place it already checked `campaign_id` agreement now also
    checks `timeline_id` agreement, since a pre-existing corrupted row
    could disagree on either column independently.

    Session review (same correction pass, no code change): is
    `narrative.encounters.session_id` exposed to the same risk, and
    should it be made immutable too? No — unlike `timeline_id`/
    `campaign_id`, nothing derives its *own* session scope from the
    encounter's `session_id`. `_resolve_combat_turn_impl()`/
    `_end_encounter_impl()` (`src/dnd_ai/commands/encounters.py`) each
    take their *own* `session_id` argument for the `interaction.
    interactions`/`narrative.events` row they create, independent of
    whatever `narrative.encounters.session_id` holds and deliberately
    never inherited from it (documented on those functions themselves —
    an encounter can span more than one `campaign.sessions` row over its
    life, so inheriting the encounter's *starting* session onto a turn
    played in a later one would misattribute it). `narrative.encounters.
    session_id` therefore records one fact only — which session the
    encounter was *started* in — that no other row's own provenance is
    built on top of; changing it later cannot orphan anything the way
    `timeline_id`/`campaign_id` could. It remains ordinary, freely
    mutable metadata, still revalidated against `campaign_id` on every
    UPDATE by `enforce_encounter_world()` (unchanged). `location_id` was
    considered on the same basis and excluded for the same reason: no
    other row's provenance derives its own location from an encounter's
    `location_id` either. Per this project's own proportional-scope
    convention, neither is protected without a concrete invariant to
    protect.

    Reparenting — original (superseded) analysis, kept for the record:
    this revision does *not* need to make `narrative.encounters.
    campaign_id`/`.timeline_id` immutable to stay correct.
    `narrative.enforce_encounter_world()` is a `BEFORE INSERT OR UPDATE`
    trigger on `narrative.encounters` itself, so a direct UPDATE of
    either column re-validates immediately, at that UPDATE — unlike the
    "parent row's own scope changes out from under an already-valid
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

    Concurrency (steady state, after this migration has committed): like
    every other same-world/same-scope guard in this project, this is a
    plain `BEFORE INSERT OR UPDATE` row trigger, not a constraint trigger
    needing `DEFERRABLE` semantics — it only reads already-committed rows
    in *other* tables (`campaign.campaigns`, `campaign.sessions`) that
    this revision's own reparenting analysis above shows cannot change in
    a way that would invalidate the check after the fact, so there is no
    ordering/timing window a deferred check would need to close.

    Concurrency (during this migration's own upgrade): closed by a
    dedicated `LOCK TABLE narrative.encounters IN SHARE MODE` — see
    "Locking considerations" below for the full account. In short: the
    pre-flight audit and `CREATE OR REPLACE FUNCTION` are two separate
    statements, and `CREATE OR REPLACE FUNCTION` takes no lock whatsoever
    on `narrative.encounters` (it only locks the function's own catalog
    entry) — so without an explicit table lock, a concurrent writer
    (a rolling-deployment application instance still running the *old*
    trigger definition, or any other session) could `INSERT`/`UPDATE` a
    row that violates this revision's new rule in the window between the
    audit observing zero violations and the new function definition
    becoming visible, commit before this migration does, and leave that
    invalid row in place permanently — the audit already ran and saw
    nothing wrong, and the new function only validates rows written
    *after* it takes effect, never retroactively.

    Sibling review (no additional `narrative.encounters`-side gap found, so
    no further change was made *here*): `location_id`/`world_time_id`
    (same-world, `enforce_encounter_world()` itself) and
    `encounter_participants.participant_entity_id` (same-world,
    `enforce_encounter_participant_world()`) were already validated by
    revision 078's own triggers. `resulting_event_id` points at a
    `narrative.events` row created by `end_encounter()`/`_insert_event_row()`
    using its own `world_id`/`timeline_id` plus the *caller-supplied*
    `campaign_id`/`session_id`, which `enforce_event_consistency()`
    (revision 057) already validates independently on that row's own
    insert; `_resolve_combat_turn_impl()`'s own `campaign_id`/`session_id`
    land on the `interaction.interactions` row it creates, guarded the same
    way by `interaction.enforce_interaction_consistency()` (revision 061).
    At the time this revision first shipped, a foreign-campaign
    `session_id` supplied to either of those two commands' request bodies
    was already rejected by those *existing* database triggers, but only
    as a generic, non-disclosing 500 — no application-level pre-check
    existed for either path yet. `_validate_session_campaign()`
    (`src/dnd_ai/commands/encounters.py`) is now called from
    `_resolve_combat_turn_impl()` and `_end_encounter_impl()` too, not just
    `_start_encounter_impl()`, upgrading both to the same clean, fixed 404
    — closing that gap in application code, not by changing anything about
    `narrative.encounters` or this migration.

    Sibling review, correction pass: `integration.sync_jobs`/`.sync_state`
    (revision 079) also reference `target_encounter_id`, but neither table
    has a `campaign_id` or `timeline_id` column at all — Phase 9's
    integration domain scopes an external system to a `world_id` only
    (see that revision, and `dnd_ai.commands.integration.
    apply_foundry_combat_sync()`'s own docstring on why its combat-turn
    calls stay unscoped until Phase 11). There is no column there for a
    reparented encounter to leave stale, so the audit and the
    immutability guard below both correctly stop at `interaction.
    interactions`/`narrative.events`/`narrative.event_causes`/`narrative.
    encounters.resulting_event_id` — every table in this domain that
    *does* carry `campaign_id`/`timeline_id`.

Corrected forward migration (folded into this same upgrade(), after the
original three steps below):
    - A second pre-flight audit (anonymous DO block), under the same
      LOCK TABLE already held: counts existing narrative.encounters rows
      whose dependent interaction.interactions (reached through
      encounter_rounds -> encounter_turns -> combat_actions -> actions),
      narrative.events (reached through event_causes.cause_encounter_id),
      or resulting_event_id's own narrative.events row already disagree
      with the encounter's own timeline_id *or* campaign_id (IS DISTINCT
      FROM either) — the durable orphaned-provenance state a past
      reparenting UPDATE (only ever exercised by this project's own
      tests, never by any command — see "Reparenting — corrected"/
      "corrected again" above) could have left behind. RAISEs, refusing
      to proceed, if any exist; this project has no live deployment yet
      (docs/PLAN.md "Current status"), so every real environment is
      expected to have zero, but the audit runs unconditionally rather
      than assuming that, the same as the original audit above.
    - narrative.enforce_encounter_identity_immutable(): a new, bespoke
      BEFORE UPDATE trigger function on narrative.encounters, rejecting
      any UPDATE where NEW.timeline_id IS DISTINCT FROM OLD.timeline_id
      or NEW.campaign_id IS DISTINCT FROM OLD.campaign_id — timeline_id
      checked first, so a caller that tries to move both together sees
      the timeline_id violation — deliberately *not* core.
      enforce_immutable_columns() (revision 030/033): that shared
      function's current body only blocks a change away from an
      already-non-NULL value, explicitly allowing one NULL -> value
      transition (see tests/database/test_immutable_identity.py::
      test_a_features_null_association_can_still_be_set_once) — the right
      behavior for a column like rules.features.class_id, which starts
      unset and is filled in once. narrative.encounters.campaign_id is
      different in kind: "no campaign" (NULL, a GM-only/campaign-less
      encounter) is itself a meaningful, permanent identity choice made at
      creation, not a placeholder awaiting a value — so a NULL -> value
      transition must be rejected exactly like a value -> value one, which
      the shared function does not do and was not changed to do (that
      would alter behavior for every one of its ~15 other existing
      callers); timeline_id is never NULL to begin with, so it needs no
      such distinction, but is checked by the same function for the one-
      trigger-covers-both-columns reason explained under "Reparenting —
      corrected again" above. Attached as tr_encounters_identity_immutable
      — sorts alphabetically before the existing tr_encounters_enforce_world
      and tr_encounters_set_updated_at (revision 078), though firing order
      between the two BEFORE UPDATE triggers is immaterial here: they
      enforce independent, non-conflicting rules, and a reparenting UPDATE
      this new trigger rejects never reaches enforce_encounter_world()'s
      own (unrelated) checks either way.

Rollback:
    Supported. CREATE OR REPLACE FUNCTION back to revision 078's original
    body (same-world checks only). Deliberately does *not* take the same
    LOCK TABLE the forward migration does — downgrade only *weakens* the
    trigger and runs no audit, so there is no analogous "audit observed a
    clean state that a concurrent writer then invalidates before the
    stricter definition takes effect" race for it to close; see
    "Locking considerations" for the full asymmetry argument.

    Corrected rollback (same reasoning, extended): also DROPs
    tr_encounters_identity_immutable and narrative.
    enforce_encounter_identity_immutable() — downgrading restores
    timeline_id's and campaign_id's original mutability, the same
    "downgrade only weakens" asymmetry as the rest of this migration's
    rollback, so no LOCK TABLE is needed for this half either.

Data implications:
    None beyond the pre-flight audits — no row is modified by either. If
    an audit finds violations, the migration fails outright rather than
    silently reinterpreting or discarding existing data.

Locking considerations:
    LOCK TABLE narrative.encounters IN SHARE ROW EXCLUSIVE MODE runs
    first, before the audit, and is held for the rest of this migration's
    transaction — through both audits, both CREATE OR REPLACE FUNCTION
    calls, CREATE TRIGGER, and this migration's own commit (Alembic runs
    one revision's upgrade() inside one transaction; PostgreSQL releases
    an explicit LOCK TABLE only at COMMIT/ROLLBACK, never earlier, and
    never implicitly re-acquires or drops it mid-transaction). This is
    SHARE ROW EXCLUSIVE from the very first statement, not the plain
    SHARE the first correction pass acquired and then let CREATE TRIGGER
    silently escalate mid-transaction — see "Why SHARE ROW EXCLUSIVE, and
    why it's acquired upfront" below for why the escalating version was
    itself corrected.

    Why a table lock is needed at all: CREATE OR REPLACE FUNCTION takes no
    lock whatsoever on narrative.encounters — it only touches the
    function's own pg_proc catalog row. Without an explicit lock, nothing
    stops a concurrent session (a rolling-deployment application instance
    still running against the *old* trigger definition, or any other
    writer) from INSERTing or UPDATEing a row that violates this
    revision's new rule at any point between the audit's SELECT and this
    migration's own COMMIT, and committing before this migration does —
    the audit already observed zero violations by then, and the new
    function only validates rows written *after* it becomes the
    committed, visible definition, never retroactively. That row would
    then persist, silently invalid, forever: exactly the race this
    revision's LOCK TABLE closes.

    Why SHARE ROW EXCLUSIVE, and why it's acquired upfront (corrected):
    PostgreSQL's own lock-conflict matrix (docs "13.3. Explicit Locking",
    "Table-Level Locks") is what decides the *floor* here, not a
    preference — INSERT and UPDATE each acquire ROW EXCLUSIVE on their
    target table, and ROW EXCLUSIVE conflicts with exactly four modes:
    SHARE, SHARE ROW EXCLUSIVE, EXCLUSIVE, and ACCESS EXCLUSIVE (never
    with ROW SHARE, ROW EXCLUSIVE itself, or SHARE UPDATE EXCLUSIVE).
    Plain SHARE would already be the weakest of those four conflicting
    modes, so it would be *sufficient* to queue every concurrent INSERT/
    UPDATE/DELETE behind this migration's own transaction — and the first
    correction pass acquired exactly that. But CREATE TRIGGER (this
    correction pass's own addition) itself requires SHARE ROW EXCLUSIVE,
    a *stronger* mode than SHARE — so that version acquired SHARE first
    and let CREATE TRIGGER escalate to SHARE ROW EXCLUSIVE mid-
    transaction. Lock escalation within one already-held lock is not by
    itself a self-deadlock (a session may always request a stronger mode
    on an object it already holds a weaker one on), but it does open a
    *different*, real hazard this correction closes: two migrations
    (a rolling deployment double-running, or any other concurrent session
    also doing `LOCK TABLE ... IN SHARE MODE`) can each successfully
    acquire plain SHARE simultaneously — SHARE does not conflict with
    itself — and then each attempt to escalate to SHARE ROW EXCLUSIVE at
    the same time. SHARE ROW EXCLUSIVE *does* conflict with SHARE, so
    each session's escalation request blocks on the *other* session's
    still-held SHARE lock: a classic lock-upgrade deadlock, which
    PostgreSQL's deadlock detector would eventually break by aborting one
    side, but only after a real wait and a failed migration run neither
    side needed to hit. Acquiring SHARE ROW EXCLUSIVE directly, as the
    very first statement, removes the two-step path entirely: two
    concurrent sessions requesting SHARE ROW EXCLUSIVE up front simply
    serialize on the normal lock queue (SHARE ROW EXCLUSIVE conflicts
    with itself, so the second waits for the first to finish and commit,
    the same as it would wait behind any other single blocking writer)
    — no escalation, so no lock-upgrade cycle for the deadlock detector
    to ever need to resolve.

    It does *not* block ordinary reads: SHARE ROW EXCLUSIVE does not
    conflict with ACCESS SHARE (plain SELECT) or ROW SHARE (SELECT ...
    FOR UPDATE/FOR SHARE), the identical read-friendliness plain SHARE
    already had — so read traffic against narrative.encounters is
    unaffected for the lock's whole duration, only writers wait. (SHARE
    ROW EXCLUSIVE does additionally conflict with SHARE UPDATE EXCLUSIVE
    — VACUUM (non-FULL), ANALYZE, CREATE INDEX CONCURRENTLY, and a few
    ALTER TABLE forms — which plain SHARE did not; immaterial here, since
    this migration's own hold is short and bounded, the same argument
    "Expected blocking, and why it is bounded" below already makes for
    ordinary writers.) A blocked writer is not rejected or retried; it
    simply waits in PostgreSQL's normal lock queue and proceeds, under
    the *new* (already-committed) trigger definition, the moment this
    migration's transaction ends — so a concurrent insert attempted
    during the migration either lands cleanly after it (revalidated by
    the stricter check) or was already valid and unaffected; none can
    land invalid.

    Expected blocking, and why it is bounded: this migration's own work
    between acquiring the lock and releasing it (at commit) is two
    COUNT(*) audit queries, two CREATE OR REPLACE FUNCTION calls, and one
    CREATE TRIGGER — no table rewrite, no index build, nothing whose cost
    scales with narrative.encounters' row count beyond those two bounded
    COUNT(*) scans. A concurrent writer therefore waits, at most, for
    however long this migration itself takes to run end to end
    (milliseconds to low seconds under normal conditions), not for an
    unrelated long-running operation. This is the same "one bounded DDL
    transaction, writers queue briefly behind it" shape every other
    trigger-replacing correction pass in this project already has —
    revision 081 differs only in making that queuing explicit via LOCK
    TABLE, where the earlier ones' own audits (when they had one) didn't
    need it because they weren't closing an audit-then-relax-enforcement
    window on a live-written table the same way.

    Deadlock: this migration acquires exactly one lock (the table lock,
    first, before anything else, at the *strongest* mode it will ever
    need for the whole transaction — no escalation, per "Why SHARE ROW
    EXCLUSIVE" above) and never waits on any other lock while holding it
    — CREATE OR REPLACE FUNCTION's own catalog-row lock and CREATE
    TRIGGER's own (already-held, non-escalating) table lock are never
    held by a session that could in turn be waiting on this table lock —
    so there is no lock-ordering cycle for PostgreSQL's deadlock detector
    to ever need to break. Both audits run under this same lock, acquired
    before either of them, so the second audit is protected identically
    to the first — there is no window where CREATE TRIGGER's own lock is
    what the second audit was relying on, since the single upfront LOCK
    TABLE already covers the entire transaction.

SQLAlchemy metadata / architecture docs:
    src/dnd_ai/persistence/tables/encounters.py declares no CHECK
    constraints or triggers (see that module's own note — alembic check
    only compares tables/columns/comments, never trigger bodies), so no
    change is needed there. docs/architecture/DATABASE_MODEL.md §13 gained
    one sentence noting the original session/campaign invariant, and a
    second sentence — now covering both timeline_id and campaign_id — for
    this correction's identity immutability.

    tests/database/test_encounter_domain.py::
    test_a_share_lock_on_encounters_blocks_a_concurrent_insert_until_released
    (the focused lock-conflict regression proving this migration's own
    lock genuinely serializes writers) is updated to acquire SHARE ROW
    EXCLUSIVE instead of plain SHARE, matching this correction — the
    property under test (a held table lock blocks a concurrent INSERT
    until released) is identical for either mode, so only the acquired
    mode changes, not the test's own structure or assertions.

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
     database/migrations/versions/033_rules_identity_immutability.py,
     database/migrations/versions/080_security_identity_and_access.py
     (campaign.campaigns.timeline_id and campaign.sessions.campaign_id
     immutability; core.enforce_immutable_columns()'s NULL-transition
     behavior, and why this revision's own campaign_id guard needed to be
     stricter than it rather than reusing it)
     src/dnd_ai/commands/encounters.py
     (_lock_encounter()/LockedEncounter — the application-layer provenance
     fix this migration's guard makes durable at the database layer too)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "081_encounter_session_scope"
down_revision = "080_security_identity_and_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # Must precede both audits — see this revision's "Locking
    # considerations" docstring section for the race this closes and why
    # SHARE ROW EXCLUSIVE (not plain SHARE, and acquired here rather than
    # via a later mid-transaction escalation) is what CREATE TRIGGER below
    # needs and what avoids a lock-upgrade deadlock hazard between two
    # concurrent migration runs.
    op.execute("LOCK TABLE narrative.encounters IN SHARE ROW EXCLUSIVE MODE;")

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

    # --- Correction (same still-unreleased revision — see "Reparenting —
    # corrected"/"corrected again" in this module's own docstring):
    # timeline_id and campaign_id identity immutability, plus a second
    # pre-flight audit for provenance already orphaned by a reparenting
    # UPDATE on either column. Both run under the LOCK TABLE already
    # acquired above, before anything in this section — see "Locking
    # considerations".

    op.execute("""
        DO $$
        DECLARE
            v_violations INTEGER;
        BEGIN
            SELECT count(*) INTO v_violations
            FROM narrative.encounters e
            WHERE EXISTS (
                SELECT 1
                FROM narrative.encounter_rounds er
                JOIN narrative.encounter_turns et ON et.encounter_round_id = er.encounter_round_id
                JOIN interaction.combat_actions ca ON ca.combat_action_id = et.combat_action_id
                JOIN interaction.actions a ON a.action_id = ca.action_id
                JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
                WHERE er.encounter_id = e.encounter_id
                  AND (
                      i.timeline_id IS DISTINCT FROM e.timeline_id
                      OR i.campaign_id IS DISTINCT FROM e.campaign_id
                  )
            )
            OR EXISTS (
                SELECT 1
                FROM narrative.event_causes ec
                JOIN narrative.events ev ON ev.event_id = ec.event_id
                WHERE ec.cause_encounter_id = e.encounter_id
                  AND (
                      ev.timeline_id IS DISTINCT FROM e.timeline_id
                      OR ev.campaign_id IS DISTINCT FROM e.campaign_id
                  )
            )
            OR (
                e.resulting_event_id IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM narrative.events ev
                    WHERE ev.event_id = e.resulting_event_id
                      AND (
                          ev.timeline_id IS DISTINCT FROM e.timeline_id
                          OR ev.campaign_id IS DISTINCT FROM e.campaign_id
                      )
                )
            );

            IF v_violations > 0 THEN
                RAISE EXCEPTION
                    'narrative.encounters has % row(s) whose dependent interaction.'
                    'interactions/narrative.events provenance disagrees with the '
                    'encounter''s own timeline_id or campaign_id (orphaned by a prior '
                    'reparenting UPDATE) — resolve them before enabling encounter '
                    'identity immutability (revision 081)',
                    v_violations
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_encounter_identity_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.timeline_id IS DISTINCT FROM OLD.timeline_id THEN
                RAISE EXCEPTION
                    'narrative.encounters.timeline_id is immutable once the encounter '
                    'exists and cannot be changed for encounter %',
                    OLD.encounter_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.campaign_id IS DISTINCT FROM OLD.campaign_id THEN
                RAISE EXCEPTION
                    'narrative.encounters.campaign_id is immutable once the encounter '
                    'exists — reparenting (including NULL <-> non-NULL transitions) is '
                    'not permitted for encounter %',
                    OLD.encounter_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_encounter_identity_immutable() IS
        'narrative.encounters.timeline_id and .campaign_id are both immutable once '
        'set — campaign_id including NULL <-> non-NULL transitions (stricter than '
        'core.enforce_immutable_columns(), revision 030/033, which allows one NULL '
        '-> value transition). An encounter''s owning timeline and campaign (or the '
        'deliberate absence of a campaign) are decided in full at creation and never '
        're-evaluated, because interaction.interactions/narrative.events rows '
        'already created under them do not themselves re-validate when the '
        'encounter later moves (revision 081 correction).';
    """)
    op.execute("""
        CREATE TRIGGER tr_encounters_identity_immutable
        BEFORE UPDATE ON narrative.encounters
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_encounter_identity_immutable();
    """)


def downgrade() -> None:
    """Revert the migration."""

    # --- Correction cleanup (same still-unreleased revision): drop the
    # timeline_id/campaign_id identity immutability guard first — no LOCK
    # TABLE needed, since downgrading only weakens enforcement (see
    # "Locking considerations").
    op.execute("DROP TRIGGER IF EXISTS tr_encounters_identity_immutable ON narrative.encounters;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_encounter_identity_immutable();")

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
