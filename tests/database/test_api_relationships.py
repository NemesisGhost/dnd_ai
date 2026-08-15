"""Tests for `dnd_ai.api.relationships` — Phase 10 workstream 8's command
endpoints over `dnd_ai.commands.relationships` (docs/PLAN.md Phase 10
"command endpoints over the existing command/application services").
Mirrors `tests/database/test_api_items.py`'s shape: `get_authenticated_
user_id` is overridden directly (the OIDC verification chain itself is
already fully covered by `tests/database/test_api_auth.py`) since these
tests exercise campaign-capability enforcement and the relationship/
organization commands' own HTTP wiring, not token verification.

Covers the deliberate entity_id asymmetry between the two routes:
`evolve_relationship_reaction_endpoint` records `entity_id=None`
(`world.relationships` rows have no `core.entities` identity of their
own), while `update_organization_status_endpoint` records
`entity_id=organization_id` directly (`world.organizations` rows are
`core.entities` rows via class-table inheritance) — see
`dnd_ai.api.relationships`'s module docstring.
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
    make_character,
    make_membership_role,
    make_organization,
    make_relationship,
    make_relationship_participant,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

# Mirrors dnd_ai.api.relationships._EVOLVE_REACTION_COMMAND_NAME/.
# _UPDATE_ORGANIZATION_STATUS_COMMAND_NAME — duplicated here deliberately
# (tests assert on the public audit.change_log contract, not by importing
# the module's private constants).
_EVOLVE_REACTION_COMMAND = "evolve_relationship_reaction"
_UPDATE_ORGANIZATION_STATUS_COMMAND = "update_organization_status"


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

        self.faction_id = make_organization(
            connection,
            self.world_id,
            organization_type_code="criminal_organization",
            name="The Ashen Hand",
        )

        self.relationship_id = make_relationship(
            connection, self.world_id, relationship_type_code="rivalry"
        )
        make_relationship_participant(
            connection, self.relationship_id, self.actor_id, role_code="subject"
        )
        make_relationship_participant(
            connection, self.relationship_id, self.faction_id, role_code="rival"
        )

        self.gm_user_id = make_user(connection, "Relationship API GM")
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
        self.capless_user_id = make_user(connection, "Relationship API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Relationship API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"relationship-api-{uuid.uuid4().hex[:8]}")
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
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
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
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _evolve_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/relationships/{f.relationship_id}/evolve"


def _status_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/organizations/{f.faction_id}/status"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "active"},
        )
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "active"},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# evolve_relationship_reaction
# ---------------------------------------------------------------------------


def test_evolving_a_relationship_updates_its_shared_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "active",
                "actor_entity_id": str(f.actor_id),
                "session_id": str(f.session_id),
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_status_code"] is None
    assert body["new_status_code"] == "active"
    event_id = uuid.UUID(body["event_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT rs.code
                FROM campaign.relationship_state rst
                JOIN campaign.relationship_statuses rs
                    ON rs.relationship_status_id = rst.relationship_status_id
                WHERE rst.timeline_id = :t AND rst.relationship_id = :r
                  AND rst.perspective_holder_entity_id IS NULL
            """),
            {"t": f.timeline_id, "r": f.relationship_id},
        ).one()
        assert row.code == "active"

        event_row = verify.execute(
            text("SELECT campaign_id, session_id FROM narrative.events WHERE event_id = :e"),
            {"e": event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id
        assert event_row.session_id == f.session_id


def test_evolving_a_holders_subjective_reaction_is_independent_of_shared_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "broken",
                "perspective_holder_entity_id": str(f.faction_id),
                "affinity": -70,
                "emotional_tone": "hostile",
            },
        )
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT rs.code, rst.affinity, rst.emotional_tone
                FROM campaign.relationship_state rst
                JOIN campaign.relationship_statuses rs
                    ON rs.relationship_status_id = rst.relationship_status_id
                WHERE rst.timeline_id = :t AND rst.relationship_id = :r
                  AND rst.perspective_holder_entity_id = :holder
            """),
            {"t": f.timeline_id, "r": f.relationship_id, "holder": f.faction_id},
        ).one()
        assert (row.code, row.affinity, row.emotional_tone) == ("broken", -70, "hostile")

        shared_count = verify.execute(
            text("""
                SELECT count(*) FROM campaign.relationship_state
                WHERE timeline_id = :t AND relationship_id = :r
                  AND perspective_holder_entity_id IS NULL
            """),
            {"t": f.timeline_id, "r": f.relationship_id},
        ).scalar_one()
        assert shared_count == 0


def test_an_invalid_new_status_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "not_a_real_status"},
        )
    assert response.status_code == 400


def test_a_session_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "active",
                "session_id": str(f.other_session_id),
            },
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# update_organization_status
# ---------------------------------------------------------------------------


def test_updating_organization_status_updates_its_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _status_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "banned",
                "actor_entity_id": str(f.actor_id),
                "session_id": str(f.session_id),
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_status_code"] is None
    assert body["new_status_code"] == "banned"
    event_id = uuid.UUID(body["event_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT os.code
                FROM campaign.organization_state ost
                JOIN campaign.organization_statuses os
                    ON os.organization_status_id = ost.organization_status_id
                WHERE ost.timeline_id = :t AND ost.organization_id = :o
            """),
            {"t": f.timeline_id, "o": f.faction_id},
        ).one()
        assert row.code == "banned"

        event_row = verify.execute(
            text("SELECT campaign_id, session_id FROM narrative.events WHERE event_id = :e"),
            {"e": event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id
        assert event_row.session_id == f.session_id


def test_an_invalid_organization_status_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _status_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "not_a_real_status"},
        )
    assert response.status_code == 400


