"""Tests for `dnd_ai.api.items` — Phase 10 workstream 6's command endpoints
over `dnd_ai.commands.items` (docs/PLAN.md Phase 10 "command endpoints over
the existing command/application services"). Mirrors
`tests/database/test_api_encounters.py`'s shape: `get_authenticated_user_id`
is overridden directly (the OIDC verification chain itself is already fully
covered by `tests/database/test_api_auth.py`) since these tests exercise
campaign-capability enforcement and the item commands' own HTTP wiring, not
token verification.
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
    make_item_definition,
    make_item_instance,
    make_location,
    make_membership_role,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database

# Mirrors dnd_ai.api.items._TRANSFER_COMMAND_NAME/._IDENTIFY_COMMAND_NAME —
# duplicated here deliberately (tests assert on the public audit.change_log
# contract, not by importing the module's private constants).
_TRANSFER_COMMAND = "transfer_item_possession"
_IDENTIFY_COMMAND = "identify_item"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant (revision 080) — these tests grant canon.edit, not
        # access.manage, and don't otherwise care about campaign lifecycle.
        self.campaign_id = make_campaign(
            connection,
            self.timeline_id,
            ruleset_version_id=ruleset_version_id,
            lifecycle_status_code="pending",
        )
        self.session_id = make_session(connection, self.campaign_id, 1)

        # A second campaign/session on the same world/timeline, used only to
        # exercise SessionNotInCampaignError (a real session belonging to a
        # different campaign than the one named in the URL).
        self.other_campaign_id = make_campaign(
            connection,
            self.timeline_id,
            "Other Campaign",
            ruleset_version_id=ruleset_version_id,
            lifecycle_status_code="pending",
        )
        self.other_session_id = make_session(connection, self.other_campaign_id, 1)

        self.actor_id = make_character(connection, self.world_id, name="Rin")
        self.holder_id = make_character(connection, self.world_id, name="Borrin")
        self.location_id = make_location(connection, self.world_id)
        item_definition_id = make_item_definition(connection, ruleset_version_id)
        self.item_instance_id = make_item_instance(connection, self.world_id, item_definition_id)

        self.gm_user_id = make_user(connection, "Item API GM")
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
        self.capless_user_id = make_user(connection, "Item API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Item API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"item-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_encounters.py's identical cleanup
        # comment: session_replication_role = replica disables the cascade
        # DELETE FROM core.worlds below would otherwise apply to
        # campaign.campaigns/.sessions and security.roles/.role_
        # capabilities/.campaign_memberships/.membership_roles, and revision
        # 080's DEFERRABLE constraint triggers on several of those tables
        # can fail a later, unrelated test in the same pytest session if
        # they're left behind. Deleted explicitly here, in dependency
        # order, scoped by timeline_id to catch both campaigns this
        # fixture created.
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
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "holder_entity_id": str(f.holder_id)},
        )
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "holder_entity_id": str(f.holder_id)},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# transfer_item_possession
# ---------------------------------------------------------------------------


def test_transferring_possession_updates_the_inventory_entry(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={
                "world_time_id": str(f.world_time_id),
                "holder_entity_id": str(f.holder_id),
                "actor_entity_id": str(f.actor_id),
                "session_id": str(f.session_id),
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    event_id = uuid.UUID(body["event_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT holder_entity_id FROM campaign.inventory_entries
                WHERE timeline_id = :t AND item_instance_id = :i
            """),
            {"t": f.timeline_id, "i": f.item_instance_id},
        ).one()
        assert row.holder_entity_id == f.holder_id

        event_row = verify.execute(
            text("SELECT campaign_id, session_id FROM narrative.events WHERE event_id = :e"),
            {"e": event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id
        assert event_row.session_id == f.session_id


def test_a_session_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={
                "world_time_id": str(f.world_time_id),
                "holder_entity_id": str(f.holder_id),
                "session_id": str(f.other_session_id),
            },
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# identify_item
# ---------------------------------------------------------------------------


def test_identifying_an_item_updates_the_knowers_identification(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/identify",
            json={
                "world_time_id": str(f.world_time_id),
                "knower_entity_id": str(f.holder_id),
                "new_level": "fully_identified",
                "known_properties": {"bonus": "+1"},
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_level"] is None
    assert body["new_level"] == "fully_identified"

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT identification_level, known_properties_jsonb
                FROM knowledge.item_identification
                WHERE timeline_id = :t AND item_instance_id = :i AND knower_entity_id = :k
            """),
            {"t": f.timeline_id, "i": f.item_instance_id, "k": f.holder_id},
        ).one()
        assert row.identification_level == "fully_identified"
        assert row.known_properties_jsonb == {"bonus": "+1"}


def test_identifying_with_an_invalid_level_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/identify",
            json={
                "world_time_id": str(f.world_time_id),
                "knower_entity_id": str(f.holder_id),
                "new_level": "not_a_real_level",
            },
        )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Idempotency (dnd_ai.api.idempotency, security.idempotent_requests)
# ---------------------------------------------------------------------------


def _event_effect_count(postgres_engine: Engine, item_instance_id: uuid.UUID) -> int:
    with postgres_engine.connect() as verify:
        return verify.execute(
            text("SELECT count(*) FROM narrative.event_effects WHERE target_entity_id = :i"),
            {"i": item_instance_id},
        ).scalar_one()


def _audit_log_rows(
    postgres_engine: Engine, item_instance_id: uuid.UUID, command_name: str
) -> list[object]:
    with postgres_engine.connect() as verify:
        return list(
            verify.execute(
                text("""
                    SELECT actor_user_id, correlation_id, command_name, event_id, entity_id,
                           world_id, change_action_id
                    FROM audit.change_log
                    WHERE entity_id = :i AND command_name = :c
                """),
                {"i": item_instance_id, "c": command_name},
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
    body = {
        "world_time_id": str(f.world_time_id),
        "holder_entity_id": str(f.holder_id),
    }
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json=body,
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json=body,
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    assert _event_effect_count(postgres_engine, f.item_instance_id) == 1
    assert len(_audit_log_rows(postgres_engine, f.item_instance_id, _TRANSFER_COMMAND)) == 1
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
    concurrency guarantee directly against the database, the same way
    every other concurrency regression in this codebase does (e.g.
    `tests/scenario/test_item_commands.py`'s `_lock_item_instance` test) —
    below the HTTP layer, since driving two genuinely concurrent requests
    through `fastapi.testclient.TestClient` is not a supported use of that
    harness (each request runs through its own blocking anyio portal).

    Deliberately does not use a second OS thread at all. An earlier version
    of this test used `threading.Thread` to run a second, genuinely
    concurrent attempt and observed it repeatedly and unpredictably stall
    at the Python/driver layer in this specific local sandbox — while
    `pg_stat_activity` independently confirmed PostgreSQL itself had
    already resolved the conflict and gone idle, and while the identical
    SQL sequence run through two plain `psql` sessions (no Python/threading
    involved at all) resolved correctly every time. That is a client-side
    thread-scheduling artifact of this environment, not a database or
    application defect, but it made a thread-based test unusable as a
    reliable regression here.

    Instead, this test converts "must block, not proceed" into a bounded,
    single-threaded, deterministic assertion — the same `lock_timeout`
    idiom `tests/database/test_party_memberships.py`,
    `test_world_ruleset_dependency_and_concurrency.py`, and
    `test_security_access_control_invariants.py` already use for this
    exact purpose: connection A reserves the key and is left deliberately
    uncommitted; a second attempt on connection B runs with `lock_timeout`
    set to 2 seconds. If `begin_idempotent_request` used a check-then-insert
    race instead of one atomic `INSERT ... ON CONFLICT`, B's attempt would
    either succeed immediately (wrongly creating a second reservation — the
    exact bug this test exists to catch) or observe "no row yet" and
    proceed to also treat itself as the reservation owner. Because it is
    instead one atomic statement waiting on PostgreSQL's own row-level
    conflict resolution, B's statement is canceled by `lock_timeout` —
    proof that it was still waiting on A, not proceeding around it.
    """
    key = f"concurrent-{uuid.uuid4().hex[:8]}"
    payload = {
        "item_instance_id": str(f.item_instance_id),
        "world_time_id": str(f.world_time_id),
        "holder_entity_id": str(f.holder_id),
        "container_id": None,
        "location_id": None,
        "actor_entity_id": None,
        "session_id": None,
        "event_details": None,
    }
    response_body = {"inventory_entry_id": str(uuid.uuid4()), "event_id": str(uuid.uuid4())}

    with postgres_engine.connect() as connection_a, connection_a.begin():
        outcome_a = begin_idempotent_request(
            connection_a,
            actor_user_id=f.gm_user_id,
            campaign_id=f.campaign_id,
            idempotency_key=key,
            command_name=_TRANSFER_COMMAND,
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
                    command_name=_TRANSFER_COMMAND,
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

    # Now that A has committed, a fresh attempt must cleanly replay rather
    # than reserve again — the same "already-committed" path
    # test_a_sequential_replay_returns_the_original_response_with_no_new_effects
    # exercises through the HTTP layer, checked here directly too since this
    # test already has the fixtures in hand.
    with postgres_engine.connect() as connection_c, connection_c.begin():
        outcome_c = begin_idempotent_request(
            connection_c,
            actor_user_id=f.gm_user_id,
            campaign_id=f.campaign_id,
            idempotency_key=key,
            command_name=_TRANSFER_COMMAND,
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
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "holder_entity_id": str(f.holder_id)},
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "location_id": str(f.location_id)},
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert _event_effect_count(postgres_engine, f.item_instance_id) == 1


def test_same_key_on_a_different_endpoint_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"cross-endpoint-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        transfer = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "holder_entity_id": str(f.holder_id)},
            headers={"Idempotency-Key": key},
        )
        identify = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/identify",
            json={
                "world_time_id": str(f.world_time_id),
                "knower_entity_id": str(f.holder_id),
                "new_level": "fully_identified",
            },
            headers={"Idempotency-Key": key},
        )

    assert transfer.status_code == 200, transfer.text
    assert identify.status_code == 409, identify.text
    assert _event_effect_count(postgres_engine, f.item_instance_id) == 1


def test_retry_after_a_rolled_back_failure_reuses_the_key(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"retry-after-failure-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        failed = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/identify",
            json={
                "world_time_id": str(f.world_time_id),
                "knower_entity_id": str(f.holder_id),
                "new_level": "not_a_real_level",
            },
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
    assert _event_effect_count(postgres_engine, f.item_instance_id) == 0
    assert len(_audit_log_rows(postgres_engine, f.item_instance_id, _IDENTIFY_COMMAND)) == 0

    with client_factory(f.gm_user_id) as client:
        retried = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/identify",
            json={
                "world_time_id": str(f.world_time_id),
                "knower_entity_id": str(f.holder_id),
                "new_level": "fully_identified",
            },
            headers={"Idempotency-Key": key},
        )
    assert retried.status_code == 200, retried.text
    assert _event_effect_count(postgres_engine, f.item_instance_id) == 1
    assert len(_audit_log_rows(postgres_engine, f.item_instance_id, _IDENTIFY_COMMAND)) == 1


def test_an_unauthorized_request_with_a_key_leaves_no_reservation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"unauthorized-{uuid.uuid4().hex[:8]}"
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "holder_entity_id": str(f.holder_id)},
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
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={
                "world_time_id": str(f.world_time_id),
                "holder_entity_id": str(f.holder_id),
                # actor_entity_id is an in-world entity, deliberately distinct
                # from the authenticated f.gm_user_id — the audit row must
                # attribute the change to the latter, never the former.
                "actor_entity_id": str(f.actor_id),
            },
            headers={"X-Correlation-Id": correlation_id},
        )
    assert response.status_code == 200, response.text
    event_id = uuid.UUID(response.json()["event_id"])

    rows = _audit_log_rows(postgres_engine, f.item_instance_id, _TRANSFER_COMMAND)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == f.gm_user_id
    assert row.correlation_id == uuid.UUID(correlation_id)
    assert row.command_name == _TRANSFER_COMMAND
    assert row.event_id == event_id
    assert row.entity_id == f.item_instance_id
    assert row.world_id == f.world_id

    with postgres_engine.connect() as verify:
        change_action_code = verify.execute(
            text("SELECT code FROM audit.change_actions WHERE change_action_id = :a"),
            {"a": row.change_action_id},
        ).scalar_one()
    assert change_action_code == "updated"
