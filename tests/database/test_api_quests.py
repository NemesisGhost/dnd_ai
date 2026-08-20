"""Tests for `dnd_ai.api.quests` — Phase 10 workstream 7's command endpoint
over `dnd_ai.commands.quests.advance_objective` (docs/PLAN.md Phase 10
"command endpoints over the existing command/application services").
Mirrors `tests/database/test_api_items.py`'s shape: `get_authenticated_
user_id` is overridden directly (the OIDC verification chain itself is
already fully covered by `tests/database/test_api_auth.py`) since these
tests exercise campaign-capability enforcement and the quest command's own
HTTP wiring, not token verification.

Includes the workstream 7 correction pass's two regressions: a `party_id`
associated only with a different campaign on the same timeline is rejected
(with and without an `Idempotency-Key`, proving no `campaign.objective_
state`/event/effect/audit row and no completed idempotency reservation
survive the rejection), and `audit.change_log.entity_id` is asserted
against the owning quest's `quest_id`, not `quest_objective_id`.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.idempotency import (
    IdempotentReplay,
    begin_idempotent_request,
    complete_idempotent_request,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_campaign_party,
    make_character,
    make_membership_role,
    make_party,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database

# Mirrors dnd_ai.api.quests._ADVANCE_OBJECTIVE_COMMAND_NAME — duplicated
# here deliberately (tests assert on the public audit.change_log contract,
# not by importing the module's private constants).
_ADVANCE_OBJECTIVE_COMMAND = "advance_objective"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant (revision 080) — these tests grant canon.edit, not
        # access.manage, and don't otherwise care about campaign lifecycle.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.session_id = make_session(connection, self.campaign_id, 1)

        # A second campaign/session on the same world/timeline, used only to
        # exercise SessionNotInCampaignError (a real session belonging to a
        # different campaign than the one named in the URL).
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )
        self.other_session_id = make_session(connection, self.other_campaign_id, 1)

        self.actor_id = make_character(connection, self.world_id, name="Rin")

        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)

        # Associated only with the *other* campaign — same world/timeline,
        # so campaign.enforce_campaign_party_world() alone lets it through.
        # Proves party_id is checked against campaign_id specifically, not
        # just world agreement.
        self.foreign_party_id = make_party(connection, self.world_id, name="Foreign Party")
        make_campaign_party(connection, self.other_campaign_id, self.foreign_party_id)

        self.quest_id = make_quest(connection, self.world_id, name="Restore the Shrine")
        self.stage_id = make_quest_stage(connection, self.quest_id)
        self.objective_id = make_quest_objective(
            connection, self.stage_id, name="Activate the pylon"
        )

        self.gm_user_id = make_user(connection, "Quest API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Quest API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Quest API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"quest-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_items.py's identical cleanup comment:
        # session_replication_role = replica disables the cascade DELETE
        # FROM core.worlds below would otherwise apply to campaign.
        # campaigns/.sessions and security.roles/.role_capabilities/.
        # campaign_memberships/.membership_roles, and revision 080's
        # DEFERRABLE constraint triggers on several of those tables can fail
        # a later, unrelated test in the same pytest session if they're left
        # behind. Deleted explicitly here, in dependency order, scoped by
        # timeline_id to catch both campaigns this fixture created.
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
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
            text(
                "DELETE FROM security.roles WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.campaign_memberships WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM campaign.sessions WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        # security.idempotent_requests carries ON DELETE CASCADE from both
        # actor_user_id/campaign_id, but that cascade is itself a trigger
        # action and is suppressed the same way session_replication_role =
        # replica suppresses everything else this cleanup relies on
        # bypassing — deleted explicitly for the same "avoid unbounded
        # leaked rows across local runs" reason as every other table above.
        cleanup.execute(
            text(
                "DELETE FROM security.idempotent_requests WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        # campaign.campaign_parties/.parties carry the same ON DELETE CASCADE
        # (from campaign_id/world_id respectively) that every other table
        # above does — suppressed identically by session_replication_role =
        # replica, so deleted explicitly here in dependency order.
        cleanup.execute(
            text(
                "DELETE FROM campaign.campaign_parties WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.parties WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
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


def _advance_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/quests/objectives/{f.objective_id}/advance"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "completed"},
        )
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "completed"},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# advance_objective
# ---------------------------------------------------------------------------


def test_advancing_an_objective_updates_its_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "completed",
                "actor_entity_id": str(f.actor_id),
                "session_id": str(f.session_id),
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_status_code"] is None
    assert body["new_status_code"] == "completed"
    event_id = uuid.UUID(body["event_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT os.code
                FROM campaign.objective_state ost
                JOIN campaign.objective_statuses os ON os.objective_status_id = ost.objective_status_id
                WHERE ost.timeline_id = :t AND ost.quest_objective_id = :o
            """),
            {"t": f.timeline_id, "o": f.objective_id},
        ).one()
        assert row.code == "completed"

        event_row = verify.execute(
            text("SELECT campaign_id, session_id FROM narrative.events WHERE event_id = :e"),
            {"e": event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id
        assert event_row.session_id == f.session_id


def test_advancing_an_already_terminal_objective_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "completed"},
        )
        assert first.status_code == 200, first.text

        second = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "failed"},
        )
    assert second.status_code == 400, second.text


