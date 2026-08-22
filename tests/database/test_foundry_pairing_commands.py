"""dnd_ai.commands.foundry_pairing — hashed pairing codes, portable Foundry
connections, per-device credentials, and short-lived access tokens
(docs/PLAN.md §23.5, Phase 11R workstream D).

Every test but the one true concurrency test uses the function-scoped,
always-rolled-back `db_connection` fixture together with each command's
composable `_..._impl(connection, ...)` form (or, for commands with no
public `Engine` wrapper at all — `exchange_foundry_device_credential`,
`revoke_foundry_device`, `revoke_foundry_connection`, `revoke_all_foundry_
connections`, `list_foundry_devices` — their only form) — never a public
`Engine`-based wrapper, which opens and commits its own independent
transaction and would leak committed rows past `db_connection`'s rollback.
The one test that genuinely needs two independent, concurrently-committing
transactions (`test_concurrent_consumption_of_the_same_code_succeeds_
exactly_once`) uses `postgres_engine` and the public wrappers instead,
mirroring `tests/database/test_local_auth_commands.py`'s identical
concurrency-test pattern.
"""

import concurrent.futures
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.foundry_pairing import (
    ForeignFoundryConnectionError,
    ForeignFoundryDeviceError,
    PairingCodeNotAcceptableError,
    _consume_foundry_pairing_code_impl,
    _create_foundry_pairing_code_impl,
    _rotate_foundry_device_impl,
    consume_foundry_pairing_code,
    create_foundry_pairing_code,
    exchange_foundry_device_credential,
    list_foundry_devices,
    revoke_all_foundry_connections,
    revoke_foundry_connection,
    revoke_foundry_device,
)
from dnd_ai.commands.integration import ExternalSystemNotFoundError
from dnd_ai.domain.foundry_pairing import FOUNDRY_SCOPES, InvalidFoundryScopeError
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_external_system,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

_SCOPES = frozenset({"encounter_read", "combat_sync"})


@pytest.fixture
def campaign_setup(db_connection: Connection) -> dict[str, uuid.UUID]:
    world_id = make_world(db_connection)
    timeline_id = make_timeline(db_connection, world_id)
    campaign_id = make_campaign(db_connection, timeline_id, lifecycle_status_code="pending")
    external_system_id = make_external_system(db_connection, world_id)
    user_id = make_user(db_connection)
    make_campaign_membership(db_connection, campaign_id, user_id)
    return {
        "world_id": world_id,
        "timeline_id": timeline_id,
        "campaign_id": campaign_id,
        "external_system_id": external_system_id,
        "user_id": user_id,
    }


def _issue_code(db_connection: Connection, setup: dict[str, uuid.UUID], **overrides: object):
    kwargs = {
        "requesting_user_id": setup["user_id"],
        "campaign_id": setup["campaign_id"],
        "external_system_id": setup["external_system_id"],
        "requested_scopes": _SCOPES,
    }
    kwargs.update(overrides)
    return _create_foundry_pairing_code_impl(db_connection, **kwargs)  # type: ignore[arg-type]


def _consume(db_connection: Connection, raw_code: str, **overrides: object):
    kwargs = {
        "raw_code": raw_code,
        "foundry_user_id": "foundry-user-1",
        "foundry_origin": "https://foundry.example.test",
        "device_label": "device-abc123",
    }
    kwargs.update(overrides)
    return _consume_foundry_pairing_code_impl(db_connection, **kwargs)  # type: ignore[arg-type]


# ==========================================================================
# Pairing code creation
# ==========================================================================


