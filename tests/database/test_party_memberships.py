"""Temporal party membership — the overlap exclusion constraint (revision 008).

The rule: the same character cannot have two overlapping memberships of the
same party. Everything else overlapping is legitimate — a character in two
parties at once, two characters in one party at once, the same character
rejoining a party after leaving it.

Enforced by a GiST exclusion constraint rather than application logic, because
only the database makes it concurrency-safe: two transactions each running
"is there an overlapping row?" and then inserting will both pass their check
and both commit. The constraint is evaluated by the index, so one of them
fails. A test at the bottom demonstrates exactly that, using two real
concurrent connections.

Note on time base: valid_from/valid_to are real-world TIMESTAMPTZ, per
conventions §12.3's operational-validity pair. If party membership should
instead track *fictional* chronology — when a character joined in the story
rather than when the record was entered — this would need
effective_from_world_time_id referencing core.world_times (§12.2, §4.7), and
the exclusion constraint would have to change shape, since world_times are
sortable rows rather than a range type. Flagged rather than assumed.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.factories import make_entity, make_entity_type, make_world

pytestmark = pytest.mark.database

T0 = datetime(1200, 1, 1, tzinfo=UTC)
T1 = T0 + timedelta(days=30)
T2 = T0 + timedelta(days=60)
T3 = T0 + timedelta(days=90)


def _make_party(
    connection: Connection, world_id: uuid.UUID, name: str = "The Company"
) -> uuid.UUID:
    value = connection.execute(
        text("INSERT INTO campaign.parties (world_id, name) VALUES (:w, :n) RETURNING party_id"),
        {"w": world_id, "n": name},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _join(
    connection: Connection,
    party_id: uuid.UUID,
    member_id: uuid.UUID,
    valid_from: datetime,
    valid_to: datetime | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.party_memberships (party_id, member_id, valid_from, valid_to)
            VALUES (:p, :m, :f, :t)
        """),
        {"p": party_id, "m": member_id, "f": valid_from, "t": valid_to},
    )


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="party-world")


@pytest.fixture
def member_ids(db_connection: Connection, world_id: uuid.UUID) -> list[uuid.UUID]:
    etype = make_entity_type(db_connection, "party_member_type")
    return [make_entity(db_connection, world_id, etype, name=f"Member {i}") for i in range(2)]


# ---------------------------------------------------------------------------
# The six required proofs
# ---------------------------------------------------------------------------


