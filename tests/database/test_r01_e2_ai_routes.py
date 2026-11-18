# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 E2: the NPC-conversation and synthesis routes across the provider call (design 9.2, T-2 to T-11).

Real routes, the real guard, the real final statement. Each request runs three transactions: R (the request
transaction, the early check, finalized and ended), T1 (the context, committed **before** the provider is called)
and T2 (the output, the proposal and any auto-application). Each is judged by its own post-write final check from
a fresh requirement factory. The provider is a spy: it records every payload it receives and, from outside the
request, commits a change **while the call is in flight**.

Decision G-2 (owner): every NPC caller, a `canon.edit` holder included, proves the established party perspective
(`character.view_knowledge` for the character, the party in the campaign, the character a current member at the
campaign clock). U7, U8 and U9 are the three callers the two precedents disagree on.
"""

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from dnd_ai.api.ai_npc import _resolve_provider
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.domain.ai_provider import FakeAiProvider
from tests.ai_e2_support import make_interactor
from tests.database.test_r01_e1_r3_three_party import (  # noqa: F401 - fixtures by name
    definition_edit,
    edit_body,
    human_reveal,
    owner_is_world_editor,
)
from tests.database.test_r01_e1_review_route import (  # noqa: F401 - fixtures by name
    EVENT_INSERT,
    GRANT_TARGET_ENTITY,
    Scene,
    grant_body,
    new_proposal,
    review_call,
    sc,
)
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures by name
    FINAL_RE,
    ROW_LOCK_RE,
    Recorder,
    idle_in_transaction,
)
from tests.database.test_r01_s3_authoring_routes import code, error_of
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixtures by name
    NthGate,
    Pool,
    assert_clean,
    pool,
    post,
    race,
    rows,
)
from tests.factories import (
    lookup_id,
    make_campaign_party,
    make_character,
    make_knowledge_item,
    make_membership_character_relationship,
    make_party,
    make_party_knowledge,
    make_party_membership,
    make_world_time,
    oidc_principal,
)
from tests.http_race_support import StatementGate, run_in_thread

pytestmark = pytest.mark.database

# --- statement patterns -----------------------------------------------------------------------------------------------

CONTEXT_SNAPSHOT_INSERT = r"^INSERT INTO ai\.context_snapshots"
OUTPUT_INSERT = r"^INSERT INTO ai\.generated_outputs"
PROPOSAL_INSERT = r"^INSERT INTO ai\.proposed_changes"
CAMPAIGN_KEY_SHARE_N3 = r"^SELECT 1 FROM campaign\.campaigns WHERE campaign_id = \S+ FOR KEY SHARE$"
ENTITY_SHARE_N4 = r"^SELECT e\.world_id, e\.canon_status_id, e\.lifecycle_status_id FROM core\.entities e .* FOR SHARE OF e$"
KI_UPDATE_N5 = r"^SELECT ki\.sensitivity, ki\.subject_entity_id FROM knowledge\.knowledge_items ki .* FOR UPDATE OF ki$"
APPLIED_UPDATE = r"^UPDATE ai\.proposed_changes SET status = 'applied'"
EDIT_KI_UPDATE = r"^UPDATE knowledge\.knowledge_items"
# `require_state_targetable`'s statement: the NPC in T1 (the 1st), the item in the apply (the 2nd). The same SQL in the parent
# and in E2, so one schedule parks the turn at the apply's entity guard (it holds `ki`) in both trees (design Q-2d).
ENTITY_ANY_SHARE = r"FROM core\.entities e WHERE e\.entity_id = ANY\(CAST\(.* FOR SHARE OF e$"
NPC_TURN = "/ai/npc-conversation"
SYNTHESIS = "/ai/synthesis"
BASE_CAPS = ("campaign.view", "character.interact", "character.view_knowledge")
A_BELIEF = "A-BELIEF: the innkeeper keeps a ledger."
B_BELIEF = "B-ONLY-BELIEF: the innkeeper owes the rival party a favour."


# --- the spy provider and the calls --------------------------------------------------------------------------------------


class Spy(FakeAiProvider):
    """Records every payload it receives; `during` runs from outside the request while the call is in flight."""

    def __init__(
        self, *, during: Callable[[], None] | None = None, raises: bool = False, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.calls = 0
        self.payloads: list[str] = []
        self.during = during
        self.raises = raises

    def _observe(self, payload: Any) -> None:
        self.calls += 1
        self.payloads.append(json.dumps(payload, default=str))
        if self.during is not None:
            self.during()
        if self.raises:
            raise RuntimeError("the provider failed")

    def generate_npc_turn(self, *, context: Any, player_message: str) -> Any:
        self._observe(context.as_prompt_payload())
        return super().generate_npc_turn(context=context, player_message=player_message)

    def generate_synthesis(self, *, context: Any, audience_tier: str, question_text: str) -> Any:
        self._observe(context)
        return super().generate_synthesis(
            context=context, audience_tier=audience_tier, question_text=question_text
        )


def client_for(p: Pool, user: uuid.UUID, provider: FakeAiProvider) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: p.engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user)
    app.dependency_overrides[_resolve_provider] = lambda: provider
    return TestClient(app, raise_server_exceptions=False)


def turn_body(sc: Scene, **overrides: Any) -> dict[str, str]:
    body = {
        "agent_assignment_id": str(sc.f.assignment_id),
        "requesting_character_id": str(sc.f.pc_id),
        "requesting_party_id": str(sc.f.party_id),
        "player_message": "Hello!",
        "world_time_id": str(sc.f.world_time_id),
    }
    body.update({k: str(v) for k, v in overrides.items()})
    return body


def turn(sc: Scene, p: Pool, user: uuid.UUID, provider: FakeAiProvider, **overrides: Any) -> Any:
    with client_for(p, user, provider) as client:
        return client.post(f"{sc.base}{NPC_TURN}", json=turn_body(sc, **overrides))


def synth_body(sc: Scene, tier: str, **overrides: Any) -> dict[str, str]:
    body = {
        "agent_assignment_id": str(sc.f.assignment_id),
        "audience_tier": tier,
        "question_text": "What do we know?",
    }
    if tier == "player_summary":
        body["requesting_character_id"] = str(sc.f.pc_id)
        body["requesting_party_id"] = str(sc.f.party_id)
    body.update({k: str(v) for k, v in overrides.items()})
    return body


def synth(
    sc: Scene, p: Pool, user: uuid.UUID, provider: FakeAiProvider, tier: str, **overrides: Any
) -> Any:
    with client_for(p, user, provider) as client:
        return client.post(f"{sc.base}{SYNTHESIS}", json=synth_body(sc, tier, **overrides))


# --- the durable state ---------------------------------------------------------------------------------------------------


def counts(
    sc: Scene, *, party: uuid.UUID | None = None, item: uuid.UUID | None = None
) -> dict[str, Any]:
    return rows(
        sc.engine,
        """
        SELECT (SELECT count(*) FROM ai.context_requests WHERE agent_assignment_id = :a) AS requests,
               (SELECT count(*) FROM ai.generated_outputs o
                  JOIN ai.context_requests r ON r.context_request_id = o.context_request_id
                 WHERE r.agent_assignment_id = :a) AS outputs,
               (SELECT count(*) FROM ai.proposed_changes WHERE campaign_id = :c) AS proposals,
               (SELECT count(*) FROM ai.proposed_changes WHERE campaign_id = :c AND status = 'applied') AS applied,
               (SELECT count(*) FROM campaign.party_knowledge WHERE party_id = :p AND knowledge_item_id = :k) AS knows,
               (SELECT count(*) FROM knowledge.party_discoveries WHERE party_id = :p AND knowledge_item_id = :k) AS discoveries,
               (SELECT count(*) FROM narrative.events WHERE campaign_id = :c) AS events
        """,
        a=sc.f.assignment_id,
        c=sc.campaign_id,
        p=party or sc.f.party_id,
        k=item or sc.secret_id,
    )[0]


NOTHING_KEPT = {
    "requests": 0,
    "outputs": 0,
    "proposals": 0,
    "applied": 0,
    "knows": 0,
    "discoveries": 0,
    "events": 0,
}
DISCLOSED_ONLY = {
    **NOTHING_KEPT,
    "requests": 1,
}  # T1 committed, T2 refused: the provider-failure state


# --- committed changes (what a lapse during the call looks like) ----------------------------------------------------------


def set_sensitivity(sc: Scene, value: str) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.knowledge_items SET sensitivity = :v WHERE knowledge_item_id = :k"
            ),
            {"v": value, "k": sc.secret_id},
        )


def membership_of(sc: Scene, user: uuid.UUID) -> uuid.UUID:
    return rows(
        sc.engine,
        "SELECT campaign_membership_id AS m FROM security.campaign_memberships WHERE campaign_id = :c AND user_id = :u",
        c=sc.campaign_id,
        u=user,
    )[0]["m"]


def revoke_role(sc: Scene, user: uuid.UUID) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE campaign_membership_id = :m"
            ),
            {"m": membership_of(sc, user)},
        )


def expire_role(sc: Scene, user: uuid.UUID) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() WHERE campaign_membership_id = :m"
            ),
            {"m": membership_of(sc, user)},
        )


def end_membership(sc: Scene, user: uuid.UUID) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = now(), "
                "membership_status_id = (SELECT membership_status_id FROM security.membership_statuses WHERE code = 'departed') "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": membership_of(sc, user)},
        )


def archive_campaign(sc: Scene) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "UPDATE campaign.campaigns SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') WHERE campaign_id = :c"
            ),
            {"c": sc.campaign_id},
        )


def drop_capability(sc: Scene, user: uuid.UUID, capability: str) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                """
                DELETE FROM security.role_capabilities WHERE capability_id =
                    (SELECT capability_id FROM security.capabilities WHERE code = :cap)
                AND role_id IN (SELECT mr.role_id FROM security.membership_roles mr
                                WHERE mr.campaign_membership_id = :m)
                """
            ),
            {"cap": capability, "m": membership_of(sc, user)},
        )


def leave_party(sc: Scene) -> None:
    """The character leaves the party and the campaign clock moves past the departure."""
    with sc.engine.begin() as c:
        left = make_world_time(c, sc.f.world_id, 150)
        later = make_world_time(c, sc.f.world_id, 200)
        c.execute(
            text(
                "UPDATE campaign.party_memberships SET effective_to_world_time_id = :left "
                "WHERE party_id = :p AND member_entity_id = :c"
            ),
            {"left": left, "p": sc.f.party_id, "c": sc.f.pc_id},
        )
        c.execute(
            text(
                "UPDATE campaign.timeline_clocks SET current_world_time_id = :w WHERE timeline_id = :t"
            ),
            {"w": later, "t": sc.f.timeline_id},
        )


def dissociate_party(sc: Scene) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text("DELETE FROM campaign.campaign_parties WHERE campaign_id = :c AND party_id = :p"),
            {"c": sc.campaign_id, "p": sc.f.party_id},
        )


def unset_clock(sc: Scene) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text("DELETE FROM campaign.timeline_clocks WHERE timeline_id = :t"),
            {"t": sc.f.timeline_id},
        )


def archive_item(sc: Scene) -> None:
    with sc.engine.begin() as c:
        c.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') WHERE entity_id = :k"
            ),
            {"k": sc.secret_id},
        )


def retarget_item(sc: Scene) -> None:
    """The item's subject becomes another entity (the pc): it no longer qualifies for this NPC."""
    with sc.engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.knowledge_items SET subject_entity_id = :s WHERE knowledge_item_id = :k"
            ),
            {"s": sc.f.pc_id, "k": sc.secret_id},
        )


