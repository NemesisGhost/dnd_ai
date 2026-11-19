# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 E1: the proposal-review route in one request transaction, over real HTTP.

Historical local design `docs/R01_E1_REVIEW_ROUTE_DESIGN_2026-11-17.md` sections 3 to 8 (T-2 to T-9). The route is
`POST /campaigns/{campaign_id}/ai/proposed-changes/{ai_proposed_change_id}/review`: **unkeyed, ordinary post-write**.
It runs the review and everything it applies in the request-owned transaction, locks the reviewer's operation scope
(world, role rows, membership, account, campaign `FOR KEY SHARE`) before the proposal row and any downstream lock, and its
final authority statement is the last one before COMMIT.

Real routes of `create_app()` on a migrated database with the real commit guard:

- **Success and order (T-2).** Approve-reveal, approve-reveal (already known), approve-advance and reject: the scope's
  campaign `KEY SHARE` precedes the proposal lock, the final statement is last and takes no row lock, no statement
  follows it, nothing updates `narrative.events` (so no deferred trigger), no `audit.change_log` row is written.
- **Freshness (T-3).** A role that lapses between the last lock wait and the final statement refuses the review with the
  early refusal and persists nothing.
- **Precedence (T-4).** A role revoked before the request (403), a campaign that is not active (409), a decided
  proposal (409), a revalidation failure (400, nothing persisted).
- **Concurrent change (T-5).** A role revoke and a membership end requested while the review holds its scope wait for it.
- **Grant race, both arrivals (T-6; P-2).** The real resource-grant route (campaign `FOR UPDATE`, then the target entity
  `FOR UPDATE`) against approve-advance (quest entity) and approve-reveal (knowledge item entity): at the parent
  `a083daf` the arrival that parks the grant after its campaign lock, and the one that parks the review after its entity
  locks, each end in one 40P01; here both serialize.
- **Human advance race, both arrivals (T-7; P-1).** The real `POST .../quests/objectives/{id}/advance` against
  approve-advance on the same objective and party: at the parent one 40P01 per arrival; here exactly one status change
  commits and the other side gets its domain refusal.
