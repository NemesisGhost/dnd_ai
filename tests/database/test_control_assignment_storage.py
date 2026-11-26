"""P15-C11-S01-T01: storage, invariants and uniqueness of control assignments (D1-D16).

A control assignment is a row of `security.membership_character_relationships` with
`is_control_assignment` true (ADR 0021 sections 2.2-2.3). T01 adds the columns, the derived values,
the CHECK constraints, the replaced legacy index and the two new partial unique indexes. It changes no
resolver and no reader. No writer exists in S01, so these tests insert rows directly through the
test-only helper `make_control_assignment`, which is not importable from `src`.
"""

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.access_grants import (
    change_character_relationship,
    grant_character_relationship,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_control_assignment,
    make_membership_character_relationship,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    relationship_type_id,
)

pytestmark = pytest.mark.database

_TABLE = "security.membership_character_relationships"


@dataclass
class World:
    world_id: uuid.UUID
    timeline_id: uuid.UUID
    campaign_id: uuid.UUID
    other_campaign_id: uuid.UUID
    character_id: uuid.UUID
    owner: uuid.UUID  # memberships, campaign 1
    member_a: uuid.UUID
    member_b: uuid.UUID
    other_member: uuid.UUID  # membership in the second campaign (same timeline)
    t10: uuid.UUID
    t20: uuid.UUID


@pytest.fixture
def w(db_connection: Connection) -> World:
    c = db_connection
    world_id = make_world(c, slug=f"assignment-storage-{uuid.uuid4().hex[:8]}")
    timeline_id = make_timeline(c, world_id, "Primary", is_primary=True)
    campaign_id = make_campaign(c, timeline_id, "One")
    other_campaign_id = make_campaign(c, timeline_id, "Two")
    return World(
        world_id=world_id,
        timeline_id=timeline_id,
        campaign_id=campaign_id,
        other_campaign_id=other_campaign_id,
        character_id=make_character(c, world_id, name="Alpha"),
        owner=make_campaign_membership(c, campaign_id, make_user(c, "Owner")),
        member_a=make_campaign_membership(c, campaign_id, make_user(c, "A")),
        member_b=make_campaign_membership(c, campaign_id, make_user(c, "B")),
        other_member=make_campaign_membership(c, other_campaign_id, make_user(c, "Other")),
        t10=make_world_time(c, world_id, 10),
        t20=make_world_time(c, world_id, 20),
    )


def refused(connection: Connection) -> "_Refused":
    return _Refused(connection)


