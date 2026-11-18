# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 E4: the four reference-corpus routes in their request transaction, judged by a final check (design 6).

Ingest, grant, revoke and query run on the request connection after the dependency's early check; the final
authorization statement (`WITH clock AS MATERIALIZED (SELECT clock_timestamp() ...)`) is the last statement before
COMMIT, and the response is built before it and returned only after the commit. Real routes, the real guard, a pool
engine, the established `NthGate` / `Recorder` / `race` machinery.

Where an authority change can be committed (lock order, observed): a role revoke, a role expiry and a membership end
cannot COMMIT while the request holds the campaign row `KEY SHARE`, which grant and query take from their first
campaign-referencing INSERT. So for those two routes a lapse is committed BEFORE that INSERT (or the one-way wait is
tested directly); every other change, and every change for ingest and revoke (which take no campaign lock), is
committed at the final statement.
"""

import re
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Engine, text

from tests.database.test_api_ai_and_corpus import (  # noqa: F401 - fixtures by name
    Fixture,
    _register_source_body,
    f,
)
from tests.database.test_r01_s2_profile_routes import Recorder, idle_in_transaction
from tests.database.test_r01_s3_authoring_routes import code, error_of
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixtures by name
    NthGate,
    Pool,
    assert_clean,
    client_for,
    pool,
    race,
    rows,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
)
from tests.http_race_support import run_in_thread
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

FINAL_STATEMENT = r"^WITH clock AS MATERIALIZED \(SELECT clock_timestamp\(\) AS t_auth\)"
GRANT_INSERT = r"^INSERT INTO ai\.reference_source_campaigns"
RETRIEVAL_INSERT = r"^INSERT INTO ai\.reference_retrievals"
INDEXING_READ = r"^SELECT allow_indexing FROM core\.source_documents"


# --- the scene --------------------------------------------------------------------------------------------------------


@dataclass
class Scene:
    f: Fixture
    pool: Pool
    engine: Engine  # the test's own engine (never the request pool)
    token: str  # a word only this scene's passages contain


@pytest.fixture
def sc(f: Fixture, pool: Pool, postgres_engine: Engine) -> Scene:
    token = "zq" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:12])
    return Scene(f, pool, postgres_engine, token)


def call(
    sc: Scene,
    method: str,
    path: str,
    *,
    user: uuid.UUID | None = None,
    campaign: uuid.UUID | None = None,
    **kw: Any,
) -> Any:
    with client_for(sc.pool, user or sc.f.gm_user_id) as client:
        return client.request(
            method, f"/campaigns/{campaign or sc.f.campaign_id}/reference-corpus{path}", **kw
        )


def register(sc: Scene, *, visibility: str = "general", allow_indexing: bool = True) -> uuid.UUID:
    body = {
        **_register_source_body(sc.f),
        "visibility": visibility,
        "allow_indexing": allow_indexing,
    }
    response = call(sc, "POST", "/sources", json=body)
    assert code(response) == 201, response.text
    return uuid.UUID(response.json()["source_document_id"])


def ingest(sc: Scene, source: uuid.UUID, order: int = 1, **kw: Any) -> Any:
    passage = {"passage_order": order, "content": f"{sc.token} grappling uses an unarmed strike"}
    return call(sc, "POST", f"/sources/{source}/passages", json={"passages": [passage]}, **kw)


def grant(sc: Scene, source: uuid.UUID, **kw: Any) -> Any:
    return call(sc, "POST", f"/sources/{source}/grant", json={}, **kw)


def revoke(sc: Scene, grant_id: uuid.UUID | str, **kw: Any) -> Any:
    return call(sc, "DELETE", f"/grants/{grant_id}", **kw)


def query(sc: Scene, **kw: Any) -> Any:
    return call(sc, "POST", "/query", json={"query_text": sc.token}, **kw)


def granted(sc: Scene, source: uuid.UUID) -> uuid.UUID:
    response = grant(sc, source)
    assert code(response) == 201, response.text
    return uuid.UUID(response.json()["reference_source_campaign_id"])


def durable(sc: Scene, source: uuid.UUID | None = None) -> dict[str, Any]:
    """Everything the four routes can persist for this scene's campaign (and one source's passages)."""
    return rows(
        sc.engine,
        """
        SELECT (SELECT count(*) FROM ai.reference_passages WHERE source_document_id = :s) AS passages,
               (SELECT count(*) FROM ai.reference_source_campaigns WHERE campaign_id = :c) AS grants,
               (SELECT count(*) FROM ai.reference_source_campaigns
                 WHERE campaign_id = :c AND revoked_at IS NULL) AS active_grants,
               (SELECT count(*) FROM ai.reference_retrievals WHERE campaign_id = :c) AS retrievals,
               (SELECT count(*) FROM ai.reference_retrieval_results r
                  JOIN ai.reference_retrievals t USING (reference_retrieval_id)
                 WHERE t.campaign_id = :c) AS results
        """,
        s=source,
        c=sc.f.campaign_id,
    )[0]


def advisory_free(sc: Scene) -> None:
    assert idle_in_transaction(sc.pool.engine) == 0
    assert sc.pool.engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def gated(
    sc: Scene,
    run: Callable[[], Any],
    during: Callable[[], None],
    *,
    pattern: str = FINAL_STATEMENT,
    nth: int = 1,
) -> Any:
    """Run `run`, stop it at the `nth` statement matching `pattern` (the final statement by default: after every earlier
    statement of its transaction); `during` commits from outside; release; return the response."""
    with NthGate(sc.pool.engine, pattern, nth) as gate:
        request = gate.track(run_in_thread("request", run))
        gate.wait_reached()
        assert gate.matched is not None and re.search(pattern, gate.matched)
        during()
        gate.release()
        assert request.done.wait(30.0)
    assert request.error is None, request.error
    return request.result


def blocked_by(sc: Scene, pid: int, *, timeout: float = 15.0) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = rows(
            sc.engine,
            "SELECT pid, wait_event_type, left(query, 70) AS query FROM pg_stat_activity "
            "WHERE datname = current_database() AND :p = ANY(pg_blocking_pids(pid))",
            p=pid,
        )
        if found:
            return found
        time.sleep(0.05)
    return []


# --- authority changes on the GM (committed from outside the request) -------------------------------------------------


def _exec(sc: Scene, sql: str, **params: Any) -> None:
    with sc.engine.begin() as c:
        c.execute(text(sql), params)


def _membership(sc: Scene) -> uuid.UUID:
    return rows(
        sc.engine,
        "SELECT campaign_membership_id AS m FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=sc.f.campaign_id,
        u=sc.f.gm_user_id,
    )[0]["m"]


def _gm_role(sc: Scene) -> uuid.UUID:
    return rows(
        sc.engine,
        "SELECT role_id AS r FROM security.membership_roles WHERE campaign_membership_id = :m",
        m=_membership(sc),
    )[0]["r"]


def revoke_role(sc: Scene, _cap: str) -> None:
    _exec(
        sc,
        "UPDATE security.membership_roles SET revoked_at = now() WHERE campaign_membership_id = :m",
        m=_membership(sc),
    )


def restore_role(sc: Scene, _cap: str) -> None:
    _exec(
        sc,
        "UPDATE security.membership_roles SET revoked_at = NULL, expires_at = NULL WHERE campaign_membership_id = :m",
        m=_membership(sc),
    )


def expire_role(sc: Scene, _cap: str) -> None:
    _exec(
        sc,
        "UPDATE security.membership_roles SET expires_at = now() WHERE campaign_membership_id = :m",
        m=_membership(sc),
    )


def remove_capability(sc: Scene, cap: str) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "DELETE FROM security.role_capabilities WHERE role_id = :r AND capability_id = :k"
            ),
            {
                "r": _gm_role(sc),
                "k": lookup_id(c, "security", "capabilities", "capability_id", cap),
            },
        )


def restore_capability(sc: Scene, cap: str) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO security.role_capabilities (role_id, capability_id) VALUES (:r, :k) ON CONFLICT DO NOTHING"
            ),
            {
                "r": _gm_role(sc),
                "k": lookup_id(c, "security", "capabilities", "capability_id", cap),
            },
        )


def end_membership(sc: Scene, _cap: str) -> None:
    _exec(
        sc,
        "UPDATE security.campaign_memberships SET ended_at = now() WHERE campaign_membership_id = :m",
        m=_membership(sc),
    )


def restore_membership(sc: Scene, _cap: str) -> None:
    _exec(
        sc,
        "UPDATE security.campaign_memberships SET ended_at = NULL WHERE campaign_membership_id = :m",
        m=_membership(sc),
    )


def _lifecycle(sc: Scene, status: str) -> None:
    _exec(
        sc,
        "UPDATE campaign.campaigns SET lifecycle_status_id = "
        "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :s) WHERE campaign_id = :c",
        s=status,
        c=sc.f.campaign_id,
    )


def archive_campaign(sc: Scene, _cap: str) -> None:
    _lifecycle(sc, "archived")


def unarchive_campaign(sc: Scene, _cap: str) -> None:
    _lifecycle(sc, "pending")


def _account(sc: Scene, status: str) -> None:
    _exec(
        sc,
        "UPDATE security.users SET lifecycle_status_id = "
        "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :s) WHERE user_id = :u",
        s=status,
        u=sc.f.gm_user_id,
    )


def deactivate_account(sc: Scene, _cap: str) -> None:
    _account(sc, "inactive")


def reactivate_account(sc: Scene, _cap: str) -> None:
    _account(sc, "active")


# change -> (apply, undo, status the route refuses with, whether its COMMIT waits for a transaction holding the campaign)
CHANGES: dict[str, tuple[Callable[[Scene, str], None], Callable[[Scene, str], None], int, bool]] = {
    "role_revoked": (revoke_role, restore_role, 403, True),
    "capability_removed_from_the_role": (remove_capability, restore_capability, 403, False),
    "role_expired": (expire_role, restore_role, 403, True),
    "membership_ended": (end_membership, restore_membership, 404, True),
    "campaign_archived": (archive_campaign, unarchive_campaign, 404, False),
    "account_deactivated": (deactivate_account, reactivate_account, 404, False),
}


# --- the four routes as one table ----------------------------------------------------------------------------------------


class Route:
    """`prepare` builds what the route needs, `run` is one request, `durable` reads what it can persist, `effect` is what a
    success must have written."""

    name: str
    capability: str
    first_write: (
        str | None
    )  # the first statement that references the campaign row (a `KEY SHARE`), if any

    def prepare(self, sc: Scene) -> None: ...
    def run(self, sc: Scene) -> Any: ...
    def snapshot(self, sc: Scene) -> dict[str, Any]: ...
    def succeeded(self, sc: Scene, before: dict[str, Any], response: Any) -> None: ...


class IngestRoute(Route):
    name, capability, first_write = "ingest", "rules_source.manage", None

    def prepare(self, sc: Scene) -> None:
        self.source = register(sc)

    def run(self, sc: Scene) -> Any:
        return ingest(sc, self.source)

    def snapshot(self, sc: Scene) -> dict[str, Any]:
        return durable(sc, self.source)

    def succeeded(self, sc: Scene, before: dict[str, Any], response: Any) -> None:
        assert code(response) == 201 and len(response.json()["reference_passage_ids"]) == 1, (
            response.text
        )
        assert self.snapshot(sc)["passages"] == before["passages"] + 1


class GrantRoute(Route):
    name, capability, first_write = "grant", "rules_source.manage", GRANT_INSERT

    def prepare(self, sc: Scene) -> None:
        self.source = register(sc, visibility="campaign_restricted")

    def run(self, sc: Scene) -> Any:
        return grant(sc, self.source)

    def snapshot(self, sc: Scene) -> dict[str, Any]:
        return durable(sc, self.source)

    def succeeded(self, sc: Scene, before: dict[str, Any], response: Any) -> None:
        assert code(response) == 201, response.text
        assert self.snapshot(sc)["active_grants"] == before["active_grants"] + 1


class RevokeRoute(Route):
    name, capability, first_write = "revoke", "rules_source.manage", None

    def prepare(self, sc: Scene) -> None:
        self.source = register(sc, visibility="campaign_restricted")
        self.grant = granted(sc, self.source)

    def run(self, sc: Scene) -> Any:
        return revoke(sc, self.grant)

    def snapshot(self, sc: Scene) -> dict[str, Any]:
        return durable(sc, self.source)

    def succeeded(self, sc: Scene, before: dict[str, Any], response: Any) -> None:
        assert code(response) == 204, response.text
        assert self.snapshot(sc)["active_grants"] == before["active_grants"] - 1


class QueryRoute(Route):
    name, capability, first_write = "query", "campaign.view", RETRIEVAL_INSERT

    def prepare(self, sc: Scene) -> None:
        self.source = register(sc)
        assert code(ingest(sc, self.source)) == 201

    def run(self, sc: Scene) -> Any:
        return query(sc)

    def snapshot(self, sc: Scene) -> dict[str, Any]:
        return durable(sc, self.source)

    def succeeded(self, sc: Scene, before: dict[str, Any], response: Any) -> None:
        assert code(response) == 200, response.text
        [passage] = response.json()["passages"]
        assert sc.token in passage["content"]
        after = self.snapshot(sc)
        assert (
            after["retrievals"] == before["retrievals"] + 1
            and after["results"] == before["results"] + 1
        )


ROUTES: dict[str, type[Route]] = {
    r.name: r for r in (IngestRoute, GrantRoute, RevokeRoute, QueryRoute)
}


def _cap(route: Route) -> str:
    return route.capability


# =====================================================================================================================
# Authorized execution
# =====================================================================================================================


@pytest.mark.parametrize("name", sorted(ROUTES))
def test_an_authorized_request_writes_once_with_one_final_statement_and_leaves_nothing_open(
    name: str, sc: Scene
) -> None:
    route = ROUTES[name]()
    route.prepare(sc)
    before = route.snapshot(sc)
    with Recorder(sc.pool.engine) as recorder:
        response = route.run(sc)
    route.succeeded(sc, before, response)
    final = re.compile(FINAL_STATEMENT)
    hits = [i for i, s in enumerate(recorder.events) if final.search(s)]
    assert (
        len(hits) == 1
    )  # the dependency's early check judges at now(), so the final statement is the only match
    tail = [s for s in recorder.events[hits[0] + 1 :] if not re.match(r"^(COMMIT|ROLLBACK)", s)]
    assert tail == [], tail  # nothing follows the final statement but the commit
    assert not any(
        re.search(r"\bFOR (UPDATE|SHARE|NO KEY UPDATE|KEY SHARE)\b", s) for s in recorder.events
    )
    advisory_free(sc)


def test_query_returns_the_same_response_contract_and_logs_what_it_returned(sc: Scene) -> None:
    route = QueryRoute()
    route.prepare(sc)
    response = route.run(sc)
    [passage] = response.json()["passages"]
    assert set(passage) == {
        "reference_passage_id",
        "source_document_id",
        "source_title",
        "chapter",
        "section",
        "page_label",
        "heading",
        "content",
        "is_house_rule",
        "rank",
        "relevance_score",
    }
    logged = rows(
        sc.engine,
        "SELECT r.reference_passage_id, r.rank, t.requested_by_user_id, t.query_text "
        "FROM ai.reference_retrieval_results r JOIN ai.reference_retrievals t USING (reference_retrieval_id) "
        "WHERE t.campaign_id = :c",
        c=sc.f.campaign_id,
    )
    assert [(str(r["reference_passage_id"]), r["rank"]) for r in logged] == [
        (passage["reference_passage_id"], passage["rank"])
    ]
    assert (
        logged[0]["requested_by_user_id"] == sc.f.gm_user_id and logged[0]["query_text"] == sc.token
    )


# =====================================================================================================================
# Refusal: nothing durable remains, nothing is disclosed, a retry succeeds
# =====================================================================================================================

# For grant and query a change that waits for the campaign `KEY SHARE` is committed BEFORE the first campaign INSERT; every
# other case is committed at the final statement.
REFUSAL_CASES = [
    (route, change, at)
    for route in sorted(ROUTES)
    for change in sorted(CHANGES)
    for at in (("first_write", "final") if ROUTES[route].first_write else ("final",))
    if not (at == "final" and CHANGES[change][3] and ROUTES[route].first_write)
]


@pytest.mark.parametrize(("name", "change", "at"), REFUSAL_CASES)
def test_a_lapse_before_the_final_check_refuses_rolls_everything_back_and_a_retry_succeeds(
    name: str, change: str, at: str, sc: Scene
) -> None:
    apply, undo, refused, _waits = CHANGES[change]
    route = ROUTES[name]()
    route.prepare(sc)
    before = route.snapshot(sc)
    pattern = route.first_write if at == "first_write" else FINAL_STATEMENT
    assert pattern is not None
    response = gated(sc, lambda: route.run(sc), lambda: apply(sc, _cap(route)), pattern=pattern)
    assert code(response) == refused, response.text
    assert route.snapshot(sc) == before  # every write rolled back together
    if name == "query":  # nothing is disclosed
        assert sc.token not in response.text and "reference_passage_id" not in response.text
        assert "passages" not in response.text
    advisory_free(sc)
    undo(sc, _cap(route))
    again = route.run(sc)
    route.succeeded(
        sc, before, again
    )  # the retry commits normally (no orphaned unique slot, no log)


@pytest.mark.parametrize("name", sorted(ROUTES))
@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_change_committed_before_the_request_is_refused_by_the_early_check_and_writes_nothing(
    name: str, change: str, sc: Scene
) -> None:
    apply, undo, refused, _waits = CHANGES[change]
    route = ROUTES[name]()
    route.prepare(sc)
    before = route.snapshot(sc)
    apply(sc, _cap(route))
    response = route.run(sc)
    assert code(response) == refused, (
        response.text
    )  # the dependency's own code and precedence, unchanged
    assert route.snapshot(sc) == before
    undo(sc, _cap(route))


# --- error precedence (R-D2): a domain refusal before the final check wins over a lapse ---------------------------------


def test_a_duplicate_grant_is_a_409_even_when_the_role_lapses_before_the_insert(sc: Scene) -> None:
    source = register(sc, visibility="campaign_restricted")
    granted(sc, source)
    # the lapse must commit BEFORE the grant INSERT, which then fails on the unique index: the final check never runs
    response = gated(
        sc, lambda: grant(sc, source), lambda: revoke_role(sc, ""), pattern=GRANT_INSERT
    )
    assert (code(response), error_of(response)) == (409, "conflict"), response.text
    restore_role(sc, "")


def test_an_unknown_source_is_a_404_from_the_command_even_when_the_capability_lapses(
    sc: Scene,
) -> None:
    response = gated(
        sc,
        lambda: ingest(sc, uuid.uuid4()),
        lambda: remove_capability(sc, "rules_source.manage"),
        pattern=INDEXING_READ,
    )
    assert (code(response), error_of(response)) == (404, "not_found"), response.text
    restore_capability(sc, "rules_source.manage")


def test_a_not_indexable_source_is_a_400_even_when_the_capability_lapses(sc: Scene) -> None:
    source = register(sc, allow_indexing=False)
    response = gated(
        sc,
        lambda: ingest(sc, source),
        lambda: remove_capability(sc, "rules_source.manage"),
        pattern=INDEXING_READ,
    )
    assert (code(response), error_of(response)) == (400, "source_not_indexable"), response.text
    assert durable(sc, source)["passages"] == 0
    restore_capability(sc, "rules_source.manage")


# =====================================================================================================================
# Query: which sources are returned (D3)
# =====================================================================================================================


def test_query_returns_general_and_granted_sources_and_excludes_the_rest(sc: Scene) -> None:
    general = register(sc)
    restricted_granted = register(sc, visibility="campaign_restricted")
    restricted_unrelated = register(sc, visibility="campaign_restricted")
    removed = register(sc)
    for order, source in enumerate(
        (general, restricted_granted, restricted_unrelated, removed), start=1
    ):
        assert code(ingest(sc, source, order)) == 201
    granted(sc, restricted_granted)
    assert code(call(sc, "DELETE", f"/sources/{removed}")) == 204
    sources = {p["source_document_id"] for p in query(sc).json()["passages"]}
    assert sources == {str(general), str(restricted_granted)}


def test_a_source_of_another_ruleset_is_never_returned(sc: Scene) -> None:
    from tests.factories import make_ruleset_version_for_world

    source = register(sc)
    assert code(ingest(sc, source)) == 201
    with sc.engine.begin() as c:
        other = make_ruleset_version_for_world(c, sc.f.world_id)
        c.execute(
            text(
                "UPDATE core.source_documents SET ruleset_version_id = :r WHERE source_document_id = :s"
            ),
            {"r": other, "s": source},
        )
    assert query(sc).json()["passages"] == []


def test_a_grant_revoked_after_retrieval_still_returns_the_retrieved_passages_and_the_log_matches(
    sc: Scene,
) -> None:
    """D3: the retrieval statement decides each source. A revoke that commits after it serializes after the query: the
    query is not refused, returns what it retrieved, its committed log equals the response, and the next query excludes it."""
    source = register(sc, visibility="campaign_restricted")
    assert code(ingest(sc, source)) == 201
    grant_id = granted(sc, source)

    def revoke_now() -> None:
        _exec(
            sc,
            "UPDATE ai.reference_source_campaigns SET revoked_at = now() WHERE reference_source_campaign_id = :g",
            g=grant_id,
        )

    started = time.monotonic()
    response = gated(sc, lambda: query(sc), revoke_now)
    assert time.monotonic() - started < 25.0  # the revoke never waited for the query
    assert code(response) == 200, response.text
    [passage] = response.json()["passages"]
    assert passage["source_document_id"] == str(source)
    logged = rows(
        sc.engine,
        "SELECT r.reference_passage_id FROM ai.reference_retrieval_results r "
        "JOIN ai.reference_retrievals t USING (reference_retrieval_id) WHERE t.campaign_id = :c",
        c=sc.f.campaign_id,
    )
    assert [str(r["reference_passage_id"]) for r in logged] == [passage["reference_passage_id"]]
    assert query(sc).json()["passages"] == []  # the next query excludes the source
    assert durable(sc, source)["retrievals"] == 2  # the empty one is logged too


def test_a_source_removed_after_retrieval_is_returned_once_and_excluded_next(sc: Scene) -> None:
    source = register(sc)
    assert code(ingest(sc, source)) == 201
    response = gated(
        sc,
        lambda: query(sc),
        lambda: _exec(
            sc,
            "UPDATE core.source_documents SET status = 'removed', removed_at = now() WHERE source_document_id = :s",
            s=source,
        ),
    )
    assert code(response) == 200 and len(response.json()["passages"]) == 1
    assert query(sc).json()["passages"] == []


def test_a_grant_created_after_retrieval_is_absent_now_and_present_next(sc: Scene) -> None:
    source = register(sc, visibility="campaign_restricted")
    assert code(ingest(sc, source)) == 201
    response = gated(sc, lambda: query(sc), lambda: granted(sc, source))
    assert code(response) == 200 and response.json()["passages"] == []
    assert len(query(sc).json()["passages"]) == 1


def test_a_final_refusal_withholds_the_whole_response_even_when_sources_were_retrieved(
    sc: Scene,
) -> None:
    """The retrieved passage is real and eligible; the final check refuses on the route authority and the response, the
    log and every result row are discarded together."""
    source = register(sc)
    assert code(ingest(sc, source)) == 201
    before = durable(sc, source)
    response = gated(sc, lambda: query(sc), lambda: remove_capability(sc, "campaign.view"))
    assert code(response) == 403
    assert sc.token not in response.text and str(source) not in response.text
    assert durable(sc, source) == before
    restore_capability(sc, "campaign.view")


# =====================================================================================================================
# Revoke: the route's campaign binding (D2)
# =====================================================================================================================


@dataclass
class Other:
    campaign: uuid.UUID
    manager: uuid.UUID


@pytest.fixture
def other(sc: Scene) -> Iterator[Other]:
    """A second campaign on the same world and ruleset whose own manager holds the corpus capabilities THERE only."""
    with sc.engine.begin() as c:
        timeline = make_timeline(c, sc.f.world_id, is_primary=False)
        campaign = make_campaign(
            c, timeline, ruleset_version_id=sc.f.ruleset_version_id, lifecycle_status_code="pending"
        )
        manager = make_user(c, "E4 Other Manager")
        membership = make_campaign_membership(c, campaign, manager)
        role = make_role(c, campaign_id=campaign, code=f"e4o_{uuid.uuid4().hex[:8]}")
        for cap in ("rules_source.manage", "campaign.view"):
            make_role_capability(
                c, role, lookup_id(c, "security", "capabilities", "capability_id", cap)
            )
        make_membership_role(c, membership, role)
    yield Other(campaign, manager)
    with sc.engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        for sql in (
            "DELETE FROM ai.reference_retrievals WHERE campaign_id = :c",
            "DELETE FROM ai.reference_source_campaigns WHERE campaign_id = :c",
            "DELETE FROM security.membership_roles WHERE role_id IN (SELECT role_id FROM security.roles WHERE campaign_id = :c)",
            "DELETE FROM security.role_capabilities WHERE role_id IN (SELECT role_id FROM security.roles WHERE campaign_id = :c)",
            "DELETE FROM security.roles WHERE campaign_id = :c",
            "DELETE FROM security.campaign_memberships WHERE campaign_id = :c",
            "DELETE FROM campaign.campaigns WHERE campaign_id = :c",
        ):
            c.execute(text(sql), {"c": campaign})


def grant_row(sc: Scene, grant_id: uuid.UUID | str) -> dict[str, Any]:
    return rows(
        sc.engine,
        "SELECT campaign_id, revoked_at FROM ai.reference_source_campaigns WHERE reference_source_campaign_id = :g",
        g=grant_id,
    )[0]


def test_another_campaigns_manager_cannot_revoke_this_campaigns_grant(
    sc: Scene, other: Other
) -> None:
    source = register(sc, visibility="campaign_restricted")
    grant_id = granted(sc, source)
    foreign = revoke(sc, grant_id, user=other.manager, campaign=other.campaign)
    assert code(foreign) == 204 and foreign.content == b""  # exactly an unknown id's answer
    assert grant_row(sc, grant_id)["revoked_at"] is None  # and no write
    unknown = revoke(sc, uuid.uuid4(), user=other.manager, campaign=other.campaign)
    assert (code(unknown), unknown.content) == (204, b"")
    assert (code(foreign), foreign.headers.get("content-type")) == (
        code(unknown),
        unknown.headers.get("content-type"),
    )


def test_this_campaigns_manager_still_revokes_an_eligible_grant_and_a_repeat_is_a_no_op(
    sc: Scene,
) -> None:
    source = register(sc, visibility="campaign_restricted")
    grant_id = granted(sc, source)
    assert code(revoke(sc, grant_id)) == 204
    first = grant_row(sc, grant_id)["revoked_at"]
    assert first is not None
    assert code(revoke(sc, grant_id)) == 204
    assert grant_row(sc, grant_id)["revoked_at"] == first  # the second revoke wrote nothing
    assert code(grant(sc, source)) == 201  # the slot is free again
    assert code(revoke(sc, uuid.uuid4())) == 204  # an unknown id is still 204


# =====================================================================================================================
# Lock order (observed)
# =====================================================================================================================


@pytest.mark.parametrize("name", ["grant", "query"])
@pytest.mark.parametrize("change", [c for c in sorted(CHANGES) if CHANGES[c][3]])
def test_a_role_or_membership_change_arriving_during_the_request_commits_after_it(
    name: str, change: str, sc: Scene
) -> None:
    """Observed: while grant or query is past its first campaign INSERT (holding the campaign `KEY SHARE`), the deferred
    access-manager triggers make the change's COMMIT queue behind it. The request judges authority before the change is
    visible and succeeds; the change then commits and the next request is refused. One way, no deadlock."""
    apply, undo, refused, _ = CHANGES[change]
    route = ROUTES[name]()
    route.prepare(sc)
    before = route.snapshot(sc)
    with NthGate(sc.pool.engine, FINAL_STATEMENT, 1) as gate:
        request = gate.track(run_in_thread("request", lambda: route.run(sc)))
        gate.wait_reached()
        changer = run_in_thread("change", lambda: apply(sc, _cap(route)))
        waiting = blocked_by(sc, gate.pid)
        assert waiting, "the change never queued behind the request"
        assert not changer.done.is_set()
        gate.release()
        assert request.done.wait(30.0) and changer.done.wait(30.0)
    route.succeeded(sc, before, request.result)  # ordered before the change
    later = route.run(sc)
    assert code(later) == refused, later.text  # the change committed afterwards and now applies
    advisory_free(sc)
    undo(sc, _cap(route))


@pytest.mark.parametrize("name", ["ingest", "revoke"])
@pytest.mark.parametrize("change", [c for c in sorted(CHANGES) if CHANGES[c][3]])
def test_ingest_and_revoke_hold_no_campaign_lock_so_no_change_waits_for_them(
    name: str, change: str, sc: Scene
) -> None:
    apply, undo, refused, _ = CHANGES[change]
    route = ROUTES[name]()
    route.prepare(sc)
    before = route.snapshot(sc)
    with NthGate(sc.pool.engine, FINAL_STATEMENT, 1) as gate:
        request = gate.track(run_in_thread("request", lambda: route.run(sc)))
        gate.wait_reached()
        started = time.monotonic()
        apply(sc, _cap(route))  # would block here if the request held a lock the change needs
        assert time.monotonic() - started < 5.0
        gate.release()
        assert request.done.wait(30.0)
    assert code(request.result) == refused  # the final check sees the change
    assert route.snapshot(sc) == before
    undo(sc, _cap(route))


@pytest.mark.parametrize("name", ["grant", "query"])
@pytest.mark.parametrize(
    "change", ["capability_removed_from_the_role", "account_deactivated", "campaign_archived"]
)
def test_a_change_that_takes_no_campaign_lock_commits_at_once_while_the_request_is_parked(
    name: str, change: str, sc: Scene
) -> None:
    """The control: a role-capability removal, an account deactivation and a plain lifecycle UPDATE do not queue behind the
    request, and its final check then refuses."""
    apply, undo, refused, _ = CHANGES[change]
    route = ROUTES[name]()
    route.prepare(sc)
    before = route.snapshot(sc)
    with NthGate(sc.pool.engine, route.first_write or FINAL_STATEMENT, 1) as gate:
        request = gate.track(run_in_thread("request", lambda: route.run(sc)))
        gate.wait_reached()
        started = time.monotonic()
        apply(sc, _cap(route))
        assert time.monotonic() - started < 5.0
        gate.release()
        assert request.done.wait(30.0)
    assert code(request.result) == refused
    assert route.snapshot(sc) == before
    undo(sc, _cap(route))


def test_the_real_campaign_archive_route_waits_for_a_grant_that_holds_the_campaign_key_share(
    sc: Scene,
) -> None:
    """V-E4-1, observed: `POST /campaigns/{id}/archive` takes the campaign row `FOR UPDATE`, which conflicts with the
    `KEY SHARE` a grant holds from its first campaign INSERT. The archive queues behind the grant, the grant (judged before
    the archive is visible) succeeds, the archive then commits, and the next grant is refused 404."""
    managers = make_managers(sc.engine, sc.f.campaign_id, label="E4 Archive")
    _lifecycle(sc, "active")  # an active campaign now retains its access manager
    source = register(sc, visibility="campaign_restricted")
    spare = register(
        sc, visibility="campaign_restricted"
    )  # registered while the campaign is still active
    version = rows(
        sc.engine,
        "SELECT row_version AS v FROM campaign.campaigns WHERE campaign_id = :c",
        c=sc.f.campaign_id,
    )[0]["v"]

    def archive() -> Any:
        with client_for(sc.pool, managers.manager_user) as client:
            return client.post(
                f"/campaigns/{sc.f.campaign_id}/archive",
                json={"expected_row_version": version, "reason": None},
            )

    with NthGate(sc.pool.engine, FINAL_STATEMENT, 1) as gate:
        request = gate.track(run_in_thread("grant", lambda: grant(sc, source)))
        gate.wait_reached()
        archiver = run_in_thread("archive", archive)
        waiting = blocked_by(sc, gate.pid)
        assert waiting, "the archive route never queued behind the grant"
        assert not archiver.done.is_set()
        gate.release()
        assert request.done.wait(30.0) and archiver.done.wait(30.0)
    assert code(request.result) == 201, request.result.text
    assert code(archiver.result) == 200, archiver.result.text
    later = grant(sc, spare)
    assert code(later) == 404, later.text


def no_cycle(o: Any) -> None:
    """No deadlock: the counter did not move and the only driver exception is the expected unique violation (a 409)."""
    assert o.deadlock_delta == 0, o.summary()
    assert all(sqlstate == "23505" for sqlstate, _ in o.failures), (
        f"driver exceptions: {o.summary()}"
    )


def test_grants_and_a_conflicting_revoke_serialize_in_both_arrivals_without_a_cycle(
    sc: Scene,
) -> None:
    source = register(sc, visibility="campaign_restricted")
    first = granted(sc, source)
    # a grant of the already-active pair, parked at its INSERT, against the revoke of the conflicting row
    o = race(
        sc,
        sc.pool,
        gate_pattern=GRANT_INSERT,
        parked=lambda: grant(sc, source),
        second=lambda: revoke(sc, first),
    )
    no_cycle(o)
    assert o.status("parked")[0] in (201, 409) and o.status("second")[0] == 204, o.summary()
    assert grant_row(sc, first)["revoked_at"] is not None
    # the other order: the revoke parked at its UPDATE, the grant arrives
    second_source = register(sc, visibility="campaign_restricted")
    held = granted(sc, second_source)
    o2 = race(
        sc,
        sc.pool,
        gate_pattern=r"^UPDATE ai\.reference_source_campaigns",
        parked=lambda: revoke(sc, held),
        second=lambda: grant(sc, second_source),
    )
    no_cycle(o2)
    assert o2.status("parked")[0] == 204 and o2.status("second")[0] in (201, 409), o2.summary()


def test_two_grants_of_one_pair_give_one_201_and_one_409_and_two_revokes_both_204(
    sc: Scene,
) -> None:
    source = register(sc, visibility="campaign_restricted")
    o = race(
        sc,
        sc.pool,
        gate_pattern=GRANT_INSERT,
        parked=lambda: grant(sc, source),
        second=lambda: grant(sc, source),
    )
    no_cycle(o)
    assert sorted(o.status(n)[0] for n in ("parked", "second")) == [201, 409], o.summary()
    [active] = rows(
        sc.engine,
        "SELECT reference_source_campaign_id AS g FROM ai.reference_source_campaigns WHERE source_document_id = :s AND revoked_at IS NULL",
        s=source,
    )
    r = race(
        sc,
        sc.pool,
        gate_pattern=r"^UPDATE ai\.reference_source_campaigns",
        parked=lambda: revoke(sc, active["g"]),
        second=lambda: revoke(sc, active["g"]),
    )
    no_cycle(r)
    assert [r.status(n)[0] for n in ("parked", "second")] == [204, 204], r.summary()
    assert durable(sc, source)["active_grants"] == 0


def test_ingest_and_the_removal_of_its_source_do_not_wait_for_each_other(sc: Scene) -> None:
    source = register(sc)
    with NthGate(sc.pool.engine, FINAL_STATEMENT, 1) as gate:
        request = gate.track(run_in_thread("ingest", lambda: ingest(sc, source)))
        gate.wait_reached()
        started = time.monotonic()
        removed = call(
            sc, "DELETE", f"/sources/{source}"
        )  # the S4b-5 route, a non-key UPDATE of the source
        assert time.monotonic() - started < 10.0
        gate.release()
        assert request.done.wait(30.0)
    assert code(removed) == 204 and code(request.result) == 201
    assert query(sc).json()["passages"] == []  # the removed source stays unretrievable


# =====================================================================================================================
# Account lifecycle (D4) across the four routes
# =====================================================================================================================


@pytest.mark.parametrize("name", sorted(ROUTES))
def test_an_account_deactivated_after_authentication_is_refused_with_the_approved_404(
    name: str, sc: Scene
) -> None:
    route = ROUTES[name]()
    route.prepare(sc)
    before = route.snapshot(sc)
    response = gated(sc, lambda: route.run(sc), lambda: deactivate_account(sc, ""))
    assert code(response) == 404, response.text
    assert route.snapshot(sc) == before
    reactivate_account(sc, "")


# =====================================================================================================================
# Characterization: today's behaviour of the OPEN findings, pinned as evidence (NOT endorsed; E4-D5 / E4-D6)
# =====================================================================================================================


def test_f_e4_2_another_campaigns_manager_can_ingest_into_and_self_grant_a_restricted_source(
    sc: Scene, other: Other
) -> None:
    """OPEN: no source ownership. A `rules_source.manage` holder of another campaign on the same ruleset ingests into and
    grants themselves another campaign's restricted source, then retrieves it. Pinned until the ownership decision."""
    source = register(sc, visibility="campaign_restricted")
    assert code(ingest(sc, source, user=other.manager, campaign=other.campaign)) == 201
    token_query = {"query_text": sc.token}
    with client_for(sc.pool, other.manager) as client:
        before = client.post(
            f"/campaigns/{other.campaign}/reference-corpus/query", json=token_query
        )
        assert before.json()["passages"] == []
        assert code(grant(sc, source, user=other.manager, campaign=other.campaign)) == 201
        after = client.post(f"/campaigns/{other.campaign}/reference-corpus/query", json=token_query)
    assert len(after.json()["passages"]) == 1


def test_f_e4_3_ingest_into_a_removed_source_succeeds(sc: Scene) -> None:
    """OPEN: ingest does not check the source's status."""
    source = register(sc)
    assert code(call(sc, "DELETE", f"/sources/{source}")) == 204
    assert code(ingest(sc, source)) == 201


def test_f_e4_4_an_unknown_source_or_a_wrong_ruleset_grant_answers_500(sc: Scene) -> None:
    """OPEN: the BEFORE trigger raises SQLSTATE 23000 (unclassified) ahead of the foreign key."""
    assert code(grant(sc, uuid.uuid4())) == 500
    from tests.factories import make_ruleset_version_for_world

    source = register(sc, visibility="campaign_restricted")
    with sc.engine.begin() as c:
        other_rules = make_ruleset_version_for_world(c, sc.f.world_id)
        c.execute(
            text(
                "UPDATE core.source_documents SET ruleset_version_id = :r WHERE source_document_id = :s"
            ),
            {"r": other_rules, "s": source},
        )
    assert code(grant(sc, source)) == 500
