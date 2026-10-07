"""System-scope roles (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

Covers the migration backfill's invariants, the closed capability mapping as the
session bootstrap reports it, the administrator commands and routes (assign,
revoke, create-with-roles), the in-app Administrator grant switch, the last-
administrator guard (including a real two-transaction race), and the guarantee
that no system role confers campaign or world access.
"""

import concurrent.futures
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dnd_ai.commands.local_auth import LastActivePlatformAdministratorError
from dnd_ai.commands.system_roles import (
    AdminGrantDisabledError,
    assign_system_role,
    revoke_system_role,
)
from dnd_ai.config import settings
from dnd_ai.domain.system_authority import capabilities_for_system_roles
from dnd_ai.queries.system_authority import resolve_system_capabilities, resolve_system_roles
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids, make_authored_campaign, make_authored_world
from tests.factories import (
    make_platform_administrator,
    make_system_role_assignment,
    make_user,
    status_id,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def _roles(connection: Connection, user_id: uuid.UUID) -> set[str]:
    return set(resolve_system_roles(connection, user_id=user_id))


def _audit_count(connection: Connection, command_name: str) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM audit.change_log WHERE command_name = :c"),
            {"c": command_name},
        ).scalar_one()
    )


# --- the closed mapping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((), set()),
        (("player",), set()),
        (("observer",), set()),
        (("admin",), {"accounts.manage", "system_roles.manage"}),
        (("gm",), {"world.create", "campaign.host", "world.administer"}),
        (
            ("admin", "gm"),
            {
                "accounts.manage",
                "system_roles.manage",
                "world.create",
                "campaign.host",
                "world.administer",
            },
        ),
        (("gm", "player", "observer"), {"world.create", "campaign.host", "world.administer"}),
        (("mystery",), set()),
    ],
)
def test_capabilities_are_the_union_of_explicit_role_sets(
    roles: tuple[str, ...], expected: set[str]
) -> None:
    assert capabilities_for_system_roles(roles) == expected


def test_admin_grant_capability_follows_the_deployment_setting() -> None:
    assert "system_roles.grant_admin" not in capabilities_for_system_roles(("admin",))
    assert "system_roles.grant_admin" in capabilities_for_system_roles(
        ("admin",), allow_in_app_admin_grant=True
    )


# --- schema ---------------------------------------------------------------------------


def test_the_four_system_roles_are_seeded_and_protected(db_connection: Connection) -> None:
    codes = {
        row.code for row in db_connection.execute(text("SELECT code FROM security.system_roles"))
    }
    assert codes == {"admin", "gm", "player", "observer"}
    with pytest.raises(DBAPIError):
        db_connection.execute(
            text("UPDATE security.system_roles SET code = 'renamed' WHERE code = 'gm'")
        )


def test_only_one_open_assignment_per_user_and_role(db_connection: Connection) -> None:
    user_id = make_user(db_connection, "Duplicate Role")
    make_system_role_assignment(db_connection, user_id, "gm")
    with pytest.raises(IntegrityError):
        make_system_role_assignment(db_connection, user_id, "gm")


def test_a_revoked_assignment_can_be_granted_again_and_history_is_kept(
    db_connection: Connection,
) -> None:
    user_id = make_user(db_connection, "Regrant")
    make_system_role_assignment(db_connection, user_id, "gm", revoked=True)
    make_system_role_assignment(db_connection, user_id, "gm")
    assert _roles(db_connection, user_id) == {"gm"}
    total = db_connection.execute(
        text("SELECT count(*) FROM security.user_system_roles WHERE user_id = :u"),
        {"u": user_id},
    ).scalar_one()
    assert total == 2


def test_assignment_identity_is_immutable(db_connection: Connection) -> None:
    user_id = make_user(db_connection, "Immutable")
    other = make_user(db_connection, "Other")
    assignment_id = make_system_role_assignment(db_connection, user_id, "gm")
    with pytest.raises(DBAPIError):
        db_connection.execute(
            text(
                "UPDATE security.user_system_roles SET user_id = :o WHERE user_system_role_id = :a"
            ),
            {"o": other, "a": assignment_id},
        )


def test_an_inactive_account_resolves_no_system_roles(db_connection: Connection) -> None:
    user_id = make_user(db_connection, "Dormant")
    make_system_role_assignment(db_connection, user_id, "gm")
    make_system_role_assignment(db_connection, user_id, "admin")
    assert resolve_system_capabilities(db_connection, user_id=user_id)
    db_connection.execute(
        text("UPDATE security.users SET lifecycle_status_id = :s WHERE user_id = :u"),
        {"s": status_id(db_connection, "lifecycle_statuses", "inactive"), "u": user_id},
    )
    assert _roles(db_connection, user_id) == set()
    assert resolve_system_capabilities(db_connection, user_id=user_id) == frozenset()


