"""begin/complete_actor_idempotent_request and record_change_log(reason=...)."""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.api.errors import ConflictError
from dnd_ai.api.idempotency import (
    ActorIdempotentReservation,
    IdempotentReplay,
    begin_actor_idempotent_request,
    complete_actor_idempotent_request,
)
from tests.factories import make_user, make_world

pytestmark = pytest.mark.database


def _begin(connection: Connection, user: uuid.UUID, key: str, **payload: object):  # type: ignore[no-untyped-def]
    return begin_actor_idempotent_request(
        connection,
        actor_user_id=user,
        idempotency_key=key,
        command_name="create_world",
        payload=dict(payload),
        correlation_id=None,
    )


def test_first_call_reserves_then_replays_the_completed_response(
    db_connection: Connection,
) -> None:
    user = make_user(db_connection)
    first = _begin(db_connection, user, "k1", name="A")
    assert isinstance(first, ActorIdempotentReservation)
    complete_actor_idempotent_request(
        db_connection,
        actor_idempotent_request_id=first.actor_idempotent_request_id,
        response_status_code=201,
        response_body={"world_id": "w"},
    )

    again = _begin(db_connection, user, "k1", name="A")
    assert isinstance(again, IdempotentReplay)
    assert again.response_status_code == 201
    assert again.response_body == {"world_id": "w"}


def test_reusing_a_key_with_a_different_payload_conflicts(db_connection: Connection) -> None:
    user = make_user(db_connection)
    first = _begin(db_connection, user, "k2", name="A")
    assert isinstance(first, ActorIdempotentReservation)
    complete_actor_idempotent_request(
        db_connection,
        actor_idempotent_request_id=first.actor_idempotent_request_id,
        response_status_code=201,
        response_body={},
    )
    with pytest.raises(ConflictError):
        _begin(db_connection, user, "k2", name="B")


def test_reusing_a_key_for_a_different_command_conflicts(db_connection: Connection) -> None:
    user = make_user(db_connection)
    first = _begin(db_connection, user, "k3", name="A")
    assert isinstance(first, ActorIdempotentReservation)
    complete_actor_idempotent_request(
        db_connection,
        actor_idempotent_request_id=first.actor_idempotent_request_id,
        response_status_code=201,
        response_body={},
    )
    with pytest.raises(ConflictError):
        begin_actor_idempotent_request(
            db_connection,
            actor_user_id=user,
            idempotency_key="k3",
            command_name="update_world",
            payload={"name": "A"},
            correlation_id=None,
        )


def test_an_incomplete_reservation_is_a_conflict_not_a_replay(db_connection: Connection) -> None:
    user = make_user(db_connection)
    _begin(db_connection, user, "k4", name="A")
    with pytest.raises(ConflictError):
        _begin(db_connection, user, "k4", name="A")


def test_keys_are_scoped_per_actor(db_connection: Connection) -> None:
    first = _begin(db_connection, make_user(db_connection, "A"), "shared", name="A")
    second = _begin(db_connection, make_user(db_connection, "B"), "shared", name="A")
    assert isinstance(first, ActorIdempotentReservation)
    assert isinstance(second, ActorIdempotentReservation)


def test_a_rolled_back_attempt_releases_the_key(postgres_engine) -> None:  # type: ignore[no-untyped-def]
    """The reservation INSERT shares the command's transaction, so a failed
    attempt never consumes the key."""
    with postgres_engine.connect() as setup:
        trans = setup.begin()
        user = make_user(setup, "Rollback")
        trans.commit()
    try:
        with postgres_engine.connect() as c1:
            t1 = c1.begin()
            assert isinstance(_begin(c1, user, "rb", name="A"), ActorIdempotentReservation)
            t1.rollback()
        with postgres_engine.connect() as c2:
            t2 = c2.begin()
            assert isinstance(_begin(c2, user, "rb", name="A"), ActorIdempotentReservation)
            t2.rollback()
    finally:
        with postgres_engine.connect() as cleanup:
            cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user})
            cleanup.commit()


def test_record_change_log_stores_a_bounded_reason_and_source(db_connection: Connection) -> None:
    user = make_user(db_connection)
    world = make_world(db_connection, "audit-reason")
    record_change_log(
        db_connection,
        change_action_code="archived",
        schema_name="core",
        table_name="worlds",
        record_id=world,
        entity_id=None,
        world_id=world,
        actor_user_id=user,
        correlation_id=None,
        command_name="archive_world",
        event_id=None,
        reason="retired for the season",
    )
    row = db_connection.execute(
        text("SELECT reason FROM audit.change_log WHERE record_id = :r"), {"r": world}
    ).one()
    assert row.reason == "retired for the season"


def test_record_change_log_rejects_an_oversized_reason(db_connection: Connection) -> None:
    with pytest.raises(ValueError, match="reason"):
        record_change_log(
            db_connection,
            change_action_code="archived",
            schema_name="core",
            table_name="worlds",
            record_id=None,
            entity_id=None,
            world_id=None,
            actor_user_id=make_user(db_connection),
            correlation_id=None,
            command_name="archive_world",
            event_id=None,
            reason="x" * 1001,
        )
