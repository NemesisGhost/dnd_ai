"""dnd_ai.domain.access.AuthenticatedPrincipal — the __post_init__ field-
combination validation for each auth_method, and assert_foundry_system_
matches (docs/PLAN.md §23.5, Phase 11R workstream C). Pure dataclass
construction and comparison — no database needed.
"""

import uuid
from collections.abc import Callable

import pytest

from dnd_ai.domain.access import (
    FOUNDRY_ACCESS_AUTH_METHOD,
    FOUNDRY_SYSTEM_AUTH_METHOD,
    LOCAL_SESSION_AUTH_METHOD,
    OIDC_AUTH_METHOD,
    AuthenticatedPrincipal,
    ForeignExternalSystemError,
    assert_foundry_system_matches,
)

pytestmark = pytest.mark.unit

_USER = uuid.uuid4()
_SYSTEM = uuid.uuid4()
_WORLD = uuid.uuid4()
_CAMPAIGN = uuid.uuid4()
_CONNECTION = uuid.uuid4()
_DEVICE = uuid.uuid4()
_SESSION = uuid.uuid4()


def test_oidc_principal_accepts_only_user_id_and_method() -> None:
    principal = AuthenticatedPrincipal(user_id=_USER, auth_method=OIDC_AUTH_METHOD)
    assert principal.foundry_external_system_id is None
    assert principal.campaign_id is None


def test_oidc_principal_rejects_a_stray_foundry_world_pair() -> None:
    with pytest.raises(ValueError, match="foundry_external_system_id"):
        AuthenticatedPrincipal(
            user_id=_USER,
            auth_method=OIDC_AUTH_METHOD,
            foundry_external_system_id=_SYSTEM,
            foundry_world_id=_WORLD,
        )


def test_oidc_principal_rejects_a_stray_claimed_actor_id() -> None:
    with pytest.raises(ValueError, match="foundry_claimed_actor_id"):
        AuthenticatedPrincipal(
            user_id=_USER, auth_method=OIDC_AUTH_METHOD, foundry_claimed_actor_id="someone"
        )


def test_foundry_system_principal_requires_system_and_world() -> None:
    with pytest.raises(ValueError, match="foundry_external_system_id"):
        AuthenticatedPrincipal(user_id=_USER, auth_method=FOUNDRY_SYSTEM_AUTH_METHOD)


def test_foundry_system_principal_accepts_system_world_and_optional_actor() -> None:
    principal = AuthenticatedPrincipal(
        user_id=_USER,
        auth_method=FOUNDRY_SYSTEM_AUTH_METHOD,
        foundry_external_system_id=_SYSTEM,
        foundry_world_id=_WORLD,
        foundry_claimed_actor_id="claimed",
    )
    assert principal.foundry_claimed_actor_id == "claimed"
    assert principal.campaign_id is None
    assert principal.foundry_connection_id is None


def test_foundry_system_principal_rejects_campaign_id() -> None:
    with pytest.raises(ValueError, match="campaign_id"):
        AuthenticatedPrincipal(
            user_id=_USER,
            auth_method=FOUNDRY_SYSTEM_AUTH_METHOD,
            foundry_external_system_id=_SYSTEM,
            foundry_world_id=_WORLD,
            campaign_id=_CAMPAIGN,
        )


def test_local_session_principal_requires_session_id() -> None:
    with pytest.raises(ValueError, match="local_session_id"):
        AuthenticatedPrincipal(user_id=_USER, auth_method=LOCAL_SESSION_AUTH_METHOD)


def test_local_session_principal_accepts_session_id() -> None:
    principal = AuthenticatedPrincipal(
        user_id=_USER, auth_method=LOCAL_SESSION_AUTH_METHOD, local_session_id=_SESSION
    )
    assert principal.local_session_id == _SESSION


def test_foundry_access_principal_requires_every_field_together() -> None:
    with pytest.raises(ValueError, match="foundry_external_system_id"):
        AuthenticatedPrincipal(user_id=_USER, auth_method=FOUNDRY_ACCESS_AUTH_METHOD)


