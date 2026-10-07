"""World roles, use grants, sharing and ownership transfer
(docs/adr/0020-scoped-system-world-and-campaign-roles.md, checkpoint SR-4).

Everything goes through the production routes on the harness's one rolled-back
connection: a GM who owns a world (and so holds system GM), plus other accounts
given world roles, a world-use grant, or nothing.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.world_authority import resolve_world_authority
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import make_system_role_assignment

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _share(s: ContentSetup, target: Actor, role: str, *, by: Actor | None = None):  # type: ignore[no-untyped-def]
    actor = by or s.gm
    return actor.post(
        f"/worlds/{s.world_id}/roles",
        {"login_name": target.login_name, "role_code": role},
        key=actor.fresh_key(),
    )


def _caps(connection: Connection, world_id: uuid.UUID, user_id: uuid.UUID) -> set[str]:
    authority = resolve_world_authority(connection, user_id=user_id, world_id=world_id)
    return set() if authority is None else set(authority.capabilities)


def _audit_count(connection: Connection, command: str) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM audit.change_log WHERE command_name = :c"), {"c": command}
        ).scalar_one()
    )


def _new_gm(harness: AuthoringHarness, name: str) -> Actor:
    return harness.new_actor(name, system_roles=("gm",))


# --- assignment ------------------------------------------------------------------


def test_the_owner_assigns_roles_and_a_replay_is_a_no_op(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    editor = _new_gm(harness, "Editor")
    before = _audit_count(db_connection, "assign_world_role")
    first = _share(s, editor, "world_editor")
    again = _share(s, editor, "world_editor")
    assert first.status_code == 201, first.text
    assert again.status_code == 200, again.text
    assert first.json()["changed"] is True and again.json()["changed"] is False
    assert _audit_count(db_connection, "assign_world_role") == before + 1


def test_editor_and_reviewer_combine_as_a_union(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    both = harness.new_actor("Both")
    assert _share(s, both, "world_editor").status_code == 201
    assert _share(s, both, "world_reviewer").status_code == 201
    caps = _caps(db_connection, s.world_id, both.user_id)
    assert {"world.canon.edit", "world.canon.review", "timeline.manage"} <= caps
    assert not caps & {"world.manage", "world.share", "world.transfer", "campaign.create"}


def test_only_an_owner_with_system_gm_may_share(s: ContentSetup, harness: AuthoringHarness) -> None:
    editor = harness.new_actor("Editor")
    stranger = harness.new_actor("Nobody")
    _share(s, editor, "world_editor")
    target = harness.new_actor("Target")
    path = f"/worlds/{s.world_id}/roles"
    body = {"login_name": target.login_name, "role_code": "world_reader"}
    assert editor.post(path, body).status_code == 403
    assert editor.get(f"/worlds/{s.world_id}/access").status_code == 403
    assert stranger.post(path, body).status_code == 404
    assert stranger.get(f"/worlds/{s.world_id}/access").status_code == 404
    assert s.player.post(path, body).status_code == 404


def test_the_target_must_be_an_active_account(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    gone = harness.new_actor("Disabled")
    db_connection.execute(
        text(
            "UPDATE security.users SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive') "
            "WHERE user_id = :u"
        ),
        {"u": gone.user_id},
    )
    for login in (gone.login_name, "nobody-by-that-name"):
        response = s.gm.post(
            f"/worlds/{s.world_id}/roles", {"login_name": login, "role_code": "world_reader"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "world_role_target_ineligible"


def test_a_new_owner_must_hold_system_gm(s: ContentSetup, harness: AuthoringHarness) -> None:
    plain = harness.new_actor("Plain")
    response = _share(s, plain, "world_owner")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "target_requires_system_gm"
    gm = _new_gm(harness, "Second Owner")
    assert _share(s, gm, "world_owner").status_code == 201


def test_ending_a_role_takes_effect_on_the_next_request(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    reader = harness.new_actor("Reader")
    created = _share(s, reader, "world_reader").json()
    assert reader.get(f"/worlds/{s.world_id}").status_code == 200
    ended = s.gm.post(
        f"/worlds/{s.world_id}/roles/{created['record_id']}/end", {}, key=s.gm.fresh_key()
    )
    assert ended.status_code == 200, ended.text
    assert reader.get(f"/worlds/{s.world_id}").status_code == 404
    # The assignment is history, never deleted.
    assert (
        db_connection.execute(
            text(
                "SELECT ended_by_user_id FROM security.world_memberships WHERE world_membership_id = :m"
            ),
            {"m": created["record_id"]},
        ).scalar_one()
        == s.gm.user_id
    )


def test_the_last_owner_cannot_be_ended(s: ContentSetup, db_connection: Connection) -> None:
    owner_row = db_connection.execute(
        text("""
            SELECT wm.world_membership_id FROM security.world_memberships wm
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            WHERE wm.world_id = :w AND wr.code = 'world_owner' AND wm.ended_at IS NULL
        """),
        {"w": s.world_id},
    ).scalar_one()
    response = s.gm.post(f"/worlds/{s.world_id}/roles/{owner_row}/end", {})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "world_owner_required"


# --- reader and use grant ---------------------------------------------------------


def test_a_reader_sees_the_world_read_only_and_it_is_listed(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    reader = harness.new_actor("Reader")
    _share(s, reader, "world_reader")
    detail = reader.get(f"/worlds/{s.world_id}").json()
    assert set(detail["capabilities"]) == {"world.view", "world.canon.read"}
    listed = {w["world_id"]: w for w in reader.get("/worlds").json()["items"]}
    assert listed[str(s.world_id)]["role_codes"] == ["world_reader"]
    assert (
        reader.post(
            f"/worlds/{s.world_id}/update", {"expected_row_version": 1, "name": "X"}
        ).status_code
        == 403
    )


def test_world_reader_access_does_not_imply_world_use(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    gm = _new_gm(harness, "Reader GM")
    _share(s, gm, "world_reader")
    timeline = s.gm.get(f"/worlds/{s.world_id}").json()["primary_timeline_id"]
    ruleset_version_id = db_connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": s.cid},
    ).scalar_one()
    response = gm.post(
        "/campaigns",
        {
            "timeline_id": timeline,
            "ruleset_version_id": str(ruleset_version_id),
            "name": "Not allowed",
            "description": None,
        },
    )
    assert response.status_code == 404


def test_a_use_grant_hosts_a_campaign_on_an_unused_timeline_only(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    host = _new_gm(harness, "Host GM")
    granted = s.gm.post(
        f"/worlds/{s.world_id}/use-grants", {"login_name": host.login_name}, key=s.gm.fresh_key()
    )
    assert granted.status_code == 201, granted.text
    assert _caps(db_connection, s.world_id, host.user_id) == {"world.view", "campaign.create"}

    ruleset_version_id = str(
        db_connection.execute(
            text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": s.cid},
        ).scalar_one()
    )
    used = s.gm.get(f"/worlds/{s.world_id}").json()["primary_timeline_id"]
    refused = host.post(
        "/campaigns",
        {
            "timeline_id": used,
            "ruleset_version_id": ruleset_version_id,
            "name": "Shared",
            "description": None,
        },
    )
    assert refused.status_code == 404

    fresh = s.gm.post(f"/worlds/{s.world_id}/timelines", {"name": "For Host", "description": None})
    assert fresh.status_code == 201, fresh.text
    created = host.post(
        "/campaigns",
        {
            "timeline_id": fresh.json()["timeline_id"],
            "ruleset_version_id": ruleset_version_id,
            "name": "Host Campaign",
            "description": None,
        },
        key=host.fresh_key(),
    )
    assert created.status_code == 201, created.text
    # The use grant never conferred canon reads, timeline management or sharing.
    assert (
        host.post(
            f"/worlds/{s.world_id}/timelines", {"name": "No", "description": None}
        ).status_code
        == 403
    )
    assert host.get(f"/worlds/{s.world_id}/access").status_code == 403


def test_revoking_a_use_grant_stops_new_campaigns_but_not_existing_ones(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    host = _new_gm(harness, "Host GM")
    grant = s.gm.post(f"/worlds/{s.world_id}/use-grants", {"login_name": host.login_name}).json()
    fresh = s.gm.post(f"/worlds/{s.world_id}/timelines", {"name": "T1", "description": None}).json()
    ruleset_version_id = str(
        db_connection.execute(
            text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": s.cid},
        ).scalar_one()
    )
    first = host.post(
        "/campaigns",
        {
            "timeline_id": fresh["timeline_id"],
            "ruleset_version_id": ruleset_version_id,
            "name": "One",
            "description": None,
        },
    )
    assert first.status_code == 201
    revoked = s.gm.post(f"/worlds/{s.world_id}/use-grants/{grant['record_id']}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    assert host.get(f"/worlds/{s.world_id}").status_code == 404
    # The campaign the holder already created still works for them.
    campaigns = host.get("/auth/session").json()["campaigns"]
    assert [c["campaign_id"] for c in campaigns] == [first.json()["campaign_id"]]


def test_editors_branch_timelines_but_reviewers_cannot(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    editor = harness.new_actor("Editor")
    reviewer = harness.new_actor("Reviewer")
    _share(s, editor, "world_editor")
    _share(s, reviewer, "world_reviewer")
    body = {"name": "Alt", "description": None}
    assert editor.post(f"/worlds/{s.world_id}/timelines", body).status_code == 201
    assert reviewer.post(f"/worlds/{s.world_id}/timelines", body).status_code == 403


# --- system GM gate (D11) --------------------------------------------------------------


def test_revoking_system_gm_withholds_world_management_and_restoring_it_returns_it(
    s: ContentSetup, db_connection: Connection
) -> None:
    owner_caps = _caps(db_connection, s.world_id, s.gm.user_id)
    assert {"world.manage", "world.share", "world.transfer", "campaign.create"} <= owner_caps

    db_connection.execute(
        text(
            "UPDATE security.user_system_roles SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"
        ),
        {"u": s.gm.user_id},
    )
    lapsed = _caps(db_connection, s.world_id, s.gm.user_id)
    assert not lapsed & {"world.manage", "world.share", "world.transfer", "campaign.create"}
    assert {
        "world.canon.edit",
        "world.canon.review",
        "world.canon.read_private",
        "timeline.manage",
    } <= lapsed
    assert s.gm.get(f"/worlds/{s.world_id}/access").status_code == 403
    assert (
        s.gm.post(
            f"/worlds/{s.world_id}/update", {"expected_row_version": 1, "name": "X"}
        ).status_code
        == 403
    )
    # Role rows are untouched.
    assert (
        db_connection.execute(
            text(
                "SELECT count(*) FROM security.world_memberships WHERE world_id = :w AND ended_at IS NULL"
            ),
            {"w": s.world_id},
        ).scalar_one()
        == 1
    )

    make_system_role_assignment(db_connection, s.gm.user_id, "gm")
    assert _caps(db_connection, s.world_id, s.gm.user_id) == owner_caps


# --- transfer ----------------------------------------------------------------------


def test_transfer_preserves_authorship_and_can_retain_the_previous_owner_as_editor(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    location = s.gm.post(
        s.url("locations"),
        {"category": "region", "name": "Founders Hall", "summary": None},
        key=s.gm.fresh_key(),
    ).json()
    author_before = db_connection.execute(
        text("SELECT created_by_user_id FROM core.entities WHERE entity_id = :e"),
        {"e": location["location_id"]},
    ).scalar_one()
    assert author_before == s.gm.user_id

    heir = _new_gm(harness, "Heir")
    done = s.gm.post(
        f"/worlds/{s.world_id}/ownership-transfer",
        {"login_name": heir.login_name, "retain_previous_owner_as": "world_editor"},
        key=s.gm.fresh_key(),
    )
    assert done.status_code == 200, done.text

    assert (
        db_connection.execute(
            text("SELECT created_by_user_id FROM core.entities WHERE entity_id = :e"),
            {"e": location["location_id"]},
        ).scalar_one()
        == s.gm.user_id
    )
    assert {"world.manage", "world.share"} <= _caps(db_connection, s.world_id, heir.user_id)
    previous = _caps(db_connection, s.world_id, s.gm.user_id)
    assert "world.manage" not in previous
    assert "world.canon.edit" in previous
    assert _audit_count(db_connection, "transfer_world_ownership") == 1


def test_transfer_requires_a_system_gm_target_and_a_different_user(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    plain = harness.new_actor("Plain")
    refused = s.gm.post(
        f"/worlds/{s.world_id}/ownership-transfer", {"login_name": plain.login_name}
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "target_requires_system_gm"
    self_transfer = s.gm.post(
        f"/worlds/{s.world_id}/ownership-transfer", {"login_name": s.gm.login_name}
    )
    assert self_transfer.status_code == 409
    assert self_transfer.json()["error"]["code"] == "invalid_ownership_transfer"