def test_create_pairing_code_returns_a_raw_code_and_hashes_it_at_rest(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    assert issued.raw_code
    assert issued.requested_scopes == tuple(sorted(_SCOPES))

    stored_hash = db_connection.execute(
        text(
            "SELECT code_hash FROM security.foundry_pairing_codes "
            "WHERE foundry_pairing_code_id = :id"
        ),
        {"id": issued.foundry_pairing_code_id},
    ).scalar()
    assert stored_hash != issued.raw_code
    assert len(stored_hash) == 64


def test_create_pairing_code_rejects_empty_scopes(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    with pytest.raises(InvalidFoundryScopeError):
        _issue_code(db_connection, campaign_setup, requested_scopes=frozenset())


def test_create_pairing_code_rejects_unknown_scope(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    with pytest.raises(InvalidFoundryScopeError):
        _issue_code(db_connection, campaign_setup, requested_scopes=frozenset({"admin_everything"}))


def test_create_pairing_code_rejects_mismatched_world(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    other_world_id = make_world(db_connection, "other-world")
    with pytest.raises(ExternalSystemNotFoundError):
        _issue_code(db_connection, campaign_setup, expected_world_id=other_world_id)


def test_create_pairing_code_accepts_matching_world(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(
        db_connection, campaign_setup, expected_world_id=campaign_setup["world_id"]
    )
    assert issued.raw_code


# ==========================================================================
# Pairing code consumption
# ==========================================================================


def test_consume_pairing_code_creates_connection_device_and_access_token(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    result = _consume(db_connection, issued.raw_code)

    assert result.user_id == campaign_setup["user_id"]
    assert result.campaign_id == campaign_setup["campaign_id"]
    assert result.external_system_id == campaign_setup["external_system_id"]
    assert result.granted_scopes == tuple(sorted(_SCOPES))
    assert result.raw_device_secret
    assert result.raw_access_token
    assert result.raw_device_secret != result.raw_access_token

    device_secret_hash = db_connection.execute(
        text(
            "SELECT device_secret_hash FROM security.foundry_devices WHERE foundry_device_id = :d"
        ),
        {"d": result.foundry_device_id},
    ).scalar()
    assert device_secret_hash != result.raw_device_secret

    consumed_device = db_connection.execute(
        text(
            "SELECT consumed_by_foundry_device_id FROM security.foundry_pairing_codes "
            "WHERE foundry_pairing_code_id = :c"
        ),
        {"c": issued.foundry_pairing_code_id},
    ).scalar()
    assert consumed_device == result.foundry_device_id


def test_consume_pairing_code_rejects_unknown_code(db_connection: Connection) -> None:
    with pytest.raises(PairingCodeNotAcceptableError):
        _consume(db_connection, "not-a-real-code")


def test_consume_pairing_code_rejects_already_consumed_code(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    _consume(db_connection, issued.raw_code)
    with pytest.raises(PairingCodeNotAcceptableError):
        _consume(db_connection, issued.raw_code, device_label="device-second-attempt")


def test_consume_pairing_code_rejects_expired_code(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    db_connection.execute(
        text(
            "UPDATE security.foundry_pairing_codes SET expires_at = now() - interval '1 minute' "
            "WHERE foundry_pairing_code_id = :c"
        ),
        {"c": issued.foundry_pairing_code_id},
    )
    with pytest.raises(PairingCodeNotAcceptableError):
        _consume(db_connection, issued.raw_code)


def test_consume_pairing_code_rejects_when_membership_no_longer_active(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 second' "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": campaign_setup["campaign_id"], "u": campaign_setup["user_id"]},
    )
    with pytest.raises(PairingCodeNotAcceptableError):
        _consume(db_connection, issued.raw_code)


def test_second_pairing_for_the_same_foundry_user_reuses_the_connection(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    first_issued = _issue_code(db_connection, campaign_setup)
    first = _consume(db_connection, first_issued.raw_code, device_label="device-one")

    second_issued = _issue_code(db_connection, campaign_setup)
    second = _consume(db_connection, second_issued.raw_code, device_label="device-two")

    assert first.foundry_connection_id == second.foundry_connection_id
    assert first.foundry_device_id != second.foundry_device_id


def test_concurrent_consumption_of_the_same_code_succeeds_exactly_once(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as setup:
        world_id = make_world(setup, f"concurrent-pairing-world-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(setup, world_id)
        campaign_id = make_campaign(setup, timeline_id, lifecycle_status_code="pending")
        external_system_id = make_external_system(setup, world_id)
        user_id = make_user(setup)
        make_campaign_membership(setup, campaign_id, user_id)

    issued = create_foundry_pairing_code(
        postgres_engine,
        requesting_user_id=user_id,
        campaign_id=campaign_id,
        external_system_id=external_system_id,
        requested_scopes=_SCOPES,
    )

    def _attempt() -> str:
        try:
            consume_foundry_pairing_code(
                postgres_engine,
                raw_code=issued.raw_code,
                foundry_user_id="foundry-user-race",
                foundry_origin="https://foundry.example.test",
                device_label="device-race",
            )
            return "consumed"
        except PairingCodeNotAcceptableError:
            return "rejected"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: _attempt(), range(8)))

    assert outcomes.count("consumed") == 1
    assert outcomes.count("rejected") == 7


# ==========================================================================
# Access-token exchange
# ==========================================================================


def test_exchange_foundry_device_credential_succeeds(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)

    exchanged = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret=consumed.raw_device_secret,
    )
    assert exchanged is not None
    assert exchanged.raw_access_token != consumed.raw_access_token
    assert exchanged.foundry_connection_id == consumed.foundry_connection_id
    assert exchanged.granted_scopes == consumed.granted_scopes


def test_exchange_rejects_wrong_secret(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)

    result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret="wrong-secret",
    )
    assert result is None


def test_exchange_rejects_unknown_device_id(db_connection: Connection) -> None:
    result = exchange_foundry_device_credential(
        db_connection, foundry_device_id=uuid.uuid4(), raw_device_secret="whatever"
    )
    assert result is None


def test_exchange_rejects_revoked_device(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    revoke_foundry_device(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        revoked_by_user_id=campaign_setup["user_id"],
    )

    result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret=consumed.raw_device_secret,
    )
    assert result is None


def test_exchange_rejects_when_connection_revoked_even_if_device_row_untouched(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    """Proves `exchange_foundry_device_credential`'s own JOIN checks
    `foundry_connections.revoked_at` independently of `foundry_devices.
    revoked_at` — revoking only the connection row directly (bypassing
    `revoke_foundry_connection`'s own device cascade) must still block a
    still-unrevoked device from obtaining a new access token."""
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    db_connection.execute(
        text(
            "UPDATE security.foundry_connections SET revoked_at = now() "
            "WHERE foundry_connection_id = :c"
        ),
        {"c": consumed.foundry_connection_id},
    )

    result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret=consumed.raw_device_secret,
    )
    assert result is None


def test_exchange_rejects_expired_device(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    db_connection.execute(
        text(
            "UPDATE security.foundry_devices SET expires_at = now() - interval '1 minute' "
            "WHERE foundry_device_id = :d"
        ),
        {"d": consumed.foundry_device_id},
    )

    result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret=consumed.raw_device_secret,
    )
    assert result is None


def test_exchange_rejects_when_membership_no_longer_active(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 second' "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": campaign_setup["campaign_id"], "u": campaign_setup["user_id"]},
    )

    result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret=consumed.raw_device_secret,
    )
    assert result is None


# ==========================================================================
# Device/connection revocation and rotation
# ==========================================================================


def test_revoke_foundry_device_by_owner_succeeds(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)

    revoke_foundry_device(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        revoked_by_user_id=campaign_setup["user_id"],
        expected_owner_user_id=campaign_setup["user_id"],
    )

    revoked_at = db_connection.execute(
        text("SELECT revoked_at FROM security.foundry_devices WHERE foundry_device_id = :d"),
        {"d": consumed.foundry_device_id},
    ).scalar()
    assert revoked_at is not None


def test_revoke_foundry_device_rejects_foreign_owner(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    other_user_id = make_user(db_connection)

    with pytest.raises(ForeignFoundryDeviceError):
        revoke_foundry_device(
            db_connection,
            foundry_device_id=consumed.foundry_device_id,
            revoked_by_user_id=other_user_id,
            expected_owner_user_id=other_user_id,
        )


def test_revoke_foundry_device_unscoped_mode_needs_no_owner(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    """The GM path: a caller already authorized via `access.manage`
    (checked one layer up, at the future API layer) revokes a campaign
    device without owning it."""
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    gm_user_id = make_user(db_connection)

    revoke_foundry_device(
        db_connection, foundry_device_id=consumed.foundry_device_id, revoked_by_user_id=gm_user_id
    )

    revoked_at = db_connection.execute(
        text("SELECT revoked_at FROM security.foundry_devices WHERE foundry_device_id = :d"),
        {"d": consumed.foundry_device_id},
    ).scalar()
    assert revoked_at is not None


def test_revoke_foundry_device_is_a_noop_for_an_already_revoked_device(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    revoke_foundry_device(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        revoked_by_user_id=campaign_setup["user_id"],
    )
    # Second call: still a no-op, not an error, even with an ownership check.
    revoke_foundry_device(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        revoked_by_user_id=campaign_setup["user_id"],
        expected_owner_user_id=campaign_setup["user_id"],
    )


def test_rotate_foundry_device_immediate_revokes_old_secret_right_away(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)

    rotated = _rotate_foundry_device_impl(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        requesting_user_id=campaign_setup["user_id"],
    )
    assert rotated.raw_device_secret != consumed.raw_device_secret

    old_secret_result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret=consumed.raw_device_secret,
    )
    assert old_secret_result is None

    new_secret_result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=rotated.new_foundry_device_id,
        raw_device_secret=rotated.raw_device_secret,
    )
    assert new_secret_result is not None

    replaced_by = db_connection.execute(
        text(
            "SELECT replaced_by_foundry_device_id FROM security.foundry_devices "
            "WHERE foundry_device_id = :d"
        ),
        {"d": consumed.foundry_device_id},
    ).scalar()
    assert replaced_by == rotated.new_foundry_device_id


def test_rotate_foundry_device_with_overlap_keeps_old_secret_valid_until_the_window_ends(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)

    _rotate_foundry_device_impl(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        requesting_user_id=campaign_setup["user_id"],
        overlap=timedelta(minutes=10),
    )

    # Still within the overlap window: the old secret still exchanges.
    old_secret_result = exchange_foundry_device_credential(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        raw_device_secret=consumed.raw_device_secret,
    )
    assert old_secret_result is not None

    old_device_revoked_at = db_connection.execute(
        text("SELECT revoked_at FROM security.foundry_devices WHERE foundry_device_id = :d"),
        {"d": consumed.foundry_device_id},
    ).scalar()
    assert old_device_revoked_at > datetime.now(UTC)


def test_rotate_foundry_device_rejects_foreign_owner(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    other_user_id = make_user(db_connection)

    with pytest.raises(ForeignFoundryDeviceError):
        _rotate_foundry_device_impl(
            db_connection,
            foundry_device_id=consumed.foundry_device_id,
            requesting_user_id=other_user_id,
        )


def test_rotate_foundry_device_rejects_an_already_revoked_device(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    revoke_foundry_device(
        db_connection,
        foundry_device_id=consumed.foundry_device_id,
        revoked_by_user_id=campaign_setup["user_id"],
    )

    with pytest.raises(ForeignFoundryDeviceError):
        _rotate_foundry_device_impl(
            db_connection,
            foundry_device_id=consumed.foundry_device_id,
            requesting_user_id=campaign_setup["user_id"],
        )


def test_revoke_foundry_connection_cascades_to_every_device(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    first_issued = _issue_code(db_connection, campaign_setup)
    first = _consume(db_connection, first_issued.raw_code, device_label="device-one")
    second_issued = _issue_code(db_connection, campaign_setup)
    second = _consume(db_connection, second_issued.raw_code, device_label="device-two")
    assert first.foundry_connection_id == second.foundry_connection_id

    revoke_foundry_connection(
        db_connection,
        foundry_connection_id=first.foundry_connection_id,
        revoked_by_user_id=campaign_setup["user_id"],
    )

    for device_id, raw_secret in (
        (first.foundry_device_id, first.raw_device_secret),
        (second.foundry_device_id, second.raw_device_secret),
    ):
        assert (
            exchange_foundry_device_credential(
                db_connection, foundry_device_id=device_id, raw_device_secret=raw_secret
            )
            is None
        )
        is_revoked = db_connection.execute(
            text(
                "SELECT revoked_at IS NOT NULL FROM security.foundry_devices WHERE foundry_device_id = :d"
            ),
            {"d": device_id},
        ).scalar()
        assert is_revoked is True


def test_revoke_foundry_connection_rejects_foreign_owner(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    other_user_id = make_user(db_connection)

    with pytest.raises(ForeignFoundryConnectionError):
        revoke_foundry_connection(
            db_connection,
            foundry_connection_id=consumed.foundry_connection_id,
            revoked_by_user_id=other_user_id,
            expected_owner_user_id=other_user_id,
        )


def test_revoke_foundry_connection_is_a_noop_for_an_already_revoked_connection(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)
    revoke_foundry_connection(
        db_connection,
        foundry_connection_id=consumed.foundry_connection_id,
        revoked_by_user_id=campaign_setup["user_id"],
    )
    revoke_foundry_connection(
        db_connection,
        foundry_connection_id=consumed.foundry_connection_id,
        revoked_by_user_id=campaign_setup["user_id"],
        expected_owner_user_id=campaign_setup["user_id"],
    )


def test_revoke_all_foundry_connections_revokes_every_connection_for_the_user(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    first_issued = _issue_code(db_connection, campaign_setup)
    first = _consume(db_connection, first_issued.raw_code, foundry_user_id="foundry-user-a")

    second_campaign_id = make_campaign(
        db_connection,
        campaign_setup["timeline_id"],
        "Second Campaign",
        lifecycle_status_code="pending",
    )
    make_campaign_membership(db_connection, second_campaign_id, campaign_setup["user_id"])
    second_issued = _issue_code(db_connection, campaign_setup, campaign_id=second_campaign_id)
    second = _consume(db_connection, second_issued.raw_code, foundry_user_id="foundry-user-b")

    revoke_all_foundry_connections(db_connection, user_id=campaign_setup["user_id"])

    for consumed in (first, second):
        assert (
            exchange_foundry_device_credential(
                db_connection,
                foundry_device_id=consumed.foundry_device_id,
                raw_device_secret=consumed.raw_device_secret,
            )
            is None
        )


def test_list_foundry_devices_reflects_connection_level_revocation(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    issued = _issue_code(db_connection, campaign_setup)
    consumed = _consume(db_connection, issued.raw_code)

    [before] = list_foundry_devices(db_connection, user_id=campaign_setup["user_id"])
    assert before.is_revoked is False
    assert before.granted_scopes == tuple(sorted(_SCOPES))

    # Revoke the connection directly, bypassing the device cascade, to prove
    # the listing itself (not just revoke_foundry_connection's own cascade)
    # treats a connection-level revocation as making its devices revoked too.
    db_connection.execute(
        text(
            "UPDATE security.foundry_connections SET revoked_at = now() "
            "WHERE foundry_connection_id = :c"
        ),
        {"c": consumed.foundry_connection_id},
    )

    [after] = list_foundry_devices(db_connection, user_id=campaign_setup["user_id"])
    assert after.is_revoked is True


def test_foundry_scopes_constant_matches_the_migrations_closed_check_set(
    db_connection: Connection, campaign_setup: dict[str, uuid.UUID]
) -> None:
    """Every code `dnd_ai.domain.foundry_pairing.FOUNDRY_SCOPES` allows must
    also be one the database's own `ck_foundry_connections_granted_scopes_
    closed` CHECK constraint accepts — proving the Python-side closed set
    and the SQL-side mirror (kept in sync by hand, per both modules' own
    docstrings) have not drifted apart. Requesting the *entire* set at once
    is sufficient: the CHECK is a subset test (`<@`), so if any single code
    were missing from the SQL array literal, this INSERT would fail."""
    issued = _issue_code(db_connection, campaign_setup, requested_scopes=FOUNDRY_SCOPES)
    assert set(issued.requested_scopes) == FOUNDRY_SCOPES
