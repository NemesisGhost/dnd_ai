"""Tests for `scripts/foundry_provision.py` — the provisioning CLI for
`foundry-module/` (Phase 11 workstream 7; converted to per-device pairing
by Phase 11R workstream I). Imports the script's functions directly (never
subprocess) and drives them against a real `fastapi.testclient.
TestClient` bound to the real application + a real PostgreSQL database
(the same `TestClient`+`get_authenticated_user_id` override every other
`tests/database/*` file uses, since the OIDC/local-session verification
chains themselves are already fully covered by `tests/database/test_api_
auth.py` — these tests exercise the script's own request construction and
error surfacing, not token verification), per `ProvisioningContext.client`'s
own docstring on why `TestClient` (itself an `httpx.Client` subclass)
can stand in for a live `httpx.Client(base_url=...)` unchanged.

The superseded `FoundrySystem`-issuing subcommands (`issue-key`/
`link-identity`/`provision`) and their backend commands (`dnd_ai.commands.
integration.issue_foundry_system_key`/`.link_foundry_identity`) were removed
from this script by Phase 11R workstream I — their own backend coverage
lives in `tests/database/test_api_integration.py` and `tests/database/
test_api_auth.py`, unaffected by this script's own change; this file no
longer needs to duplicate it.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from foundry_provision import (
    ProvisioningContext,
    ProvisioningError,
    create_pairing_code,
    register_external_system,
)
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        campaign_view_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        self.gm_user_id = make_user(connection, "Provision Script GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.capless_user_id = make_user(connection, "Provision Script Capless")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.pairer_user_id = make_user(connection, "Provision Script Pairer")
        pairer_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.pairer_user_id
        )
        pairer_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"pairer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, pairer_role_id, campaign_view_id)
        make_membership_role(connection, pairer_membership_id, pairer_role_id)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"provision-script-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.role_capabilities WHERE role_id IN "
                "(SELECT role_id FROM security.roles WHERE campaign_id = :c)"
            ),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.roles WHERE campaign_id = :c"), {"c": fixture.campaign_id}
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.capless_user_id,
                    fixture.pairer_user_id,
                ]
            },
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


@pytest.fixture
def context_factory(
    postgres_engine: Engine,
) -> Callable[[uuid.UUID, uuid.UUID], ProvisioningContext]:
    """Builds a `ProvisioningContext` whose `client` is a real `TestClient`
    for the actual application (bound to `postgres_engine`), with
    `get_authenticated_user_id` overridden to resolve directly to
    `user_id` — the token string itself is therefore irrelevant to these
    tests (it is never inspected once the dependency is overridden), so
    a fixed placeholder is used throughout."""

    def _make(user_id: uuid.UUID, campaign_id: uuid.UUID) -> ProvisioningContext:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        client = TestClient(app, raise_server_exceptions=False)
        return ProvisioningContext(
            client=client, campaign_id=campaign_id, token="placeholder-token"
        )

    return _make


def test_register_external_system_succeeds_for_a_canon_edit_holder(
    context_factory: Callable[[uuid.UUID, uuid.UUID], ProvisioningContext],
    f: Fixture,
    postgres_engine: Engine,
) -> None:
    ctx = context_factory(f.gm_user_id, f.campaign_id)

    external_system_id = register_external_system(
        ctx, system_type="foundry", display_name="Test Foundry World"
    )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT world_id, display_name FROM integration.external_systems "
                "WHERE external_system_id = :s"
            ),
            {"s": external_system_id},
        ).one()
    assert row.world_id == f.world_id
    assert row.display_name == "Test Foundry World"


def test_register_external_system_surfaces_insufficient_capability_clearly(
    context_factory: Callable[[uuid.UUID, uuid.UUID], ProvisioningContext], f: Fixture
) -> None:
    ctx = context_factory(f.capless_user_id, f.campaign_id)

    with pytest.raises(ProvisioningError) as exc_info:
        register_external_system(ctx, system_type="foundry", display_name="Test Foundry World")

    message = str(exc_info.value)
    assert "403" in message
    assert "canon.edit" in message or "access.manage" in message


def test_create_pairing_code_succeeds_for_a_campaign_view_holder(
    context_factory: Callable[[uuid.UUID, uuid.UUID], ProvisioningContext],
    f: Fixture,
    postgres_engine: Engine,
) -> None:
    gm_ctx = context_factory(f.gm_user_id, f.campaign_id)
    external_system_id = register_external_system(
        gm_ctx, system_type="foundry", display_name="Test Foundry World"
    )

    pairer_ctx = context_factory(f.pairer_user_id, f.campaign_id)
    raw_code, granted_scopes, expires_at = create_pairing_code(
        pairer_ctx, external_system_id=external_system_id, requested_scopes=["combat_sync"]
    )

    assert len(raw_code) > 20
    assert granted_scopes == ["combat_sync"]
    assert expires_at

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT user_id, external_system_id FROM security.foundry_pairing_codes "
                "WHERE campaign_id = :c"
            ),
            {"c": f.campaign_id},
        ).one()
    assert row.user_id == f.pairer_user_id
    assert row.external_system_id == external_system_id


def test_create_pairing_code_surfaces_insufficient_capability_clearly(
    context_factory: Callable[[uuid.UUID, uuid.UUID], ProvisioningContext],
    f: Fixture,
) -> None:
    gm_ctx = context_factory(f.gm_user_id, f.campaign_id)
    external_system_id = register_external_system(
        gm_ctx, system_type="foundry", display_name="Test Foundry World"
    )

    capless_ctx = context_factory(f.capless_user_id, f.campaign_id)
    with pytest.raises(ProvisioningError) as exc_info:
        create_pairing_code(
            capless_ctx, external_system_id=external_system_id, requested_scopes=["combat_sync"]
        )
    assert "403" in str(exc_info.value)
