"""Tests for `dnd_ai.api.preview` (Phase 13E-B checkpoint 15) — the
per-resource audience preview: `GET /campaigns/{campaign_id}/members/
{campaign_membership_id}/preview/quests/{quest_id}` and `.../preview/
knowledge/{knowledge_item_id}`.

Mirrors `tests/database/test_api_quests_query.py`/`test_api_knowledge.py`'s
GM/player fixture shape, plus a distinct `access.manage`-holding actor
(never one of the subjects) to exercise the actor/subject separation this
checkpoint's own security invariant is built around.

Covers: access control (actor without access.manage refused by the existing
dependency, non-member actor 404), non-disclosing subject-resolution
failures (subject membership from another campaign, closed/departed
subject membership, platform-disabled subject account, a subject denied
the resource by a targeted deny grant), audience-correct rendering (a GM
subject sees a `gm_only` quest objective and knowledge ground truth; a
player subject sees neither), and the anti-lying byte-identical comparison
— a preview response is identical to what the subject's own authenticated
request against the same resource and query parameters returns.
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
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_campaign_party,
    make_character,
    make_knowledge_item,
    make_membership_role,
    make_party,
    make_party_knowledge,
    make_party_membership,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_quest_state,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Preview Campaign", lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection,
            self.timeline_id,
            "Other Preview Campaign",
            lifecycle_status_code="pending",
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        view_knowledge_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_knowledge"
        )
        self.view_capability_id = view_capability_id

        # --- The actor: holds access.manage, never a preview subject ---
        admin_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, admin_role_id, access_manage_id)
        self.actor_user_id = make_user(connection, "Preview Actor")
        self.actor_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.actor_user_id
        )
        make_membership_role(connection, self.actor_membership_id, admin_role_id)

        # A member with no role/capability at all — proves ForbiddenError.
        self.capless_user_id = make_user(connection, "Preview Capless Actor")
        self.capless_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.capless_user_id
        )

        self.outsider_user_id = make_user(connection, "Preview Outsider")

        # --- GM/player roles (subjects hold these, never access.manage) ---
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        # Role-derived (never a fresh security.character_relationship_types
        # row): AccessContext.has_capability's own baseline already ORs in
        # role_capabilities regardless of character_id, so this is
        # sufficient to authorize the player subject's party perspective
        # without touching that shared, global lookup table at all — a
        # second character_relationship_type_capabilities row for this same
        # capability is exactly what test_api_quests_query.py/test_api_
        # knowledge.py's own fixtures already do, but doing it here as well
        # was found (in this checkpoint's own development) to sometimes
        # perturb an unrelated, pre-existing unordered lookup elsewhere in
        # this codebase's dev-data bootstrap tooling when both run in the
        # same pytest session — avoided here structurally rather than
        # chasing that separate, unrelated latent issue.
        make_role_capability(connection, player_role_id, view_knowledge_capability_id)

        self.gm_user_id = make_user(connection, "Preview GM Subject")
        self.gm_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.gm_user_id
        )
        make_membership_role(connection, self.gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Preview Player Subject")
        self.player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        make_membership_role(connection, self.player_membership_id, player_role_id)

        self.character_id = make_character(connection, self.world_id, name="Preview PC")
        self.party_id = make_party(connection, self.world_id, name="Preview Party")
        make_campaign_party(connection, self.campaign_id, self.party_id)
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.character_id, self.world_time_id
        )

        # --- Quest: one visible, one gm_only objective ---
        self.quest_id = make_quest(connection, self.world_id, name="Preview Quest")
        self.stage_id = make_quest_stage(connection, self.quest_id, name="Stage One")
        self.visible_objective_id = make_quest_objective(
            connection, self.stage_id, name="Talk to the elder", visibility_policy="visible"
        )
        self.gm_only_objective_id = make_quest_objective(
            connection, self.stage_id, name="Secret GM note", visibility_policy="gm_only"
        )
        make_quest_state(connection, self.timeline_id, self.quest_id, status_code="active")
        make_quest_state(
            connection,
            self.timeline_id,
            self.quest_id,
            party_id=self.party_id,
            status_code="active",
        )

        # --- Knowledge item: ground truth vs. the party's own distorted
        # belief ---
        self.knowledge_item_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The idol grants wishes.",
            truth_status_code="false",
        )
        make_party_knowledge(
            connection,
            self.timeline_id,
            self.party_id,
            self.knowledge_item_id,
            awareness_level="aware",
            confidence=60,
            interpretation="Everyone says it's cursed, but I've heard it grants wishes.",
        )

        # --- A subject with a targeted campaign.view deny on the quest ---
        self.denied_user_id = make_user(connection, "Preview Denied Subject")
        self.denied_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.denied_user_id
        )
        make_membership_role(connection, self.denied_membership_id, player_role_id)
        make_resource_grant(
            connection,
            self.campaign_id,
            view_capability_id,
            grantee_campaign_membership_id=self.denied_membership_id,
            quest_id=self.quest_id,
            effect="deny",
        )

        # --- A closed (departed) subject membership ---
        self.departed_user_id = make_user(connection, "Preview Departed Subject")
        self.departed_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.departed_user_id, status_code="departed", ended=True
        )

        # --- A platform-disabled subject account, otherwise a normal
        # open, active membership ---
        self.disabled_user_id = make_user(connection, "Preview Disabled Subject")
        self.disabled_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.disabled_user_id
        )
        make_membership_role(connection, self.disabled_membership_id, player_role_id)
        connection.execute(
            text("""
                UPDATE security.users SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive'
                ) WHERE user_id = :u
            """),
            {"u": self.disabled_user_id},
        )

        # --- A membership belonging to a different campaign ---
        self.other_campaign_user_id = make_user(connection, "Preview Other-Campaign Subject")
        self.other_campaign_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_campaign_user_id
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"preview-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM knowledge.entity_knowledge WHERE knowledge_item_id IN (
                    SELECT entity_id FROM core.entities WHERE world_id = :w
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.party_knowledge WHERE knowledge_item_id IN (
                    SELECT entity_id FROM core.entities WHERE world_id = :w
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.party_memberships WHERE party_id = :p
            """),
            {"p": fixture.party_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaign_parties WHERE party_id = :p"),
            {"p": fixture.party_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.objective_state WHERE quest_objective_id IN (
                    SELECT quest_objective_id FROM narrative.quest_objectives WHERE quest_stage_id = :s
                )
            """),
            {"s": fixture.stage_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.quest_state WHERE quest_id = :q"),
            {"q": fixture.quest_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships
                WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.resource_grants WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.actor_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.gm_user_id,
                    fixture.player_user_id,
                    fixture.denied_user_id,
                    fixture.departed_user_id,
                    fixture.disabled_user_id,
                    fixture.other_campaign_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _quest_preview_url(f: Fixture, membership_id: uuid.UUID) -> str:
    return f"/campaigns/{f.campaign_id}/members/{membership_id}/preview/quests/{f.quest_id}"


def _knowledge_preview_url(f: Fixture, membership_id: uuid.UUID) -> str:
    return (
        f"/campaigns/{f.campaign_id}/members/{membership_id}"
        f"/preview/knowledge/{f.knowledge_item_id}"
    )


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_an_actor_without_access_manage_is_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_quest_preview_url(f, f.player_membership_id))
    assert response.status_code == 403


def test_a_non_member_actor_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_quest_preview_url(f, f.player_membership_id))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Non-disclosing subject-resolution failures
# ---------------------------------------------------------------------------


def test_a_subject_from_another_campaign_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_quest_preview_url(f, f.other_campaign_membership_id))
    assert response.status_code == 404


def test_a_departed_subject_membership_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_quest_preview_url(f, f.departed_membership_id))
    assert response.status_code == 404


def test_a_platform_disabled_subject_account_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_quest_preview_url(f, f.disabled_membership_id))
    assert response.status_code == 404


def test_a_subject_denied_the_resource_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_quest_preview_url(f, f.denied_membership_id))
    assert response.status_code == 404


def test_an_unknown_membership_id_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_quest_preview_url(f, uuid.uuid4()))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Audience-correct rendering
# ---------------------------------------------------------------------------


def _objective_names(payload: dict) -> set[str]:
    return {objective["name"] for stage in payload["stages"] for objective in stage["objectives"]}


def test_a_gm_subjects_quest_preview_includes_the_hidden_objective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_quest_preview_url(f, f.gm_membership_id))
    assert response.status_code == 200
    assert "Secret GM note" in _objective_names(response.json())


def test_a_player_subjects_quest_preview_excludes_the_hidden_objective(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_quest_preview_url(f, f.player_membership_id))
    assert response.status_code == 200
    names = _objective_names(response.json())
    assert "Secret GM note" not in names
    assert "Talk to the elder" in names


def test_a_gm_subjects_knowledge_preview_shows_ground_truth(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(_knowledge_preview_url(f, f.gm_membership_id))
    assert response.status_code == 200
    assert response.json()["truth_status_code"] == "false"


def test_a_player_subjects_knowledge_preview_shows_the_partys_own_belief(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(
            _knowledge_preview_url(f, f.player_membership_id)
            + f"?party_id={f.party_id}&character_id={f.character_id}"
        )
    assert response.status_code == 200
    body = response.json()
    assert body["statement"] == "Everyone says it's cursed, but I've heard it grants wishes."
    assert body["truth_status_code"] is None


# ---------------------------------------------------------------------------
# The anti-lying test: byte-identical to the subject's own request
# ---------------------------------------------------------------------------


def test_the_quest_preview_is_byte_identical_to_the_subjects_own_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        preview_response = client.get(_quest_preview_url(f, f.player_membership_id))
    with client_factory(f.player_user_id) as client:
        direct_response = client.get(f"/campaigns/{f.campaign_id}/quests/{f.quest_id}")

    assert preview_response.status_code == direct_response.status_code == 200
    assert preview_response.json() == direct_response.json()


def test_the_knowledge_preview_is_byte_identical_to_the_subjects_own_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    query = f"?party_id={f.party_id}&character_id={f.character_id}"
    with client_factory(f.actor_user_id) as client:
        preview_response = client.get(_knowledge_preview_url(f, f.player_membership_id) + query)
    with client_factory(f.player_user_id) as client:
        direct_response = client.get(
            f"/campaigns/{f.campaign_id}/knowledge/{f.knowledge_item_id}{query}"
        )

    assert preview_response.status_code == direct_response.status_code == 200
    assert preview_response.json() == direct_response.json()


def test_the_gm_quest_preview_is_byte_identical_to_the_subjects_own_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        preview_response = client.get(_quest_preview_url(f, f.gm_membership_id))
    with client_factory(f.gm_user_id) as client:
        direct_response = client.get(f"/campaigns/{f.campaign_id}/quests/{f.quest_id}")

    assert preview_response.status_code == direct_response.status_code == 200
    assert preview_response.json() == direct_response.json()


# ---------------------------------------------------------------------------
# Audit: metadata-only `sensitive_read` rows (checkpoint 15.2A-3)
# ---------------------------------------------------------------------------


def _preview_audit_rows(
    engine: Engine, *, actor_user_id: uuid.UUID, command_name: str | None = None
) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT ca.code AS action, cl.command_name, cl.record_id, cl.entity_id,
                       cl.actor_user_id, cl.correlation_id, cl.changed_fields, cl.reason
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.actor_user_id = :u
                  AND ca.code = 'sensitive_read'
                  AND (CAST(:c AS text) IS NULL OR cl.command_name = :c)
                ORDER BY cl.change_log_id
            """),
            {"u": actor_user_id, "c": command_name},
        ).mappings()
        return [dict(row) for row in rows]


