"""HTTP test harness for the Phase 14 authoring routes.

Real cookie sessions, real CSRF tokens, and real allowed-Origin checking —
every `Actor` signs in through `/auth/activate` and `/auth/login` exactly as
the portal does — but every request runs on **one shared, transactional
connection** that the test's `db_connection` fixture rolls back, so nothing
has to be cleaned up afterward.

Each request still gets request-transaction semantics: the harness wraps it
in a SAVEPOINT that is rolled back when the handler raises (so a failed
command leaves no partial writes, which is exactly what the "no hidden
half-objects" tests assert), and runs `SET CONSTRAINTS <every deferrable
constraint but one> IMMEDIATE` before releasing it, so deferred constraint
triggers (owner retention, access-manager retention) are evaluated per
request just as they would be at the real commit.

Two things differ from a real request since the keyed pre-write routes (R01
S5-D and S5-E1). The savepoint is a raw `SAVEPOINT` statement, not a
SQLAlchemy nested transaction, because a keyed plan refuses to defer the
reservation's campaign foreign key inside one. And the flush excludes that
foreign key (and never says `ALL`), because the plan guard refuses every
statement that may change its mode other than the plan's own deferral. The
plan's deferral therefore outlives its request in the one shared
transaction, and this harness does not evaluate the reservation's campaign
check; nothing here depends on it. Tests of what a plan guarantees (locks,
order, completeness, deferral) use real connections, never this harness.

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
from dnd_ai.api.idempotency import reset_idempotency_key_lock
from dnd_ai.api.local_auth import (
    get_login_account_rate_limiter,
    get_login_ip_rate_limiter,
    get_token_consumption_rate_limiter,
)
from dnd_ai.commands.local_auth import _create_local_account_impl
from dnd_ai.domain.access import AuthenticatedPrincipal
from dnd_ai.domain.authorization import _forget as forget_bound_plans  # harness: end of request
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
        reset_idempotency_key_lock(self.connection)  # one outer transaction serves many requests
        # A raw SAVEPOINT, not `begin_nested()`: a keyed pre-write plan (R01 S5-D, S5-E1) defers the
        # reservation's campaign foreign key and refuses to do so inside a SQLAlchemy nested transaction
        # (`connection.in_nested_transaction()`), because a rolled-back savepoint silently undoes the
        # deferral. Here the savepoint is only the harness's own per-request rollback boundary.
        self.connection.exec_driver_sql("SAVEPOINT harness_request")
        try:
            yield self.connection
            # The request is over, as a COMMIT would end it: its plan is no longer bound (a finalized
            # pre-write plan refuses every later statement not declared by the plan).
            forget_bound_plans(self.connection)
            # Evaluate deferred constraint triggers now (as the real commit would),
            # then put them back to deferred: SET CONSTRAINTS IMMEDIATE persists
            # for the rest of the transaction and would otherwise make the next
            # request's multi-statement writes trip them mid-command.
            #
            # Not `ALL`: the plan guard remembers any statement that may change the reservation FK's
            # mode (`SET CONSTRAINTS ALL` included) for the whole outer transaction this harness
            # shares, and refuses every later keyed pre-write plan in it. The explicit list is every
            # other deferrable constraint and constraint trigger. A plan's own deferral of the
            # reservation FK is left in place after the request: this harness never commits, and
            # nothing in it relies on the reservation's campaign check (tests of the lock behaviour
            # use real connections).
            flush = self._deferrable_constraints()
            self.connection.execute(text(f"SET CONSTRAINTS {flush} IMMEDIATE"))
            self.connection.execute(text(f"SET CONSTRAINTS {flush} DEFERRED"))
        except BaseException:
            forget_bound_plans(self.connection)
            self.connection.exec_driver_sql("ROLLBACK TO SAVEPOINT harness_request")
            self.connection.exec_driver_sql("RELEASE SAVEPOINT harness_request")
            raise
        else:
            self.connection.exec_driver_sql("RELEASE SAVEPOINT harness_request")

    def _deferrable_constraints(self) -> str:
        names = (
            self.connection.execute(
                text(
                    "SELECT format('%I.%I', n.nspname, c.conname) FROM pg_catalog.pg_constraint c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = c.connamespace "
                    "WHERE c.condeferrable "
                    "AND c.conname <> 'idempotent_requests_campaign_id_fkey' "
                    "ORDER BY 1"
                )
            )
            .scalars()
            .all()
        )
        return ", ".join(names)

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
