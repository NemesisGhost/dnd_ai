# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 E1-C1: the E1 approve-reveal and the knowledge definition edit take the item's locks in one order.

Before the correction the approve-reveal took `knowledge.knowledge_items ... FOR UPDATE OF ki` and then the item's
`core.entities` row `FOR SHARE`, while the definition edit takes the entity row `FOR UPDATE` and then updates the item:
a two-party cycle (plan 6.47.3; probes Q-2a/Q-2b, one 40P01 each, deadlock delta 1, in 3 of 3 runs, at `d932d7f`).
The correction (plan 6.58) takes the item's entity row `FOR SHARE` first in `_apply_proposal`'s reveal branch.

Both operation orders, through the real routes (the review route and `POST .../authoring/knowledge/{id}/update`) on a
pool engine with the commit guard installed. Each case asserts, in order: the gate fired (an incompatible gate is
reported, never read as the absence of a cycle); the competitor queued behind the parked backend and only behind it, on
the expected statement; no driver exception and an unchanged deadlock counter; both operations succeeded; and the
durable state is the union of both effects (the proposal applied with one review, one reveal event and one party
knowledge row, the definition changed with its row version advanced).
"""

import re
import uuid
from typing import Any

import pytest
from sqlalchemy import event

from tests.database.test_r01_e1_r3_three_party import (  # noqa: F401 - fixtures by name
    definition_edit,
    durable_state,
    edit_body,
    owner_is_world_editor,
)
from tests.database.test_r01_e1_review_route import (  # noqa: F401 - fixtures by name
    Scene,
    new_proposal,
    review_call,
    sc,
)
from tests.database.test_r01_s3_authoring_routes import code
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixtures by name
    Outcome,
    Pool,
    assert_clean,
    assert_waited_on_parked,
    pool,
    race,
)

pytestmark = pytest.mark.database

#: The correction's statement: the item's entity row, shared, before the item row is locked.
ENTITY_SHARE_FIRST = r"^SELECT 1 FROM core\.entities WHERE entity_id = \S+ FOR SHARE\s*$"
#: The shared reveal's item lock (`_lock_knowledge_item`).
ITEM_FOR_UPDATE = (
    r"FROM knowledge\.knowledge_items ki JOIN core\.entities e ON .* FOR UPDATE OF ki$"
)
#: The definition edit's item update and its entity lock (`lock_entities`, one id with a world).
EDIT_ITEM_UPDATE = r"^UPDATE knowledge\.knowledge_items SET"
EDIT_ENTITY_LOCK = (
    r"FROM core\.entities e WHERE e\.entity_id = \S+ AND e\.world_id = \S+ FOR UPDATE OF e\s*$"
)


def settled(sc: Scene, proposal: uuid.UUID, before: dict[str, Any]) -> dict[str, Any]:
    after = durable_state(sc, proposal)
    assert after["proposal_status"] == "applied", after
    assert (
        after["reviews"] == 1 and after["party_knowledge"] == 1 and after["reveal_events"] == 1
    ), after
    assert after["sensitivity"] != before["sensitivity"], after  # the edit's effect
    assert after["row_version"] > before["row_version"], after
    return after


def test_review_first_the_edit_waits_for_the_reviews_entity_lock_and_both_commit(
    sc: Scene, pool: Pool, owner_is_world_editor: uuid.UUID
) -> None:
    """The review is parked after its entity lock and before the item lock; the edit queues at its entity lock behind
    it (the review holds the entity `FOR SHARE`), and neither deadlocks."""
    proposal = new_proposal(sc, "reveal")
    body = edit_body(sc)
    before = durable_state(sc, proposal)
    o = race(
        sc,
        pool,
        gate_pattern=ITEM_FOR_UPDATE,
        parked=lambda: review_call(sc, pool, proposal, "approve"),
        second=lambda: definition_edit(sc, pool, body),
    )
    # the outcome keeps the first 150 characters of the gated statement
    assert o.gate_statement is not None
    assert o.gate_statement.startswith("SELECT e.world_id FROM knowledge.knowledge_items ki"), (
        o.gate_statement
    )
    assert_waited_on_parked(o, EDIT_ENTITY_LOCK)
    assert_clean(o)
    assert (code(o.results["parked"]), code(o.results["second"])) == (200, 200), o.summary()
    settled(sc, proposal, before)


def test_edit_first_the_review_waits_for_the_edits_entity_lock_and_both_commit(
    sc: Scene, pool: Pool, owner_is_world_editor: uuid.UUID
) -> None:
    """The edit is parked at its item UPDATE (it holds the entity `FOR UPDATE`); the review queues at its new entity
    lock behind it, before it holds the item row (the pre-correction order held the item row here, the cycle)."""
    proposal = new_proposal(sc, "reveal")
    body = edit_body(sc)
    before = durable_state(sc, proposal)
    o = race(
        sc,
        pool,
        gate_pattern=EDIT_ITEM_UPDATE,
        parked=lambda: definition_edit(sc, pool, body),
        second=lambda: review_call(sc, pool, proposal, "approve"),
    )
    assert o.gate_statement is not None and re.search(EDIT_ITEM_UPDATE, o.gate_statement)
    assert_waited_on_parked(o, ENTITY_SHARE_FIRST)
    assert_clean(o)
    assert (code(o.results["parked"]), code(o.results["second"])) == (200, 200), o.summary()
    settled(sc, proposal, before)


def test_the_approve_reveal_locks_the_entity_before_the_item_and_nothing_else_changes(
    sc: Scene, pool: Pool
) -> None:
    """Statement order of the real review: the entity share precedes the item `FOR UPDATE`, and the item lock is taken
    once per reveal. The durable result is the unchanged one (applied, one review, one event, one party row)."""
    proposal = new_proposal(sc, "reveal")
    statements: list[str] = []

    def record(_c: Any, _cur: Any, statement: Any, *_: Any) -> None:
        statements.append(" ".join(str(statement).split()))

    event.listen(pool.engine, "before_cursor_execute", record)
    try:
        response = review_call(sc, pool, proposal, "approve")
    finally:
        event.remove(pool.engine, "before_cursor_execute", record)
    assert code(response) == 200, response.text
    first_share = next(i for i, s in enumerate(statements) if re.search(ENTITY_SHARE_FIRST, s))
    item_lock = [i for i, s in enumerate(statements) if re.search(ITEM_FOR_UPDATE, s)]
    assert len(item_lock) == 1 and first_share < item_lock[0], (first_share, item_lock)
    after = durable_state(sc, proposal)
    assert after["proposal_status"] == "applied" and after["reviews"] == 1, after
    assert after["party_knowledge"] == 1 and after["reveal_events"] == 1, after


def test_a_reject_never_reaches_the_reveal_branch_and_takes_no_item_lock(
    sc: Scene, pool: Pool
) -> None:
    """A reject never reaches the reveal branch, so it takes no item lock at all; the correction adds nothing there."""
    proposal = new_proposal(sc, "reveal")
    statements: list[str] = []

    def record(_c: Any, _cur: Any, statement: Any, *_: Any) -> None:
        statements.append(" ".join(str(statement).split()))

    event.listen(pool.engine, "before_cursor_execute", record)
    try:
        response = review_call(sc, pool, proposal, "reject")
    finally:
        event.remove(pool.engine, "before_cursor_execute", record)
    assert code(response) == 200, response.text
    assert not [
        s for s in statements if re.search(ENTITY_SHARE_FIRST, s) or re.search(ITEM_FOR_UPDATE, s)
    ]
    assert durable_state(sc, proposal)["proposal_status"] == "rejected"
