# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 O-2 (design 4.3 and N-6): the two relationship savepoints do not change a keyed request's response.

`create_relationship` and `update_relationship` each run their typed write in `connection.begin_nested()`; a unique /
exclusion violation rolls the savepoint back and the command re-raises the translated refusal (409
`membership_overlap`). AM-1.8 latches an opted-in plan at that rollback, so the request, already refusing, must still
answer exactly what the unkeyed request answers, persist nothing (no row, audit row or reservation) and leave the key
reusable. The comparison is made inside one test, keyed against unkeyed, and the same assertions hold at the parent
(`369bd8a`) where the request is not opted in, so the response is identical to what it was.

The savepoint inventory itself (only these two sites, both re-raising) is pinned in `tests/unit/test_r01_o2_structure.py`.
"""

import pytest
from sqlalchemy import text

from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_organization_members import (  # noqa: F401 - fixtures by name
    act,
    harness,
    join,
    npc,
    organization,
    s,
)

pytestmark = pytest.mark.database


def _reservations(s: ContentSetup, key: str) -> int:
    return int(
        s.connection.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :k"),
            {"k": key},
        ).scalar_one()
    )


def _membership_rows(s: ContentSetup) -> int:
    return int(
        s.connection.execute(
            text(
                "SELECT count(*) FROM world.relationships WHERE relationship_id IN "
                "(SELECT relationship_id FROM world.relationship_participants)"
            )
        ).scalar_one()
    )


def _comparable(response: object) -> tuple[int, str, str]:
    body = response.json()  # type: ignore[attr-defined]
    error = body["error"]
    return (response.status_code, error["code"], error["message"])  # type: ignore[attr-defined]


def _create_body(org: str, member: str, start: str) -> dict[str, object]:
    return {
        "kind": "membership",
        "relationship_type": "membership",
        "participants": [
            {"entity_id": member, "role": "member"},
            {"entity_id": org, "role": "organization"},
        ],
        "started_world_time_id": start,
    }


def test_a_keyed_create_that_overlaps_is_the_unkeyed_refusal_and_leaves_the_key_reusable(
    s: ContentSetup,
) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    times = Times(s)
    year1, year3 = times.at(1), times.at(3)
    first = join(s, guild, mira, year1, role="Initiate")
    assert first.status_code == 201
    rows_before = _membership_rows(s)

    unkeyed = s.gm.post_raw(s.url("relationships"), _create_body(guild, mira, year3), key=None)
    key = s.gm.fresh_key()
    keyed = s.gm.post_raw(s.url("relationships"), _create_body(guild, mira, year3), key=key)
    assert _comparable(unkeyed) == (409, "membership_overlap", _comparable(unkeyed)[2])
    assert _comparable(keyed) == _comparable(unkeyed), "the keyed refusal is the unkeyed one"
    assert _membership_rows(s) == rows_before, "nothing persisted"
    assert _reservations(s, key) == 0, "the reservation rolled back with the refusal"

    # the same key is reusable: it executes (it is not a replay) and is refused the same way
    again = s.gm.post_raw(s.url("relationships"), _create_body(guild, mira, year3), key=key)
    assert _comparable(again) == _comparable(unkeyed)
    assert _reservations(s, key) == 0
    # and once the overlap is gone the same key succeeds
    year5, year8 = times.at(5), times.at(8)
    assert act(s, first.json(), "end", {"ended_world_time_id": year5}).status_code == 200
    ok = s.gm.post_raw(s.url("relationships"), _create_body(guild, mira, year8), key=key)
    assert ok.status_code == 201, ok.text
    assert _reservations(s, key) == 1


def test_a_keyed_update_that_overlaps_is_the_unkeyed_refusal_and_leaves_the_key_reusable(
    s: ContentSetup,
) -> None:
    guild, mira = organization(s, "The Guild"), npc(s, "Mira")
    times = Times(s)
    year1, year3, year5, year8 = times.at(1), times.at(3), times.at(5), times.at(8)
    first = join(s, guild, mira, year1).json()
    act(s, first, "end", {"ended_world_time_id": year3})
    second = join(s, guild, mira, year5).json()
    version = s.gm.get(s.url(f"relationships/{second['relationship_id']}")).json()["row_version"]
    path = s.url(f"relationships/{second['relationship_id']}/update")
    body = {"expected_row_version": version, "started_world_time_id": year1}

    unkeyed = s.gm.post_raw(path, body, key=None)
    key = s.gm.fresh_key()
    keyed = s.gm.post_raw(path, body, key=key)
    assert _comparable(unkeyed) == (409, "membership_overlap", _comparable(unkeyed)[2])
    assert _comparable(keyed) == _comparable(unkeyed), "the keyed refusal is the unkeyed one"
    assert _reservations(s, key) == 0, "the reservation rolled back with the refusal"
    after = s.gm.get(s.url(f"relationships/{second['relationship_id']}")).json()
    assert after["row_version"] == version, "nothing persisted"

    again = s.gm.post_raw(path, body, key=key)
    assert _comparable(again) == _comparable(unkeyed)
    fine = s.gm.post_raw(path, {**body, "started_world_time_id": year8}, key=key)
    assert fine.status_code == 200, fine.text
    assert _reservations(s, key) == 1
