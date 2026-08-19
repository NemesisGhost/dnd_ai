"""Tests for `scripts/foundry_provision.py` — the GM-facing,
OIDC-authenticated provisioning CLI for `foundry-module/` (Phase 11
workstream 7). Imports the script's functions directly (never
subprocess) and drives them against a real `fastapi.testclient.
TestClient` bound to the real application + a real PostgreSQL database
(the same `TestClient`+`get_authenticated_user_id` override every other
`tests/database/*` file uses, since the OIDC verification chain itself
is already fully covered by `tests/database/test_api_auth.py` — these
tests exercise the script's own request construction and error
surfacing, not token verification), per `ProvisioningContext.client`'s
own docstring on why `TestClient` (itself an `httpx.Client` subclass)
can stand in for a live `httpx.Client(base_url=...)` unchanged.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from foundry_provision import (
    ProvisioningContext,
    ProvisioningError,
    issue_system_key,
    link_foundry_identity,
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
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )

        self.gm_user_id = make_user(connection, "Provision Script GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.admin_user_id = make_user(connection, "Provision Script Admin")
        admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        admin_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, admin_role_id, access_manage_id)
        make_membership_role(connection, admin_membership_id, admin_role_id)

        self.capless_user_id = make_user(connection, "Provision Script Capless")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.link_target_user_id = make_user(connection, "Provision Script Link Target")


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
                    fixture.admin_user_id,
                    fixture.capless_user_id,
                    fixture.link_target_user_id,
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


def test_issue_and_link_end_to_end(
    context_factory: Callable[[uuid.UUID, uuid.UUID], ProvisioningContext],
    f: Fixture,
    postgres_engine: Engine,
) -> None:
    gm_ctx = context_factory(f.gm_user_id, f.campaign_id)
    external_system_id = register_external_system(
        gm_ctx, system_type="foundry", display_name="Test Foundry World"
    )

    admin_ctx = context_factory(f.admin_user_id, f.campaign_id)
    raw_key = issue_system_key(admin_ctx, external_system_id=external_system_id)
    assert len(raw_key) > 20

    external_identity_id = link_foundry_identity(
        admin_ctx,
        external_system_id=external_system_id,
        foundry_user_id="foundry-user-1",
        user_id=f.link_target_user_id,
    )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT user_id FROM security.external_identities WHERE external_identity_id = :i"
            ),
            {"i": external_identity_id},
        ).one()
    assert row.user_id == f.link_target_user_id


def test_issue_system_key_surfaces_insufficient_capability_clearly(
    context_factory: Callable[[uuid.UUID, uuid.UUID], ProvisioningContext], f: Fixture
) -> None:
    gm_ctx = context_factory(f.gm_user_id, f.campaign_id)
    external_system_id = register_external_system(
        gm_ctx, system_type="foundry", display_name="Test Foundry World"
    )

    # f.gm_user_id holds canon.edit (sufficient for register) but not
    # access.manage — issue-key requires the narrower capability.
    with pytest.raises(ProvisioningError) as exc_info:
        issue_system_key(gm_ctx, external_system_id=external_system_id)
    assert "403" in str(exc_info.value)


def test_link_foundry_identity_surfaces_404_for_a_nonexistent_external_system(
    context_factory: Callable[[uuid.UUID, uuid.UUID], ProvisioningContext], f: Fixture
) -> None:
    admin_ctx = context_factory(f.admin_user_id, f.campaign_id)

    with pytest.raises(ProvisioningError) as exc_info:
        link_foundry_identity(
            admin_ctx,
            external_system_id=uuid.uuid4(),
            foundry_user_id="foundry-user-1",
            user_id=f.link_target_user_id,
        )
    assert "404" in str(exc_info.value)