# --- personas and a second party ----------------------------------------------------------------------------------------


def persona(
    sc: Scene, name: str, capabilities: tuple[str, ...], relationship: str | None = None
) -> uuid.UUID:
    with sc.engine.begin() as c:
        user = make_interactor(c, sc.campaign_id, name, capabilities=capabilities)
        if relationship is not None:
            make_membership_character_relationship(
                c,
                membership_of_c(c, sc.campaign_id, user),
                sc.f.pc_id,
                lookup_id(
                    c,
                    "security",
                    "character_relationship_types",
                    "character_relationship_type_id",
                    relationship,
                ),
            )
    return user


def membership_of_c(c: Any, campaign_id: uuid.UUID, user: uuid.UUID) -> uuid.UUID:
    return c.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": campaign_id, "u": user},
    ).scalar_one()


def add_beliefs_and_party_b(sc: Scene) -> uuid.UUID:
    """The party A believes `A_BELIEF`; a second campaign party B (its own character) believes `B_BELIEF`. Both are about the NPC."""
    with sc.engine.begin() as c:
        a_item = make_knowledge_item(
            c, sc.f.world_id, statement=A_BELIEF, subject_entity_id=sc.f.npc_id
        )
        make_party_knowledge(c, sc.f.timeline_id, sc.f.party_id, a_item)
        rival = make_character(c, sc.f.world_id, name="Rival")
        party_b = make_party(c, sc.f.world_id, "Rivals")
        make_campaign_party(c, sc.campaign_id, party_b)
        make_party_membership(c, sc.f.timeline_id, party_b, rival, sc.f.world_time_id)
        b_item = make_knowledge_item(
            c, sc.f.world_id, statement=B_BELIEF, subject_entity_id=sc.f.npc_id
        )
        make_party_knowledge(c, sc.f.timeline_id, party_b, b_item)
    return party_b


# =====================================================================================================================
# T-2: the statement order of the three transactions
# =====================================================================================================================


def segments(events: list[str]) -> list[list[str]]:
    """The recorded events split at COMMIT: R, T1 and T2 (a COMMIT closes each)."""
    out: list[list[str]] = [[]]
    for e in events:
        if e == "COMMIT":
            out.append([])
        else:
            out[-1].append(e)
    return [s for s in out if s]


