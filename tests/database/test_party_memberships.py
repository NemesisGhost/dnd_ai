"""Temporal party membership — the overlap exclusion constraint (revision 009).

The rule: within one timeline, the same character cannot have two overlapping
memberships of the same party. Everything else overlapping is legitimate — a
character in two parties at once, two characters in one party at once, the same
character rejoining after leaving, and the same character having different
membership histories in two sibling branches.

Enforced by a GiST exclusion constraint rather than application logic, because
only the database makes it concurrency-safe: two transactions each running "is
there an overlapping row?" and then inserting will both pass their check and
both commit. The constraint is evaluated by the index, so one of them fails. A
test at the bottom demonstrates exactly that with two real connections.

Intervals are fictional time, not real-world time (ADR 0010): endpoints are
core.world_times rows and the constraint runs on effective_period, an INT8RANGE
derived from their sort_key values by trigger. Tests therefore assert on the
derived range as well as on the accept/reject behaviour, because a trigger that
silently stopped firing would leave every behavioural test passing against
whatever the client happened to supply.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_entity,
    make_entity_type,
    make_party,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

# Trigger-raised errors surface as InternalError, constraint violations as
# IntegrityError; a few arrive as ProgrammingError depending on driver state.
CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)

# Four ordered points in one world's chronology.
K0, K1, K2, K3 = 100, 200, 300, 400


class World:
    """One world with a timeline, a party, two members, and four world times."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.party_id = make_party(connection, self.world_id)
        entity_type = make_entity_type(connection, f"{slug.replace('-', '_')}_member")
        self.members = [
            make_entity(connection, self.world_id, entity_type, name=f"Member {i}")
            for i in range(2)
        ]
        self.times = {k: make_world_time(connection, self.world_id, k) for k in (K0, K1, K2, K3)}


@pytest.fixture
def w(db_connection: Connection) -> World:
    return World(db_connection, "party-world")


def _join(
    connection: Connection,
    world: World,
    member_index: int = 0,
    *,
    frm: int = K0,
    to: int | None = None,
    timeline_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.party_memberships
                (timeline_id, party_id, member_entity_id,
                 effective_from_world_time_id, effective_to_world_time_id)
            VALUES (:tl, :p, :m, :f, :t)
        """),
        {
            "tl": timeline_id or world.timeline_id,
            "p": party_id or world.party_id,
            "m": world.members[member_index],
            "f": world.times[frm],
            "t": world.times[to] if to is not None else None,
        },
    )


# ---------------------------------------------------------------------------
# The six required proofs
# ---------------------------------------------------------------------------


def test_overlapping_membership_same_party_same_member_is_rejected(
    db_connection: Connection, w: World
) -> None:
    """The rule itself."""
    _join(db_connection, w, frm=K0, to=K2)

    with pytest.raises(IntegrityError) as exc:
        _join(db_connection, w, frm=K1, to=K3)  # starts inside the first
    assert "ex_party_memberships_no_overlap" in str(exc.value)


def test_boundary_touching_interval_is_accepted(db_connection: Connection, w: World) -> None:
    """Half-open '[)': leaving and rejoining at the same world time is ordinary.

    A '[]' range would reject this, which is the mistake this test exists to
    catch if the interval style is ever changed.
    """
    _join(db_connection, w, frm=K0, to=K1)
    _join(db_connection, w, frm=K1, to=K2)  # starts exactly where the first ended

    count = db_connection.execute(
        text("""
            SELECT count(*) FROM campaign.party_memberships
            WHERE party_id = :p AND member_entity_id = :m
        """),
        {"p": w.party_id, "m": w.members[0]},
    ).scalar()
    assert count == 2


def test_overlapping_dates_for_different_members_are_accepted(
    db_connection: Connection, w: World
) -> None:
    """A party has more than one member at a time — the case a constraint keyed
    only on party_id would break."""
    _join(db_connection, w, 0, frm=K0, to=K2)
    _join(db_connection, w, 1, frm=K0, to=K2)


def test_overlapping_dates_same_member_different_parties_are_accepted(
    db_connection: Connection, w: World
) -> None:
    """A character may belong to two parties at once — the case a constraint
    keyed only on member_entity_id would break."""
    other_party = make_party(db_connection, w.world_id, name="Party B")
    _join(db_connection, w, frm=K0, to=K2)
    _join(db_connection, w, frm=K0, to=K2, party_id=other_party)


def test_open_ended_membership_blocks_a_later_overlapping_membership(
    db_connection: Connection, w: World
) -> None:
    """A NULL end must produce an unbounded upper range, not an empty one."""
    _join(db_connection, w, frm=K0, to=None)  # still a member

    with pytest.raises(IntegrityError) as exc:
        _join(db_connection, w, frm=K2, to=K3)
    assert "ex_party_memberships_no_overlap" in str(exc.value)


def test_migration_produced_the_extension_and_constraint(db_connection: Connection) -> None:
    """The migration succeeds from a clean database with the extension enabled.

    The ephemeral database this suite runs against is built from base by
    `alembic upgrade head` in conftest, so reaching this assertion at all means
    the full chain applied cleanly. What is asserted here is that it produced
    the right objects rather than merely not erroring — and specifically that
    the constraint has the exact shape ADR 0010 specifies, since a constraint
    missing one of its four keys would still pass most behavioural tests.
    """
    assert (
        db_connection.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        ).scalar()
        == 1
    ), "btree_gist missing — the exclusion constraint cannot exist without it"

    definition = db_connection.execute(
        text("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = 'campaign.party_memberships'::regclass
              AND conname = 'ex_party_memberships_no_overlap'
        """)
    ).scalar()
    assert definition is not None, "exclusion constraint missing"
    assert str(definition) == (
        "EXCLUDE USING gist (timeline_id WITH =, party_id WITH =, "
        "member_entity_id WITH =, effective_period WITH &&)"
    ), f"constraint shape changed: {definition}"


