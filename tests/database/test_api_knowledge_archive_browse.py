"""CP-7: Archived Knowledge browsing (`GET /campaigns/{id}/knowledge?lifecycle=active|archived|all`).

Eligibility is the *baseline* campaign `canon.edit` AND `world.canon.read_private` (DR-5); a targeted
claim grant never opens archive browsing, an ineligible non-`active` request is a safe 403, and the
filter runs in SQL before keyset paging with the cursor bound to the filter. The historical direct
read by id (DR-1) is independent of browse eligibility.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.database.test_api_knowledge_browse import Fixture, client_factory, f  # noqa: F401
from tests.factories import (
    make_knowledge_item,
    make_public_knowledge,
    make_resource_grant,
    make_world_role_assignment,
    status_id,
)

pytestmark = pytest.mark.database


class Claims:
    """Claims in every state this checkpoint distinguishes, built on top of the browse fixture."""

    def __init__(self, engine: Engine, fx: Fixture) -> None:
        self.f = fx
        with engine.begin() as connection:
            self.active = self._claim(connection, "Active claim zulu")
            self.archived_a = self._claim(connection, "Archived claim alpha", "canon", "archived")
            self.archived_b = self._claim(connection, "Archived claim bravo", "canon", "archived")
            self.archived_c = self._claim(connection, "Archived claim charlie", "canon", "archived")
            self.archived_superseded = self._claim(
                connection, "Archived superseded delta", "superseded", "archived"
            )
            self.archived_deprecated = self._claim(
                connection, "Archived deprecated echo", "deprecated", "archived"
            )
            self.archived_draft = self._claim(
                connection, "Archived draft foxtrot", "draft", "archived"
            )
            self.archived_rejected = self._claim(
                connection, "Archived rejected golf", "rejected", "archived"
            )
            self.draft = self._claim(connection, "Active draft hotel", "draft", "active")
            self.active_superseded = self._claim(
                connection, "Active superseded juliet", "superseded", "active"
            )
            self.active_deprecated = self._claim(
                connection, "Active deprecated kilo", "deprecated", "active"
            )
            self.active_unpublished = [
                self._claim(connection, f"Active {status} lima", status, "active")
                for status in ("proposed", "approved", "rejected")
            ]
            self.archived_unpublished = [
                self._claim(connection, f"Archived {status} mike", status, "archived")
                for status in ("proposed", "approved")
            ]
            self.deleted = self._claim(connection, "Deleted claim india", "canon", "deleted")
            self.editor_user_id = fx.gm_user_id

    def _claim(
        self, connection: Any, statement: str, canon: str = "canon", lifecycle: str = "active"
    ) -> uuid.UUID:
        item_id = make_knowledge_item(connection, self.f.world_id, statement=statement)
        connection.execute(
            text(
                "UPDATE core.entities SET canon_status_id = :c, lifecycle_status_id = :l "
                "WHERE entity_id = :i"
            ),
            {
                "c": status_id(connection, "canon_statuses", canon),
                "l": status_id(connection, "lifecycle_statuses", lifecycle),
                "i": item_id,
            },
        )
        return item_id


@pytest.fixture
def claims(postgres_engine: Engine, f: Fixture) -> Claims:  # noqa: F811
    return Claims(postgres_engine, f)


@pytest.fixture
def gm_world_role(postgres_engine: Engine, f: Fixture) -> Iterator[uuid.UUID]:  # noqa: F811
    """The GM also holds an Editor world role (`world.canon.read_private`)."""
    with postgres_engine.begin() as connection:
        membership_id = make_world_role_assignment(
            connection, f.world_id, f.gm_user_id, "world_editor"
        )
    yield membership_id
    with postgres_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM security.world_memberships WHERE world_id = :w"),
            {"w": f.world_id},
        )


def _list(client: TestClient, fx: Fixture, **params: Any) -> Any:
    return client.get(f"/campaigns/{fx.campaign_id}/knowledge", params=params)


def _ids(response: Any) -> set[str]:
    return {item["knowledge_item_id"] for item in response.json()["items"]}


def _page_all(client: TestClient, fx: Fixture, **params: Any) -> list[str]:  # noqa: F811
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(50):
        query = dict(params, limit=2)
        if cursor:
            query["cursor"] = cursor
        response = _list(client, fx, **query)
        assert response.status_code == 200, response.text
        seen += [item["knowledge_item_id"] for item in response.json()["items"]]
        cursor = response.json()["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("pagination did not terminate")


def test_active_is_the_default_and_unchanged(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    client = client_factory(f.gm_user_id)
    default = _list(client, f, view="known")
    explicit = _list(client, f, view="known", lifecycle="active")
    assert default.status_code == explicit.status_code == 200
    assert _ids(default) == _ids(explicit)
    ids = _ids(default)
    assert str(claims.active) in ids
    assert str(claims.draft) in ids  # existing GM behavior: unpublished active claims
    for archived in (claims.archived_a, claims.archived_superseded, claims.archived_draft):
        assert str(archived) not in ids
    assert default.json()["archive_browse_available"] is True


def test_archived_and_all_semantics(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    client = client_factory(f.gm_user_id)
    archived = _ids(_list(client, f, view="known", lifecycle="archived"))
    assert archived == {str(claims.archived_a), str(claims.archived_b), str(claims.archived_c)}

    everything = _ids(_list(client, f, view="known", lifecycle="all", limit=100))
    active = _ids(_list(client, f, view="known", lifecycle="active", limit=100))
    # `active` is unchanged: the editor's unpublished active claims are still there.
    assert str(claims.draft) in active
    assert {str(c) for c in claims.active_unpublished} <= active
    # `all` is published history in either operational state, whatever the canon status.
    published_history = {
        claims.active,
        claims.active_superseded,
        claims.active_deprecated,
        claims.archived_a,
        claims.archived_b,
        claims.archived_c,
        claims.archived_superseded,
        claims.archived_deprecated,
        f.fact_id,
    }
    assert {str(c) for c in published_history} <= everything
    # Unpublished claims never appear in archive browsing, active or archived; deleted never does.
    unpublished = {
        claims.draft,
        claims.archived_draft,
        claims.archived_rejected,
        claims.deleted,
        *claims.active_unpublished,
        *claims.archived_unpublished,
    }
    for hidden in unpublished:
        assert str(hidden) not in everything
        assert str(hidden) not in archived


def test_archived_cards_carry_lifecycle_status(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    client = client_factory(f.gm_user_id)
    items = _list(client, f, view="known", lifecycle="all", limit=100).json()["items"]
    by_id = {item["knowledge_item_id"]: item for item in items}
    assert by_id[str(claims.archived_a)]["lifecycle_status"] == "archived"
    assert by_id[str(claims.archived_superseded)]["canon_status"] == "superseded"
    assert by_id[str(claims.active)]["lifecycle_status"] == "active"


def test_campaign_only_gm_cannot_browse_archives(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
) -> None:
    client = client_factory(f.gm_user_id)  # baseline canon.edit, no world.canon.read_private
    active = _list(client, f, view="known")
    assert active.status_code == 200
    assert active.json()["archive_browse_available"] is False
    for lifecycle in ("archived", "all"):
        response = _list(client, f, view="known", lifecycle=lifecycle)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "archive_browse_forbidden"
        assert str(claims.archived_a) not in response.text


def test_player_cannot_browse_archives_but_active_is_unchanged(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
) -> None:
    client = client_factory(f.player_user_id)
    ok = _list(client, f, view="known", **{"character_id": str(f.character_id)})
    assert ok.status_code == 200
    assert ok.json()["archive_browse_available"] is False
    for lifecycle in ("archived", "all"):
        response = _list(client, f, view="known", lifecycle=lifecycle)
        assert response.status_code == 403
    assert _list(client, f, view="known", lifecycle="forged").status_code == 422


def test_targeted_claim_grant_never_grants_archive_browse(
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
) -> None:
    with postgres_engine.begin() as connection:
        make_resource_grant(
            connection,
            f.campaign_id,
            f.canon_edit_capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            knowledge_item_id=claims.archived_a,
        )
        make_world_role_assignment(connection, f.world_id, f.player_user_id, "world_editor")
    try:
        client = client_factory(f.player_user_id)
        response = _list(client, f, view="known")
        assert response.status_code == 200
        assert response.json()["archive_browse_available"] is False
        assert _list(client, f, view="known", lifecycle="archived").status_code == 403
        assert _list(client, f, view="known", lifecycle="all").status_code == 403
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM security.world_memberships WHERE world_id = :w"),
                {"w": f.world_id},
            )


def test_targeted_denies_apply_without_changing_archive_eligibility(
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    """A targeted `campaign.view` deny hides its claim from `all`; a targeted `canon.edit` deny
    strips ground truth only. Neither touches the baseline eligibility to browse archives. (A
    resource grant only resolves while its target is `active`, so grants never act on an archived
    claim -- existing grant resolution, not a CP-7 rule.)"""
    with postgres_engine.begin() as connection:
        for capability_id, target in (
            (f.view_capability_id, claims.active),
            (f.canon_edit_capability_id, claims.draft),
        ):
            make_resource_grant(
                connection,
                f.campaign_id,
                capability_id,
                grantee_campaign_membership_id=f.gm_membership_id,
                knowledge_item_id=target,
                effect="deny",
            )
    client = client_factory(f.gm_user_id)
    everything = _list(client, f, view="known", lifecycle="all", limit=100)
    assert everything.status_code == 200
    assert str(claims.active) not in _ids(everything)  # view deny
    assert everything.json()["archive_browse_available"] is True
    archived = _list(client, f, view="known", lifecycle="archived")
    assert archived.status_code == 200


def test_revoked_world_role_is_not_eligible(
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    client = client_factory(f.gm_user_id)
    assert _list(client, f, view="known", lifecycle="archived").status_code == 200
    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE security.world_memberships SET ended_at = now() WHERE world_id = :w"),
            {"w": f.world_id},
        )
    assert _list(client, f, view="known", lifecycle="archived").status_code == 403


def test_direct_read_is_independent_of_browse_eligibility(
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
) -> None:
    """DR-1: published history stays readable by id for a caller who may not browse it."""
    with postgres_engine.begin() as connection:
        for item_id in (claims.archived_a, claims.archived_superseded, claims.archived_draft):
            make_public_knowledge(connection, f.timeline_id, item_id, f.location_id)
    client = client_factory(f.player_user_id)
    assert _list(client, f, view="known", lifecycle="archived").status_code == 403
    direct = client.get(f"/campaigns/{f.campaign_id}/knowledge/{claims.archived_a}")
    assert direct.status_code == 200
    superseded = client.get(f"/campaigns/{f.campaign_id}/knowledge/{claims.archived_superseded}")
    assert superseded.status_code == 200
    # Unpublished history is still the same 404 as a missing record.
    draft = client.get(f"/campaigns/{f.campaign_id}/knowledge/{claims.archived_draft}")
    assert draft.status_code == 404


@pytest.mark.parametrize("lifecycle", ["archived", "all"])
def test_pagination_has_no_omission_or_duplication(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
    lifecycle: str,
) -> None:
    client = client_factory(f.gm_user_id)
    expected = _ids(_list(client, f, view="known", lifecycle=lifecycle, limit=100))
    paged = _page_all(client, f, view="known", lifecycle=lifecycle)
    assert len(paged) == len(set(paged))
    assert set(paged) == expected
    assert len(expected) >= 3


def test_recent_view_archive_filter_pages_cleanly(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    client = client_factory(f.gm_user_id)
    response = _list(client, f, view="recent", lifecycle="archived", limit=2)
    assert response.status_code == 200
    # Every archived claim visible in the stream is archived history, never an active claim.
    assert _ids(response) <= {
        str(claims.archived_a),
        str(claims.archived_b),
        str(claims.archived_c),
    }


def test_cursor_is_bound_to_the_lifecycle_filter(
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    client = client_factory(f.gm_user_id)
    cursors = {}
    for lifecycle in ("active", "archived", "all"):
        page = _list(client, f, view="known", lifecycle=lifecycle, limit=1).json()
        assert page["next_cursor"], lifecycle
        cursors[lifecycle] = page["next_cursor"]
    for issued, cursor in cursors.items():
        for requested in ("active", "archived", "all"):
            response = _list(client, f, view="known", lifecycle=requested, limit=1, cursor=cursor)
            if issued == requested:
                assert response.status_code == 200
            else:
                assert response.status_code == 400
                assert response.json()["error"]["code"] == "cursor_filter_mismatch"
    garbage = _list(client, f, view="known", lifecycle="archived", cursor="not-a-cursor")
    assert garbage.status_code == 422
    assert garbage.json()["error"]["code"] == "invalid_cursor"


def test_member_preview_never_offers_archive_browse(
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],  # noqa: F811
    f: Fixture,  # noqa: F811
    claims: Claims,
    gm_world_role: uuid.UUID,
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO security.role_capabilities (role_id, capability_id)
                SELECT mr.role_id, c.capability_id
                FROM security.membership_roles mr, security.capabilities c
                WHERE mr.campaign_membership_id = :m AND c.code = 'access.manage'
            """),
            {"m": f.gm_membership_id},
        )
    client = client_factory(f.gm_user_id)
    url = f"/campaigns/{f.campaign_id}/members/{f.player_membership_id}/preview/knowledge"
    response = client.get(url, params={"view": "known"})
    assert response.status_code == 200, response.text
    assert response.json()["archive_browse_available"] is False
    assert str(claims.archived_a) not in _ids(response)
    # The preview route has no lifecycle parameter: a forged one is ignored, never honored.
    forged = client.get(url, params={"view": "known", "lifecycle": "archived"})
    assert str(claims.archived_a) not in _ids(forged)