def index(statements: list[str], pattern: str) -> int:
    return next(i for i, s in enumerate(statements) if re.search(pattern, s))


@pytest.mark.parametrize("sensitivity", ("public", "secret"))
def test_t2_the_npc_turn_runs_three_judged_transactions_in_the_designed_order(
    sensitivity: str, sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, sensitivity)
    provider = Spy(dialogue="Welcome.", reveal_first_candidate=True)
    with Recorder(pool.engine) as recorded:
        response = turn(sc, pool, sc.f.interactor_id, provider)
    assert code(response) == 200, response.text
    body = response.json()
    assert body["dialogue"] == "Welcome."
    assert body["proposal_status"] == ("applied" if sensitivity == "public" else "pending")
    parts = segments(recorded.events)
    assert len(parts) == 3, [len(p) for p in parts]
    request, t1, t2 = parts
    for part in parts:  # each transaction ends with its own final check, which takes no row lock
        assert FINAL_RE.search(part[-1]), part[-2:]
        assert not ROW_LOCK_RE.search(part[-1])
        assert sum(1 for s in part if FINAL_RE.search(s)) == 1
    # T1: the final check is after the snapshot INSERT; T1 committed before the provider was called
    assert index(t1, CONTEXT_SNAPSHOT_INSERT) < len(t1) - 1
    assert provider.calls == 1
    # T2: N3 (campaign) < N4 (entity) < N5 (ki) < the proposal INSERT, then the apply, the final check last
    n3, n4, n5, n7 = (
        index(t2, CAMPAIGN_KEY_SHARE_N3),
        index(t2, ENTITY_SHARE_N4),
        index(t2, KI_UPDATE_N5),
        index(t2, PROPOSAL_INSERT),
    )
    assert index(t2, OUTPUT_INSERT) < n3 < n4 < n5 < n7
    if sensitivity == "public":
        assert n7 < index(t2, EVENT_INSERT) < index(t2, APPLIED_UPDATE) < len(t2) - 1
    assert not any(s.startswith("UPDATE narrative.events") for s in t2)
    assert request  # the request transaction judged and ended before T1
    state = counts(sc)
    assert (state["requests"], state["outputs"], state["proposals"]) == (1, 1, 1)
    assert state["applied"] == (1 if sensitivity == "public" else 0)
    assert state["knows"] == (1 if sensitivity == "public" else 0)


@pytest.mark.parametrize("tier", ("gm_brief", "player_summary", "observer_summary"))
def test_t2_synthesis_runs_three_judged_transactions_for_each_tier(
    tier: str, sc: Scene, pool: Pool
) -> None:
    provider = Spy(dialogue="Summary.")
    with Recorder(pool.engine) as recorded:
        response = synth(sc, pool, sc.f.interactor_id, provider, tier)
    assert code(response) == 200, response.text
    assert "Summary." in response.json()["answer"]
    parts = segments(recorded.events)
    assert len(parts) == 3
    for part in parts:
        assert FINAL_RE.search(part[-1]) and not ROW_LOCK_RE.search(part[-1])
    assert provider.calls == 1
    state = counts(sc)
    assert (state["requests"], state["outputs"], state["proposals"]) == (1, 1, 0)


# =====================================================================================================================
# T-3 (and T-11e): a lapse during the provider call discards everything derived from it
# =====================================================================================================================

LAPSES: dict[str, tuple[Callable[[Scene, uuid.UUID], None], int | None]] = {
    # name -> (the committed change, None: compare with the same request made after the change)
    "role_revoked": (lambda sc, u: revoke_role(sc, u), None),
    "role_expired": (lambda sc, u: expire_role(sc, u), None),
    "membership_ended": (lambda sc, u: end_membership(sc, u), None),
    "campaign_archived": (lambda sc, u: archive_campaign(sc), None),
    "interact_removed": (lambda sc, u: drop_capability(sc, u, "character.interact"), None),
    "view_knowledge_removed": (
        lambda sc, u: drop_capability(sc, u, "character.view_knowledge"),
        None,
    ),
    "left_the_party": (lambda sc, u: leave_party(sc), None),
    "party_dissociated": (lambda sc, u: dissociate_party(sc), None),
}


@pytest.mark.parametrize("lapse", sorted(LAPSES))
def test_t3_an_npc_turn_whose_authority_lapses_during_the_provider_call_keeps_nothing(
    lapse: str, sc: Scene, pool: Pool
) -> None:
    """Fail-before (the parent): 200, the output is persisted and the public reveal is applied to the party."""
    set_sensitivity(sc, "public")
    user = persona(sc, "Lapsing", BASE_CAPS)
    change = LAPSES[lapse][0]
    provider = Spy(
        dialogue="Welcome.", reveal_first_candidate=True, during=lambda: change(sc, user)
    )
    response = turn(sc, pool, user, provider)
    refused = (code(response), error_of(response))
    assert refused[0] in (403, 404), (refused, response.text)
    assert provider.calls == 1
    # T1 committed (the disclosure was authorized), T2 kept nothing: no output, proposal, reveal or event
    assert counts(sc) == DISCLOSED_ONLY, counts(sc)
    assert idle_in_transaction(sc.engine) == 0
    # the refusal is the early refusal: the same request after the change is refused the same way, before T1
    spy = Spy(dialogue="Welcome.", reveal_first_candidate=True)
    early = turn(sc, pool, user, spy)
    assert (code(early), error_of(early)) == refused, (early.text, response.text)
    assert spy.calls == 0
    assert counts(sc) == DISCLOSED_ONLY


@pytest.mark.parametrize("lapse", ("role_revoked", "membership_ended", "campaign_archived"))
@pytest.mark.parametrize("tier", ("gm_brief", "observer_summary"))
def test_t3_a_synthesis_whose_authority_lapses_during_the_provider_call_keeps_nothing(
    tier: str, lapse: str, sc: Scene, pool: Pool
) -> None:
    user = persona(sc, "Lapsing GM", (*BASE_CAPS, "canon.edit"))
    change = LAPSES[lapse][0]
    provider = Spy(dialogue="Summary.", during=lambda: change(sc, user))
    response = synth(sc, pool, user, provider, tier)
    refused = (code(response), error_of(response))
    assert refused[0] in (403, 404), (refused, response.text)
    assert provider.calls == 1
    assert counts(sc) == DISCLOSED_ONLY
    spy = Spy(dialogue="Summary.")
    early = synth(sc, pool, user, spy, tier)
    assert (code(early), error_of(early)) == refused and spy.calls == 0


def test_t3_a_gm_brief_loses_canon_edit_during_the_call(sc: Scene, pool: Pool) -> None:
    user = persona(sc, "Brief GM", (*BASE_CAPS, "canon.edit"))
    provider = Spy(dialogue="Summary.", during=lambda: drop_capability(sc, user, "canon.edit"))
    response = synth(sc, pool, user, provider, "gm_brief")
    assert (code(response), error_of(response)) == (403, "forbidden"), response.text
    assert provider.calls == 1 and counts(sc) == DISCLOSED_ONLY