- **Concurrent reviews (T-8) and rollback (T-9).**
"""

import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Engine, event, text

from dnd_ai.domain.ai_provider import FakeAiProvider
from tests.ai_e2_support import delete_campaign_security_rows, npc_turn
from tests.ai_review_support import delete_reviewer, make_gm_reviewer
from tests.database.test_ai_advance_objective_proposal import Fixture as AdvanceFixture
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures by name
    FINAL,
    FINAL_RE,
    ROW_LOCK_RE,
    Factory,
    Recorder,
    idle_in_transaction,
    pooled,
    pooled_factory,
    wait_lapsed,
)
from tests.database.test_r01_s3_authoring_routes import code, error_of
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixtures by name
    Pool,
    assert_clean,
    assert_waited_on_parked,
    pool,
    post,
    race,
    rows,
)
from tests.factories import (
    cleanup_committed_ai_world,
    make_agent,
    make_agent_assignment,
    make_knowledge_item,
)
from tests.http_race_support import StatementGate, run_in_thread

pytestmark = pytest.mark.database

# --- statement patterns ---------------------------------------------------------------------------------------------

WORLD_SHARE = r"^SELECT lifecycle_status_id FROM core\.worlds WHERE world_id = \S+ FOR SHARE$"
CAMPAIGN_KEY_SHARE = re.compile(r"FROM campaign\.campaigns\b.* FOR KEY SHARE")
PROPOSAL_LOCK = re.compile(
    r"^SELECT status, campaign_id, proposed_arguments FROM ai\.proposed_changes WHERE .* FOR UPDATE$"
)
REVIEW_INSERT = r"^INSERT INTO ai\.change_reviews"
APPLIED_UPDATE = r"^UPDATE ai\.proposed_changes SET status = 'applied'"
ADVISORY = r"pg_advisory_xact_lock"
EVENT_INSERT = r"^INSERT INTO narrative\.events"
HUMAN_OBJECTIVE_LOCK = r"^SELECT quest_objective_id FROM narrative\.quest_objectives WHERE quest_objective_id = \S+ FOR UPDATE$"
GRANT_TARGET_ENTITY = r"FROM core\.entities WHERE core\.entities\.entity_id = .* FOR UPDATE$"
GRANT_CAMPAIGN_UPDATE = (
    r"FROM campaign\.campaigns WHERE (campaign\.campaigns\.)?campaign_id = .* FOR UPDATE"
)
NOT_PENDING = (409, "proposed_change_not_pending")


# --- the scene: one committed campaign, a GM reviewer, an NPC proposal source --------------------------------------


@dataclass
class Scene:
    engine: Engine
    f: AdvanceFixture
    owner: uuid.UUID
    reviewer: uuid.UUID
    reviewer_membership: uuid.UUID
    reviewer_role: uuid.UUID
    secret_id: uuid.UUID

    @property
    def base(self) -> str:
        return f"/campaigns/{self.f.campaign_id}"

    @property
    def campaign_id(self) -> uuid.UUID:
        return self.f.campaign_id

    def review_path(self, proposal: uuid.UUID) -> str:
        return f"{self.base}/ai/proposed-changes/{proposal}/review"


@pytest.fixture
def sc(postgres_engine: Engine) -> Iterator[Scene]:
    with postgres_engine.begin() as connection:
        f = AdvanceFixture(connection, f"e1-{uuid.uuid4().hex[:8]}")
        f.agent_id = make_agent(connection)
        f.assignment_id = make_agent_assignment(connection, f.agent_id, f.campaign_id, f.npc_id)
        secret = make_knowledge_item(
            connection,
            f.world_id,
            statement="The innkeeper is secretly a retired adventurer.",
            subject_entity_id=f.npc_id,
        )
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_items SET sensitivity = 'secret' WHERE knowledge_item_id = :k"
            ),
            {"k": secret},
        )
        reviewer = make_gm_reviewer(connection, f.campaign_id, "E1 Reviewer")
        owner = connection.execute(
            text("""
                SELECT cm.user_id FROM security.campaign_memberships cm
                JOIN security.membership_roles mr ON mr.campaign_membership_id = cm.campaign_membership_id
                JOIN security.roles r ON r.role_id = mr.role_id
                WHERE cm.campaign_id = :c AND r.code = 'campaign_owner'
            """),
            {"c": f.campaign_id},
        ).scalar_one()
        membership, role = connection.execute(
            text("""
                SELECT cm.campaign_membership_id, mr.membership_role_id
                FROM security.campaign_memberships cm
                JOIN security.membership_roles mr ON mr.campaign_membership_id = cm.campaign_membership_id
                WHERE cm.campaign_id = :c AND cm.user_id = :u
            """),
            {"c": f.campaign_id, "u": reviewer},
        ).one()
    scene = Scene(postgres_engine, f, owner, reviewer, membership, role, secret)
    try:
        yield scene
    finally:
        with postgres_engine.begin() as cleanup:
            cleanup.execute(text("SET LOCAL statement_timeout = '30s'"))
            cleanup.execute(text("SET LOCAL session_replication_role = replica"))
            delete_campaign_security_rows(cleanup, f.campaign_id)
            cleanup_committed_ai_world(
                cleanup, world_id=f.world_id, campaign_id=f.campaign_id, agent_id=f.agent_id
            )
            delete_reviewer(cleanup, reviewer)


def new_proposal(sc: Scene, kind: str) -> uuid.UUID:
    """A pending `advance_quest_objective` or `reveal_knowledge` proposal, made by the NPC turn (E2, unchanged)."""
    provider = (
        FakeAiProvider(dialogue="Done.", advance_first_candidate=True)
        if kind == "advance"
        else FakeAiProvider(dialogue="Perhaps.", reveal_first_candidate=True)
    )
    result = npc_turn(
        sc.engine,
        user_id=sc.f.interactor_id,
        campaign_id=sc.f.campaign_id,
        agent_assignment_id=sc.f.assignment_id,
        requesting_character_id=sc.f.pc_id,
        requesting_party_id=sc.f.party_id,
        player_message="Hello",
        provider=provider,
        timeline_id=sc.f.timeline_id,
        expected_world_id=sc.f.world_id,
        world_time_id=sc.f.world_time_id,
    )
    assert result.ai_proposed_change_id is not None
    assert result.proposal_status == "pending"
    return result.ai_proposed_change_id


def review_call(
    sc: Scene, p: Pool, proposal: uuid.UUID, decision: str, user: uuid.UUID | None = None
) -> Any:
    return post(p, user or sc.reviewer, sc.review_path(proposal), {"decision": decision})


def state(sc: Scene, proposal: uuid.UUID) -> dict[str, Any]:
    """The durable state a review writes or applies, in one comparable value."""
    one = rows(
        sc.engine,
        """
        SELECT (SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :p) AS reviews,
               (SELECT status FROM ai.proposed_changes WHERE ai_proposed_change_id = :p) AS status,
               (SELECT applied_event_id FROM ai.proposed_changes WHERE ai_proposed_change_id = :p) AS applied_event,
               (SELECT count(*) FROM narrative.events WHERE campaign_id = :c) AS events,
               (SELECT count(*) FROM campaign.objective_state WHERE quest_objective_id = :o) AS objective_states,
               (SELECT count(*) FROM campaign.party_knowledge WHERE knowledge_item_id = :k) AS party_knowledge,
               (SELECT count(*) FROM audit.change_log) AS audit_rows
        """,
        p=proposal,
        c=sc.campaign_id,
        o=sc.f.open_objective_id,
        k=sc.secret_id,
    )[0]
    return one


# --- T-2: success paths, statement order -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", ("reveal", "reveal_already_known", "advance", "reject"))
def test_t2_each_success_path_locks_the_scope_first_and_finalizes_last(
    case: str, sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    kind = "advance" if case in ("advance", "reject") else "reveal"
    if case == "reveal_already_known":
        # two pending proposals name the same secret (the candidate set is read at proposal time); the first
        # approval makes it known, so the second resolves to `applied` with the existing event and creates none
        first = new_proposal(sc, "reveal")
        proposal = new_proposal(sc, "reveal")
        with pooled_factory(sc.reviewer) as client:
            assert code(client.post(sc.review_path(first), json={"decision": "approve"})) == 200
    else:
        proposal = new_proposal(sc, kind)
    before = state(sc, proposal)
    decision = "reject" if case == "reject" else "approve"
    with Recorder(pooled) as recorder, pooled_factory(sc.reviewer) as client:
        response = client.post(sc.review_path(proposal), json={"decision": decision})
    assert code(response) == 200, response.text
    body = response.json()
    after = state(sc, proposal)
    statements = [e for e in recorder.events if e != "COMMIT"]
    # the scope's campaign KEY SHARE precedes the proposal lock
    campaign_lock = next(i for i, s in enumerate(statements) if CAMPAIGN_KEY_SHARE.search(s))
    proposal_lock = next(i for i, s in enumerate(statements) if PROPOSAL_LOCK.search(s))
    assert campaign_lock < proposal_lock, statements
    # the final statement is the last one before COMMIT, takes no row lock, and nothing follows it
    assert recorder.events[-1] == "COMMIT"
    assert FINAL_RE.search(statements[-1]), statements[-3:]
    assert not ROW_LOCK_RE.search(statements[-1])
    assert sum(1 for s in statements if FINAL_RE.search(s)) == 1
    # no event status update, so no deferred trigger fires at COMMIT (V-T1 does not apply)
    assert not any(s.startswith("UPDATE narrative.events") for s in statements)
    # one review row, the proposal's decision, and no audit row
    assert after["reviews"] == before["reviews"] + 1
    assert after["audit_rows"] == before["audit_rows"], (
        "E1 adds no audit.change_log row (design D-4)"
    )
    if case == "reject":
        assert (body["status"], body["applied_event_id"]) == ("rejected", None)
        assert after["status"] == "rejected" and after["events"] == before["events"]
        return
    assert body["status"] == "applied" and body["applied_event_id"] is not None
    assert after["status"] == "applied" and str(after["applied_event"]) == body["applied_event_id"]
    if case == "advance":
        assert after["objective_states"] == before["objective_states"] + 1
        assert after["events"] == before["events"] + 1
    elif case == "reveal":
        assert after["party_knowledge"] == before["party_knowledge"] + 1
        assert after["events"] == before["events"] + 1
    else:  # already known: the review resolves to applied with the existing event, and creates none
        assert after["party_knowledge"] == before["party_knowledge"]
        assert after["events"] == before["events"]


# --- T-3: a role that lapses before the final statement --------------------------------------------------------------


def run_with_role_expiring_before_final(
    sc: Scene, app_engine: Engine, call: Callable[[], Any]
) -> Any:
    """The S4 method with the scope's first statement as the early gate: the request is paused at its world lock (it has
    passed the route's early check and holds nothing that conflicts with the role row), the role's `expires_at` is set to
    the request's own transaction start plus one second, and the request is released to its final statement, which it
    reaches after the second has passed."""
    with StatementGate(app_engine, WORLD_SHARE) as first, StatementGate(app_engine, FINAL) as final:
        request = run_in_thread("e1-review", call)
        first.wait_reached()
        with sc.engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            moved = connection.execute(
                text("""
                    UPDATE security.membership_roles
                    SET expires_at = (SELECT xact_start FROM pg_stat_activity WHERE pid = :pid)
                                     + interval '1 second'
                    WHERE membership_role_id = :r AND revoked_at IS NULL
                """),
                {"pid": first.pid, "r": sc.reviewer_role},
            ).rowcount
            assert moved == 1
        first.release()
        final.wait_reached()
        wait_lapsed(sc.engine, sc.reviewer_role)
        final.release()
        return request.wait("the gated request finishes")


@pytest.mark.parametrize("case", ("reveal", "advance", "reject"))
def test_t3_a_role_that_lapses_before_the_final_statement_refuses_and_persists_nothing(
    case: str, sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    proposal = new_proposal(sc, "advance" if case != "reveal" else "reveal")
    before = state(sc, proposal)
    decision = "reject" if case == "reject" else "approve"

    def call() -> Any:
        with pooled_factory(sc.reviewer) as client:
            return client.post(sc.review_path(proposal), json={"decision": decision})

    response = run_with_role_expiring_before_final(sc, pooled, call)
    refused = (code(response), error_of(response))
    assert refused == (403, "forbidden"), (refused, response.text)
    # nothing persisted: no review row, the proposal still pending, no event, no state change, no audit row
    assert state(sc, proposal) == before
    assert before["status"] == "pending" and before["reviews"] == 0
    assert idle_in_transaction(sc.engine) == 0
    # the pooled connection is clean: the next request on it commits only its own work
    with pooled_factory(sc.owner) as client:
        assert code(client.get(f"{sc.base}/sessions")) in (200, 404)
    assert state(sc, proposal) == before
    # the early refusal of the same caller (role revoked before the request) is the same refusal
    with sc.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": sc.reviewer_role},
        )
    with pooled_factory(sc.reviewer) as client:
        early = client.post(sc.review_path(proposal), json={"decision": decision})
    assert (code(early), error_of(early)) == refused, early.text


# --- T-4: refusal precedence -------------------------------------------------------------------------------------------


def test_t4a_a_role_revoked_before_the_request_is_refused_by_the_dependency(
    sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    proposal = new_proposal(sc, "advance")
    with sc.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": sc.reviewer_role},
        )
    with pooled_factory(sc.reviewer) as client:
        response = client.post(sc.review_path(proposal), json={"decision": "approve"})
    assert (code(response), error_of(response)) == (403, "forbidden"), response.text
    assert state(sc, proposal)["reviews"] == 0


@pytest.mark.parametrize("lifecycle", ("pending", "inactive"))
def test_t4b_a_campaign_that_is_not_active_is_refused_and_nothing_is_persisted(
    lifecycle: str, sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """Design D-5 (approved): the review requires an `active` campaign, like every operation route."""
    proposal = new_proposal(sc, "advance")
    before = state(sc, proposal)
    with sc.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE campaign.campaigns SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :s) WHERE campaign_id = :c"
            ),
            {"s": lifecycle, "c": sc.campaign_id},
        )
    with pooled_factory(sc.reviewer) as client:
        response = client.post(sc.review_path(proposal), json={"decision": "approve"})
    assert code(response) in (404, 409), (code(response), response.text)
    assert state(sc, proposal) == before
    assert idle_in_transaction(sc.engine) == 0


def test_t4c_a_decided_proposal_is_the_unchanged_409_for_an_authorized_reviewer(
    sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    proposal = new_proposal(sc, "advance")
    with pooled_factory(sc.reviewer) as client:
        assert code(client.post(sc.review_path(proposal), json={"decision": "approve"})) == 200
        again = client.post(sc.review_path(proposal), json={"decision": "approve"})
        rejected = client.post(sc.review_path(proposal), json={"decision": "reject"})
    assert (code(again), error_of(again)) == NOT_PENDING, again.text
    assert (code(rejected), error_of(rejected)) == NOT_PENDING, rejected.text
    assert state(sc, proposal)["reviews"] == 1


def test_t4d_a_proposal_of_another_campaign_is_the_non_disclosing_404(
    sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    with pooled_factory(sc.reviewer) as client:
        response = client.post(sc.review_path(uuid.uuid4()), json={"decision": "approve"})
    assert code(response) == 404, response.text
    assert idle_in_transaction(sc.engine) == 0


def test_t4e_a_revalidation_failure_rolls_the_whole_review_back_over_http(
    sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """A domain refusal at the apply stage (400) wins and leaves nothing: no review row, the proposal pending."""
    proposal = new_proposal(sc, "advance")
    before = state(sc, proposal)
    with sc.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE narrative.quest_objectives SET visibility_policy = 'gm_only' WHERE quest_objective_id = :o"
            ),
            {"o": sc.f.open_objective_id},
        )
    with pooled_factory(sc.reviewer) as client:
        response = client.post(sc.review_path(proposal), json={"decision": "approve"})
    assert code(response) == 400, response.text
    after = state(sc, proposal)
    assert after == before and after["reviews"] == 0 and after["status"] == "pending"
    assert idle_in_transaction(sc.engine) == 0


# --- T-5: a revocation or membership end requested during the review waits for it -----------------------------------


@pytest.mark.parametrize("writer", ("role_revoke", "membership_end"))
def test_t5_a_revocation_in_flight_waits_for_the_review_and_the_next_review_is_refused(
    writer: str, sc: Scene, pool: Pool
) -> None:
    first = new_proposal(sc, "advance")
    second = new_proposal(sc, "reveal")
    if writer == "role_revoke":
        path = f"{sc.base}/memberships/roles/{sc.reviewer_role}/revoke"
        body: dict[str, Any] = {}
    else:
        path = f"{sc.base}/memberships/{sc.reviewer_membership}/end"
        body = {}

    def review() -> Any:
        return review_call(sc, pool, first, "approve")

    def writer_call() -> Any:
        return post(pool, sc.owner, path, body)

    o = race(sc, pool, gate_pattern=REVIEW_INSERT, parked=review, second=writer_call)
    assert_clean(o)
    assert_waited_on_parked(o, r"FOR UPDATE|FOR NO KEY UPDATE|UPDATE")
    assert o.status("parked")[0] == 200, o.summary()
    assert o.status("second")[0] == 200, o.summary()
    assert state(sc, first)["reviews"] == 1 and state(sc, first)["status"] == "applied"
    refused = review_call(sc, pool, second, "approve")
    assert code(refused) in (403, 404), (code(refused), refused.text)
    assert state(sc, second)["reviews"] == 0


# --- T-6: the grant routes against the review, both arrivals (P-2) -------------------------------------------------


def grant_body(sc: Scene, target: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "capability_code": "character.view_summary" if target == "npc" else "campaign.view",
        "grantee_campaign_membership_id": str(sc.reviewer_membership),
    }
    if target == "quest":
        body["quest_id"] = str(sc.f.quest_id)
    elif target == "knowledge":
        body["knowledge_item_id"] = str(sc.secret_id)
    else:
        body["character_id"] = str(sc.f.npc_id)
    return body


@pytest.mark.parametrize(
    ("target", "kind"), (("quest", "advance"), ("npc", "advance"), ("knowledge", "reveal"))
)
@pytest.mark.parametrize("arrival", ("review_parked", "grant_parked"))
def test_t6_a_grant_on_what_the_review_applies_serializes_in_both_arrivals(
    arrival: str, target: str, kind: str, sc: Scene, pool: Pool
) -> None:
    """P-2: at the parent the review took the quest or NPC entity `FOR SHARE` before the event foreign key took the campaign
    `KEY SHARE`, and the grant routes take the campaign `FOR UPDATE` and then the target entity `FOR UPDATE`. *review_parked*:
    the review parked at its event INSERT (the entities held, the campaign not yet), the grant takes the campaign and waits at
    the entity. *grant_parked*: the grant parked at its entity lock (the campaign held), the review runs to its event INSERT
    and waits at the campaign. At the parent either release is one 40P01. With E1 the review's scope holds the campaign
    `KEY SHARE` first, so the grant waits at the campaign, or the review waits at the scope, and neither holds what the other
    wants."""
    proposal = new_proposal(sc, kind)

    def review() -> Any:
        return review_call(sc, pool, proposal, "approve")

    def grant() -> Any:
        return post(pool, sc.owner, f"{sc.base}/resource-grants", grant_body(sc, target))

    if arrival == "review_parked":
        o = race(sc, pool, gate_pattern=EVENT_INSERT, parked=review, second=grant)
        reviewed, granted = o.results["parked"], o.results["second"]
    else:
        o = race(sc, pool, gate_pattern=GRANT_TARGET_ENTITY, parked=grant, second=review)
        reviewed, granted = o.results["second"], o.results["parked"]
    assert_clean(o)
    assert o.blocked, f"the second request never queued behind the parked one: {o.summary()}"
    assert code(reviewed) == 200, (reviewed.text, o.summary())
    assert code(granted) == 201, (granted.text, o.summary())
    after = state(sc, proposal)
    assert after["reviews"] == 1 and after["status"] == "applied" and after["events"] == 1
    assert not pool.failures, pool.failures


# --- T-7: the human advance against the review, both arrivals (P-1) ------------------------------------------------


def human_advance(sc: Scene, p: Pool) -> Any:
    return post(
        p,
        sc.reviewer,
        f"{sc.base}/quests/objectives/{sc.f.open_objective_id}/advance",
        {
            "world_time_id": str(sc.f.world_time_id),
            "new_status_code": "completed",
            "party_id": str(sc.f.party_id),
        },
    )


@pytest.mark.parametrize("arrival", ("review_parked", "human_parked"))
def test_t7_the_human_advance_and_the_review_of_one_objective_serialize_in_both_arrivals(
    arrival: str, sc: Scene, pool: Pool
) -> None:
    """P-1: the review locked the objective row before the quest-runtime advisory lock, the human advance locks them the other
    way round. *review_parked*: parked at the advisory lock (at the parent, the objective held), the human advance takes the
    advisory lock and waits at the objective. *human_parked*: the human advance parked at its objective lock (the advisory
    held), the review takes the objective and waits at the advisory lock. At the parent either release is one 40P01. With
    D-3(a) the review takes the quest entity and the advisory lock first, so exactly one status change commits and the other
    side gets its domain refusal."""
    proposal = new_proposal(sc, "advance")

    def review() -> Any:
        return review_call(sc, pool, proposal, "approve")

    def human() -> Any:
        return human_advance(sc, pool)

    if arrival == "review_parked":
        o = race(sc, pool, gate_pattern=ADVISORY, parked=review, second=human)
        reviewed, advanced = o.results["parked"], o.results["second"]
    else:
        o = race(sc, pool, gate_pattern=HUMAN_OBJECTIVE_LOCK, parked=human, second=review)
        reviewed, advanced = o.results["second"], o.results["parked"]
    assert_clean(o)
    outcomes = (code(reviewed), code(advanced))
    # exactly one of the two status changes commits; the other is the existing domain refusal
    assert sorted(outcomes) in ([200, 400], [200, 409]) or 200 in outcomes, (outcomes, o.summary())
    status_changes = rows(
        sc.engine,
        "SELECT count(*) AS n FROM campaign.objective_state WHERE quest_objective_id = :o",
        o=sc.f.open_objective_id,
    )[0]["n"]
    assert status_changes == 1, o.summary()
    after = state(sc, proposal)
    if code(reviewed) == 200:
        assert after["status"] == "applied" and after["reviews"] == 1
    else:
        # the review was refused by revalidation or the terminal check: nothing of it persisted
        assert after["status"] == "pending" and after["reviews"] == 0, (after, o.summary())
    assert not pool.failures, pool.failures


# --- T-8: concurrent reviews of one proposal, both arrivals -----------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"), (("approve", "approve"), ("approve", "reject"), ("reject", "approve"))
)
def test_t8_two_concurrent_reviews_of_one_proposal_give_one_200_and_one_409(
    first: str, second: str, sc: Scene, pool: Pool
) -> None:
    proposal = new_proposal(sc, "advance")
    o = race(
        sc,
        pool,
        gate_pattern=REVIEW_INSERT,
        parked=lambda: review_call(sc, pool, proposal, first),
        second=lambda: review_call(sc, pool, proposal, second),
    )
    assert_clean(o)
    assert o.status("parked")[0] == 200, o.summary()
    assert o.status("second") == NOT_PENDING, o.summary()
    after = state(sc, proposal)
    assert after["reviews"] == 1 and after["status"] == (
        "applied" if first == "approve" else "rejected"
    )
    assert after["events"] == (1 if first == "approve" else 0)


# --- T-9: rollback ---------------------------------------------------------------------------------------------------------


def test_t9_a_failure_at_the_last_write_leaves_nothing_and_the_connection_clean(
    sc: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    proposal = new_proposal(sc, "advance")
    before = state(sc, proposal)

    def boom(_c: Any, _cur: Any, statement: Any, *_: Any) -> None:
        if re.search(APPLIED_UPDATE, " ".join(str(statement).split())):
            raise RuntimeError("injected failure at the applied UPDATE")

    event.listen(pooled, "before_cursor_execute", boom)
    try:
        with pooled_factory(sc.reviewer) as client:
            response = client.post(sc.review_path(proposal), json={"decision": "approve"})
    finally:
        event.remove(pooled, "before_cursor_execute", boom)
    assert code(response) == 500, response.text
    assert state(sc, proposal) == before, (
        "the review row, the event and the state rows were all rolled back"
    )
    assert idle_in_transaction(sc.engine) == 0
    with pooled_factory(sc.reviewer) as client:
        again = client.post(sc.review_path(proposal), json={"decision": "approve"})
    assert code(again) == 200, again.text