def test_an_invalid_new_status_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "active"},
        )
    assert response.status_code == 400


def test_a_session_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "completed",
                "session_id": str(f.other_session_id),
            },
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Party authorization/scope (dnd_ai.commands.quests._validate_campaign_party)
# ---------------------------------------------------------------------------


def test_advancing_with_a_party_from_the_correct_campaign_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "completed",
                "party_id": str(f.party_id),
            },
        )
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT party_id FROM campaign.objective_state "
                "WHERE timeline_id = :t AND quest_objective_id = :o"
            ),
            {"t": f.timeline_id, "o": f.objective_id},
        ).one()
        assert row.party_id == f.party_id


def test_a_party_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "completed",
                "party_id": str(f.foreign_party_id),
            },
        )
    assert response.status_code == 404
    assert _objective_state_count(postgres_engine, f.objective_id) == 0
    assert _event_effect_count(postgres_engine, f.objective_id) == 0
    assert len(_audit_log_rows(postgres_engine, f.quest_id, _ADVANCE_OBJECTIVE_COMMAND)) == 0


def test_a_party_from_a_different_campaign_with_an_idempotency_key_leaves_no_reservation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"foreign-party-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "completed",
                "party_id": str(f.foreign_party_id),
            },
            headers={"Idempotency-Key": key},
        )
    assert response.status_code == 404
    assert _objective_state_count(postgres_engine, f.objective_id) == 0
    assert _event_effect_count(postgres_engine, f.objective_id) == 0
    assert len(_audit_log_rows(postgres_engine, f.quest_id, _ADVANCE_OBJECTIVE_COMMAND)) == 0
    assert (
        _idempotent_request_count(
            postgres_engine, user_id=f.gm_user_id, campaign_id=f.campaign_id, key=key
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Idempotency (dnd_ai.api.idempotency, security.idempotent_requests)
# ---------------------------------------------------------------------------


def _objective_state_count(postgres_engine: Engine, objective_id: uuid.UUID) -> int:
    with postgres_engine.connect() as verify:
        return verify.execute(
            text("SELECT count(*) FROM campaign.objective_state WHERE quest_objective_id = :o"),
            {"o": objective_id},
        ).scalar_one()


def _event_effect_count(postgres_engine: Engine, objective_id: uuid.UUID) -> int:
    with postgres_engine.connect() as verify:
        return verify.execute(
            text(
                "SELECT count(*) FROM narrative.event_effects WHERE target_quest_objective_id = :o"
            ),
            {"o": objective_id},
        ).scalar_one()


def _audit_log_rows(
    postgres_engine: Engine, entity_id: uuid.UUID, command_name: str
) -> list[object]:
    with postgres_engine.connect() as verify:
        return list(
            verify.execute(
                text("""
                    SELECT actor_user_id, correlation_id, command_name, event_id, entity_id,
                           world_id, change_action_id
                    FROM audit.change_log
                    WHERE entity_id = :e AND command_name = :c
                """),
                {"e": entity_id, "c": command_name},
            )
        )


def _idempotent_request_count(
    postgres_engine: Engine, *, user_id: uuid.UUID, campaign_id: uuid.UUID, key: str
) -> int:
    with postgres_engine.connect() as verify:
        return verify.execute(
            text("""
                SELECT count(*) FROM security.idempotent_requests
                WHERE actor_user_id = :u AND campaign_id = :c AND idempotency_key = :k
            """),
            {"u": user_id, "c": campaign_id, "k": key},
        ).scalar_one()


def test_a_sequential_replay_returns_the_original_response_with_no_new_effects(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"replay-{uuid.uuid4().hex[:8]}"
    body = {"world_time_id": str(f.world_time_id), "new_status_code": "completed"}
    with client_factory(f.gm_user_id) as client:
        first = client.post(_advance_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_advance_url(f), json=body, headers={"Idempotency-Key": key})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    assert _event_effect_count(postgres_engine, f.objective_id) == 1
    assert len(_audit_log_rows(postgres_engine, f.quest_id, _ADVANCE_OBJECTIVE_COMMAND)) == 1
    assert (
        _idempotent_request_count(
            postgres_engine, user_id=f.gm_user_id, campaign_id=f.campaign_id, key=key
        )
        == 1
    )


def test_a_concurrent_reservation_attempt_blocks_rather_than_racing(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Proves `begin_idempotent_request()`'s "no check-then-insert race"
    concurrency guarantee directly against the database — see
    `tests/database/test_api_items.py`'s identical test for the full
    rationale on why this bypasses `fastapi.testclient.TestClient` in favor
    of a bounded, single-threaded `lock_timeout` idiom rather than a second
    OS thread."""
    key = f"concurrent-{uuid.uuid4().hex[:8]}"
    payload = {
        "quest_objective_id": str(f.objective_id),
        "world_time_id": str(f.world_time_id),
        "new_status_code": "completed",
        "party_id": None,
        "actor_entity_id": None,
        "session_id": None,
        "cause_interaction_id": None,
        "cause_event_id": None,
        "event_details": None,
    }
    response_body = {
        "objective_state_id": str(uuid.uuid4()),
        "event_id": str(uuid.uuid4()),
        "previous_status_code": None,
        "new_status_code": "completed",
    }

    with postgres_engine.connect() as connection_a, connection_a.begin():
        outcome_a = begin_idempotent_request(
            connection_a,
            actor_user_id=f.gm_user_id,
            campaign_id=f.campaign_id,
            idempotency_key=key,
            command_name=_ADVANCE_OBJECTIVE_COMMAND,
            payload=payload,
            correlation_id=None,
        )
        assert not isinstance(outcome_a, IdempotentReplay), "the first attempt must reserve"

        with postgres_engine.connect() as connection_b:
            connection_b.begin()
            connection_b.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                begin_idempotent_request(
                    connection_b,
                    actor_user_id=f.gm_user_id,
                    campaign_id=f.campaign_id,
                    idempotency_key=key,
                    command_name=_ADVANCE_OBJECTIVE_COMMAND,
                    payload=payload,
                    correlation_id=None,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected a lock timeout while B waited on A's uncommitted reservation, "
                f"got: {message}"
            )
            connection_b.rollback()

        complete_idempotent_request(
            connection_a,
            idempotent_request_id=outcome_a.idempotent_request_id,
            response_status_code=200,
            response_body=response_body,
        )

    with postgres_engine.connect() as connection_c, connection_c.begin():
        outcome_c = begin_idempotent_request(
            connection_c,
            actor_user_id=f.gm_user_id,
            campaign_id=f.campaign_id,
            idempotency_key=key,
            command_name=_ADVANCE_OBJECTIVE_COMMAND,
            payload=payload,
            correlation_id=None,
        )
    assert isinstance(outcome_c, IdempotentReplay)
    assert outcome_c.response_body == response_body

    assert (
        _idempotent_request_count(
            postgres_engine, user_id=f.gm_user_id, campaign_id=f.campaign_id, key=key
        )
        == 1
    )


def test_same_key_with_a_different_payload_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"mismatch-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "completed"},
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "failed"},
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert _event_effect_count(postgres_engine, f.objective_id) == 1


def test_retry_after_a_rolled_back_failure_reuses_the_key(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"retry-after-failure-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        failed = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "active"},
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code == 400, failed.text

    # The failed attempt must not have left any trace: no idempotent_requests
    # row (the key is not permanently consumed) and no audit/event/effect row.
    assert (
        _idempotent_request_count(
            postgres_engine, user_id=f.gm_user_id, campaign_id=f.campaign_id, key=key
        )
        == 0
    )
    assert _event_effect_count(postgres_engine, f.objective_id) == 0
    assert len(_audit_log_rows(postgres_engine, f.quest_id, _ADVANCE_OBJECTIVE_COMMAND)) == 0

    with client_factory(f.gm_user_id) as client:
        retried = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "completed"},
            headers={"Idempotency-Key": key},
        )
    assert retried.status_code == 200, retried.text
    assert _event_effect_count(postgres_engine, f.objective_id) == 1
    assert len(_audit_log_rows(postgres_engine, f.quest_id, _ADVANCE_OBJECTIVE_COMMAND)) == 1


def test_an_unauthorized_request_with_a_key_leaves_no_reservation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"unauthorized-{uuid.uuid4().hex[:8]}"
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "completed"},
            headers={"Idempotency-Key": key},
        )
    assert response.status_code == 404
    assert (
        _idempotent_request_count(
            postgres_engine, user_id=f.outsider_user_id, campaign_id=f.campaign_id, key=key
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Auditing (dnd_ai.api.audit, audit.change_log)
# ---------------------------------------------------------------------------


def test_the_audit_row_identifies_the_authenticated_actor_not_the_in_world_actor(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    correlation_id = str(uuid.uuid4())
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _advance_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "completed",
                # actor_entity_id is an in-world entity, deliberately distinct
                # from the authenticated f.gm_user_id — the audit row must
                # attribute the change to the latter, never the former.
                "actor_entity_id": str(f.actor_id),
            },
            headers={"X-Correlation-Id": correlation_id},
        )
    assert response.status_code == 200, response.text
    event_id = uuid.UUID(response.json()["event_id"])

    rows = _audit_log_rows(postgres_engine, f.quest_id, _ADVANCE_OBJECTIVE_COMMAND)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == f.gm_user_id
    assert row.correlation_id == uuid.UUID(correlation_id)
    assert row.command_name == _ADVANCE_OBJECTIVE_COMMAND
    assert row.event_id == event_id
    # entity_id is the owning quest's core.entities row, not the objective
    # itself — narrative.quest_objectives has no entity identity of its own
    # (audit.change_log.entity_id's documented contract, migration 007).
    assert row.entity_id == f.quest_id
    assert row.world_id == f.world_id

    with postgres_engine.connect() as verify:
        change_action_code = verify.execute(
            text("SELECT code FROM audit.change_actions WHERE change_action_id = :a"),
            {"a": row.change_action_id},
        ).scalar_one()
    assert change_action_code == "updated"