# --- commands -------------------------------------------------------------------------


def test_assign_and_revoke_are_idempotent_and_change_nothing_else(
    db_connection: Connection,
) -> None:
    admin_id = make_platform_administrator(db_connection)
    target = make_user(db_connection, "Future GM")
    memberships_before = db_connection.execute(
        text("SELECT count(*) FROM security.campaign_memberships WHERE user_id = :u"),
        {"u": target},
    ).scalar_one()

    first = assign_system_role(
        db_connection,
        admin_user_id=admin_id,
        target_user_id=target,
        role_code="gm",
        allow_in_app_admin_grant=False,
    )
    again = assign_system_role(
        db_connection,
        admin_user_id=admin_id,
        target_user_id=target,
        role_code="gm",
        allow_in_app_admin_grant=False,
    )
    assert first.changed and not again.changed
    assert _roles(db_connection, target) == {"gm"}

    revoked = revoke_system_role(
        db_connection, admin_user_id=admin_id, target_user_id=target, role_code="gm"
    )
    repeat = revoke_system_role(
        db_connection, admin_user_id=admin_id, target_user_id=target, role_code="gm"
    )
    assert revoked.changed and not repeat.changed
    assert _roles(db_connection, target) == set()
    # No campaign membership was created or removed by any of it.
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM security.campaign_memberships WHERE user_id = :u"),
            {"u": target},
        ).scalar_one()
        == memberships_before
    )


def test_a_non_administrator_cannot_assign_or_revoke(db_connection: Connection) -> None:
    from dnd_ai.commands.local_auth import NotPlatformAdministratorError

    gm = make_user(db_connection, "Just A GM")
    make_system_role_assignment(db_connection, gm, "gm")
    target = make_user(db_connection, "Target")
    with pytest.raises(NotPlatformAdministratorError):
        assign_system_role(
            db_connection,
            admin_user_id=gm,
            target_user_id=target,
            role_code="gm",
            allow_in_app_admin_grant=False,
        )
    with pytest.raises(NotPlatformAdministratorError):
        revoke_system_role(db_connection, admin_user_id=gm, target_user_id=gm, role_code="gm")
    assert _roles(db_connection, gm) == {"gm"}


def test_granting_admin_needs_the_deployment_setting(db_connection: Connection) -> None:
    admin_id = make_platform_administrator(db_connection)
    target = make_user(db_connection, "Second Admin")
    with pytest.raises(AdminGrantDisabledError):
        assign_system_role(
            db_connection,
            admin_user_id=admin_id,
            target_user_id=target,
            role_code="admin",
            allow_in_app_admin_grant=False,
        )
    assert _roles(db_connection, target) == set()
    assign_system_role(
        db_connection,
        admin_user_id=admin_id,
        target_user_id=target,
        role_code="admin",
        allow_in_app_admin_grant=True,
    )
    assert _roles(db_connection, target) == {"admin"}


def test_the_sole_active_administrator_cannot_be_revoked(db_connection: Connection) -> None:
    admin_id = make_platform_administrator(db_connection)
    db_connection.execute(
        text("""
            UPDATE security.users SET lifecycle_status_id = :s
            WHERE user_id <> :keep AND user_id IN (
                SELECT usr.user_id FROM security.user_system_roles usr
                JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
                WHERE sr.code = 'admin' AND usr.revoked_at IS NULL
            )
        """),
        {"s": status_id(db_connection, "lifecycle_statuses", "inactive"), "keep": admin_id},
    )
    with pytest.raises(LastActivePlatformAdministratorError):
        revoke_system_role(
            db_connection, admin_user_id=admin_id, target_user_id=admin_id, role_code="admin"
        )
    assert "admin" in _roles(db_connection, admin_id)

    # Another active administrator makes the same revocation legitimate.
    second = make_platform_administrator(db_connection, "Second")
    revoke_system_role(
        db_connection, admin_user_id=second, target_user_id=admin_id, role_code="admin"
    )
    assert "admin" not in _roles(db_connection, admin_id)