def test_foundry_access_principal_requires_connection_and_device_ids() -> None:
    with pytest.raises(ValueError, match="foundry_connection_id"):
        AuthenticatedPrincipal(
            user_id=_USER,
            auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
            foundry_external_system_id=_SYSTEM,
            foundry_world_id=_WORLD,
            campaign_id=_CAMPAIGN,
        )


def test_foundry_access_principal_requires_campaign_id() -> None:
    with pytest.raises(ValueError, match="campaign_id"):
        AuthenticatedPrincipal(
            user_id=_USER,
            auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
            foundry_external_system_id=_SYSTEM,
            foundry_world_id=_WORLD,
            foundry_connection_id=_CONNECTION,
            foundry_device_id=_DEVICE,
        )


def test_foundry_access_principal_rejects_a_claimed_actor_id() -> None:
    # Unlike FOUNDRY_SYSTEM_AUTH_METHOD, a paired connection already names
    # its one Foundry user — there is no "claimed actor" concept for it.
    with pytest.raises(ValueError, match="foundry_claimed_actor_id"):
        AuthenticatedPrincipal(
            user_id=_USER,
            auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
            foundry_external_system_id=_SYSTEM,
            foundry_world_id=_WORLD,
            campaign_id=_CAMPAIGN,
            foundry_connection_id=_CONNECTION,
            foundry_device_id=_DEVICE,
            foundry_claimed_actor_id="not-allowed",
        )


def test_foundry_access_principal_accepts_the_full_field_set() -> None:
    principal = AuthenticatedPrincipal(
        user_id=_USER,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=_SYSTEM,
        foundry_world_id=_WORLD,
        campaign_id=_CAMPAIGN,
        foundry_connection_id=_CONNECTION,
        foundry_device_id=_DEVICE,
    )
    assert principal.campaign_id == _CAMPAIGN
    assert principal.foundry_connection_id == _CONNECTION
    assert principal.foundry_device_id == _DEVICE


def _foundry_system_principal(system_id: uuid.UUID) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=_USER,
        auth_method=FOUNDRY_SYSTEM_AUTH_METHOD,
        foundry_external_system_id=system_id,
        foundry_world_id=_WORLD,
    )


def _foundry_access_principal(system_id: uuid.UUID) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=_USER,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=system_id,
        foundry_world_id=_WORLD,
        campaign_id=_CAMPAIGN,
        foundry_connection_id=_CONNECTION,
        foundry_device_id=_DEVICE,
    )


@pytest.mark.parametrize("make_principal", [_foundry_system_principal, _foundry_access_principal])
def test_assert_foundry_system_matches_accepts_the_authenticated_system(
    make_principal: Callable[[uuid.UUID], AuthenticatedPrincipal],
) -> None:
    assert_foundry_system_matches(make_principal(_SYSTEM), _SYSTEM)


@pytest.mark.parametrize("make_principal", [_foundry_system_principal, _foundry_access_principal])
def test_assert_foundry_system_matches_rejects_a_foreign_system(
    make_principal: Callable[[uuid.UUID], AuthenticatedPrincipal],
) -> None:
    other_system = uuid.uuid4()
    with pytest.raises(ForeignExternalSystemError):
        assert_foundry_system_matches(make_principal(_SYSTEM), other_system)


def test_assert_foundry_system_matches_is_a_noop_for_oidc() -> None:
    principal = AuthenticatedPrincipal(user_id=_USER, auth_method=OIDC_AUTH_METHOD)
    assert_foundry_system_matches(principal, uuid.uuid4())


def test_assert_foundry_system_matches_is_a_noop_for_local_session() -> None:
    principal = AuthenticatedPrincipal(
        user_id=_USER, auth_method=LOCAL_SESSION_AUTH_METHOD, local_session_id=_SESSION
    )
    assert_foundry_system_matches(principal, uuid.uuid4())
