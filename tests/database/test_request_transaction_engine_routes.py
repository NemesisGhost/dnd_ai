# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Engine-backed routes end their authorization transaction first (P03-A prerequisite P3, T12).

Eight routes carry a request transaction for authentication and authorization only, and their
command opens its own transactions on the engine. Each now calls `end_request_transaction` after
authorization and before its first engine-side effect, so no database transaction is open during a
provider call and a failed authorization commit precedes every engine effect.

These run on the real routes with a **one-connection** application pool: if the request connection
were still checked out when the command asked the engine for its own, the command would time out.
"""

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError

import dnd_ai.api.deps as deps
from dnd_ai.api.ai_npc import _resolve_provider
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.cookies import DEV_SESSION_COOKIE_NAME
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.local_auth import create_browser_session
from dnd_ai.config import local_session_allowed_origins_tuple, settings
from dnd_ai.domain.ai_provider import FakeAiProvider
from tests.database.test_api_ai_and_corpus import (  # noqa: F401 - fixtures used by name
    Fixture,
    _register_source_body,
    f,
)
from tests.database.test_api_integration import (
    Fixture as IntegrationFixture,
)
from tests.database.test_api_integration import (
    _combat_sync_body,
    _combat_sync_url,
    _register_system_as_gm,
    _start_encounter,
)
from tests.database.test_api_integration import (
    f as integration_f,  # noqa: F401 - fixture used by name
)
from tests.factories import make_timeline_clock, oidc_principal

pytestmark = pytest.mark.database


@pytest.fixture
def small_engine(postgres_engine: Engine) -> Iterator[Engine]:
    name = f"p3ae{uuid.uuid4().hex[:8]}"
    engine = create_engine(
        postgres_engine.url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
        connect_args={"application_name": name},
    )
    engine.application_name = name  # type: ignore[attr-defined]
    try:
        yield engine
    finally:
        engine.dispose()


class _Observing(FakeAiProvider):
    """A fake provider that, when called, looks at the database from outside the request."""

    def __init__(
        self,
        postgres_engine: Engine,
        small: Engine,
        browser_session_id: uuid.UUID | None,
        *,
        fail: bool = False,
    ) -> None:
        super().__init__(dialogue="Welcome, traveler.")
        self.postgres_engine = postgres_engine
        self.small = small
        self.browser_session_id = browser_session_id
        self.fail = fail
        self.calls = 0
        self.observed: dict[str, Any] = {}

    def _observe(self) -> None:
        self.calls += 1
        with self.postgres_engine.connect() as connection:
            self.observed["idle_in_transaction"] = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE application_name = :n AND state = 'idle in transaction'"
                ),
                {"n": self.small.application_name},  # type: ignore[attr-defined]
            ).scalar_one()
        self.observed["checked_out"] = self.small.pool.checkedout()  # type: ignore[attr-defined]
        if self.browser_session_id is not None:
            try:
                with self.postgres_engine.begin() as connection:
                    connection.execute(text("SET LOCAL lock_timeout = '1s'"))
                    connection.execute(
                        text(
                            "UPDATE security.browser_sessions SET user_agent = 'p3-observer' "
                            "WHERE browser_session_id = :s"
                        ),
                        {"s": self.browser_session_id},
                    )
                self.observed["session_row_free"] = True
            except OperationalError:
                self.observed["session_row_free"] = False
        if self.fail:
            raise RuntimeError("the provider failed")

    def generate_npc_turn(self, **kwargs: Any) -> Any:
        self._observe()
        return super().generate_npc_turn(**kwargs)

    def generate_synthesis(self, **kwargs: Any) -> Any:
        self._observe()
        return super().generate_synthesis(**kwargs)


def _cookie(postgres_engine: Engine, user_id: uuid.UUID) -> tuple[dict[str, str], uuid.UUID]:
    with postgres_engine.begin() as connection:
        created = create_browser_session(connection, user_id=user_id)
    origins = local_session_allowed_origins_tuple(settings)
    headers = {
        "Cookie": f"{DEV_SESSION_COOKIE_NAME}={created.raw_session_token}",
        "X-CSRF-Token": created.csrf_token,
        "Origin": origins[0],
    }
    return headers, created.browser_session_id


@pytest.fixture
def cookie_session(
    postgres_engine: Engine, f: Fixture
) -> Iterator[tuple[dict[str, str], uuid.UUID]]:
    headers, session_id = _cookie(postgres_engine, f.gm_user_id)
    try:
        yield headers, session_id
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM security.browser_sessions WHERE user_id = :u"),
                {"u": f.gm_user_id},
            )


def _app_with(small: Engine, provider: FakeAiProvider) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: small
    app.dependency_overrides[_resolve_provider] = lambda: provider
    return TestClient(app, raise_server_exceptions=False)


def _turn_body(f: Fixture) -> dict[str, str]:
    return {
        "agent_assignment_id": str(f.assignment_id),
        "requesting_character_id": str(f.pc_id),
        "requesting_party_id": str(f.party_id),
        "player_message": "Hello!",
        "world_time_id": str(f.world_time_id),
    }


def _requests_and_outputs(engine: Engine, f: Fixture) -> tuple[int, int]:
    with engine.connect() as connection:
        requests = connection.execute(
            text("SELECT count(*) FROM ai.context_requests WHERE agent_assignment_id = :a"),
            {"a": f.assignment_id},
        ).scalar_one()
        outputs = connection.execute(
            text(
                "SELECT count(*) FROM ai.generated_outputs o "
                "JOIN ai.context_requests r ON r.context_request_id = o.context_request_id "
                "WHERE r.agent_assignment_id = :a"
            ),
            {"a": f.assignment_id},
        ).scalar_one()
    return int(requests), int(outputs)


def test_t12a_an_npc_turn_holds_no_transaction_and_no_session_lock_during_the_provider_call(
    postgres_engine: Engine,
    small_engine: Engine,
    f: Fixture,
    cookie_session: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, session_id = cookie_session
    provider = _Observing(postgres_engine, small_engine, session_id)
    with _app_with(small_engine, provider) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/npc-conversation", json=_turn_body(f), headers=headers
        )
    assert response.status_code == 200, response.text
    assert response.json()["dialogue"] == "Welcome, traveler."
    assert provider.calls == 1
    assert provider.observed == {
        "idle_in_transaction": 0,
        "checked_out": 0,
        "session_row_free": True,
    }
    assert _requests_and_outputs(postgres_engine, f) == (1, 1)


def test_t12b_a_failed_authorization_commit_precedes_every_engine_effect(
    postgres_engine: Engine,
    small_engine: Engine,
    f: Fixture,
    cookie_session: tuple[dict[str, str], uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, session_id = cookie_session
    provider = _Observing(postgres_engine, small_engine, session_id)

    def failing_commit(connection: Connection) -> None:
        raise OperationalError("COMMIT", {}, Exception("commit failed"))

    monkeypatch.setattr(deps, "_commit", failing_commit)
    with _app_with(small_engine, provider) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/npc-conversation", json=_turn_body(f), headers=headers
        )
    assert response.status_code == 500
    assert provider.calls == 0  # the provider was never called
    assert _requests_and_outputs(postgres_engine, f) == (0, 0)  # and no engine row exists
    assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_t12c_a_provider_failure_leaves_the_request_row_and_no_output(
    postgres_engine: Engine,
    small_engine: Engine,
    f: Fixture,
    cookie_session: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, session_id = cookie_session
    provider = _Observing(postgres_engine, small_engine, session_id, fail=True)
    with _app_with(small_engine, provider) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/npc-conversation", json=_turn_body(f), headers=headers
        )
    assert response.status_code == 500
    assert provider.calls == 1
    assert _requests_and_outputs(postgres_engine, f) == (1, 0)  # the existing contract, pinned


def test_t12d_a_player_summary_reads_the_party_perspective_before_the_transaction_ends(
    postgres_engine: Engine,
    small_engine: Engine,
    f: Fixture,
    cookie_session: tuple[dict[str, str], uuid.UUID],
) -> None:
    headers, session_id = cookie_session
    with postgres_engine.begin() as connection:
        # Let the GM view the player character's knowledge, and give the campaign a clock the party
        # membership is current on.
        make_timeline_clock(connection, f.timeline_id, f.world_time_id)
        connection.execute(
            text("""
                INSERT INTO security.role_capabilities (role_id, capability_id)
                SELECT mr.role_id,
                       (SELECT capability_id FROM security.capabilities
                        WHERE code = 'character.view_knowledge')
                FROM security.membership_roles mr
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = mr.campaign_membership_id
                WHERE cm.campaign_id = :c AND cm.user_id = :u
            """),
            {"c": f.campaign_id, "u": f.gm_user_id},
        )
    provider = _Observing(postgres_engine, small_engine, session_id)
    with _app_with(small_engine, provider) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/synthesis",
            json={
                "agent_assignment_id": str(f.assignment_id),
                "audience_tier": "player_summary",
                "question_text": "What do we know?",
                "requesting_character_id": str(f.pc_id),
                "requesting_party_id": str(f.party_id),
            },
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert provider.calls == 1
    assert provider.observed == {
        "idle_in_transaction": 0,
        "checked_out": 0,
        "session_row_free": True,
    }
    assert _requests_and_outputs(postgres_engine, f) == (1, 1)


def test_t12e_a_failing_corpus_command_is_mapped_after_the_authorization_transaction_ended(
    postgres_engine: Engine, small_engine: Engine, f: Fixture
) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: small_engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(f.gm_user_id)
    base = f"/campaigns/{f.campaign_id}/reference-corpus"
    with TestClient(app, raise_server_exceptions=False) as client:
        source = client.post(f"{base}/sources", json=_register_source_body(f))
        assert source.status_code == 201, source.text
        source_id = source.json()["source_document_id"]
        first = client.post(f"{base}/sources/{source_id}/grant", json={"is_house_rule": False})
        second = client.post(f"{base}/sources/{source_id}/grant", json={"is_house_rule": False})
    assert first.status_code == 201, first.text
    # The duplicate fails inside the command's own transaction and is mapped as usual; with a
    # one-connection pool it could not even start unless the request connection had been returned.
    assert second.status_code in (400, 409), second.text
    assert "internal_error" not in second.text
    with postgres_engine.connect() as connection:
        grants = connection.execute(
            text(
                "SELECT count(*) FROM ai.reference_source_campaigns "
                "WHERE campaign_id = :c AND source_document_id = :s"
            ),
            {"c": f.campaign_id, "s": uuid.UUID(source_id)},
        ).scalar_one()
    assert grants == 1
    assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_t12f_combat_sync_closes_the_request_connection_before_opening_its_lock_connection(
    postgres_engine: Engine, integration_f: IntegrationFixture
) -> None:
    fixture = integration_f

    def client_for(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    class _Factory:
        def __call__(self, user_id: uuid.UUID) -> TestClient:
            return client_for(user_id)

    external_system_id = _register_system_as_gm(_Factory(), fixture, fixture.campaign_id)  # type: ignore[arg-type]
    operation_id = f"op-{uuid.uuid4().hex[:8]}"
    events: list[tuple[str, int]] = []
    lock = threading.Lock()

    def record(name: str) -> Any:
        def listener(dbapi_connection: Any, *rest: Any) -> None:
            with lock:
                events.append((name, id(dbapi_connection)))

        return listener

    checkout, checkin = record("checkout"), record("checkin")
    with client_for(fixture.gm_user_id) as client:
        encounter_id = _start_encounter(client, fixture)
        body = _combat_sync_body(
            fixture,
            encounter_id,
            external_system_id=external_system_id,
            external_operation_id=operation_id,
        )
        event.listen(postgres_engine, "checkout", checkout)
        event.listen(postgres_engine, "checkin", checkin)
        try:
            first = client.post(_combat_sync_url(fixture.campaign_id), json=body)
            after_first = len(events)
            second = client.post(_combat_sync_url(fixture.campaign_id), json=body)
        finally:
            event.remove(postgres_engine, "checkout", checkout)
            event.remove(postgres_engine, "checkin", checkin)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["replayed"] is False and second.json()["replayed"] is True
    assert second.json()["sync_job_id"] == first.json()["sync_job_id"]  # one applied outcome

    # First request: the request connection (the first checkout) was checked in before any other
    # connection was checked out.
    first_request = events[:after_first]
    names = [name for name, _ in first_request]
    assert names[0] == "checkout"
    request_connection = first_request[0][1]
    first_checkin = names.index("checkin")
    assert first_request[first_checkin][1] == request_connection
    assert "checkout" not in names[1:first_checkin]  # nothing else was open beside it