def test_a_shown_preview_writes_one_metadata_only_sensitive_read_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = client.get(
            _quest_preview_url(f, f.gm_membership_id),
            headers={"X-Correlation-Id": "preview-audit-shown-0001"},
        )
    assert response.status_code == 200
    rows = _preview_audit_rows(
        postgres_engine, actor_user_id=f.actor_user_id, command_name="preview_quest"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["record_id"] == f.quest_id and row["entity_id"] == f.quest_id
    assert row["changed_fields"] == {
        "resource_kind": "quest",
        "subject_membership_id": str(f.gm_membership_id),
        "outcome": "shown",
        "character_perspective_supplied": False,
        "party_perspective_supplied": False,
    }
    # No projected response, narrative, or reason is ever stored.
    stored = str(row)
    assert "Secret GM note" not in stored and row["reason"] is None


def test_a_refused_preview_is_still_audited_with_the_identical_404(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.actor_user_id) as client:
        refused = client.get(_knowledge_preview_url(f, f.denied_membership_id))
        unknown = client.get(_knowledge_preview_url(f, uuid.uuid4()))
    assert refused.status_code == 404 and unknown.status_code == 404
    assert refused.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert refused.json()["error"]["message"] == unknown.json()["error"]["message"]
    rows = _preview_audit_rows(
        postgres_engine, actor_user_id=f.actor_user_id, command_name="preview_knowledge"
    )
    assert [r["changed_fields"]["outcome"] for r in rows] == ["refused", "refused"]
    assert all(r["changed_fields"]["resource_kind"] == "knowledge_item" for r in rows)
    # The 404 body never reveals why (and the audit row holds no reason either).
    assert all(r["reason"] is None for r in rows)


def test_perspective_parameters_are_recorded_only_as_booleans(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    character = uuid.uuid4()
    party = uuid.uuid4()
    with client_factory(f.actor_user_id) as client:
        client.get(
            _quest_preview_url(f, f.player_membership_id),
            params={"character_id": str(character), "party_id": str(party)},
        )
    rows = _preview_audit_rows(
        postgres_engine, actor_user_id=f.actor_user_id, command_name="preview_quest"
    )
    last = rows[-1]["changed_fields"]
    assert last["character_perspective_supplied"] is True
    assert last["party_perspective_supplied"] is True
    assert str(character) not in str(last) and str(party) not in str(last)


def test_an_unauthorized_actor_writes_no_preview_audit_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.capless_user_id) as client:
        assert client.get(_quest_preview_url(f, f.player_membership_id)).status_code == 403
    with client_factory(f.outsider_user_id) as client:
        assert client.get(_quest_preview_url(f, f.player_membership_id)).status_code == 404
    for user in (f.capless_user_id, f.outsider_user_id):
        assert _preview_audit_rows(postgres_engine, actor_user_id=user) == []


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_a_preview_path_accepts_only_get(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, method: str
) -> None:
    with client_factory(f.actor_user_id) as client:
        response = getattr(client, method)(_quest_preview_url(f, f.gm_membership_id))
    assert response.status_code == 405


def test_an_unregistered_resource_cannot_be_previewed(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.actor_user_id) as client:
        for kind in ("sessions", "characters", "items", "notes"):
            response = client.get(
                f"/campaigns/{f.campaign_id}/members/{f.gm_membership_id}/preview/{kind}/{uuid.uuid4()}"
            )
            assert response.status_code == 404
