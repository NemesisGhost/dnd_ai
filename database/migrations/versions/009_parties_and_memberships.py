"""Parties and timeline-scoped temporal party memberships

Revision ID: 009_parties_memberships
Revises: 008_timelines
Create Date: 2026-08-01 22:00:00.000000

Purpose:
    Delivers campaign.parties and campaign.party_memberships (docs/PLAN.md
    §5.4), implementing the interval contract in ADR 0010.

    A party is a stable world-level identity. Membership is timeline-scoped
    mutable state, because membership can diverge after a branch: the same
    character may leave the party in one timeline and stay in another.

    The rule that matters — the same character cannot be recorded as in a
    party they have not left, within one timeline — is enforced by a GiST
    exclusion constraint rather than application logic, because only the
    database makes it concurrency-safe. Two transactions each running "is
    there an overlapping row?" and then inserting will both pass their check
    and both commit; an exclusion constraint is evaluated by the index, so one
    of them fails.

Forward migration:
    - btree_gist extension (first revision to need it)
    - campaign.parties
    - campaign.party_memberships, with the overlap exclusion constraint
    - campaign.sync_party_membership_period(), which validates endpoints and
      derives the stored range from them

Rollback:
    Supported. Drops both tables and the trigger function. btree_gist is
    deliberately left installed — see the note in downgrade().

Data implications:
    Creates no rows.

Locking considerations:
    None here; both tables are new and empty. Worth knowing for later: adding
    a GiST exclusion constraint to a *populated* table builds its index under
    an ACCESS EXCLUSIVE lock.

Deferred to later phases:
    - member_entity_id references core.entities, not character.characters,
      which arrives in Phase 4. Characters are entities, so this is correct
      but weaker than it will be: the database cannot yet reject a location
      being added to a party. Phase 4 closes it.
    - Join/leave causal event references arrive in Phase 6 with
      narrative.events, rather than being stored now as unconstrained UUIDs.

See: docs/PLAN.md §5.4 (parties), Phase 3 exit criteria
     docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md
     docs/DATABASE_CONVENTIONS.md §12.3 (half-open intervals), §12.5 (overlap)
     docs/architecture/DATABASE_MODEL.md §6.3
"""

from alembic import op