# ---------------------------------------------------------------------------
# Timeline scoping — the reason timeline_id is in the key at all
# ---------------------------------------------------------------------------


def test_same_membership_in_two_branches_does_not_conflict(
    db_connection: Connection, w: World
) -> None:
    """Membership diverges after a branch, so identical periods in sibling
    timelines are not an overlap. A constraint keyed only on
    (party_id, member_entity_id) would reject this."""
    branch = make_timeline(
        db_connection,
        w.world_id,
        name="What if",
        parent_timeline_id=w.timeline_id,
        branch_world_time_id=w.times[K1],
    )
    _join(db_connection, w, frm=K0, to=K2)
    _join(db_connection, w, frm=K0, to=K2, timeline_id=branch)


def test_membership_written_to_one_branch_is_absent_from_its_sibling(
    db_connection: Connection, w: World
) -> None:
    """Phase 3 proves membership rows are timeline-scoped. It does NOT prove
    branch history isolation — that needs events and the effective-history
    query, which arrive in Phase 6 (docs/PLAN.md Phase 6 exit criteria)."""
    branch = make_timeline(
        db_connection,
        w.world_id,
        name="What if",
        parent_timeline_id=w.timeline_id,
        branch_world_time_id=w.times[K1],
    )
    _join(db_connection, w, frm=K0, to=None, timeline_id=branch)

    in_parent = db_connection.execute(
        text("SELECT count(*) FROM campaign.party_memberships WHERE timeline_id = :tl"),
        {"tl": w.timeline_id},
    ).scalar()
    assert in_parent == 0


def test_timeline_from_another_world_is_rejected(db_connection: Connection, w: World) -> None:
    other_world = make_world(db_connection, slug="party-other-world")
    foreign_timeline = make_timeline(db_connection, other_world, name="Elsewhere")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _join(db_connection, w, timeline_id=foreign_timeline)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# The interval contract: endpoints, derived range, world agreement
# ---------------------------------------------------------------------------


