"""HTTP test harness for the Phase 14 authoring routes.

Real cookie sessions, real CSRF tokens, and real allowed-Origin checking —
every `Actor` signs in through `/auth/activate` and `/auth/login` exactly as
the portal does — but every request runs on **one shared, transactional
connection** that the test's `db_connection` fixture rolls back, so nothing
has to be cleaned up afterward.

Each request still gets request-transaction semantics: the harness wraps it
in a SAVEPOINT that is rolled back when the handler raises (so a failed
command leaves no partial writes, which is exactly what the "no hidden
half-objects" tests assert), and runs `SET CONSTRAINTS ALL IMMEDIATE`
before releasing it, so deferred constraint triggers (owner retention,
access-manager retention) are evaluated per request just as they would be at
the real commit.

Tests that need *real* concurrency across separate connections do not use
this harness; they commit and clean up explicitly
(`tests/database/test_authoring_concurrency.py`).
"""

import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Connection, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_connection
from dnd_ai.api.local_auth import (
    get_login_account_rate_limiter,
    get_login_ip_rate_limiter,
    get_token_consumption_rate_limiter,
)
from dnd_ai.commands.local_auth import _create_local_account_impl
from dnd_ai.domain.access import AuthenticatedPrincipal
from dnd_ai.domain.rate_limit import RateLimiter
from tests.builders import make_world_creator
from tests.factories import make_platform_administrator, make_system_role_assignment

ORIGIN = "http://localhost:5173"
PASSWORD = "a genuinely random passphrase 1"


def _generous() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


# Receipt id field -> authoring GET route segment (see Actor.post).
_RECEIPT_ROUTES = {
    "location_id": "locations",
    "organization_id": "organizations",
    "religion_id": "religions",
    "npc_id": "npcs",
    "knowledge_item_id": "knowledge",
    "quest_id": "quests",
}


@dataclass
class Actor:
    """One signed-in human: a cookie-jar client plus the CSRF token."""

    harness: "AuthoringHarness"
    client: TestClient
    csrf: str
    user_id: uuid.UUID
    name: str
    login_name: str = ""
    _keys: int = field(default=0, repr=False)

    def headers(self, *, key: str | None = None, csrf: bool = True, origin: bool = True) -> dict:
        headers: dict[str, str] = {}
        if origin:
            headers["Origin"] = ORIGIN
        if csrf:
            headers["X-CSRF-Token"] = self.csrf
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    def get(self, path: str, **params: Any) -> Response:
        return self.client.get(path, params=params or None)

    def post_raw(
        self,
        path: str,
        body: dict | None = None,
        *,
        key: str | None = None,
        csrf: bool = True,
        origin: bool = True,
    ) -> Response:
        """The response exactly as the server sent it (a typed authoring write
        answers with a receipt: ids, `row_version`, `created`, `changed`)."""
        return self.client.post(
            path,
            json=body if body is not None else {},
            headers=self.headers(key=key, csrf=csrf, origin=origin),
        )

    def post(
        self,
        path: str,
        body: dict | None = None,
        *,
        key: str | None = None,
        csrf: bool = True,
        origin: bool = True,
    ) -> Response:
        """Like `post_raw`, but a successful typed authoring write is followed by
        the authoritative GET (as the portal does) and the response body becomes
        that view plus the receipt's `changed` flag, so tests can assert on the
        authored record. Tests of the receipt contract itself use `post_raw`."""
        response = self.post_raw(path, body, key=key, csrf=csrf, origin=origin)
        return self._hydrate(path, response)

    def _hydrate(self, path: str, response: Response) -> Response:
        if response.status_code not in (200, 201) or "/authoring/" not in path:
            return response
        try:
            receipt = response.json()
        except ValueError:
            return response
        if not isinstance(receipt, dict) or not {"row_version", "created", "changed"} <= set(
            receipt
        ):
            return response
        prefix = path.split("/authoring/")[0] + "/authoring/"
        for id_field, route in _RECEIPT_ROUTES.items():
            if id_field in receipt:
                view = self.client.get(f"{prefix}{route}/{receipt[id_field]}")
                assert view.status_code == 200, view.text
                body = view.json()
                body["changed"] = receipt["changed"]
                response._content = json.dumps(body).encode()
                return response
        return response

    def fresh_key(self) -> str:
        self._keys += 1
        slug = "".join(ch if ch.isalnum() else "-" for ch in self.name)
        return f"{slug}-{uuid.uuid4().hex[:12]}-{self._keys}"


