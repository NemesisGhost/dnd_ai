"""Tests for the default `security.role_capabilities` matrix migration 086
seeds for the system-template `gm`/`assistant_gm`/`player`/`observer`
roles — the sibling High-severity fix to migration 085's own
`campaign_owner` fix (see `dnd_ai.commands.campaigns`'s module docstring
for the full defect/fix narrative both migrations share).

Covers two layers: the raw `security.role_capabilities` matrix itself
(exactly the documented codes, never `access.manage`), and the
API-observable least-privilege behavior that matrix produces for an
ordinary, non-owner member holding each role — `campaign.view` passing,
`canon.edit`/`access.manage`-gated routes correctly split by role.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_location,
    make_membership_role,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database

# The exact capability matrix migration 086 documents — access.manage
# deliberately absent from every entry here.
_EXPECTED_CAPABILITIES: dict[str, frozenset[str]] = {
    "campaign_owner": frozenset({"access.manage", "campaign.view", "canon.edit"}),
    "gm": frozenset(
        {"campaign.view", "canon.edit", "character.view_full", "character.view_knowledge"}
    ),
    "assistant_gm": frozenset({"campaign.view", "canon.edit", "character.view_full"}),
    "player": frozenset({"campaign.view"}),
    "observer": frozenset({"campaign.view"}),
    "import_reviewer": frozenset(),
    "rules_curator": frozenset(),
}


def test_the_system_role_capability_matrix_matches_the_documented_defaults(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        for role_code, expected in _EXPECTED_CAPABILITIES.items():
            actual = frozenset(
                connection.execute(
                    text("""
                        SELECT cap.code
                        FROM security.roles r
                        JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                        JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
                        WHERE r.code = :code AND r.campaign_id IS NULL
                    """),
                    {"code": role_code},
                ).scalars()
            )
            assert actual == expected, f"{role_code}: expected {expected}, got {actual}"


def test_no_ordinary_role_holds_access_manage(postgres_engine: Engine) -> None:
    """Direct proof of the task's own "do not accidentally grant
    access.manage to ordinary roles" requirement: only `campaign_owner`
    may hold it, checked against the live table rather than the hardcoded
    matrix above, so a future migration accidentally widening one of these
    roles fails this test immediately."""
    with postgres_engine.connect() as connection:
        role_codes = (
            connection.execute(
                text("""
                SELECT DISTINCT r.code
                FROM security.roles r
                JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
                WHERE r.campaign_id IS NULL AND cap.code = 'access.manage'
            """)
            )
            .scalars()
            .all()
        )
    assert list(role_codes) == ["campaign_owner"]


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant — this fixture never sets up an owner, mirroring
        # tests/database/test_api_memberships.py's own Fixture reasoning.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.player_user_id = make_user(connection, "System Role Player")
        self.observer_user_id = make_user(connection, "System Role Observer")
        self.gm_user_id = make_user(connection, "System Role GM")
        self.assistant_gm_user_id = make_user(connection, "System Role Assistant GM")

        # Content for the representative canon.edit command
        # (dnd_ai.commands.movement.enter_location) — content authoring,
        # not a security write.
        self.character_id = make_character(connection, self.world_id, name="Role Test Subject")
        self.location_id = make_location(connection, self.world_id, name="Role Test Location")
        self.world_time_id = make_world_time(connection, self.world_id, 10)

        for user_id, role_code, attr in (
            (self.player_user_id, "player", "player_membership_id"),
            (self.observer_user_id, "observer", "observer_membership_id"),
            (self.gm_user_id, "gm", "gm_membership_id"),
            (self.assistant_gm_user_id, "assistant_gm", "assistant_gm_membership_id"),
        ):
            role_id = connection.execute(
                text(
                    "SELECT role_id FROM security.roles WHERE code = :code AND campaign_id IS NULL"
                ),
                {"code": role_code},
            ).scalar_one()
            membership_id = make_campaign_membership(connection, self.campaign_id, user_id)
            make_membership_role(connection, membership_id, role_id)
            setattr(self, attr, membership_id)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"system-roles-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM campaign.character_location_history WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                "(SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c)"
            ),
            {"c": fixture.campaign_id},
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
            text("DELETE FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.player_user_id,
                    fixture.observer_user_id,
                    fixture.gm_user_id,
                    fixture.assistant_gm_user_id,
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
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _summary_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/summary"


def _invitations_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/invitations"


def _location_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/characters/{f.character_id}/location"


@pytest.mark.parametrize("user_attr", ["player_user_id", "observer_user_id"])
def test_player_and_observer_pass_campaign_view_but_hold_no_other_capability(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, user_attr: str
) -> None:
    user_id = getattr(f, user_attr)
    with client_factory(user_id) as client:
        summary_response = client.get(_summary_url(f))
        assert summary_response.status_code == 200, summary_response.text

        # access.manage-gated: neither role may invite anyone.
        invite_response = client.post(_invitations_url(f), json={})
        assert invite_response.status_code == 403, invite_response.text

        # canon.edit-gated: neither role may move a character — "character-
        # specific powers continuing to come from membership_character_
        # relationships/resource grants" (migration 086's own docstring),
        # never the bare role.
        move_response = client.post(
            _location_url(f),
            json={"world_time_id": str(f.world_time_id), "location_id": str(f.location_id)},
        )
    assert move_response.status_code == 403, move_response.text


def test_gm_and_assistant_gm_pass_canon_edit_but_not_access_manage(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    for user_id in (f.gm_user_id, f.assistant_gm_user_id):
        with client_factory(user_id) as client:
            summary_response = client.get(_summary_url(f))
            assert summary_response.status_code == 200, summary_response.text

            # access.manage-gated: neither gm nor assistant_gm may invite —
            # that capability stays exclusive to campaign_owner.
            invite_response = client.post(_invitations_url(f), json={})
            assert invite_response.status_code == 403, invite_response.text

            # canon.edit-gated: both gm and assistant_gm may move a
            # character — real narrative authority, unlike player/observer
            # above. A repeat call for the same character is a defined
            # no-op (dnd_ai.commands.movement's own docstring) and still
            # returns 200, so calling this once per user in the same loop
            # is safe.
            move_response = client.post(
                _location_url(f),
                json={"world_time_id": str(f.world_time_id), "location_id": str(f.location_id)},
            )
        assert move_response.status_code == 200, move_response.text
