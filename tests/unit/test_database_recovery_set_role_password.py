"""Tests for `scripts/operations/database_recovery.py`'s `set-role-password`
support — `_pg_string_literal` (SQL-literal escaping) and
`_read_role_password` (env-var/file credential resolution) — exercised as
plain Python, no Docker or database needed. The command's own end-to-end
behavior (preflight, `ALTER ROLE`, reporting) requires a running `db`
container and is exercised manually/in CI rather than duplicated here — see
docs/operations/DATABASE_RECOVERY.md's "Provisioning application-role
credentials" section.
"""

import argparse
from pathlib import Path

import pytest
from operations.database_recovery import OperationError, _pg_string_literal, _read_role_password

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _pg_string_literal
# ---------------------------------------------------------------------------


def test_a_plain_password_round_trips() -> None:
    assert _pg_string_literal("hunter2") == "'hunter2'"


def test_an_embedded_single_quote_is_doubled() -> None:
    # The standard SQL escaping mechanism under standard_conforming_strings
    # = on (PostgreSQL's default since 9.1, never overridden in this
    # project) — doubling is the only special case this function needs.
    assert _pg_string_literal("o'brien") == "'o''brien'"


def test_multiple_embedded_quotes_are_all_doubled() -> None:
    assert _pg_string_literal("''") == "''''''"


def test_a_password_containing_sql_metacharacters_is_still_a_single_literal() -> None:
    # Semicolons, comments, and backslashes are not special inside a
    # standard_conforming_strings string literal — only the quote
    # character is. This is the regression case an f-string interpolation
    # bug (no escaping at all) would get wrong.
    value = "pw; DROP TABLE core.worlds; --"
    literal = _pg_string_literal(value)
    assert literal == "'pw; DROP TABLE core.worlds; --'"
    # Still exactly one literal: no unescaped quote splits it into two
    # tokens or terminates it early.
    assert literal.count("'") == 2


def test_an_empty_password_is_a_valid_empty_literal() -> None:
    # Emptiness is rejected by _read_role_password below, not by the
    # quoting function itself — this function's only job is correct
    # escaping of whatever string it's given.
    assert _pg_string_literal("") == "''"


def test_a_nul_byte_is_rejected() -> None:
    with pytest.raises(OperationError, match="NUL byte"):
        _pg_string_literal("bad\x00password")


# ---------------------------------------------------------------------------
# _read_role_password
# ---------------------------------------------------------------------------


def _args(**overrides: object) -> argparse.Namespace:
    defaults = {"password_env_var": None, "password_file": None}
    return argparse.Namespace(**{**defaults, **overrides})


def test_reads_from_the_named_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ROLE_PASSWORD", "s3cret")
    args = _args(password_env_var="TEST_ROLE_PASSWORD")
    assert _read_role_password(args) == "s3cret"


def test_fails_when_the_named_environment_variable_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_ROLE_PASSWORD_UNSET", raising=False)
    args = _args(password_env_var="TEST_ROLE_PASSWORD_UNSET")
    with pytest.raises(OperationError, match="not set"):
        _read_role_password(args)


def test_reads_from_a_file_and_strips_exactly_one_trailing_newline(tmp_path: Path) -> None:
    secret_file = tmp_path / "app_read_write_password"
    secret_file.write_text("file-secret\n", encoding="utf-8", newline="")
    args = _args(password_file=str(secret_file))
    assert _read_role_password(args) == "file-secret"


def test_reads_from_a_file_and_strips_a_trailing_crlf(tmp_path: Path) -> None:
    secret_file = tmp_path / "app_read_write_password"
    secret_file.write_bytes(b"file-secret\r\n")
    args = _args(password_file=str(secret_file))
    assert _read_role_password(args) == "file-secret"


def test_a_file_with_no_trailing_newline_is_read_verbatim(tmp_path: Path) -> None:
    secret_file = tmp_path / "app_read_write_password"
    secret_file.write_text("file-secret", encoding="utf-8", newline="")
    args = _args(password_file=str(secret_file))
    assert _read_role_password(args) == "file-secret"


def test_internal_whitespace_in_a_file_secret_is_preserved(tmp_path: Path) -> None:
    # Only a single trailing newline is stripped — never a full .strip(),
    # which would silently corrupt a password with meaningful leading/
    # trailing spaces of its own.
    secret_file = tmp_path / "app_read_write_password"
    secret_file.write_text(" file secret \n", encoding="utf-8", newline="")
    args = _args(password_file=str(secret_file))
    assert _read_role_password(args) == " file secret "


def test_fails_when_the_password_file_does_not_exist(tmp_path: Path) -> None:
    args = _args(password_file=str(tmp_path / "does-not-exist"))
    with pytest.raises(OperationError, match="does not exist"):
        _read_role_password(args)


def test_fails_when_neither_source_is_given() -> None:
    with pytest.raises(OperationError, match="exactly one"):
        _read_role_password(_args())


def test_fails_when_both_sources_are_given(tmp_path: Path) -> None:
    secret_file = tmp_path / "app_read_write_password"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    with pytest.raises(OperationError, match="exactly one"):
        _read_role_password(_args(password_env_var="SOME_VAR", password_file=str(secret_file)))


def test_fails_when_the_resolved_password_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ROLE_PASSWORD_EMPTY", "")
    args = _args(password_env_var="TEST_ROLE_PASSWORD_EMPTY")
    with pytest.raises(OperationError, match="empty"):
        _read_role_password(args)