# revision identifiers, used by Alembic.
# Kept under 32 characters: alembic_version.version_num is VARCHAR(32).
revision = "009_parties_memberships"
down_revision = "008_timelines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. btree_gist
    # ==========================================================================
    # GiST has no built-in equality operator class for UUID, so the exclusion
    # constraint below cannot be created without this extension: it fails with
    # "data type uuid has no default operator class for access method gist".
    #
    # Created here rather than in 001_bootstrap because docs/PLAN.md §4.1 makes
    # it the responsibility of the Phase 3 revision that first needs it, not a
    # bootstrap dependency. It must exist before the CREATE TABLE below, which
    # is why it is the first statement in this revision.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # ==========================================================================
    # 2. campaign.parties
    # ==========================================================================
    # A party belongs to a world, not to a campaign or a timeline: §5.4 says a
    # party may persist across campaigns, and campaign.campaign_parties (later)
    # associates it with a given game. The party's *identity* is world-level
    # and shared by every branch; only its membership is timeline-scoped.
    op.execute("""
        CREATE TABLE campaign.parties (
            party_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            world_id     UUID NOT NULL
                         REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            name         TEXT NOT NULL,
            description  TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_parties_name_length CHECK (char_length(name) BETWEEN 1 AND 200)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.parties IS
        'A group of characters who adventure together. A stable world-level identity that '
        'may persist across campaigns; membership is timeline-scoped state, not a property '
        'of this row (docs/PLAN.md §5.4).';
    """)
    op.execute("""
        CREATE TRIGGER tr_parties_set_updated_at
        BEFORE UPDATE ON campaign.parties
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_parties_world_id ON campaign.parties (world_id);")

    # ==========================================================================
    # 3. campaign.party_memberships
    # ==========================================================================
    # Membership identity is the TRIPLE (timeline_id, party_id,
    # member_entity_id), not any one of them. The exclusion constraint has to
    # match on all three, or it would forbid a character from being in two
    # parties at once, forbid two characters from being in the same party at
    # once, or leak a membership across sibling branches — none of which is
    # the rule.
    #
    # Time is fictional, not real-world: endpoints are core.world_times rows,
    # which carry calendar, precision, label, and provenance. PostgreSQL
    # cannot apply the overlap operator to a pair of foreign keys, so the
    # constraint runs on effective_period, an INT8RANGE over the endpoints'
    # sort_key values. The range is derived, never client-supplied — see the
    # trigger below.
    op.execute("""
        CREATE TABLE campaign.party_memberships (
            party_membership_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                   UUID NOT NULL
                                          REFERENCES campaign.timelines(timeline_id)
                                          ON DELETE CASCADE,
            party_id                      UUID NOT NULL
                                          REFERENCES campaign.parties(party_id)
                                          ON DELETE CASCADE,
            member_entity_id              UUID NOT NULL
                                          REFERENCES core.entities(entity_id)
                                          ON DELETE CASCADE,
            effective_from_world_time_id  UUID NOT NULL
                                          REFERENCES core.world_times(world_time_id)
                                          ON DELETE RESTRICT,
            effective_to_world_time_id    UUID
                                          REFERENCES core.world_times(world_time_id)
                                          ON DELETE RESTRICT,
            effective_period              INT8RANGE NOT NULL,
            joined_reason                 TEXT,
            left_reason                   TEXT,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- The stored range must agree with the endpoint columns about
            -- whether the membership is open-ended. The trigger derives both
            -- from the same source, so this catches a future code path that
            -- writes the range some other way.
            CONSTRAINT ck_party_memberships_open_ended_agrees
                CHECK (
                    (effective_to_world_time_id IS NULL) = (upper_inf(effective_period))
                ),

            -- A finite start, always. An unbounded lower bound would make the
            -- membership overlap all of prior history.
            CONSTRAINT ck_party_memberships_lower_bound_finite
                CHECK (NOT lower_inf(effective_period)),

            -- An empty range overlaps nothing and would slip past the
            -- exclusion constraint entirely. The trigger rejects
            -- to.sort_key <= from.sort_key, which is what would produce one.
            CONSTRAINT ck_party_memberships_period_not_empty
                CHECK (NOT isempty(effective_period)),

            -- The rule this table exists to enforce. Half-open '[)' so a
            -- membership may begin at the exact world time the previous one
            -- ended — leaving and rejoining is ordinary, and a '[]' range
            -- would reject it. A NULL end produces an unbounded upper range,
            -- so a current membership blocks every later overlap without a
            -- sentinel value.
            CONSTRAINT ex_party_memberships_no_overlap
                EXCLUDE USING gist (
                    timeline_id WITH =,
                    party_id WITH =,
                    member_entity_id WITH =,
                    effective_period WITH &&
                )
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.party_memberships IS
        'Timeline-scoped temporal record of a character belonging to a party. A character '
        'may leave and rejoin, and may belong to several parties at once, but cannot have '
        'two overlapping memberships of the SAME party in the SAME timeline — enforced by '
        'an exclusion constraint, which is concurrency-safe in a way an application check '
        'is not (ADR 0010).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.timeline_id IS
        'Membership is timeline state: it can diverge after a branch. A row written to one '
        'branch is not a row in its sibling.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.member_entity_id IS
        'References core.entities, not character.characters, which arrives in Phase 4. '
        'Characters are entities, so this is correct but weaker than it will be — the '
        'database cannot yet reject a non-character being added to a party.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.effective_to_world_time_id IS
        'NULL means the membership is open-ended — the single representation of "still a '
        'member". Bounded memberships are half-open: this world time is the first moment '
        'NOT in the membership, so one membership may start exactly where another ends.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.effective_period IS
        'Derived, never client-authoritative: an INT8RANGE over the endpoint rows'' '
        'core.world_times.sort_key values, rebuilt by trigger on every INSERT and UPDATE. '
        'It exists because PostgreSQL cannot apply the overlap operator to foreign keys.';
    """)

    op.execute("""
        CREATE TRIGGER tr_party_memberships_set_updated_at
        BEFORE UPDATE ON campaign.party_memberships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # The exclusion constraint's GiST index leads with timeline_id, so it
    # already serves that foreign key. The others need their own (§19.1).
    op.execute(
        "CREATE INDEX ix_party_memberships_member_entity_id "
        "ON campaign.party_memberships (member_entity_id);"
    )
    op.execute(
        "CREATE INDEX ix_party_memberships_party_id ON campaign.party_memberships (party_id);"
    )
    # The world-time endpoints need their own indexes too (§19.1): without
    # them, deleting a world time has to sequentially scan this table to
    # evaluate the ON DELETE RESTRICT.
    op.execute("""
        CREATE INDEX ix_party_memberships_effective_from_world_time_id
        ON campaign.party_memberships (effective_from_world_time_id);
    """)
    op.execute("""
        CREATE INDEX ix_party_memberships_effective_to_world_time_id
        ON campaign.party_memberships (effective_to_world_time_id)
        WHERE effective_to_world_time_id IS NOT NULL;
    """)

    # ==========================================================================
    # 4. Endpoint validation and range derivation
    # ==========================================================================
    # One trigger owns the whole interval contract, so there is no way to write
    # a row whose IDs and range disagree:
    #
    #   1. Both endpoints belong to the same world as the party.
    #   2. The membership's timeline belongs to that world.
    #   3. The member entity belongs to that world.
    #   4. to.sort_key > from.sort_key for a bounded interval.
    #   5. effective_period is overwritten from the endpoints' sort_keys.
    #
    # Rule 5 runs last and unconditionally, which is what makes the column
    # trustworthy: whatever the caller supplied is discarded.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.sync_party_membership_period()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_party_world     UUID;
            v_timeline_world  UUID;
            v_member_world    UUID;
            v_from_world      UUID;
            v_from_sort_key   BIGINT;
            v_to_world        UUID;
            v_to_sort_key     BIGINT;
        BEGIN
            SELECT world_id INTO v_party_world
            FROM campaign.parties WHERE party_id = NEW.party_id;

            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            IF v_timeline_world IS DISTINCT FROM v_party_world THEN
                RAISE EXCEPTION
                    'Party % belongs to world %, but timeline % belongs to world %',
                    NEW.party_id, v_party_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id INTO v_member_world
            FROM core.entities WHERE entity_id = NEW.member_entity_id;

            IF v_member_world IS DISTINCT FROM v_party_world THEN
                RAISE EXCEPTION
                    'Party % belongs to world %, but member % belongs to world %',
                    NEW.party_id, v_party_world, NEW.member_entity_id, v_member_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id, sort_key INTO v_from_world, v_from_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_from_world_time_id;

            IF v_from_world IS DISTINCT FROM v_party_world THEN
                RAISE EXCEPTION
                    'Start world time % belongs to world %, but party % belongs to world %',
                    NEW.effective_from_world_time_id, v_from_world,
                    NEW.party_id, v_party_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.effective_to_world_time_id IS NULL THEN
                NEW.effective_period := int8range(v_from_sort_key, NULL, '[)');
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_to_world, v_to_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_to_world_time_id;

            IF v_to_world IS DISTINCT FROM v_party_world THEN
                RAISE EXCEPTION
                    'End world time % belongs to world %, but party % belongs to world %',
                    NEW.effective_to_world_time_id, v_to_world,
                    NEW.party_id, v_party_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_to_sort_key <= v_from_sort_key THEN
                RAISE EXCEPTION
                    'Membership end (sort_key %) must be later than its start (sort_key %)',
                    v_to_sort_key, v_from_sort_key
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.effective_period := int8range(v_from_sort_key, v_to_sort_key, '[)');
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.sync_party_membership_period() IS
        'Owns the ADR 0010 interval contract for party memberships: validates that the '
        'timeline, member, and both world-time endpoints share the party''s world, that a '
        'bounded interval ends after it begins, and then overwrites effective_period from '
        'the endpoints'' sort_keys so the IDs and the range can never disagree.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_memberships_sync_period
        BEFORE INSERT OR UPDATE ON campaign.party_memberships
        FOR EACH ROW EXECUTE FUNCTION campaign.sync_party_membership_period();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.party_memberships;")
    op.execute("DROP FUNCTION IF EXISTS campaign.sync_party_membership_period();")
    op.execute("DROP TABLE IF EXISTS campaign.parties;")

    # btree_gist is deliberately NOT dropped. Dropping an extension takes down
    # everything depending on it, and this revision cannot know whether a later
    # one has since created its own exclusion constraint. Leaving it installed
    # is harmless; removing it is not reversible from here.