def test_effective_period_is_derived_from_the_endpoint_sort_keys(
    db_connection: Connection, w: World
) -> None:
    """The range is the trigger's output, not the caller's input."""
    _join(db_connection, w, frm=K0, to=K2)

    period = db_connection.execute(
        text("SELECT effective_period::text FROM campaign.party_memberships")
    ).scalar()
    assert period == f"[{K0},{K2})"


def test_open_ended_membership_stores_an_unbounded_upper_range(
    db_connection: Connection, w: World
) -> None:
    _join(db_connection, w, frm=K1, to=None)

    period = db_connection.execute(
        text("SELECT effective_period::text FROM campaign.party_memberships")
    ).scalar()
    assert period == f"[{K1},)"


def test_a_client_supplied_range_is_overwritten(db_connection: Connection, w: World) -> None:
    """The range column is NOT NULL, so a caller can supply one. The trigger
    must discard it — otherwise the IDs and the range could disagree and the
    exclusion constraint would be enforcing a fiction."""
    db_connection.execute(
        text("""
            INSERT INTO campaign.party_memberships
                (timeline_id, party_id, member_entity_id,
                 effective_from_world_time_id, effective_to_world_time_id, effective_period)
            VALUES (:tl, :p, :m, :f, :t, '[1,2)'::int8range)
        """),
        {
            "tl": w.timeline_id,
            "p": w.party_id,
            "m": w.members[0],
            "f": w.times[K0],
            "t": w.times[K2],
        },
    )

    period = db_connection.execute(
        text("SELECT effective_period::text FROM campaign.party_memberships")
    ).scalar()
    assert period == f"[{K0},{K2})", "trigger did not overwrite the client-supplied range"


def test_bounded_membership_must_end_after_it_begins(db_connection: Connection, w: World) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _join(db_connection, w, frm=K2, to=K0)
    assert "must be later than its start" in str(exc.value)


def test_zero_length_membership_is_rejected(db_connection: Connection, w: World) -> None:
    """Equal endpoints make an empty '[)' range, which overlaps nothing and
    would slip past the exclusion constraint entirely."""
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _join(db_connection, w, frm=K1, to=K1)
    assert "must be later than its start" in str(exc.value)


def test_start_world_time_is_required(db_connection: Connection, w: World) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO campaign.party_memberships
                    (timeline_id, party_id, member_entity_id, effective_from_world_time_id)
                VALUES (:tl, :p, :m, NULL)
            """),
            {"tl": w.timeline_id, "p": w.party_id, "m": w.members[0]},
        )


def test_endpoint_from_another_world_is_rejected(db_connection: Connection, w: World) -> None:
    other_world = make_world(db_connection, slug="party-time-other-world")
    foreign_time = make_world_time(db_connection, other_world, K1)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.party_memberships
                    (timeline_id, party_id, member_entity_id, effective_from_world_time_id)
                VALUES (:tl, :p, :m, :f)
            """),
            {
                "tl": w.timeline_id,
                "p": w.party_id,
                "m": w.members[0],
                "f": foreign_time,
            },
        )
    assert "belongs to world" in str(exc.value)