def test_an_organization_session_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _status_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "banned",
                "session_id": str(f.other_session_id),
            },
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Idempotency (dnd_ai.api.idempotency, security.idempotent_requests)
# ---------------------------------------------------------------------------


def _relationship_effect_count(postgres_engine: Engine, relationship_id: uuid.UUID) -> int:
    with postgres_engine.connect() as verify:
        return verify.execute(
            text("SELECT count(*) FROM narrative.event_effects WHERE target_relationship_id = :r"),
            {"r": relationship_id},
        ).scalar_one()


def _organization_effect_count(postgres_engine: Engine, organization_id: uuid.UUID) -> int:
    with postgres_engine.connect() as verify:
        return verify.execute(
            text("SELECT count(*) FROM narrative.event_effects WHERE target_entity_id = :o"),
            {"o": organization_id},
        ).scalar_one()


def _audit_log_rows_by_record(
    postgres_engine: Engine, record_id: uuid.UUID, command_name: str
) -> list[object]:
    with postgres_engine.connect() as verify:
        return list(
            verify.execute(
                text("""
                    SELECT actor_user_id, correlation_id, command_name, event_id, entity_id,
                           world_id, change_action_id
                    FROM audit.change_log
                    WHERE record_id = :r AND command_name = :c
                """),
                {"r": record_id, "c": command_name},
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
    body = {"world_time_id": str(f.world_time_id), "new_status_code": "active"}
    with client_factory(f.gm_user_id) as client:
        first = client.post(_evolve_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_evolve_url(f), json=body, headers={"Idempotency-Key": key})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    assert _relationship_effect_count(postgres_engine, f.relationship_id) == 1
    relationship_state_id = uuid.UUID(first.json()["relationship_state_id"])
    assert (
        len(
            _audit_log_rows_by_record(
                postgres_engine, relationship_state_id, _EVOLVE_REACTION_COMMAND
            )
        )
        == 1
    )
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
        "relationship_id": str(f.relationship_id),
        "world_time_id": str(f.world_time_id),
        "new_status_code": "active",
        "perspective_holder_entity_id": None,
        "affinity": None,
        "trust": None,
        "respect": None,
        "fear": None,
        "obligation": None,
        "emotional_tone": None,
        "private_interpretation": None,
        "actor_entity_id": None,
        "session_id": None,
        "cause_interaction_id": None,
        "cause_event_id": None,
        "event_details": None,
    }
    response_body = {
        "relationship_state_id": str(uuid.uuid4()),
        "event_id": str(uuid.uuid4()),
        "previous_status_code": None,
        "new_status_code": "active",
    }

    with postgres_engine.connect() as connection_a, connection_a.begin():
        outcome_a = begin_idempotent_request(
            connection_a,
            actor_user_id=f.gm_user_id,
            campaign_id=f.campaign_id,
            idempotency_key=key,
            command_name=_EVOLVE_REACTION_COMMAND,
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
                    command_name=_EVOLVE_REACTION_COMMAND,
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
            command_name=_EVOLVE_REACTION_COMMAND,
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
            _evolve_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "active"},
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _evolve_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "broken"},
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert _relationship_effect_count(postgres_engine, f.relationship_id) == 1