@pytest.mark.parametrize(
    "change", ("view_knowledge_removed", "left_the_party", "party_dissociated")
)
def test_t3_a_player_summary_loses_the_perspective_during_the_call(
    change: str, sc: Scene, pool: Pool
) -> None:
    user = persona(sc, "Summary Player", BASE_CAPS)
    provider = Spy(dialogue="Summary.", during=lambda: LAPSES[change][0](sc, user))
    response = synth(sc, pool, user, provider, "player_summary")
    assert code(response) == 404, response.text
    assert provider.calls == 1 and counts(sc) == DISCLOSED_ONLY


# =====================================================================================================================
# T-4: a lapse between the request transaction and T1's final check discloses nothing
# =====================================================================================================================


@pytest.mark.parametrize(
    "lapse", ("role_revoked", "membership_ended", "view_knowledge_removed", "left_the_party")
)
def test_t4_a_lapse_before_t1s_final_check_refuses_and_the_provider_is_never_called(
    lapse: str, sc: Scene, pool: Pool
) -> None:
    """Fail-before (the parent): T1 has no final check, so the provider is called and receives the context."""
    user = persona(sc, "Early Lapse", BASE_CAPS)
    provider = Spy(dialogue="Welcome.", reveal_first_candidate=True)
    with StatementGate(
        pool.engine, CONTEXT_SNAPSHOT_INSERT, strict=True, hold_seconds=30.0
    ) as gate:
        request = gate.track(run_in_thread("turn", lambda: turn(sc, pool, user, provider)))
        gate.wait_reached()
        LAPSES[lapse][0](sc, user)
        gate.release()
        assert request.done.wait(30.0)
    response = request.result
    assert code(response) in (403, 404), (code(response), response.text)
    assert provider.calls == 0
    assert counts(sc) == NOTHING_KEPT, counts(sc)
    assert idle_in_transaction(sc.engine) == 0


# =====================================================================================================================
# T-5, T-9: precedence and rollback
# =====================================================================================================================


def test_t5_the_domain_refusal_of_an_unknown_assignment_wins_over_a_lapse(
    sc: Scene, pool: Pool
) -> None:
    user = persona(sc, "Unknown Assignment", BASE_CAPS)
    response = turn(sc, pool, user, Spy(), agent_assignment_id=uuid.uuid4())
    assert (code(response), error_of(response)) == (404, "not_found"), response.text
    assert counts(sc) == NOTHING_KEPT


