# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 O-2 (design 5.3 N-5, decision D-8): a direct keyed test for each designated adopter that the keyed sweep's
existing route and API suites do not reach with a successful, reserving request.

The sweep (a temporary plugin that adds an `Idempotency-Key` to every keyless request to the 129 routes of
`R01_DEFERRED_RESERVATION_ROUTES`, retained as evidence, not committed) reached 127 of them with a `RESERVED`
`finalize` that held campaign evidence. These two had no such request: `items/{item_instance_id}/unequip` is not
exercised by any suite, and `quests/{quest_id}/abandon` appears only in a loop of refusals. Each test drives the route
with a key, to success, then replays the same key:

* a missed evidence site fails closed (the keyed request ends in the sanitized 500 of an unmet obligation), so the 200
  proves the plan took its campaign evidence at the scope and `finalize` held;
* the replay answers the stored receipt, writes nothing again and leaves the audit rows as they were.

These requests run through the in-process authoring harness, as the sibling suites do; the harness does not evaluate the
reservation's campaign foreign-key check (design 4.4), and the real-connection modules carry that.
"""

import pytest

from dnd_ai.domain.data_classification import replay_body
from tests.content_support import ContentSetup
from tests.database.test_api_item_runtime import (  # noqa: F401 - fixture by name
    award,
    harness,
    item,
    op,
    pc,
    s,
)
from tests.database.test_api_quest_runtime import (  # noqa: F401 - fixtures by name
    published_quest,
    runtime,
)

pytestmark = pytest.mark.database


def test_the_keyed_unequip_route_succeeds_and_replays_its_receipt(s: ContentSetup) -> None:
    holder = pc(s, "Aldric")
    made = item(s)
    item_id = made["item_instance_id"]
    token = award(s, item_id, holder).json()["last_event_id"]
    equipped = op(s, item_id, "equip", token)
    assert equipped.status_code == 200 and equipped.json()["is_equipped"] is True
    token = equipped.json()["last_event_id"]

    key = s.gm.fresh_key()
    url = f"/campaigns/{s.cid}/items/{item_id}/unequip"
    first = s.gm.post_raw(url, {"expected_last_event_id": token}, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["is_equipped"] is False
    audits = len(s.audit("unequip_item"))
    assert audits == 1

    again = s.gm.post_raw(url, {"expected_last_event_id": token}, key=key)
    assert again.status_code == 200, again.text
    assert again.json() == replay_body(first.json()), "the same key answers the stored receipt"
    assert len(s.audit("unequip_item")) == audits, "the replay wrote nothing again"


def test_the_keyed_quest_abandon_route_succeeds_and_replays_its_receipt(s: ContentSetup) -> None:
    quest = published_quest(s)
    quest_id = quest["quest_id"]
    assert runtime(s, quest_id, "activate", None).status_code == 200

    key = s.gm.fresh_key()
    url = f"/campaigns/{s.cid}/quests/{quest_id}/abandon"
    first = s.gm.post_raw(url, {"expected_status": "active"}, key=key)
    assert first.status_code == 200, first.text
    audits = len(s.audit("quest_abandon"))
    assert audits == 1

    again = s.gm.post_raw(url, {"expected_status": "active"}, key=key)
    assert again.status_code == 200, again.text
    assert again.json() == replay_body(first.json()), "the same key answers the stored receipt"
    assert len(s.audit("quest_abandon")) == audits, "the replay wrote nothing again"