def test_concurrent_revocation_cannot_leave_zero_active_administrators(
    postgres_engine: Engine,
) -> None:
    """Two administrators each revoke the other's `admin` role at the same moment;
    the shared advisory lock serializes them so exactly one wins."""
    with postgres_engine.begin() as setup:
        previously_active = [
            row[0]
            for row in setup.execute(
                text("""
                    SELECT u.user_id
                    FROM security.users u
                    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                    WHERE ls.code = 'active' AND EXISTS (
                        SELECT 1 FROM security.user_system_roles usr
                        JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
                        WHERE usr.user_id = u.user_id AND usr.revoked_at IS NULL
                          AND sr.code = 'admin'
                    )
                """)
            )
        ]
        if previously_active:
            setup.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = :s WHERE user_id = ANY(:ids)"
                ),
                {"s": status_id(setup, "lifecycle_statuses", "inactive"), "ids": previously_active},
            )
        admin_a = make_platform_administrator(setup, "Revoke Race A")
        admin_b = make_platform_administrator(setup, "Revoke Race B")

    def _revoke(actor: uuid.UUID, target: uuid.UUID) -> str:
        try:
            with postgres_engine.begin() as connection:
                revoke_system_role(
                    connection, admin_user_id=actor, target_user_id=target, role_code="admin"
                )
        except LastActivePlatformAdministratorError:
            return "rejected"
        except Exception:  # the loser may also be told it is no longer an administrator
            return "rejected"
        return "accepted"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [
                f.result()
                for f in [
                    pool.submit(_revoke, admin_a, admin_b),
                    pool.submit(_revoke, admin_b, admin_a),
                ]
            ]
        assert sorted(outcomes) == ["accepted", "rejected"]
        with postgres_engine.connect() as verify:
            remaining = verify.execute(
                text("""
                    SELECT count(*) FROM security.user_system_roles usr
                    JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id
                    WHERE sr.code = 'admin' AND usr.revoked_at IS NULL
                      AND usr.user_id IN (:a, :b)
                """),
                {"a": admin_a, "b": admin_b},
            ).scalar_one()
        assert remaining == 1
    finally:
        with postgres_engine.begin() as cleanup:
            if previously_active:
                cleanup.execute(
                    text(
                        "UPDATE security.users SET lifecycle_status_id = :s "
                        "WHERE user_id = ANY(:ids)"
                    ),
                    {
                        "s": status_id(cleanup, "lifecycle_statuses", "active"),
                        "ids": previously_active,
                    },
                )


# --- routes ---------------------------------------------------------------------------


def test_an_admin_creates_and_activates_a_gm_without_any_campaign(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = harness.new_actor("Platform Admin", system_roles=("admin",))
    login_name = f"new-gm-{uuid.uuid4().hex[:8]}"
    created = admin.post(
        "/admin/accounts",
        {"login_name": login_name, "display_name": "Brand New GM", "system_role_codes": ["gm"]},
    )
    assert created.status_code == 201, created.text
    new_user_id = uuid.UUID(created.json()["user_id"])
    assert _roles(db_connection, new_user_id) == {"gm"}

    activated = harness.anonymous_client().post(
        "/auth/activate",
        json={
            "token": created.json()["raw_activation_token"],
            "password": "correct horse battery 9",
        },
        headers={"Origin": "http://localhost:5173"},
    )
    assert activated.status_code == 200, activated.text
    # Activation alone created no membership of any kind.
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM security.campaign_memberships WHERE user_id = :u"),
            {"u": new_user_id},
        ).scalar_one()
        == 0
    )


