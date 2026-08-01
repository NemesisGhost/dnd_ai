"""Tests for the shared domain types created in
database/migrations/versions/002_shared_domains.py (docs/PLAN.md §4.2).

Every nontrivial constraint requires a positive and a negative test per
docs/DATABASE_CONVENTIONS.md §32.1. Each test creates its own TEMP TABLE inside
the fixture's transaction, which rolls back after the test (DDL is transactional
in PostgreSQL), so tests never see each other's tables.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.database


def test_rating_1_10_accepts_values_in_range(db_connection: Connection) -> None:
    db_connection.execute(text("CREATE TEMP TABLE t_rating (value core.rating_1_10)"))
    db_connection.execute(text("INSERT INTO t_rating (value) VALUES (1), (10), (5)"))


@pytest.mark.parametrize("value", [0, 11, -1])
def test_rating_1_10_rejects_values_out_of_range(db_connection: Connection, value: int) -> None:
    db_connection.execute(text("CREATE TEMP TABLE t_rating (value core.rating_1_10)"))
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("INSERT INTO t_rating (value) VALUES (:value)"), {"value": value}
        )


def test_percentage_0_100_accepts_values_in_range(db_connection: Connection) -> None:
    db_connection.execute(text("CREATE TEMP TABLE t_pct (value core.percentage_0_100)"))
    db_connection.execute(text("INSERT INTO t_pct (value) VALUES (0), (100), (50)"))


@pytest.mark.parametrize("value", [-1, 101])
def test_percentage_0_100_rejects_values_out_of_range(
    db_connection: Connection, value: int
) -> None:
    db_connection.execute(text("CREATE TEMP TABLE t_pct (value core.percentage_0_100)"))
    with pytest.raises(IntegrityError):
        db_connection.execute(text("INSERT INTO t_pct (value) VALUES (:value)"), {"value": value})


def test_nonnegative_integer_accepts_zero_and_positive(db_connection: Connection) -> None:
    db_connection.execute(text("CREATE TEMP TABLE t_nonneg (value core.nonnegative_integer)"))
    db_connection.execute(text("INSERT INTO t_nonneg (value) VALUES (0), (1), (1000000)"))


def test_nonnegative_integer_rejects_negative(db_connection: Connection) -> None:
    db_connection.execute(text("CREATE TEMP TABLE t_nonneg (value core.nonnegative_integer)"))
    with pytest.raises(IntegrityError):
        db_connection.execute(text("INSERT INTO t_nonneg (value) VALUES (-1)"))
