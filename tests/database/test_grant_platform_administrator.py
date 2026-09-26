"""Tests for `dnd_ai.commands.local_auth.grant_platform_administrator` —
the out-of-band platform-administrator recovery path (Phase 13E
checkpoint 9b; owner decision D-10).

Uses `postgres_engine` directly (not the rolled-back `db_connection`
fixture): `grant_platform_administrator` takes an `Engine` and commits its
own transaction, matching every other `Engine`-based public wrapper this
test suite already exercises this way (`test_local_auth_commands.py`'s
own docstring). Every test cleans up the rows it creates explicitly.
"""

import uuid

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.local_auth import (
    LastActivePlatformAdministratorError,
    PlatformAccountNotFoundError,
    grant_platform_administrator,
)
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from tests.factories import make_external_identity, make_user

pytestmark = pytest.mark.database


def _cleanup_user(engine: Engine, user_id: uuid.UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM audit.change_log WHERE record_id = :u"), {"u": user_id}
        )
        connection.execute(
            text("DELETE FROM security.external_identities WHERE user_id = :u"), {"u": user_id}
        )
        connection.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id})


def test_promotes_an_active_account(postgres_engine: Engine) -> None:
    login_name = f"gpa.promote.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as setup:
        user_id = make_user(setup, "Grant Recovery Target")
        make_external_identity(setup, user_id, issuer=LOCAL_AUTH_ISSUER, subject=login_name)

    try:
        result = grant_platform_administrator(postgres_engine, login_name=login_name)
        assert result.user_id == user_id
        assert result.already_administrator is False

        with postgres_engine.connect() as verify:
            is_admin = verify.execute(
                text("SELECT is_platform_administrator FROM security.users WHERE user_id = :u"),
                {"u": user_id},
            ).scalar_one()
            assert is_admin is True
    finally:
        _cleanup_user(postgres_engine, user_id)


def test_is_idempotent_on_an_already_administrator_account(postgres_engine: Engine) -> None:
    login_name = f"gpa.noop.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as setup:
        user_id = make_user(setup, "Grant Recovery Already Admin")
        make_external_identity(setup, user_id, issuer=LOCAL_AUTH_ISSUER, subject=login_name)

    try:
        first = grant_platform_administrator(postgres_engine, login_name=login_name)
        assert first.already_administrator is False

        second = grant_platform_administrator(postgres_engine, login_name=login_name)
        assert second.already_administrator is True
        assert second.user_id == user_id
    finally:
        _cleanup_user(postgres_engine, user_id)


def test_refuses_an_unknown_login_name(postgres_engine: Engine) -> None:
    with pytest.raises(PlatformAccountNotFoundError):
        grant_platform_administrator(postgres_engine, login_name=f"gpa.unknown.{uuid.uuid4().hex}")


def test_refuses_a_platform_disabled_account(postgres_engine: Engine) -> None:
    login_name = f"gpa.disabled.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as setup:
        user_id = make_user(setup, "Grant Recovery Disabled", status_code="inactive")
        make_external_identity(setup, user_id, issuer=LOCAL_AUTH_ISSUER, subject=login_name)

    try:
        with pytest.raises(PlatformAccountNotFoundError):
            grant_platform_administrator(postgres_engine, login_name=login_name)
    finally:
        _cleanup_user(postgres_engine, user_id)


def test_refuses_an_account_with_no_unrevoked_local_identity(postgres_engine: Engine) -> None:
    login_name = f"gpa.revoked.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as setup:
        user_id = make_user(setup, "Grant Recovery Revoked Identity")
        make_external_identity(
            setup, user_id, issuer=LOCAL_AUTH_ISSUER, subject=login_name, revoked=True
        )

    try:
        with pytest.raises(PlatformAccountNotFoundError):
            grant_platform_administrator(postgres_engine, login_name=login_name)
    finally:
        _cleanup_user(postgres_engine, user_id)


def test_normalizes_login_name_the_same_way_authentication_does(postgres_engine: Engine) -> None:
    login_name = f"gpa.normalize.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as setup:
        user_id = make_user(setup, "Grant Recovery Case")
        make_external_identity(setup, user_id, issuer=LOCAL_AUTH_ISSUER, subject=login_name)

    try:
        result = grant_platform_administrator(
            postgres_engine, login_name=f"  {login_name.upper()}  "
        )
        assert result.user_id == user_id
        assert result.login_name == login_name
    finally:
        _cleanup_user(postgres_engine, user_id)


def test_concurrent_promotion_and_disablement_serialize_on_the_advisory_lock(
    postgres_engine: Engine,
) -> None:
    """The recovery script's own promotion must serialize against a
    concurrent disable attempting to count active administrators — both
    acquire the identical `_PLATFORM_ADMINISTRATOR_LIFECYCLE_LOCK_KEY`
    advisory lock."""
    from dnd_ai.commands.local_auth import _disable_local_account_impl

    login_name = f"gpa.race.{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as setup:
        target_user_id = make_user(setup, "Grant Recovery Race Target")
        make_external_identity(setup, target_user_id, issuer=LOCAL_AUTH_ISSUER, subject=login_name)
        # A second, unrelated administrator so disabling the first is not
        # itself blocked by LastActivePlatformAdministratorError before the
        # lock contention this test exercises is ever reached.
        other_admin_login = f"gpa.race.other.{uuid.uuid4().hex[:8]}"
        other_admin_id = make_user(setup, "Grant Recovery Race Other Admin")
        make_external_identity(
            setup, other_admin_id, issuer=LOCAL_AUTH_ISSUER, subject=other_admin_login
        )
        setup.execute(
            text("UPDATE security.users SET is_platform_administrator = true WHERE user_id = :u"),
            {"u": other_admin_id},
        )

    try:
        with postgres_engine.connect() as first, postgres_engine.connect() as second:
            first.begin()
            second.begin()

            first.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('platform_administrator_lifecycle'))")
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                _disable_local_account_impl(
                    second, admin_user_id=other_admin_id, target_user_id=target_user_id
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected disable to block on the held advisory lock, got: {message}"
            )
            second.rollback()
            first.commit()

        result = grant_platform_administrator(postgres_engine, login_name=login_name)
        assert result.already_administrator is False
    finally:
        _cleanup_user(postgres_engine, target_user_id)
        _cleanup_user(postgres_engine, other_admin_id)


def test_last_active_administrator_message_no_longer_advises_an_impossible_remedy() -> None:
    message = LastActivePlatformAdministratorError().safe_message
    assert "Activate another administrator account first" not in message
    assert "direct database access" in message