def test_member_must_belong_to_the_partys_world(db_connection: Connection, w: World) -> None:
    other_world = make_world(db_connection, slug="party-member-other-world")
    entity_type = make_entity_type(db_connection, "foreign_member_type")
    foreign_member = make_entity(db_connection, other_world, entity_type)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.party_memberships
                    (timeline_id, party_id, member_entity_id, effective_from_world_time_id)
                VALUES (:tl, :p, :m, :f)
            """),
            {
                "tl": w.timeline_id,
                "p": w.party_id,
                "m": foreign_member,
                "f": w.times[K0],
            },
        )
    assert "belongs to world" in str(exc.value)


def test_two_open_ended_memberships_of_the_same_party_conflict(
    db_connection: Connection, w: World
) -> None:
    _join(db_connection, w, frm=K0, to=None)
    with pytest.raises(IntegrityError):
        _join(db_connection, w, frm=K3, to=None)


def test_a_later_return_after_a_gap_is_accepted(db_connection: Connection, w: World) -> None:
    """Leave at K1, return at K2 — the case temporal membership exists for."""
    _join(db_connection, w, frm=K0, to=K1)
    _join(db_connection, w, frm=K2, to=K3)


def test_updating_a_membership_re_derives_its_range(db_connection: Connection, w: World) -> None:
    """The trigger is BEFORE INSERT OR UPDATE. Corrections must re-run the whole
    contract, not just insertion (ADR 0010's correction policy)."""
    _join(db_connection, w, frm=K0, to=K1)

    db_connection.execute(
        text("""
            UPDATE campaign.party_memberships
            SET effective_to_world_time_id = :t
        """),
        {"t": w.times[K3]},
    )

    period = db_connection.execute(
        text("SELECT effective_period::text FROM campaign.party_memberships")
    ).scalar()
    assert period == f"[{K0},{K3})"


def test_updating_a_membership_into_an_overlap_is_rejected(
    db_connection: Connection, w: World
) -> None:
    _join(db_connection, w, frm=K0, to=K1)
    _join(db_connection, w, frm=K2, to=K3)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                UPDATE campaign.party_memberships
                SET effective_to_world_time_id = :t
                WHERE effective_from_world_time_id = :f
            """),
            {"t": w.times[K3], "f": w.times[K0]},
        )
    assert "ex_party_memberships_no_overlap" in str(exc.value)


# ---------------------------------------------------------------------------
# Concurrency — why this is a database constraint and not an application check
# ---------------------------------------------------------------------------


def test_concurrent_overlapping_inserts_cannot_both_commit(postgres_engine: Engine) -> None:
    """Two simultaneous transactions inserting overlapping memberships.

    This is the case an application-level "check then insert" cannot handle:
    both transactions would see no conflicting row, both would insert, and both
    would commit.

    Takes the session engine rather than the db_connection fixture, because it
    needs two concurrent transactions and committed setup data — and that
    fixture wraps everything in one transaction it always rolls back. Setup is
    therefore committed here, under a unique slug, and removed explicitly at
    the end.
    """
    engine = postgres_engine
    slug = f"party-concurrency-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            w = World(setup, slug)

        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            _join(first, w, frm=K0, to=K2)

            # Overlaps the row above, which is not yet committed. The exclusion
            # constraint makes this *wait* on the first transaction rather than
            # fail immediately — the block is itself the evidence that the
            # database, not the application, is serialising these. A short
            # lock_timeout turns that wait into an observable error.
            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                _join(second, w, frm=K1, to=K3)
                second.commit()

            message = str(exc.value)
            assert (
                "lock_timeout" in message
                or "ex_party_memberships_no_overlap" in message
                or "canceling statement" in message
            ), f"expected a conflict or lock timeout, got: {message}"

            second.rollback()

            # With the blocker resolved, the same insert now fails outright on
            # the constraint rather than merely blocking.
            first.commit()
            with engine.begin() as third:
                with pytest.raises(IntegrityError) as exc2:
                    _join(third, w, frm=K1, to=K3)
                assert "ex_party_memberships_no_overlap" in str(exc2.value)
    finally:
        # This test commits, so it owns its teardown. Deleted child-first and
        # explicitly rather than leaning on cascades: core.entities does not
        # cascade from core.worlds, and party_memberships references
        # core.world_times with ON DELETE RESTRICT, so a bare "DELETE FROM
        # core.worlds" fails on both counts.
        with engine.begin() as cleanup:
            params = {"s": slug}
            cleanup.execute(
                text("""
                    DELETE FROM campaign.party_memberships
                    WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines
                        WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
                    )
                """),
                params,
            )
            for table, column in (
                ("campaign.parties", "world_id"),
                ("campaign.timelines", "world_id"),
                ("core.entities", "world_id"),
                ("core.world_times", "world_id"),
            ):
                cleanup.execute(
                    text(f"""
                        DELETE FROM {table}
                        WHERE {column} IN (SELECT world_id FROM core.worlds WHERE slug = :s)
                    """),
                    params,
                )
            cleanup.execute(text("DELETE FROM core.worlds WHERE slug = :s"), params)