def test_same_key_on_a_different_endpoint_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"cross-endpoint-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        evolve = client.post(
            _evolve_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "active"},
            headers={"Idempotency-Key": key},
        )
        status = client.post(
            _status_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "banned"},
            headers={"Idempotency-Key": key},
        )

    assert evolve.status_code == 200, evolve.text
    assert status.status_code == 409, status.text
    assert _organization_effect_count(postgres_engine, f.faction_id) == 0


def test_retry_after_a_rolled_back_failure_reuses_the_key(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"retry-after-failure-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        failed = client.post(
            _status_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "not_a_real_status"},
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code == 400, failed.text

    # The failed attempt must not have left any trace: no idempotent_requests
    # row (the key is not permanently consumed) and no event/effect row.
    assert (
        _idempotent_request_count(
            postgres_engine, user_id=f.gm_user_id, campaign_id=f.campaign_id, key=key
        )
        == 0
    )
    assert _organization_effect_count(postgres_engine, f.faction_id) == 0

    with client_factory(f.gm_user_id) as client:
        retried = client.post(
            _status_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "banned"},
            headers={"Idempotency-Key": key},
        )
    assert retried.status_code == 200, retried.text
    assert _organization_effect_count(postgres_engine, f.faction_id) == 1


def test_an_unauthorized_request_with_a_key_leaves_no_reservation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"unauthorized-{uuid.uuid4().hex[:8]}"
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={"world_time_id": str(f.world_time_id), "new_status_code": "active"},
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


def test_the_relationship_audit_row_has_no_entity_id(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """world.relationships rows have no core.entities identity of their
    own (unlike world.organizations) — see
    dnd_ai.api.relationships's module docstring for why entity_id is
    deliberately None here."""
    correlation_id = str(uuid.uuid4())
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _evolve_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "active",
                # actor_entity_id is an in-world entity, deliberately distinct
                # from the authenticated f.gm_user_id — the audit row must
                # attribute the change to the latter, never the former.
                "actor_entity_id": str(f.actor_id),
            },
            headers={"X-Correlation-Id": correlation_id},
        )
    assert response.status_code == 200, response.text
    event_id = uuid.UUID(response.json()["event_id"])
    relationship_state_id = uuid.UUID(response.json()["relationship_state_id"])

    rows = _audit_log_rows_by_record(
        postgres_engine, relationship_state_id, _EVOLVE_REACTION_COMMAND
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == f.gm_user_id
    assert row.correlation_id == uuid.UUID(correlation_id)
    assert row.command_name == _EVOLVE_REACTION_COMMAND
    assert row.event_id == event_id
    assert row.entity_id is None
    assert row.world_id == f.world_id

    with postgres_engine.connect() as verify:
        change_action_code = verify.execute(
            text("SELECT code FROM audit.change_actions WHERE change_action_id = :a"),
            {"a": row.change_action_id},
        ).scalar_one()
    assert change_action_code == "updated"


def test_the_organization_audit_row_identifies_the_organization_entity(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    correlation_id = str(uuid.uuid4())
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _status_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "new_status_code": "banned",
                "actor_entity_id": str(f.actor_id),
            },
            headers={"X-Correlation-Id": correlation_id},
        )
    assert response.status_code == 200, response.text
    event_id = uuid.UUID(response.json()["event_id"])
    organization_state_id = uuid.UUID(response.json()["organization_state_id"])

    rows = _audit_log_rows_by_record(
        postgres_engine, organization_state_id, _UPDATE_ORGANIZATION_STATUS_COMMAND
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == f.gm_user_id
    assert row.correlation_id == uuid.UUID(correlation_id)
    assert row.command_name == _UPDATE_ORGANIZATION_STATUS_COMMAND
    assert row.event_id == event_id
    assert row.entity_id == f.faction_id
    assert row.world_id == f.world_id

    with postgres_engine.connect() as verify:
        change_action_code = verify.execute(
            text("SELECT code FROM audit.change_actions WHERE change_action_id = :a"),
            {"a": row.change_action_id},
        ).scalar_one()
    assert change_action_code == "updated"