class _Refused:
    """`with refused(c):` expects an integrity error and rolls back to a savepoint."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._savepoint = connection.begin_nested()

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            self._savepoint.rollback()
            raise AssertionError("expected the database to refuse the statement")
        self._savepoint.rollback()
        return isinstance(exc, IntegrityError)


def row(connection: Connection, row_id: uuid.UUID) -> dict[str, object]:
    return dict(
        connection.execute(
            text(f"SELECT * FROM {_TABLE} WHERE membership_character_relationship_id = :id"),
            {"id": row_id},
        )
        .mappings()
        .one()
    )


# ---------------------------------------------------------------------------
# D1-D2: derived and immutable columns
# ---------------------------------------------------------------------------


def test_d1_an_ongoing_primary_fills_campaign_and_derives_is_primary(
    db_connection: Connection, w: World
) -> None:
    rid = make_control_assignment(
        db_connection, w.member_a, w.character_id, "primary_controller", "ongoing"
    )
    stored = row(db_connection, rid)
    assert stored["campaign_id"] == w.campaign_id
    assert stored["is_primary"] is True
    assert stored["is_control_assignment"] is True
    assert stored["assignment_period_kind"] == "ongoing"
    co = make_control_assignment(
        db_connection, w.member_b, w.character_id, "co_controller", "ongoing"
    )
    assert row(db_connection, co)["is_primary"] is False


def test_d2_a_foreign_campaign_id_and_a_campaign_update_are_refused(
    db_connection: Connection, w: World
) -> None:
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "primary_controller",
            "ongoing",
            campaign_id=w.other_campaign_id,
        )
    rid = make_control_assignment(
        db_connection, w.member_a, w.character_id, "primary_controller", "ongoing"
    )
    with refused(db_connection):
        db_connection.execute(
            text(
                f"UPDATE {_TABLE} SET campaign_id = :c WHERE membership_character_relationship_id = :id"
            ),
            {"c": w.other_campaign_id, "id": rid},
        )
    for column, value in (
        ("is_control_assignment", "false"),
        ("assignment_period_kind", "'dated'"),
    ):
        with refused(db_connection):
            db_connection.execute(
                text(
                    f"UPDATE {_TABLE} SET {column} = {value} "
                    "WHERE membership_character_relationship_id = :id"
                ),
                {"id": rid},
            )


# ---------------------------------------------------------------------------
# D3-D7: type, kind and period shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "viewer", "portrayer", "former_controller"])
def test_d3_only_the_two_controller_types_can_be_assignments(
    db_connection: Connection, w: World, role: str
) -> None:
    with refused(db_connection):
        make_control_assignment(db_connection, w.member_a, w.character_id, role, "ongoing")


def test_d4_kind_is_present_exactly_when_the_row_is_an_assignment(
    db_connection: Connection, w: World
) -> None:
    with refused(db_connection):
        make_control_assignment(db_connection, w.member_a, w.character_id, "co_controller", None)
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "owner",
            "ongoing",
            is_assignment=False,
        )
    with refused(db_connection):
        make_control_assignment(
            db_connection, w.member_a, w.character_id, "co_controller", "forever"
        )


def test_d5_an_ongoing_assignment_carries_no_world_time(
    db_connection: Connection, w: World
) -> None:
    with refused(db_connection):
        make_control_assignment(
            db_connection, w.member_a, w.character_id, "co_controller", "ongoing", from_time=w.t10
        )
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "co_controller",
            "ongoing",
            from_time=w.t10,
            to_time=w.t20,
        )


def test_d6_a_dated_assignment_needs_a_start_and_derives_its_period(
    db_connection: Connection, w: World
) -> None:
    with refused(db_connection):
        make_control_assignment(db_connection, w.member_a, w.character_id, "co_controller", "dated")
    with refused(db_connection):
        make_control_assignment(
            db_connection, w.member_a, w.character_id, "co_controller", "dated", to_time=w.t20
        )
    open_ended = make_control_assignment(
        db_connection, w.member_a, w.character_id, "co_controller", "dated", from_time=w.t10
    )
    closed = make_control_assignment(
        db_connection,
        w.member_b,
        w.character_id,
        "co_controller",
        "dated",
        from_time=w.t10,
        to_time=w.t20,
    )
    ranges = {
        rid: db_connection.execute(
            text(
                f"SELECT lower(effective_period), upper(effective_period), "
                f"lower_inc(effective_period), upper_inc(effective_period) FROM {_TABLE} "
                "WHERE membership_character_relationship_id = :id"
            ),
            {"id": rid},
        ).one()
        for rid in (open_ended, closed)
    }
    assert tuple(ranges[open_ended]) == (10, None, True, False)
    assert tuple(ranges[closed]) == (10, 20, True, False)


def test_d7_an_assignment_cannot_expire_or_be_timeline_scoped(
    db_connection: Connection, w: World
) -> None:
    with refused(db_connection):
        make_control_assignment(
            db_connection, w.member_a, w.character_id, "co_controller", "ongoing", expires=True
        )
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "co_controller",
            "ongoing",
            timeline_id=w.timeline_id,
        )


# ---------------------------------------------------------------------------
# D8-D13: uniqueness
# ---------------------------------------------------------------------------


def test_d8_one_live_primary_per_campaign_and_character(
    db_connection: Connection, w: World
) -> None:
    first = make_control_assignment(
        db_connection, w.member_a, w.character_id, "primary_controller", "ongoing"
    )
    with refused(db_connection):
        make_control_assignment(
            db_connection, w.member_b, w.character_id, "primary_controller", "ongoing"
        )
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_b,
            w.character_id,
            "primary_controller",
            "dated",
            from_time=w.t10,
        )
    db_connection.execute(
        text(
            f"UPDATE {_TABLE} SET revoked_at = now() WHERE membership_character_relationship_id = :id"
        ),
        {"id": first},
    )
    make_control_assignment(
        db_connection, w.member_b, w.character_id, "primary_controller", "ongoing"
    )


def test_d9_one_membership_cannot_hold_two_live_assignments_on_a_character(
    db_connection: Connection, w: World
) -> None:
    make_control_assignment(
        db_connection, w.member_a, w.character_id, "primary_controller", "ongoing"
    )
    with refused(db_connection):
        make_control_assignment(
            db_connection, w.member_a, w.character_id, "co_controller", "ongoing"
        )


def test_d10_co_controllers_coexist_with_each_other_and_with_a_primary(
    db_connection: Connection, w: World
) -> None:
    make_control_assignment(db_connection, w.owner, w.character_id, "primary_controller", "ongoing")
    make_control_assignment(db_connection, w.member_a, w.character_id, "co_controller", "ongoing")
    make_control_assignment(
        db_connection, w.member_b, w.character_id, "co_controller", "dated", from_time=w.t10
    )
    live = db_connection.execute(
        text(
            f"SELECT count(*) FROM {_TABLE} WHERE character_id = :c AND is_control_assignment "
            "AND revoked_at IS NULL"
        ),
        {"c": w.character_id},
    ).scalar_one()
    assert live == 3


def test_d11_a_legacy_primary_and_a_primary_assignment_coexist(
    db_connection: Connection, w: World
) -> None:
    make_membership_character_relationship(
        db_connection,
        w.member_a,
        w.character_id,
        relationship_type_id(db_connection, "primary_controller"),
    )
    make_control_assignment(
        db_connection, w.member_a, w.character_id, "primary_controller", "ongoing"
    )


def test_d12_two_live_legacy_rows_of_one_type_are_still_refused_under_the_existing_name(
    db_connection: Connection, w: World
) -> None:
    """Guard: passes at baseline and after."""
    rtype = relationship_type_id(db_connection, "primary_controller")
    make_membership_character_relationship(db_connection, w.member_a, w.character_id, rtype)
    with pytest.raises(IntegrityError) as caught, db_connection.begin_nested():
        make_membership_character_relationship(db_connection, w.member_a, w.character_id, rtype)
    assert "ux_membership_character_relationships_active_type" in str(caught.value)


def test_d13_two_campaigns_on_one_timeline_each_hold_their_own_primary(
    db_connection: Connection, w: World
) -> None:
    make_control_assignment(
        db_connection, w.member_a, w.character_id, "primary_controller", "ongoing"
    )
    other = make_control_assignment(
        db_connection, w.other_member, w.character_id, "primary_controller", "ongoing"
    )
    assert row(db_connection, other)["campaign_id"] == w.other_campaign_id


# ---------------------------------------------------------------------------
# D14-D15: revocation columns
# ---------------------------------------------------------------------------


def test_d14_revoker_and_reason_are_scoped_and_only_for_revoked_rows(
    db_connection: Connection, w: World
) -> None:
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "co_controller",
            "ongoing",
            revoked=True,
            revoked_by=w.other_member,
        )
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "co_controller",
            "ongoing",
            revocation_reason="not revoked",
        )
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "co_controller",
            "ongoing",
            revoked=True,
            revocation_reason="",
        )
    with refused(db_connection):
        make_control_assignment(
            db_connection,
            w.member_a,
            w.character_id,
            "co_controller",
            "ongoing",
            revoked_by=w.owner,
        )
    ok = make_control_assignment(
        db_connection,
        w.member_a,
        w.character_id,
        "co_controller",
        "ongoing",
        revoked=True,
        revoked_by=w.owner,
        revocation_reason="Stepped down",
    )
    assert row(db_connection, ok)["revoked_by_membership_id"] == w.owner


def test_d15_a_revoked_assignment_may_have_neither_revoker_nor_reason(
    db_connection: Connection, w: World
) -> None:
    rid = make_control_assignment(
        db_connection, w.member_a, w.character_id, "co_controller", "ongoing", revoked=True
    )
    stored = row(db_connection, rid)
    assert stored["revoked_at"] is not None
    assert stored["revoked_by_membership_id"] is None and stored["revocation_reason"] is None


# ---------------------------------------------------------------------------
# D16: pre-existing insert paths
# ---------------------------------------------------------------------------


def test_d16_the_existing_insert_paths_still_produce_legacy_rows(
    db_connection: Connection, w: World
) -> None:
    """Guard (pre-change part): the factory and both legacy commands work unchanged."""
    factory_id = make_membership_character_relationship(
        db_connection,
        w.member_a,
        w.character_id,
        relationship_type_id(db_connection, "viewer"),
    )
    granted = grant_character_relationship(
        db_connection,
        campaign_membership_id=w.member_b,
        character_id=w.character_id,
        relationship_type_code="co_controller",
        campaign_id=w.campaign_id,
        expected_world_id=w.world_id,
        granted_by_membership_id=w.owner,
    )
    changed = change_character_relationship(
        db_connection,
        membership_character_relationship_id=granted.membership_character_relationship_id,
        campaign_id=w.campaign_id,
        expected_world_id=w.world_id,
        new_relationship_type_id=relationship_type_id(db_connection, "primary_controller"),
        granted_by_membership_id=w.owner,
    )
    for rid in (
        factory_id,
        granted.membership_character_relationship_id,
        changed.membership_character_relationship_id,
    ):
        assert row(db_connection, rid)["membership_character_relationship_id"] == rid
    assert changed.new_relationship_type_code == "primary_controller"


def test_d16b_legacy_rows_carry_their_campaign_and_are_never_assignments(
    db_connection: Connection, w: World
) -> None:
    """The new-column half of D16, added with the migration."""
    factory_id = make_membership_character_relationship(
        db_connection,
        w.member_a,
        w.character_id,
        relationship_type_id(db_connection, "viewer"),
    )
    granted = grant_character_relationship(
        db_connection,
        campaign_membership_id=w.member_b,
        character_id=w.character_id,
        relationship_type_code="co_controller",
        campaign_id=w.campaign_id,
        expected_world_id=w.world_id,
        granted_by_membership_id=w.owner,
    )
    changed = change_character_relationship(
        db_connection,
        membership_character_relationship_id=granted.membership_character_relationship_id,
        campaign_id=w.campaign_id,
        expected_world_id=w.world_id,
        new_relationship_type_id=relationship_type_id(db_connection, "primary_controller"),
        granted_by_membership_id=w.owner,
    )
    for rid in (
        factory_id,
        granted.membership_character_relationship_id,
        changed.membership_character_relationship_id,
    ):
        stored = row(db_connection, rid)
        assert stored["campaign_id"] == w.campaign_id
        assert stored["is_control_assignment"] is False
        assert stored["assignment_period_kind"] is None
    # a legacy primary row never touches the assignment slot
    assert row(db_connection, changed.membership_character_relationship_id)["is_primary"] is True
    make_control_assignment(
        db_connection, w.member_b, w.character_id, "primary_controller", "ongoing"
    )


def test_d11b_a_legacy_primary_never_occupies_the_live_primary_slot(
    db_connection: Connection, w: World
) -> None:
    """A legacy primary_controller row has is_primary true (derived for every row) and still never enters
    the live-primary index, whose predicate requires is_control_assignment."""
    legacy = make_membership_character_relationship(
        db_connection,
        w.member_a,
        w.character_id,
        relationship_type_id(db_connection, "primary_controller"),
    )
    assert row(db_connection, legacy)["is_primary"] is True
    assert row(db_connection, legacy)["is_control_assignment"] is False
    assigned = make_control_assignment(
        db_connection, w.member_b, w.character_id, "primary_controller", "ongoing"
    )
    assert row(db_connection, assigned)["is_primary"] is True
    # and a second legacy primary of another member is still accepted (legacy semantics unchanged)
    make_membership_character_relationship(
        db_connection,
        w.owner,
        w.character_id,
        relationship_type_id(db_connection, "primary_controller"),
    )
