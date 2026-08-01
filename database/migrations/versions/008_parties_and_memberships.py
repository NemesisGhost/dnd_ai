"""Parties and temporal party memberships

Revision ID: 008_parties_and_memberships
Revises: 007_audit_change_log
Create Date: 2026-08-01 21:00:00.000000

Purpose:
    Delivers the first two tables of Phase 3 (docs/PLAN.md §5.4):
    campaign.parties and campaign.party_memberships.

    Memberships are temporal so a character can join, leave, and return
    (§5.4). The rule that matters — the same character cannot be recorded as
    in a party they have not left — is enforced by a GiST exclusion
    constraint rather than application logic, because only the database can
    make it concurrency-safe. Two transactions each checking "is there an
    overlapping row?" and then inserting will both pass their check and both
    commit; an exclusion constraint is evaluated by the index itself and one
    of them fails.

    Delivered ahead of campaign.timelines and campaign.campaigns because it
    does not depend on them: parties belong to a world and members are
    entities, both of which exist. campaign.campaign_parties, which joins
    parties to campaigns, waits for campaigns.

Forward migration:
    - campaign.parties
    - campaign.party_memberships, with the overlap exclusion constraint

Rollback:
    Supported. Drops both tables; the constraint and its index go with them.

Data implications:
    Creates no rows.

Locking considerations:
    None. Both tables are new and empty. Note that building the GiST index
    behind the exclusion constraint would take an ACCESS EXCLUSIVE lock on a
    populated table — irrelevant here, but relevant to any future migration
    adding one to a table with data.

See: docs/PLAN.md §5.4 (parties)
     docs/DATABASE_CONVENTIONS.md §12.5 (overlap prevention), §12.3 (temporal validity)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "008_parties_and_memberships"
down_revision = "007_audit_change_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # btree_gist is created by 001_bootstrap, which lists it as a required
    # extension. Repeated here because that is only true for databases
    # bootstrapped after it was added there, and this revision cannot build its
    # exclusion constraint without it. IF NOT EXISTS makes it a no-op otherwise.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # ==========================================================================
    # 1. campaign.parties
    # ==========================================================================
    # A party belongs to a world, not to a campaign: §5.4 says a party may
    # persist across campaigns, and campaign.campaign_parties (later) is what
    # associates one with a given game.
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
        'A group of characters who adventure together. Belongs to a world and may '
        'persist across campaigns (docs/PLAN.md §5.4).';
    """)
    op.execute("""
        CREATE TRIGGER tr_parties_set_updated_at
        BEFORE UPDATE ON campaign.parties
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_parties_world_id ON campaign.parties (world_id);")

    # ==========================================================================
    # 2. campaign.party_memberships
    # ==========================================================================
    # Membership identity is the PAIR (party_id, member_id), not either alone.
    # The exclusion constraint below has to match on both, or it would forbid a
    # character from being in two parties at once, and forbid two characters
    # from being in the same party at once — neither of which is the rule.
    #
    # member_id references core.entities rather than character.characters
    # because that table does not exist until Phase 4. Characters are entities,
    # so this is correct but weaker than it will eventually be: the database
    # cannot yet reject a location being added to a party. Phase 4 tightens it
    # once character.characters exists.
    #
    # valid_from / valid_to are real-world TIMESTAMPTZ per conventions §12.3's
    # operational-validity pair. See the note in the docstring of the test
    # module about when this would instead need world time.
    op.execute("""
        CREATE TABLE campaign.party_memberships (
            party_membership_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            party_id             UUID NOT NULL
                                 REFERENCES campaign.parties(party_id) ON DELETE CASCADE,
            member_id            UUID NOT NULL
                                 REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            valid_from           TIMESTAMPTZ NOT NULL,
            valid_to             TIMESTAMPTZ,
            joined_reason        TEXT,
            left_reason          TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- A bounded membership must end strictly after it begins. Equal
            -- endpoints would make an empty '[)' range, which overlaps nothing
            -- and would slip past the exclusion constraint entirely.
            CONSTRAINT ck_party_memberships_valid_range
                CHECK (valid_to IS NULL OR valid_to > valid_from),

            -- One representation of "still a member": valid_to IS NULL.
            -- 'infinity' would be a second, and two rows meaning the same thing
            -- is how "is this person still in the party?" starts returning
            -- different answers depending on who wrote the row.
            CONSTRAINT ck_party_memberships_open_ended_is_null
                CHECK (valid_to IS NULL OR valid_to <> 'infinity'::timestamptz),
            CONSTRAINT ck_party_memberships_valid_from_finite
                CHECK (valid_from <> 'infinity'::timestamptz
                       AND valid_from <> '-infinity'::timestamptz),

            -- The rule this table exists to enforce. Half-open '[)' so a
            -- membership may begin at the exact instant the previous one ended
            -- — leaving and rejoining on the same day is ordinary, and a '[]'
            -- range would reject it.
            --
            -- A NULL valid_to produces an unbounded upper range, so an
            -- open-ended membership correctly blocks every later overlap
            -- without needing a sentinel value.
            CONSTRAINT ex_party_memberships_no_overlap
                EXCLUDE USING gist (
                    party_id WITH =,
                    member_id WITH =,
                    tstzrange(valid_from, valid_to, '[)') WITH &&
                )
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.party_memberships IS
        'Temporal record of a character belonging to a party. A character may leave and '
        'rejoin, and may belong to several parties at once, but cannot have two '
        'overlapping memberships of the SAME party — enforced by the exclusion '
        'constraint, which is concurrency-safe in a way an application check is not.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.member_id IS
        'References core.entities, not character.characters, which arrives in Phase 4. '
        'Characters are entities, so this is correct but weaker than it will be — the '
        'database cannot yet reject a non-character being added to a party.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.valid_to IS
        'NULL means the membership is open-ended — the single representation of "still a '
        'member". Bounded memberships are half-open: valid_to is the first instant NOT '
        'in the membership, so one membership may start exactly when another ends.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_memberships_set_updated_at
        BEFORE UPDATE ON campaign.party_memberships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # The exclusion constraint's own GiST index leads with party_id, so it
    # already covers that foreign key. member_id needs its own (§19.1), and the
    # common read is "which parties is this character in right now".
    op.execute(
        "CREATE INDEX ix_party_memberships_member_id ON campaign.party_memberships (member_id);"
    )
    op.execute("""
        CREATE INDEX ix_party_memberships_party_id_valid_from
        ON campaign.party_memberships (party_id, valid_from DESC);
    """)

    # A party and its members must belong to the same world. Same class as the
    # cross-world guards in Phase 2, and again not expressible as a foreign key
    # because the world is reached through two different parents.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_party_membership_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_party_world  UUID;
            v_member_world UUID;
        BEGIN
            SELECT world_id INTO v_party_world
            FROM campaign.parties WHERE party_id = NEW.party_id;

            SELECT world_id INTO v_member_world
            FROM core.entities WHERE entity_id = NEW.member_id;

            IF v_party_world IS DISTINCT FROM v_member_world THEN
                RAISE EXCEPTION
                    'Party % belongs to world %, but member % belongs to world %',
                    NEW.party_id, v_party_world, NEW.member_id, v_member_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_party_membership_world() IS
        'Keeps a party from admitting a member that belongs to a different world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_memberships_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.party_memberships
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_party_membership_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.party_memberships;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_party_membership_world();")
    op.execute("DROP TABLE IF EXISTS campaign.parties;")

    # btree_gist is deliberately NOT dropped: 001_bootstrap owns its lifecycle,
    # and other objects may depend on it.