def test_a_new_gm_lands_with_no_campaigns_and_the_gm_capabilities(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = harness.new_actor("Fresh GM", system_roles=("gm",))
    session = gm.get("/auth/session").json()
    assert session["campaigns"] == []
    assert session["startup_campaign_id"] is None
    assert set(session["system_roles"]) == {"player", "gm"}
    assert set(session["global_capabilities"]) == {
        "world.create",
        "campaign.host",
        "world.administer",
    }
    assert "is_platform_administrator" not in session


def test_an_admin_alone_can_neither_create_a_world_nor_read_a_campaign(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    owner = harness.new_actor("Host", world_creator=True)
    world = make_authored_world(db_connection, owner_user_id=owner.user_id)
    campaign_id = make_authored_campaign(db_connection, world)
    admin = harness.new_actor("Bare Admin", system_roles=("admin",))

    session = admin.get("/auth/session").json()
    assert "accounts.manage" in session["global_capabilities"]
    assert set(session["global_capabilities"]) == {"accounts.manage", "system_roles.manage"}
    assert admin.get(f"/campaigns/{campaign_id}/clock").status_code == 404
    assert admin.get(f"/worlds/{world.world_id}").status_code == 404


def test_creating_an_account_defaults_to_player_and_admin_is_refused_by_default(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = harness.new_actor("Creating Admin", system_roles=("admin",))
    plain = admin.post(
        "/admin/accounts",
        {"login_name": f"plain-{uuid.uuid4().hex[:8]}", "display_name": "Plain"},
    )
    assert plain.status_code == 201, plain.text
    assert _roles(db_connection, uuid.UUID(plain.json()["user_id"])) == {"player"}

    users_before = db_connection.execute(text("SELECT count(*) FROM security.users")).scalar_one()
    refused = admin.post(
        "/admin/accounts",
        {
            "login_name": f"adm-{uuid.uuid4().hex[:8]}",
            "display_name": "Wannabe Admin",
            "system_role_codes": ["admin"],
        },
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "admin_grant_disabled"
    assert (
        db_connection.execute(text("SELECT count(*) FROM security.users")).scalar_one()
        == users_before
    )

    empty = admin.post(
        "/admin/accounts",
        {
            "login_name": f"none-{uuid.uuid4().hex[:8]}",
            "display_name": "None",
            "system_role_codes": [],
        },
    )
    assert empty.status_code == 422


def test_assign_route_audits_once_and_replay_writes_nothing(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = harness.new_actor("Role Admin", system_roles=("admin",))
    target = harness.new_actor("Role Target")
    path = f"/admin/accounts/{target.user_id}/system-roles"
    before = _audit_count(db_connection, "system_roles.assign")

    first = admin.post(path, {"system_role_code": "gm"})
    second = admin.post(path, {"system_role_code": "gm"})
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["changed"] is True and second.json()["changed"] is False
    assert _audit_count(db_connection, "system_roles.assign") == before + 1

    row = db_connection.execute(
        text("""
            SELECT changed_fields FROM audit.change_log
            WHERE command_name = 'system_roles.assign' AND actor_user_id = :a
        """),
        {"a": admin.user_id},
    ).one()
    assert row.changed_fields["system_role_code"] == "gm"
    assert row.changed_fields["target_user_id"] == str(target.user_id)


def test_non_administrators_get_a_non_disclosing_404_on_the_role_routes(
    harness: AuthoringHarness,
) -> None:
    gm = harness.new_actor("Only GM", system_roles=("gm",))
    target = harness.new_actor("Target")
    base = f"/admin/accounts/{target.user_id}/system-roles"
    assert gm.post(base, {"system_role_code": "gm"}).status_code == 404
    assert gm.post(f"{base}/gm/revoke", {}).status_code == 404
    assert gm.get("/admin/accounts").status_code == 404


def test_the_admin_assign_route_needs_the_setting_and_then_audits(
    harness: AuthoringHarness, db_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = harness.new_actor("Granting Admin", system_roles=("admin",))
    target = harness.new_actor("Promoted")
    path = f"/admin/accounts/{target.user_id}/system-roles"

    refused = admin.post(path, {"system_role_code": "admin"})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "admin_grant_disabled"
    assert "admin" not in _roles(db_connection, target.user_id)

    monkeypatch.setattr(settings, "allow_in_app_admin_grant", True)
    granted = admin.post(path, {"system_role_code": "admin"})
    assert granted.status_code == 201, granted.text
    assert "admin" in _roles(db_connection, target.user_id)
    assert _audit_count(db_connection, "system_roles.assign") >= 1


def test_revoking_gm_takes_effect_on_the_next_request_and_keeps_campaign_roles(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = harness.new_actor("Revoking Admin", system_roles=("admin",))
    gm = harness.new_actor("Revoked GM", world_creator=True)
    world = make_authored_world(db_connection, owner_user_id=gm.user_id)
    campaign_id = make_authored_campaign(db_connection, world)
    # `gm` also holds a campaign role in a campaign created for the test.
    assert gm.get("/auth/session").json()["global_capabilities"]

    revoked = admin.post(f"/admin/accounts/{gm.user_id}/system-roles/gm/revoke", {})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["changed"] is True

    session = gm.get("/auth/session").json()
    assert session["global_capabilities"] == []
    ruleset_id, _ = dnd5e_ids(db_connection)
    world_body = {
        "name": "Nope",
        "description": None,
        "ruleset_ids": [str(ruleset_id)],
        "default_ruleset_id": str(ruleset_id),
        "primary_timeline": {"name": "Main", "description": None},
    }
    assert gm.post("/worlds", world_body).status_code == 403
    # Campaign scope is untouched by a system-role change.
    memberships_after = db_connection.execute(
        text("SELECT count(*) FROM security.campaign_memberships WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar_one()
    assert memberships_after >= 1


def test_an_account_list_reports_roles_and_filters_by_role(
    harness: AuthoringHarness,
) -> None:
    admin = harness.new_actor("Listing Admin", system_roles=("admin",))
    gm = harness.new_actor("Listed Dungeon Master", system_roles=("gm",))
    plain = harness.new_actor("Listed Plain Person")

    everyone = admin.get("/admin/accounts", q="Listed").json()["items"]
    by_name = {item["display_name"]: item for item in everyone}
    assert set(by_name["Listed Dungeon Master"]["system_roles"]) == {"player", "gm"}
    assert by_name["Listed Plain Person"]["system_roles"] == ["player"]

    only_gms = admin.get("/admin/accounts", q="Listed", system_role="gm").json()["items"]
    assert [item["user_id"] for item in only_gms] == [str(gm.user_id)]
    assert str(plain.user_id) not in [item["user_id"] for item in only_gms]