def test_overlapping_membership_same_party_same_member_is_rejected(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """The rule itself."""
    party = _make_party(db_connection, world_id)
    _join(db_connection, party, member_ids[0], T0, T2)

    with pytest.raises(IntegrityError) as exc:
        _join(db_connection, party, member_ids[0], T1, T3)  # starts inside the first
    assert "ex_party_memberships_no_overlap" in str(exc.value)


def test_boundary_touching_interval_is_accepted(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """Half-open '[)': leaving and rejoining at the same instant is ordinary.

    A '[]' range would reject this, which is the mistake this test exists to
    catch if the interval style is ever changed.
    """
    party = _make_party(db_connection, world_id)
    _join(db_connection, party, member_ids[0], T0, T1)
    _join(db_connection, party, member_ids[0], T1, T2)  # starts exactly when the first ended

    count = db_connection.execute(
        text(
            "SELECT count(*) FROM campaign.party_memberships WHERE party_id = :p AND member_id = :m"
        ),
        {"p": party, "m": member_ids[0]},
    ).scalar()
    assert count == 2


def test_overlapping_dates_for_different_members_are_accepted(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """A party has more than one member at a time — the obvious case a
    constraint keyed only on party_id would break."""
    party = _make_party(db_connection, world_id)
    _join(db_connection, party, member_ids[0], T0, T2)
    _join(db_connection, party, member_ids[1], T0, T2)


def test_overlapping_dates_same_member_different_parties_are_accepted(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """A character may belong to two parties at once — the case a constraint
    keyed only on member_id would break."""
    first = _make_party(db_connection, world_id, name="Party A")
    second = _make_party(db_connection, world_id, name="Party B")
    _join(db_connection, first, member_ids[0], T0, T2)
    _join(db_connection, second, member_ids[0], T0, T2)


def test_open_ended_membership_blocks_a_later_overlapping_membership(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """NULL valid_to must produce an unbounded upper range, not an empty one."""
    party = _make_party(db_connection, world_id)
    _join(db_connection, party, member_ids[0], T0, None)  # still a member

    with pytest.raises(IntegrityError) as exc:
        _join(db_connection, party, member_ids[0], T2, T3)
    assert "ex_party_memberships_no_overlap" in str(exc.value)


def test_migration_produced_the_extension_and_constraint(db_connection: Connection) -> None:
    """The migration succeeds from a clean database with the extension enabled.

    The ephemeral database this suite runs against is built from base by
    `alembic upgrade head` in conftest, so reaching this assertion at all means
    the full chain applied cleanly. What is asserted here is that it produced
    the right objects rather than merely not erroring.
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
    normalized = str(definition).replace("'::text", "'")
    assert normalized == (
        "EXCLUDE USING gist (party_id WITH =, member_id WITH =, "
        "tstzrange(valid_from, valid_to, '[)') WITH &&)"
    ), f"constraint shape changed: {definition}"


# ---------------------------------------------------------------------------
# Temporal column validation
# ---------------------------------------------------------------------------


def test_valid_from_is_required(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    party = _make_party(db_connection, world_id)
    with pytest.raises(IntegrityError):
        _join(db_connection, party, member_ids[0], None)  # type: ignore[arg-type]


def test_bounded_membership_must_end_after_it_begins(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    party = _make_party(db_connection, world_id)
    with pytest.raises(IntegrityError) as exc:
        _join(db_connection, party, member_ids[0], T2, T0)
    assert "ck_party_memberships_valid_range" in str(exc.value)


def test_zero_length_membership_is_rejected(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """Equal endpoints make an empty '[)' range, which overlaps nothing and
    would slip past the exclusion constraint entirely."""
    party = _make_party(db_connection, world_id)
    with pytest.raises(IntegrityError) as exc:
        _join(db_connection, party, member_ids[0], T0, T0)
    assert "ck_party_memberships_valid_range" in str(exc.value)


def test_infinity_is_not_an_alternative_to_null(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """One representation of open-ended, not two."""
    party = _make_party(db_connection, world_id)
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.party_memberships (party_id, member_id, valid_from, valid_to)
                VALUES (:p, :m, :f, 'infinity'::timestamptz)
            """),
            {"p": party, "m": member_ids[0], "f": T0},
        )
    assert "ck_party_memberships_open_ended_is_null" in str(exc.value)


def test_two_open_ended_memberships_of_the_same_party_conflict(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    party = _make_party(db_connection, world_id)
    _join(db_connection, party, member_ids[0], T0, None)
    with pytest.raises(IntegrityError):
        _join(db_connection, party, member_ids[0], T3, None)


def test_member_must_belong_to_the_partys_world(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    other_world = make_world(db_connection, slug="party-other-world")
    etype = make_entity_type(db_connection, "foreign_member_type")
    foreign_member = make_entity(db_connection, other_world, etype)
    party = _make_party(db_connection, world_id)

    with pytest.raises(Exception) as exc:
        _join(db_connection, party, foreign_member, T0)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# Concurrency — why this is a database constraint and not an application check
# ---------------------------------------------------------------------------


def test_concurrent_overlapping_inserts_cannot_both_commit(
    db_connection: Connection, world_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    """Two simultaneous transactions inserting overlapping memberships.

    This is the case an application-level "check then insert" cannot handle:
    both transactions would see no conflicting row, both would insert, and both
    would commit. The exclusion constraint makes the second block on the first
    and then fail.

    Runs on its own connections rather than the fixture's, because it needs two
    real concurrent transactions. It therefore commits, so it cleans up after
    itself explicitly.
    """
    import os

    party = _make_party(db_connection, world_id)
    member = member_ids[0]
    # Make the party and member visible to the other connections.
    db_connection.commit()

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            _join(first, party, member, T0, T2)

            # Overlaps the uncommitted row above. The exclusion constraint makes
            # this wait rather than fail immediately, so it is issued with a
            # short lock timeout: the block itself is the evidence.
            second.execute(text("SET LOCAL lock_timeout = '1s'"))
            with pytest.raises(Exception) as exc:
                _join(second, party, member, T1, T3)
                second.commit()

            message = str(exc.value)
            assert (
                "lock_timeout" in message
                or "ex_party_memberships_no_overlap" in message
                or "canceling statement" in message
            ), f"expected a conflict or lock timeout, got: {message}"

            second.rollback()
            first.rollback()
    finally:
        engine.dispose()
        # The fixture transaction was committed above, so undo it by hand.
        db_connection.execute(
            text("DELETE FROM campaign.party_memberships WHERE party_id = :p"), {"p": party}
        )
        db_connection.execute(
            text("DELETE FROM campaign.parties WHERE party_id = :p"), {"p": party}
        )
        db_connection.commit()