def test_t9_a_failure_at_the_applied_update_rolls_t2_back_and_keeps_t1(
    sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")

    def boom(_conn: Any, _cursor: Any, statement: Any, *_: Any) -> None:
        if re.search(APPLIED_UPDATE, " ".join(str(statement).split())):
            raise RuntimeError("injected failure at the applied update")

    event.listen(pool.engine, "before_cursor_execute", boom)
    try:
        response = turn(sc, pool, sc.f.interactor_id, Spy(reveal_first_candidate=True))
    finally:
        event.remove(pool.engine, "before_cursor_execute", boom)
    assert code(response) == 500, response.text
    assert counts(sc) == DISCLOSED_ONLY, counts(sc)
    assert idle_in_transaction(sc.engine) == 0
    # the pooled connection is clean: the next request commits only its own work
    again = turn(sc, pool, sc.f.interactor_id, Spy(reveal_first_candidate=True))
    assert code(again) == 200 and counts(sc)["knows"] == 1


def test_t9_a_provider_exception_keeps_t1_and_no_output(sc: Scene, pool: Pool) -> None:
    response = turn(sc, pool, sc.f.interactor_id, Spy(raises=True))
    assert code(response) == 500
    assert counts(sc) == DISCLOSED_ONLY


# =====================================================================================================================
# T-6: the auto-approval inputs are read fresh, under lock, in both directions (OP-3)
# =====================================================================================================================


def test_t6a_an_item_made_secret_during_the_call_gets_a_pending_proposal_not_an_application(
    sc: Scene, pool: Pool
) -> None:
    """Fail-before (the parent): the tier comes from T1's read ('public'), so the secret is applied to the party."""
    set_sensitivity(sc, "public")
    provider = Spy(
        dialogue="Perhaps.",
        reveal_first_candidate=True,
        during=lambda: set_sensitivity(sc, "secret"),
    )
    response = turn(sc, pool, sc.f.interactor_id, provider)
    assert code(response) == 200, response.text
    body = response.json()
    assert (body["proposal_status"], body["ai_proposed_change_id"] is not None) == ("pending", True)
    state = counts(sc)
    assert (state["proposals"], state["applied"], state["knows"], state["events"]) == (1, 0, 0, 0)
    assert (
        rows(
            sc.engine,
            "SELECT risk_tier FROM ai.proposed_changes WHERE campaign_id = :c",
            c=sc.campaign_id,
        )[0]["risk_tier"]
        == "requires_approval"
    )


def test_t6b_an_item_made_public_during_the_call_is_applied(sc: Scene, pool: Pool) -> None:
    set_sensitivity(sc, "secret")
    provider = Spy(
        dialogue="Fine.", reveal_first_candidate=True, during=lambda: set_sensitivity(sc, "public")
    )
    response = turn(sc, pool, sc.f.interactor_id, provider)
    assert code(response) == 200, response.text
    assert response.json()["proposal_status"] == "applied"
    state = counts(sc)
    assert (state["applied"], state["knows"], state["events"]) == (1, 1, 1)


@pytest.mark.parametrize("change", ("retargeted", "archived"))
def test_t6cd_a_candidate_that_stops_qualifying_gets_no_proposal_but_the_dialogue(
    change: str, sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    mutate = retarget_item if change == "retargeted" else archive_item
    provider = Spy(dialogue="Hello.", reveal_first_candidate=True, during=lambda: mutate(sc))
    response = turn(sc, pool, sc.f.interactor_id, provider)
    assert code(response) == 200, response.text
    body = response.json()
    assert (body["dialogue"], body["ai_proposed_change_id"], body["proposal_status"]) == (
        "Hello.",
        None,
        None,
    )
    state = counts(sc)
    assert (state["outputs"], state["proposals"], state["knows"], state["events"]) == (1, 0, 0, 0)


# =====================================================================================================================
# T-10: an assignment of another campaign (D-1)
# =====================================================================================================================


def test_t10_an_assignment_of_another_campaign_is_a_404_with_no_disclosure(
    sc: Scene, pool: Pool
) -> None:
    """Fail-before (the parent): the turn assembles the context from the foreign assignment's NPC and the provider receives it."""
    from tests.ai_review_support import make_active_campaign
    from tests.factories import make_agent_assignment

    with sc.engine.begin() as c:
        other = make_active_campaign(c, sc.f.timeline_id, "Other Campaign")
        foreign = make_agent_assignment(c, sc.f.agent_id, other, sc.f.npc_id)
    try:
        provider = Spy(dialogue="Hello.", reveal_first_candidate=True)
        response = turn(sc, pool, sc.f.interactor_id, provider, agent_assignment_id=foreign)
        assert (code(response), error_of(response)) == (404, "not_found"), response.text
        assert provider.calls == 0
        assert counts(sc) == NOTHING_KEPT
        n = rows(
            sc.engine,
            "SELECT count(*) AS n FROM ai.context_requests WHERE agent_assignment_id = :a",
            a=foreign,
        )[0]["n"]
        assert n == 0
    finally:
        with sc.engine.begin() as c:
            c.execute(
                text("DELETE FROM ai.agent_assignments WHERE agent_assignment_id = :a"),
                {"a": foreign},
            )
            c.execute(text("SET LOCAL session_replication_role = replica"))
            c.execute(text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": other})


# =====================================================================================================================
# T-11: the party perspective (decision G-2), who may request which party's context
# =====================================================================================================================

OWNER_REL = ("owner",)


def run_case(
    sc: Scene,
    pool: Pool,
    user: uuid.UUID,
    party: uuid.UUID | None = None,
    *,
    reveal: bool = True,
    **kw: Any,
) -> tuple[Any, Spy]:
    spy = Spy(dialogue="Hello.", reveal_first_candidate=reveal)
    overrides = dict(kw)
    if party is not None:
        overrides["requesting_party_id"] = party
    with Recorder(pool.engine) as recorded:
        response = turn(sc, pool, user, spy, **overrides)
    spy.events = recorded.events  # type: ignore[attr-defined]
    return response, spy


def assert_refused_without_disclosure(
    sc: Scene, response: Any, spy: Spy, party: uuid.UUID | None = None
) -> None:
    assert (code(response), error_of(response)) == (404, "not_found"), response.text
    assert spy.calls == 0, "the provider must never receive a refused perspective's context"
    # refused by the request transaction itself (the early check): no engine transaction (T1) ever started
    events: list[str] = spy.events  # type: ignore[attr-defined]
    assert not any("ai.agent_assignments" in e for e in events), events
    state = counts(sc, party=party)
    assert state == {**NOTHING_KEPT, "events": 0}, state


def test_t11_authorized_controls_receive_only_their_own_partys_beliefs(
    sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    add_beliefs_and_party_b(sc)
    player = persona(
        sc, "Owner Player", ("campaign.view", "character.interact"), "owner"
    )  # U1: view_knowledge by relationship
    portrayer = persona(
        sc, "Portrayer AGM", ("campaign.view", "character.interact", "canon.edit"), "portrayer"
    )  # U10
    for user in (player, sc.f.interactor_id, portrayer):  # U1, U6 (gm role: view_knowledge), U10
        response, spy = run_case(
            sc, pool, user, reveal=False
        )  # a reveal would change what the next caller knows
        assert code(response) == 200, (user, response.text)
        assert spy.calls == 1
        known = " ".join(json.loads(spy.payloads[0])["known_facts_about_npc"])
        assert A_BELIEF in known and B_BELIEF not in known  # only the requesting party's beliefs


def test_t11a_u2_a_player_naming_another_campaign_party_is_refused_at_the_request(
    sc: Scene, pool: Pool
) -> None:
    """Fail-before (the parent): 200; the provider payload contains the rival party's belief and a public candidate is
    auto-revealed to the rival party."""
    set_sensitivity(sc, "public")
    party_b = add_beliefs_and_party_b(sc)
    player = persona(sc, "Owner Player", ("campaign.view", "character.interact"), "owner")
    response, spy = run_case(sc, pool, player, party=party_b)
    assert_refused_without_disclosure(sc, response, spy, party_b)
    assert counts(sc, party=party_b)["knows"] == 0


def test_t11c_u7_a_gm_naming_a_party_the_character_is_not_in_is_refused(
    sc: Scene, pool: Pool
) -> None:
    """No canon.edit bypass (G-2). Fail-before (the parent): 200, B's beliefs disclosed, the reveal applied to B."""
    set_sensitivity(sc, "public")
    party_b = add_beliefs_and_party_b(sc)
    response, spy = run_case(sc, pool, sc.f.interactor_id, party=party_b)
    assert_refused_without_disclosure(sc, response, spy, party_b)


def test_t11c_u8_a_gm_is_refused_when_the_campaign_clock_is_unset(sc: Scene, pool: Pool) -> None:
    set_sensitivity(sc, "public")
    unset_clock(sc)
    response, spy = run_case(sc, pool, sc.f.interactor_id)
    assert_refused_without_disclosure(sc, response, spy)


def test_t11c_u9_an_assistant_gm_without_view_knowledge_or_a_relationship_is_refused(
    sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    agm = persona(sc, "Assistant GM", ("campaign.view", "character.interact", "canon.edit"))
    response, spy = run_case(sc, pool, agm)
    assert_refused_without_disclosure(sc, response, spy)


@pytest.mark.parametrize(
    "case", ("viewer_relationship", "left_party", "clock_unset", "foreign_campaign_party")
)
def test_t11b_u3_u4_u5_u11_each_unproved_perspective_is_one_404(
    case: str, sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    party: uuid.UUID | None = None
    if case == "viewer_relationship":  # U5: a viewer relationship gives no view_knowledge
        user = persona(sc, "Viewer", ("campaign.view", "character.interact"), "viewer")
    else:
        user = persona(sc, "Owner Player", ("campaign.view", "character.interact"), "owner")
    if case == "left_party":
        leave_party(sc)
    elif case == "clock_unset":
        unset_clock(sc)
    elif case == "foreign_campaign_party":
        with sc.engine.begin() as c:
            party = make_party(c, sc.f.world_id, "Elsewhere")  # a party that no campaign has
    response, spy = run_case(sc, pool, user, party=party)
    assert_refused_without_disclosure(sc, response, spy)


def test_t11g_a_caller_without_interact_is_a_403_before_any_perspective_judgement(
    sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    party_b = add_beliefs_and_party_b(sc)
    no_interact = persona(sc, "No Interact", ("campaign.view", "character.view_knowledge"))
    response, spy = run_case(sc, pool, no_interact, party=party_b)
    assert (code(response), error_of(response)) == (403, "forbidden"), response.text
    assert spy.calls == 0 and counts(sc) == NOTHING_KEPT


@pytest.mark.parametrize(
    "change", ("view_knowledge_removed", "left_the_party", "party_dissociated")
)
def test_t11d_a_perspective_that_lapses_before_t1s_final_check_discloses_nothing(
    change: str, sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    user = persona(sc, "Owner Player", ("campaign.view", "character.interact"), "owner")
    spy = Spy(dialogue="Hello.", reveal_first_candidate=True)
    with StatementGate(
        pool.engine, CONTEXT_SNAPSHOT_INSERT, strict=True, hold_seconds=30.0
    ) as gate:
        request = gate.track(run_in_thread("turn", lambda: turn(sc, pool, user, spy)))
        gate.wait_reached()
        if change == "view_knowledge_removed":
            with sc.engine.begin() as c:
                c.execute(
                    text(
                        "DELETE FROM security.membership_character_relationships WHERE campaign_membership_id = :m"
                    ),
                    {"m": membership_of(sc, user)},
                )
        else:
            LAPSES[change][0](sc, user)
        gate.release()
        assert request.done.wait(30.0)
    assert code(request.result) == 404, request.result.text
    assert spy.calls == 0 and counts(sc) == NOTHING_KEPT


@pytest.mark.parametrize(
    "change", ("view_knowledge_removed", "left_the_party", "party_dissociated", "clock_moved")
)
def test_t11e_a_perspective_that_lapses_during_the_provider_call_reveals_nothing(
    change: str, sc: Scene, pool: Pool
) -> None:
    """Fail-before (the parent): 200 and the public reveal is applied to the party."""
    set_sensitivity(sc, "public")
    user = persona(sc, "Owner Player", ("campaign.view", "character.interact"), "owner")

    def lapse() -> None:
        if change == "view_knowledge_removed":
            with sc.engine.begin() as c:
                c.execute(
                    text(
                        "DELETE FROM security.membership_character_relationships WHERE campaign_membership_id = :m"
                    ),
                    {"m": membership_of(sc, user)},
                )
        elif change == "clock_moved":
            leave_party(sc)
        else:
            LAPSES[change][0](sc, user)

    spy = Spy(dialogue="Hello.", reveal_first_candidate=True, during=lapse)
    response = turn(sc, pool, user, spy)
    assert code(response) == 404, response.text
    assert spy.calls == 1
    assert counts(sc) == DISCLOSED_ONLY, counts(sc)


# =====================================================================================================================
# T-7 and T-8: lock-order races on the real routes, both arrivals
# =====================================================================================================================


def interactor_turn(sc: Scene, pool: Pool) -> Callable[[], Any]:
    return lambda: turn(
        sc, pool, sc.f.interactor_id, Spy(dialogue="Hi.", reveal_first_candidate=True)
    )


@pytest.mark.parametrize(
    "arrival", ("edit_parked", "turn_parked_at_the_apply", "turn_parked_at_n5")
)
def test_t7a_the_auto_apply_and_a_definition_edit_do_not_deadlock(
    arrival: str, sc: Scene, pool: Pool, owner_is_world_editor: Any
) -> None:
    """P-3. Fail-before (the parent): one 40P01 in both arrivals (the apply took `ki` and then the entity `FOR SHARE`; the
    edit takes the entity `FOR UPDATE` and then `ki`). E2's T2 takes the entity first (N4), then `ki` (N5): the edit and
    the turn meet at the entity row."""
    set_sensitivity(sc, "public")
    turn_call = interactor_turn(sc, pool)

    def edit() -> Any:
        return definition_edit(sc, pool, edit_body(sc))

    if arrival == "edit_parked":  # Q-2c: the edit holds the entity and waits to update `ki`
        o = race(sc, pool, gate_pattern=EDIT_KI_UPDATE, parked=edit, second=turn_call)
        edited, turned = o.results["parked"], o.results["second"]
    elif (
        arrival == "turn_parked_at_the_apply"
    ):  # Q-2d: the turn holds `ki` (and, in E2, the entity) at the apply's guard
        o = race(sc, pool, gate_pattern=ENTITY_ANY_SHARE, nth=2, parked=turn_call, second=edit)
        turned, edited = o.results["parked"], o.results["second"]
    else:  # E2's own order only: the turn holds the entity `SHARE` and the campaign, and has not asked for `ki`
        o = race(sc, pool, gate_pattern=KI_UPDATE_N5, parked=turn_call, second=edit)
        turned, edited = o.results["parked"], o.results["second"]
    assert_clean(o)
    assert o.blocked, f"the second request never queued behind the parked one: {o.summary()}"
    assert code(turned) == 200 and code(edited) == 200, o.summary()
    assert not pool.failures, pool.failures


@pytest.mark.parametrize("arrival", ("turn_parked", "turn_parked_at_n5", "grant_parked"))
def test_t7b_the_auto_apply_and_a_grant_on_the_item_serialize(
    arrival: str, sc: Scene, pool: Pool
) -> None:
    """R-4 regression (absent today; N3 keeps it absent): the grant takes the campaign `FOR UPDATE` and then the item's
    entity; T2 takes the campaign `KEY SHARE` (N3) before any entity lock."""
    set_sensitivity(sc, "public")
    turn_call = interactor_turn(sc, pool)

    def grant() -> Any:
        return post(pool, sc.owner, f"{sc.base}/resource-grants", grant_body(sc, "knowledge"))

    if arrival == "turn_parked":
        o = race(sc, pool, gate_pattern=EVENT_INSERT, parked=turn_call, second=grant)
        turned, granted = o.results["parked"], o.results["second"]
    elif (
        arrival == "turn_parked_at_n5"
    ):  # E2's order only: the turn holds the entity `SHARE` and must already hold the campaign
        o = race(sc, pool, gate_pattern=KI_UPDATE_N5, parked=turn_call, second=grant)
        turned, granted = o.results["parked"], o.results["second"]
    else:
        o = race(sc, pool, gate_pattern=GRANT_TARGET_ENTITY, parked=grant, second=turn_call)
        turned, granted = o.results["second"], o.results["parked"]
    assert_clean(o)
    assert o.blocked, f"the second request never queued behind the parked one: {o.summary()}"
    assert code(turned) == 200 and code(granted) == 201, o.summary()
    assert counts(sc)["knows"] == 1


@pytest.mark.parametrize("arrival", ("turn_parked", "review_parked"))
def test_t7c_the_auto_apply_and_the_review_of_another_reveal_proposal_serialize(
    arrival: str, sc: Scene, pool: Pool
) -> None:
    proposal = new_proposal(sc, "reveal")  # secret: pending
    set_sensitivity(sc, "public")
    turn_call = interactor_turn(sc, pool)

    def review() -> Any:
        return review_call(sc, pool, proposal, "approve")

    if arrival == "turn_parked":
        o = race(sc, pool, gate_pattern=KI_UPDATE_N5, parked=turn_call, second=review)
        turned, reviewed = o.results["parked"], o.results["second"]
    else:
        o = race(sc, pool, gate_pattern=EVENT_INSERT, parked=review, second=turn_call)
        reviewed, turned = o.results["parked"], o.results["second"]
    assert_clean(o)
    assert code(turned) == 200 and code(reviewed) == 200, o.summary()
    state = counts(sc)
    assert (
        state["knows"] == 1 and state["events"] == 1
    )  # exactly one reveal; the other side was the applied no-op


@pytest.mark.parametrize("arrival", ("turn_parked", "reveal_parked"))
def test_t7d_the_auto_apply_and_the_human_reveal_serialize(
    arrival: str, sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    turn_call = interactor_turn(sc, pool)

    def reveal() -> Any:
        return human_reveal(sc, pool)

    if arrival == "turn_parked":
        o = race(sc, pool, gate_pattern=ENTITY_ANY_SHARE, nth=2, parked=turn_call, second=reveal)
        turned, revealed = o.results["parked"], o.results["second"]
    else:
        o = race(sc, pool, gate_pattern=r"FOR UPDATE OF ki$", parked=reveal, second=turn_call)
        revealed, turned = o.results["parked"], o.results["second"]
    assert_clean(o)
    assert code(turned) == 200 and code(revealed) in (200, 201), o.summary()
    assert counts(sc)["knows"] == 1 and counts(sc)["events"] == 1


@pytest.mark.parametrize("writer", ("role_revoke", "membership_end"))
def test_t8_a_revocation_requested_during_t2_waits_and_the_next_turn_is_refused(
    writer: str, sc: Scene, pool: Pool
) -> None:
    set_sensitivity(sc, "public")
    user = persona(sc, "Revoked Player", BASE_CAPS)
    if writer == "role_revoke":
        role = rows(
            sc.engine,
            "SELECT membership_role_id AS r FROM security.membership_roles WHERE campaign_membership_id = :m",
            m=membership_of(sc, user),
        )[0]["r"]
        path = f"{sc.base}/memberships/roles/{role}/revoke"
    else:
        path = f"{sc.base}/memberships/{membership_of(sc, user)}/end"

    def turn_call() -> Any:
        return turn(sc, pool, user, Spy(dialogue="Hi.", reveal_first_candidate=True))

    def writer_call() -> Any:
        return post(pool, sc.owner, path, {})

    o = race(sc, pool, gate_pattern=ENTITY_ANY_SHARE, nth=2, parked=turn_call, second=writer_call)
    assert_clean(o)
    assert code(o.results["second"]) == 200, o.summary()
    assert o.status("parked")[0] in (200, 403, 404), o.summary()
    refused = turn(sc, pool, user, Spy(dialogue="Hi."))
    assert code(refused) in (403, 404), refused.text


# =====================================================================================================================
# T-5c and T-7e
# =====================================================================================================================

R_FINAL = r"^WITH clock AS MATERIALIZED"


def test_t5c_a_lapse_between_the_dependency_and_the_request_final_check_refuses_before_t1(
    sc: Scene, pool: Pool
) -> None:
    """The request transaction's own final check (A1) is the first one: gate it, lapse the role, release."""
    user = persona(sc, "Lapse At R", BASE_CAPS)
    provider = Spy(dialogue="Welcome.", reveal_first_candidate=True)
    with StatementGate(pool.engine, R_FINAL, strict=True, hold_seconds=30.0) as gate:
        request = gate.track(run_in_thread("turn", lambda: turn(sc, pool, user, provider)))
        gate.wait_reached()
        revoke_role(sc, user)
        gate.release()
        assert request.done.wait(30.0)
    assert code(request.result) in (403, 404), request.result.text
    assert provider.calls == 0 and counts(sc) == NOTHING_KEPT
    assert idle_in_transaction(sc.engine) == 0


@pytest.mark.parametrize("arrival", ("turn_parked", "grant_parked"))
def test_t7e_t1_and_a_grant_on_the_npc_do_not_wait_in_a_cycle(
    arrival: str, sc: Scene, pool: Pool
) -> None:
    """T1 takes only the NPC entity `FOR SHARE` (no campaign lock); a grant takes the campaign and then the entity."""
    turn_call = interactor_turn(sc, pool)

    def grant() -> Any:
        return post(pool, sc.owner, f"{sc.base}/resource-grants", grant_body(sc, "npc"))

    if arrival == "turn_parked":
        o = race(sc, pool, gate_pattern=ENTITY_ANY_SHARE, parked=turn_call, second=grant)
        turned, granted = o.results["parked"], o.results["second"]
    else:
        o = race(sc, pool, gate_pattern=GRANT_TARGET_ENTITY, parked=grant, second=turn_call)
        turned, granted = o.results["second"], o.results["parked"]
    assert_clean(o)
    assert code(turned) == 200 and code(granted) == 201, o.summary()


# =====================================================================================================================
# Correction C-1 / C-2 / C-3: the final snapshot judges the party, incomplete player summaries are refused, T-5(b)
# =====================================================================================================================

FINAL_STATEMENT = r"^WITH clock AS MATERIALIZED \(SELECT clock_timestamp\(\) AS t_auth\)"


def end_membership_then_clock_moved_setup(sc: Scene) -> Callable[[], None]:
    """The character's membership ends at 150 while the clock reads 100 (still a member); the returned change moves the
    clock to 200 (no longer a member)."""
    with sc.engine.begin() as c:
        left = make_world_time(c, sc.f.world_id, 150)
        later = make_world_time(c, sc.f.world_id, 200)
        c.execute(
            text(
                "UPDATE campaign.party_memberships SET effective_to_world_time_id = :left "
                "WHERE party_id = :p AND member_entity_id = :c"
            ),
            {"left": left, "p": sc.f.party_id, "c": sc.f.pc_id},
        )

    def move() -> None:
        with sc.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE campaign.timeline_clocks SET current_world_time_id = :w WHERE timeline_id = :t"
                ),
                {"w": later, "t": sc.f.timeline_id},
            )

    return move


T1_START_RE = re.compile(r"FROM ai\.agent_assignments\s+WHERE agent_assignment_id")


class T1StartMarker:
    """Records T1's first statement (the active-assignment read of `_lock_active_assignment`; T2 locks by the output). The request transaction and its early checks never run it, so any hit means the command
    entered a transaction after the request's own authorization."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self.seen: list[str] = []

    def _record(self, _c: Any, _cur: Any, statement: Any, *_: Any) -> None:
        flat = " ".join(str(statement).split())
        if T1_START_RE.search(flat):
            self.seen.append(flat)

    def __enter__(self) -> "T1StartMarker":
        event.listen(self._engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *_: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._record)


@pytest.mark.parametrize(
    "change", ("left_the_party", "party_dissociated", "clock_moved", "clock_unset")
)
@pytest.mark.parametrize("phase", ("request", "t1", "t2"))
def test_c3_a_party_or_clock_change_before_each_final_snapshot_decides_it(
    phase: str, change: str, sc: Scene, pool: Pool
) -> None:
    """The gate stops the phase's FINAL statement itself, after every early check and every earlier read of that
    transaction; the change commits there. The final snapshot (which evaluates the association and the membership at the
    clock in its own statement) must see it: R and T1 refuse before any disclosure, T2 rolls back and T1 stays."""
    set_sensitivity(sc, "public")
    user = persona(sc, "Owner Player", ("campaign.view", "character.interact"), "owner")
    mutate: Callable[[], None]
    if change == "clock_moved":
        mutate = end_membership_then_clock_moved_setup(sc)
    elif change == "clock_unset":
        mutate = lambda: unset_clock(sc)  # noqa: E731
    elif change == "party_dissociated":
        mutate = lambda: dissociate_party(sc)  # noqa: E731
    else:
        mutate = lambda: leave_party(sc)  # noqa: E731
    spy = Spy(dialogue="Hello.", reveal_first_candidate=True)
    nth = {"request": 1, "t1": 2, "t2": 3}[phase]
    t1_started = T1StartMarker(pool.engine)
    with t1_started, NthGate(pool.engine, FINAL_STATEMENT, nth) as gate:
        request = gate.track(run_in_thread("turn", lambda: turn(sc, pool, user, spy)))
        gate.wait_reached()
        assert gate.matched is not None and re.search(FINAL_STATEMENT, gate.matched)
        assert spy.calls == (
            1 if phase == "t2" else 0
        )  # the gate is at the phase's own final statement
        mutate()
        gate.release()
        assert request.done.wait(30.0)
    response = request.result
    assert (code(response), error_of(response)) == (404, "not_found"), response.text
    assert spy.calls == (1 if phase == "t2" else 0)
    assert counts(sc) == (DISCLOSED_ONLY if phase == "t2" else NOTHING_KEPT), counts(sc)
    if phase == "request":
        # T1 never starts once the request's own final check refuses (not merely refused by T1's early check)
        assert t1_started.seen == [], t1_started.seen
    assert idle_in_transaction(sc.engine) == 0


def test_c3_the_t1_marker_fires_on_an_authorized_turn(sc: Scene, pool: Pool) -> None:
    """Control for the request-phase marker: an authorized turn runs T1, so the marker sees it once."""
    set_sensitivity(sc, "public")
    user = persona(sc, "Owner Player", ("campaign.view", "character.interact"), "owner")
    with T1StartMarker(pool.engine) as marker:
        response = turn(sc, pool, user, Spy(dialogue="Hello.", reveal_first_candidate=True))
    assert code(response) == 200, response.text
    assert len(marker.seen) == 1, marker.seen  # only T1 reads the active assignment


def test_c3_the_control_without_a_change_passes_every_final_snapshot(sc: Scene, pool: Pool) -> None:
    set_sensitivity(sc, "public")
    user = persona(sc, "Owner Player", ("campaign.view", "character.interact"), "owner")
    response = turn(sc, pool, user, Spy(dialogue="Hello.", reveal_first_candidate=True))
    assert code(response) == 200 and counts(sc)["knows"] == 1


def test_t5b_a_party_made_inactive_during_the_call_and_a_lapse_give_the_domain_refusal_and_roll_t2_back(
    sc: Scene, pool: Pool
) -> None:
    """The domain refusal precedes the final check (design refusal precedence, R-D2): the party is archived and the caller's
    role is revoked after T2's early perspective check and before the apply, so the apply's `validate_campaign_party` refuses
    (409 party_not_active) and that is the response, never the lapse's 403. T2 is rolled back whole (no output, no proposal,
    no reveal, no event); T1's request row remains."""
    set_sensitivity(sc, "public")
    user = persona(sc, "Lapsing Player", BASE_CAPS)
    spy = Spy(dialogue="Hello.", reveal_first_candidate=True)
    with StatementGate(pool.engine, OUTPUT_INSERT, strict=True, hold_seconds=30.0) as gate:
        request = gate.track(run_in_thread("turn", lambda: turn(sc, pool, user, spy)))
        gate.wait_reached()
        with (
            sc.engine.begin() as c
        ):  # after T2's early checks (they ran before this gated output INSERT, T2's first write)
            c.execute(
                text(
                    "UPDATE campaign.parties SET lifecycle_status_id = "
                    "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                    "WHERE party_id = :p"
                ),
                {"p": sc.f.party_id},
            )
        revoke_role(sc, user)
        gate.release()
        assert request.done.wait(30.0)
    response = request.result
    assert (code(response), error_of(response)) == (409, "party_not_active"), response.text
    assert spy.calls == 1
    assert counts(sc) == DISCLOSED_ONLY, counts(sc)
    assert idle_in_transaction(sc.engine) == 0
    # control: the same inactive party without a lapse gives the same domain refusal (so it is not the lapse's)
    other = persona(sc, "Second Player", BASE_CAPS)
    again = turn(sc, pool, other, Spy(dialogue="Hello.", reveal_first_candidate=True))
    assert (code(again), error_of(again)) == (409, "party_not_active")
    assert counts(sc)["outputs"] == 0 and counts(sc)["proposals"] == 0


# --- C-2: a player summary needs its whole perspective ------------------------------------------------------------------


def direct_summary(sc: Scene, **overrides: Any) -> Any:
    from tests.ai_e2_support import synthesis

    arguments: dict[str, Any] = {
        "user_id": sc.f.interactor_id,
        "agent_assignment_id": sc.f.assignment_id,
        "campaign_id": sc.campaign_id,
        "audience_tier": "player_summary",
        "question_text": "What do we know?",
        "provider": Spy(dialogue="Summary."),
        "timeline_id": sc.f.timeline_id,
        "requesting_character_id": sc.f.pc_id,
        "requesting_party_id": sc.f.party_id,
    }
    arguments.update(overrides)
    return synthesis(sc.engine, **arguments)


@pytest.mark.parametrize(
    "missing", ("timeline_id", "requesting_character_id", "requesting_party_id")
)
def test_c2_a_player_summary_missing_an_input_is_refused_before_any_database_work(
    missing: str, sc: Scene
) -> None:
    statements: list[str] = []

    def record(_c: Any, _cur: Any, statement: Any, *_: Any) -> None:
        statements.append(str(statement))

    event.listen(sc.engine, "before_cursor_execute", record)
    try:
        with pytest.raises(ValueError, match="player_summary"):
            direct_summary(sc, **{missing: None})
    finally:
        event.remove(sc.engine, "before_cursor_execute", record)
    assert statements == []
    assert counts(sc) == NOTHING_KEPT


def test_c2_a_complete_player_summary_registers_the_perspective_and_succeeds(sc: Scene) -> None:
    provider = Spy(dialogue="Summary.")
    result = direct_summary(sc, provider=provider)
    assert result.answer is not None and provider.calls == 1
    assert counts(sc)["outputs"] == 1


def test_c2_a_complete_player_summary_is_judged_on_the_perspective(sc: Scene) -> None:
    """The perspective requirement is always registered: with the party dissociated the command refuses."""
    from dnd_ai.domain.errors import DomainAuthorizationError

    dissociate_party(sc)
    provider = Spy(dialogue="Summary.")
    with pytest.raises(DomainAuthorizationError):
        direct_summary(sc, provider=provider)
    assert provider.calls == 0 and counts(sc) == NOTHING_KEPT