class AuthoringHarness:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.admin_id = make_platform_administrator(connection, "Harness Admin")
        self.app = self._make_app()
        self._clients: list[TestClient] = []

    def _make_app(self) -> FastAPI:
        app = create_app()
        app.dependency_overrides[get_connection] = self._connection
        app.dependency_overrides[get_login_ip_rate_limiter] = _generous
        app.dependency_overrides[get_login_account_rate_limiter] = _generous
        app.dependency_overrides[get_token_consumption_rate_limiter] = _generous
        return app

    def principal_client(self, principal: AuthenticatedPrincipal) -> TestClient:
        """A client whose every request authenticates as `principal` (an OIDC
        bearer-style principal, or a Foundry device principal) with no cookie,
        so CSRF/Origin do not apply -- exactly as for a real bearer caller."""
        app = self._make_app()
        app.dependency_overrides[get_authenticated_user_id] = lambda: principal
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        self._clients.append(client)
        return client

    def _connection(self) -> Iterator[Connection]:
        savepoint = self.connection.begin_nested()
        try:
            yield self.connection
            # Evaluate deferred constraint triggers now (as the real commit would),
            # then put them back to deferred: SET CONSTRAINTS IMMEDIATE persists
            # for the rest of the transaction and would otherwise make the next
            # request's multi-statement writes trip them mid-command.
            self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            self.connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        except BaseException:
            savepoint.rollback()
            raise
        else:
            savepoint.commit()

    def new_actor(
        self,
        name: str = "Author",
        *,
        world_creator: bool = False,
        system_roles: tuple[str, ...] = (),
    ) -> Actor:
        """A signed-in human. `world_creator=True` makes the account a
        legitimate world creator (`tests.builders.make_world_creator`) for a
        test that authors a world through `POST /worlds`; every other actor is
        an ordinary user who may not create worlds. `system_roles` adds open
        system-role assignments (every new account already holds `player`)."""
        login_name = f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"
        issued = _create_local_account_impl(
            self.connection,
            created_by_user_id=self.admin_id,
            login_name=login_name,
            display_name=name,
        )
        client = TestClient(self.app, raise_server_exceptions=False)
        client.__enter__()
        self._clients.append(client)
        activated = client.post(
            "/auth/activate",
            json={"token": issued.raw_token, "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert activated.status_code == 200, activated.text
        login = client.post(
            "/auth/login",
            json={"login_name": login_name, "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200, login.text
        if world_creator:
            make_world_creator(self.connection, issued.user_id)
        for role_code in system_roles:
            make_system_role_assignment(self.connection, issued.user_id, role_code)
        return Actor(
            harness=self,
            client=client,
            csrf=login.json()["csrf_token"],
            user_id=issued.user_id,
            name=name,
            login_name=login_name,
        )

    def anonymous_client(self) -> TestClient:
        client = TestClient(self.app, raise_server_exceptions=False)
        client.__enter__()
        self._clients.append(client)
        return client

    def close(self) -> None:
        for client in self._clients:
            client.__exit__(None, None, None)


def harness_fixture_factory() -> Callable[..., Iterator[AuthoringHarness]]:
    """Returns the generator body of a pytest fixture; defined here so the
    fixture itself can live in each test module's namespace via a one-line
    wrapper and keep tests/conftest.py untouched."""

    def _gen(db_connection: Connection) -> Iterator[AuthoringHarness]:
        harness = AuthoringHarness(db_connection)
        try:
            yield harness
        finally:
            harness.close()

    return _gen
