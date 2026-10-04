"""security.actor_idempotent_requests (revision 112): constraints only.

The reserve/replay behavior is covered against the API-layer helpers in
test_actor_idempotency.py; this file pins what the schema itself enforces.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.factories import make_user

pytestmark = pytest.mark.database


def _insert(
    connection: Connection,
    user_id: object,
    key: str,
    *,
    status: int | None = None,
    body: str | None = None,
    completed: bool = False,
) -> None:
    connection.execute(
        text("""
            INSERT INTO security.actor_idempotent_requests
                (actor_user_id, idempotency_key, request_fingerprint,
                 response_status_code, response_body, completed_at)
            VALUES (:u, :k, 'f', :s, CAST(:b AS jsonb),
                    CASE WHEN :c THEN now() ELSE NULL END)
        """),
        {"u": user_id, "k": key, "s": status, "b": body, "c": completed},
    )


def test_a_key_is_unique_per_actor(db_connection: Connection) -> None:
    user = make_user(db_connection)
    _insert(db_connection, user, "key-1")
    with pytest.raises(IntegrityError) as exc:
        _insert(db_connection, user, "key-1")
    assert "ux_actor_idempotent_requests_scope" in str(exc.value)


def test_the_same_key_is_independent_across_actors(db_connection: Connection) -> None:
    _insert(db_connection, make_user(db_connection, "A"), "shared")
    _insert(db_connection, make_user(db_connection, "B"), "shared")


@pytest.mark.parametrize("key", ["", "has space", "x" * 256, "semi;colon"])
def test_key_format_is_restricted(db_connection: Connection, key: str) -> None:
    with pytest.raises(IntegrityError) as exc:
        _insert(db_connection, make_user(db_connection), key)
    assert "ck_actor_idempotent_requests_key_format" in str(exc.value)


@pytest.mark.parametrize(
    ("status", "body", "completed"),
    [(201, None, False), (None, "{}", False), (201, "{}", False), (None, None, True)],
)
def test_completion_columns_are_set_together(
    db_connection: Connection, status: int | None, body: str | None, completed: bool
) -> None:
    with pytest.raises(IntegrityError) as exc:
        _insert(
            db_connection,
            make_user(db_connection),
            "partial",
            status=status,
            body=body,
            completed=completed,
        )
    assert "ck_actor_idempotent_requests_completion_consistent" in str(exc.value)


def test_a_fully_completed_row_is_accepted(db_connection: Connection) -> None:
    _insert(db_connection, make_user(db_connection), "done", status=201, body="{}", completed=True)
