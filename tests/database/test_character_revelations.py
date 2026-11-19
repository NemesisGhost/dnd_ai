# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Character revelations over HTTP (P03-A A3a, plan section 10): create, revoke, list, snapshot,
lifecycle hooks, audit and receipts.

Everything runs against committed data across real connections, on the `Gate` fixture (owners
`o1` and `o2`, a custom `access.manage` manager, a player) plus the A1 members (`gm`, assistant GM,
a `gm` look-alike). A3a stored revelations and changed no audience response; from A4 the detail opens at the public tier, and the sweep at the end
pins that and nothing else changes. Keyed regressions are in test_character_revelations_keyed.py and the schema's own
constraints in test_character_revelations_schema.py.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.access_groups import deactivate_access_group, reactivate_access_group
from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.commands.character_reveal import (
    grant_character_reveal_delegation,
    revoke_character_reveal_delegation,
)
from dnd_ai.commands.memberships import end_campaign_membership
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import deny
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import (
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_timeline,
    make_user,
)
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
_CORRELATION = re.compile(r',"correlation_id":"[^"]*"')
SUMMARY_MARKER = "PUBLIC-SUMMARY-MARKER-5512"
REASON_MARKER = "REVELATION-REASON-MARKER-9034"


@dataclass
class Rev:
    character_id: uuid.UUID  # released
    unreleased_id: uuid.UUID  # canon and active, but no release
    group_id: uuid.UUID
    delegation_id: uuid.UUID


@pytest.fixture
def rev(postgres_engine: Engine, g: Gate, m: Members) -> Rev:
    """A character with a release, one without, an access group holding the player, and a live
    reveal delegation for `gm`."""
    with postgres_engine.begin() as connection:
        character = make_character(connection, g.world_id, name="Revealed Subject")
        unreleased = make_character(connection, g.world_id, name="Unreleased Subject")
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_appearance": "A weathered face", "public_summary": SUMMARY_MARKER},
            plan=fixture_plan(connection, g.campaign_id),
        )
    with postgres_engine.begin() as connection:
        release_character_public_profile(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_membership_id=g.o1,
            expected_draft_row_version=1,
            release_note=None,
            plan=fixture_plan(connection, g.campaign_id),
        )
    with postgres_engine.begin() as connection:
        group = make_access_group(connection, g.campaign_id, name="Revealed Group")
        make_access_group_membership(connection, group, g.player)
        delegation = grant_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Runs the reveals",
        )
    return Rev(
        character_id=character,
        unreleased_id=unreleased,
        group_id=group,
        delegation_id=delegation.character_reveal_delegation_id,
    )


# --- helpers ----------------------------------------------------------------------------------


def url(g: Gate, character: uuid.UUID, suffix: str = "") -> str:
    return f"/campaigns/{g.campaign_id}/characters/{character}/revelations{suffix}"


def member_body(target: uuid.UUID, reason: str = "For the table") -> dict[str, object]:
    return {
        "audience_kind": "member",
        "target_campaign_membership_id": str(target),
        "reason": reason,
    }


def group_body(group: uuid.UUID, reason: str = "For the table") -> dict[str, object]:
    return {"audience_kind": "access_group", "target_access_group_id": str(group), "reason": reason}


def campaign_body(kind: str, reason: str = "For the table") -> dict[str, object]:
    return {"audience_kind": kind, "reason": reason}


def create(
    factory: Factory,
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    payload: dict[str, object],
    *,
    key: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(user) as client:
        return client.post(url(g, character), json=payload, headers=headers)


def revoke(
    factory: Factory,
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    revelation: uuid.UUID,
    reason: str = "No longer needed",
    *,
    key: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(user) as client:
        return client.post(
            url(g, character, f"/{revelation}/revoke"), json={"reason": reason}, headers=headers
        )


def listing(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> Any:
    with factory(user) as client:
        return client.get(url(g, character))


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def revelations(engine: Engine, g: Gate, character: uuid.UUID) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT r.character_revelation_id, k.code AS kind,
                       r.target_campaign_membership_id, r.target_access_group_id,
                       r.created_by_membership_id, r.authority_source_code,
                       r.character_reveal_delegation_id, r.reason,
                       r.ended_at, r.ended_by_membership_id, r.end_reason, r.revocation_reason
                FROM security.character_revelations r
                JOIN security.revelation_audience_kinds k
                    ON k.revelation_audience_kind_id = r.revelation_audience_kind_id
                WHERE r.campaign_id = :c AND r.character_id = :ch
                ORDER BY r.created_at, r.character_revelation_id
            """),
            {"c": g.campaign_id, "ch": character},
        ).mappings()
        return [dict(row) for row in rows]


def snapshot(engine: Engine, revelation: uuid.UUID) -> dict[uuid.UUID, tuple[Any, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT campaign_membership_id, removed_at, removal_reason
                FROM security.character_revelation_members
                WHERE character_revelation_id = :r
            """),
            {"r": revelation},
        ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def audit(engine: Engine, g: Gate, *commands: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT command_name, record_id, changed_fields::text AS changed_fields
                FROM audit.change_log
                WHERE world_id = :w AND command_name = ANY(:names)
                ORDER BY recorded_at, change_log_id
            """),
            {"w": g.world_id, "names": list(commands)},
        ).mappings()
        return [dict(row) for row in rows]


CREATE_COMMAND = "create_character_revelation"
REVOKE_COMMAND = "revoke_character_revelation"


def state(engine: Engine, g: Gate, character: uuid.UUID) -> tuple[int, int, int]:
    """(revelations, snapshot rows, revelation audit rows): a refusal changes none of them."""
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT
                  (SELECT count(*) FROM security.character_revelations WHERE campaign_id = :c),
                  (SELECT count(*) FROM security.character_revelation_members
                     WHERE campaign_id = :c),
                  (SELECT count(*) FROM audit.change_log WHERE world_id = :w
                     AND command_name IN ('create_character_revelation',
                                          'revoke_character_revelation'))
            """),
            {"c": g.campaign_id, "w": g.world_id},
        ).one()
    return (row[0], row[1], row[2])


# --- authority --------------------------------------------------------------------------------


def test_an_owner_creates_a_member_revelation_with_a_minimal_receipt_and_one_audit_row(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    response = create(
        client_factory, g.o1_user_id, g, rev.character_id, member_body(g.player, REASON_MARKER)
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"character_revelation_id", "created"} and body["created"] is True
    [row] = revelations(postgres_engine, g, rev.character_id)
    assert str(row["character_revelation_id"]) == body["character_revelation_id"]
    assert row["kind"] == "member" and row["target_campaign_membership_id"] == g.player
    assert row["authority_source_code"] == "owner" and row["character_reveal_delegation_id"] is None
    assert row["created_by_membership_id"] == g.o1 and row["reason"] == REASON_MARKER
    assert row["ended_at"] is None and row["end_reason"] is None
    [entry] = audit(postgres_engine, g, CREATE_COMMAND)
    assert str(entry["record_id"]) == body["character_revelation_id"]
    assert REASON_MARKER not in entry["changed_fields"]
    assert '"audience_kind": "member"' in entry["changed_fields"]
    assert '"audience_size": 1' in entry["changed_fields"]


def test_a_delegated_gm_creates_and_the_provenance_names_the_delegation(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    response = create(
        client_factory,
        m.gm_user_id,
        g,
        rev.character_id,
        campaign_body("campaign_current_and_future"),
    )
    assert response.status_code == 201, response.text
    [row] = revelations(postgres_engine, g, rev.character_id)
    assert row["authority_source_code"] == "delegation"
    assert row["character_reveal_delegation_id"] == rev.delegation_id
    assert row["created_by_membership_id"] == m.gm


def test_callers_without_reveal_authority_get_403_and_nothing_is_written(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    before = state(postgres_engine, g, rev.character_id)
    for user in (m.ast_user_id, m.lookalike_user_id, g.manager_user_id, g.player_user_id):
        response = create(
            client_factory, user, g, rev.character_id, campaign_body("campaign_current")
        )
        assert response.status_code == 403, (user, response.text)
        # The look-alike holds no campaign.view, so the route filter refuses it first.
        expected = "forbidden" if user == m.lookalike_user_id else "character_reveal_required"
        assert error_code(response) == expected
    assert state(postgres_engine, g, rev.character_id) == before


def test_a_revoked_delegation_and_an_outsider_are_refused(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    with postgres_engine.begin() as connection:
        revoke_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="No more",
        )
        stranger = make_user(connection, "Revelation Stranger")
    refused = create(
        client_factory, m.gm_user_id, g, rev.character_id, campaign_body("campaign_current")
    )
    assert refused.status_code == 403 and error_code(refused) == "character_reveal_required"
    outsider = create(
        client_factory, stranger, g, rev.character_id, campaign_body("campaign_current")
    )
    assert outsider.status_code == 404
    assert state(postgres_engine, g, rev.character_id)[0] == 0


def test_a_whole_character_deny_is_404_and_a_canon_edit_deny_does_not_stop_a_revelation(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    deny(postgres_engine, g, g.o1, "canon.edit", rev.character_id)
    allowed = create(client_factory, g.o1_user_id, g, rev.character_id, member_body(g.player))
    assert allowed.status_code == 201, allowed.text  # revealing is not editing (D8 item 5)
    deny(postgres_engine, g, g.o2, "campaign.view", rev.character_id)
    refused = create(client_factory, g.o2_user_id, g, rev.character_id, member_body(g.manager))
    assert refused.status_code == 404
    assert state(postgres_engine, g, rev.character_id)[0] == 1


# --- rules and receipts -----------------------------------------------------------------------


def test_a_character_with_no_release_cannot_be_revealed(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    response = create(client_factory, g.o1_user_id, g, rev.unreleased_id, member_body(g.player))
    assert response.status_code == 409 and error_code(response) == "public_profile_not_released"
    assert state(postgres_engine, g, rev.unreleased_id) == (0, 0, 0)


def test_an_archived_character_cannot_be_revealed(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = (SELECT lifecycle_status_id "
                "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE entity_id = :c"
            ),
            {"c": rev.character_id},
        )
    response = create(client_factory, g.o1_user_id, g, rev.character_id, member_body(g.player))
    assert response.status_code == 409
    assert error_code(response) == "public_profile_character_not_active"
    assert state(postgres_engine, g, rev.character_id)[0] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"audience_kind": "member", "reason": "x"},
        {"audience_kind": "access_group", "reason": "x"},
        {"audience_kind": "campaign_current", "target_access_group_id": str(uuid.uuid4()), "reason": "x"},
        {"audience_kind": "campaign_current_and_future", "target_campaign_membership_id": str(uuid.uuid4()), "reason": "x"},
        {"audience_kind": "everyone", "reason": "x"},
        {"audience_kind": "campaign_current", "reason": ""},
        {"audience_kind": "campaign_current", "reason": "x", "extra": 1},
    ],
)  # fmt: skip
def test_a_body_whose_target_does_not_match_its_kind_is_422(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, payload: dict[str, object]
) -> None:
    response = create(client_factory, g.o1_user_id, g, rev.character_id, payload)
    assert response.status_code == 422, response.text
    assert state(postgres_engine, g, rev.character_id) == (0, 0, 0)


def test_targets_must_exist_in_the_campaign_and_be_active(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    with postgres_engine.begin() as connection:
        ended_user = make_user(connection, "Ended Target")
        ended = make_campaign_membership(connection, g.campaign_id, ended_user, ended=True)
        suspended_user = make_user(connection, "Suspended Target")
        suspended = make_campaign_membership(
            connection, g.campaign_id, suspended_user, status_code="suspended"
        )
        other_timeline = make_timeline(connection, g.world_id, name="Other")
        other_campaign = make_campaign(
            connection, other_timeline, "Other Campaign", lifecycle_status_code="pending"
        )
        elsewhere_user = make_user(connection, "Elsewhere")
        elsewhere = make_campaign_membership(connection, other_campaign, elsewhere_user)
        other_group = make_access_group(connection, other_campaign, name="Elsewhere Group")
        archived_group = make_access_group(connection, g.campaign_id, name="Archived Group")
        deactivate_access_group(
            connection, access_group_id=archived_group, campaign_id=g.campaign_id
        )
    c = rev.character_id
    for target in (ended, suspended):
        response = create(client_factory, g.o1_user_id, g, c, member_body(target))
        assert response.status_code == 409, response.text
        assert error_code(response) == "revelation_target_not_active"
    for target in (elsewhere, uuid.uuid4()):
        assert create(client_factory, g.o1_user_id, g, c, member_body(target)).status_code == 404
    for group in (other_group, uuid.uuid4()):
        assert create(client_factory, g.o1_user_id, g, c, group_body(group)).status_code == 404
    archived = create(client_factory, g.o1_user_id, g, c, group_body(archived_group))
    assert archived.status_code == 409 and error_code(archived) == "revelation_target_not_active"
    assert state(postgres_engine, g, c) == (0, 0, 0)


def test_a_natural_retry_and_a_keyed_replay_return_the_existing_revelation(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    first = create(client_factory, g.o1_user_id, g, c, member_body(g.player), key="rev-natural-1")
    assert first.status_code == 201
    replay = create(client_factory, g.o1_user_id, g, c, member_body(g.player), key="rev-natural-1")
    assert replay.status_code == 201 and replay.json() == first.json()
    natural = create(client_factory, g.o1_user_id, g, c, member_body(g.player, "Another reason"))
    assert natural.status_code == 200
    assert natural.json() == {
        "character_revelation_id": first.json()["character_revelation_id"],
        "created": False,
    }
    assert len(revelations(postgres_engine, g, c)) == 1
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1  # no row for a retry or replay


def test_the_same_key_on_another_character_is_a_conflict_and_writes_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    created = create(
        client_factory, g.o1_user_id, g, rev.character_id, member_body(g.player), key="rev-xchar"
    )
    assert created.status_code == 201
    conflict = create(
        client_factory, g.o1_user_id, g, rev.unreleased_id, member_body(g.player), key="rev-xchar"
    )
    assert conflict.status_code == 409
    assert state(postgres_engine, g, rev.character_id) == (1, 0, 1)
    assert revelations(postgres_engine, g, rev.unreleased_id) == []


# --- audiences and the snapshot ---------------------------------------------------------------


def test_a_campaign_current_revelation_snapshots_only_active_open_members(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    with postgres_engine.begin() as connection:
        ended_user = make_user(connection, "Left Before")
        ended = make_campaign_membership(connection, g.campaign_id, ended_user, ended=True)
        suspended_user = make_user(connection, "Suspended Before")
        suspended = make_campaign_membership(
            connection, g.campaign_id, suspended_user, status_code="suspended"
        )
    response = create(
        client_factory, g.o1_user_id, g, rev.character_id, campaign_body("campaign_current")
    )
    assert response.status_code == 201, response.text
    [row] = revelations(postgres_engine, g, rev.character_id)
    members = snapshot(postgres_engine, row["character_revelation_id"])
    assert set(members) == {g.o1, g.o2, g.manager, g.player, m.gm, m.ast, m.lookalike}
    assert ended not in members and suspended not in members
    assert all(removed is None for removed, _ in members.values())
    [entry] = audit(postgres_engine, g, CREATE_COMMAND)
    assert '"audience_size": 7' in entry["changed_fields"]


def test_a_member_who_joins_later_is_not_in_a_campaign_current_snapshot(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    created = create(
        client_factory, g.o1_user_id, g, rev.character_id, campaign_body("campaign_current")
    )
    assert created.status_code == 201
    with postgres_engine.begin() as connection:
        late_user = make_user(connection, "Late Joiner")
        late = make_campaign_membership(connection, g.campaign_id, late_user)
    [row] = revelations(postgres_engine, g, rev.character_id)
    assert late not in snapshot(postgres_engine, row["character_revelation_id"])


def test_group_and_future_audiences_store_no_snapshot(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    assert create(client_factory, g.o1_user_id, g, c, group_body(rev.group_id)).status_code == 201
    assert (
        create(
            client_factory, g.o1_user_id, g, c, campaign_body("campaign_current_and_future")
        ).status_code
        == 201
    )
    rows = revelations(postgres_engine, g, c)
    assert {r["kind"] for r in rows} == {"access_group", "campaign_current_and_future"}
    assert state(postgres_engine, g, c)[1] == 0
    sizes = [e["changed_fields"] for e in audit(postgres_engine, g, CREATE_COMMAND)]
    assert any('"audience_size": 1' in s for s in sizes)  # the group holds the player
    assert any('"audience_size": 7' in s for s in sizes)


# --- revoke -----------------------------------------------------------------------------------


def test_revoking_closes_the_row_once_and_a_second_revoke_writes_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    created = create(client_factory, g.o1_user_id, g, c, member_body(g.player)).json()
    revelation = uuid.UUID(created["character_revelation_id"])
    first = revoke(client_factory, g.o1_user_id, g, c, revelation, REASON_MARKER)
    assert first.status_code == 200 and first.json() == {
        "character_revelation_id": str(revelation),
        "revoked": True,
    }
    [row] = revelations(postgres_engine, g, c)
    assert row["end_reason"] == "revoked" and row["ended_at"] is not None
    assert row["ended_by_membership_id"] == g.o1 and row["revocation_reason"] == REASON_MARKER
    [entry] = audit(postgres_engine, g, REVOKE_COMMAND)
    assert REASON_MARKER not in entry["changed_fields"]
    again = revoke(client_factory, g.o1_user_id, g, c, revelation)
    assert again.status_code == 200 and again.json()["revoked"] is False
    assert len(audit(postgres_engine, g, REVOKE_COMMAND)) == 1
    # A closed audience can be revealed again: a new row, the old one kept as history.
    renewed = create(client_factory, g.o1_user_id, g, c, member_body(g.player))
    assert renewed.status_code == 201
    assert len(revelations(postgres_engine, g, c)) == 2


def test_a_revelation_id_of_another_character_is_404_and_authority_is_required(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    created = create(
        client_factory, g.o1_user_id, g, rev.character_id, member_body(g.player)
    ).json()
    revelation = uuid.UUID(created["character_revelation_id"])
    other = revoke(client_factory, g.o1_user_id, g, rev.unreleased_id, revelation)
    assert other.status_code == 404
    unknown = revoke(client_factory, g.o1_user_id, g, rev.character_id, uuid.uuid4())
    assert unknown.status_code == 404
    refused = revoke(client_factory, m.ast_user_id, g, rev.character_id, revelation)
    assert refused.status_code == 403 and error_code(refused) == "character_reveal_required"
    assert revelations(postgres_engine, g, rev.character_id)[0]["ended_at"] is None


def test_a_revelation_outlives_its_revealers_authority_and_the_owner_can_revoke_it(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    created = create(
        client_factory,
        m.gm_user_id,
        g,
        rev.character_id,
        campaign_body("campaign_current_and_future"),
    ).json()
    with postgres_engine.begin() as connection:
        revoke_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="No more",
        )
    [row] = revelations(postgres_engine, g, rev.character_id)
    assert row["ended_at"] is None  # D9-f: it survives the revealer losing authority
    assert (
        revoke(
            client_factory,
            m.gm_user_id,
            g,
            rev.character_id,
            uuid.UUID(created["character_revelation_id"]),
        ).status_code
        == 403
    )
    done = revoke(
        client_factory,
        g.o2_user_id,
        g,
        rev.character_id,
        uuid.UUID(created["character_revelation_id"]),
    )
    assert done.status_code == 200 and done.json()["revoked"] is True


# --- lifecycle hooks --------------------------------------------------------------------------


def _reopen(engine: Engine, membership: uuid.UUID) -> None:
    """What an invitation reopen does to the row: the same membership id becomes active again."""
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.campaign_memberships
                SET ended_at = NULL, ended_by_membership_id = NULL,
                    membership_status_id = (SELECT membership_status_id
                        FROM security.membership_statuses WHERE code = 'active')
                WHERE campaign_membership_id = :m
            """),
            {"m": membership},
        )


def test_ending_a_membership_closes_its_revelation_and_snapshot_row_and_a_reopen_restores_neither(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    member = uuid.UUID(
        create(client_factory, g.o1_user_id, g, c, member_body(g.player)).json()[
            "character_revelation_id"
        ]
    )
    current = uuid.UUID(
        create(client_factory, g.o1_user_id, g, c, campaign_body("campaign_current")).json()[
            "character_revelation_id"
        ]
    )
    future = uuid.UUID(
        create(
            client_factory, g.o1_user_id, g, c, campaign_body("campaign_current_and_future")
        ).json()["character_revelation_id"]
    )
    with client_factory(g.o1_user_id) as client:
        ended = client.post(f"/campaigns/{g.campaign_id}/memberships/{g.player}/end", json={})
    assert ended.status_code == 200, ended.text

    by_id = {r["character_revelation_id"]: r for r in revelations(postgres_engine, g, c)}
    assert by_id[member]["end_reason"] == "target_membership_ended"
    assert by_id[member]["ended_at"] is not None and by_id[member]["ended_by_membership_id"] is None
    assert by_id[current]["ended_at"] is None and by_id[future]["ended_at"] is None
    removed, reason = snapshot(postgres_engine, current)[g.player]
    assert removed is not None and reason == "membership_ended"
    assert snapshot(postgres_engine, current)[g.o2][0] is None  # nobody else is touched
    [entry] = audit(postgres_engine, g, "end_campaign_membership")
    assert str(member) in entry["changed_fields"]
    assert "removed_character_revelation_member_ids" in entry["changed_fields"]

    _reopen(postgres_engine, g.player)
    after = {r["character_revelation_id"]: r for r in revelations(postgres_engine, g, c)}
    assert after[member]["end_reason"] == "target_membership_ended"  # closed rows stay closed
    assert snapshot(postgres_engine, current)[g.player][0] is not None  # not restored
    assert after[future]["ended_at"] is None  # a returning member is a future member (D9-c)


def test_deactivating_a_group_closes_its_revelation_and_reactivating_does_not_restore_it(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    created = create(client_factory, g.o1_user_id, g, c, group_body(rev.group_id)).json()
    with client_factory(g.o1_user_id) as client:
        response = client.post(
            f"/campaigns/{g.campaign_id}/access-groups/{rev.group_id}/deactivate", json={}
        )
    assert response.status_code == 200, response.text
    [row] = revelations(postgres_engine, g, c)
    assert row["end_reason"] == "access_group_deactivated" and row["ended_at"] is not None
    [entry] = audit(postgres_engine, g, "deactivate_access_group")
    assert created["character_revelation_id"] in entry["changed_fields"]
    with postgres_engine.begin() as connection:
        reactivate_access_group(connection, access_group_id=rev.group_id, campaign_id=g.campaign_id)
    assert revelations(postgres_engine, g, c)[0]["ended_at"] is not None
    # The group is active and empty again; it can be revealed to afresh.
    assert create(client_factory, g.o1_user_id, g, c, group_body(rev.group_id)).status_code == 201


def test_ending_a_membership_against_an_unrevealed_campaign_still_works(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    """The end command's new explicit locks leave an ordinary end unchanged (no revelations)."""
    with postgres_engine.begin() as connection:
        result = end_campaign_membership(
            connection,
            campaign_membership_id=g.player,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o1,
        )
    assert result.ended and result.closed_character_revelation_ids == ()
    assert result.removed_character_revelation_member_ids == ()


# --- the GM list ------------------------------------------------------------------------------


def test_the_gm_list_shows_live_and_ended_revelations_and_the_snapshot_to_readers_only(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    c = rev.character_id
    create(client_factory, g.o1_user_id, g, c, member_body(g.player, REASON_MARKER))
    create(client_factory, g.o1_user_id, g, c, campaign_body("campaign_current"))
    ended = create(client_factory, g.o1_user_id, g, c, group_body(rev.group_id)).json()
    revoke(client_factory, g.o1_user_id, g, c, uuid.UUID(ended["character_revelation_id"]))

    response = listing(client_factory, g.o1_user_id, g, c)
    assert response.status_code == 200, response.text
    entries = response.json()["revelations"]
    assert [e["audience_kind"] for e in entries].count("campaign_current") == 1
    current = next(e for e in entries if e["audience_kind"] == "campaign_current")
    assert current["audience_size"] == 7 and len(current["snapshot_members"]) == 7
    member = next(e for e in entries if e["audience_kind"] == "member")
    assert member["target_member_name"] == "Gate Player" and member["live"] is True
    group = next(e for e in entries if e["audience_kind"] == "access_group")
    assert group["live"] is False and group["end_reason"] == "revoked"
    assert REASON_MARKER not in response.text  # the reason is stored, never listed

    assert listing(client_factory, m.ast_user_id, g, c).status_code == 200  # canon.edit reader
    assert listing(client_factory, g.player_user_id, g, c).status_code == 404
    with postgres_engine.begin() as connection:
        stranger = make_user(connection, "List Stranger")
    assert listing(client_factory, stranger, g, c).status_code == 404
    deny(postgres_engine, g, g.o1, "campaign.view", c)
    assert listing(client_factory, g.o1_user_id, g, c).status_code == 404


# --- public_summary (D5-c) --------------------------------------------------------------------


def _save(
    factory: Factory, g: Gate, character: uuid.UUID, version: int | None, **fields: object
) -> Any:
    with factory(g.o1_user_id) as client:
        return client.post(
            f"/campaigns/{g.campaign_id}/characters/{character}/public-profile/draft",
            json={"expected_row_version": version, **fields},
        )


def test_public_summary_saves_clears_snapshots_into_a_release_and_is_never_copied(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.unreleased_id
    created = _save(client_factory, g, c, None, public_summary=SUMMARY_MARKER)
    assert created.status_code == 201, created.text
    repeat = _save(client_factory, g, c, 1, public_summary=SUMMARY_MARKER)
    assert repeat.status_code == 200 and repeat.json()["changed"] is False
    too_long = _save(client_factory, g, c, 1, public_summary="x" * 4001)
    assert too_long.status_code == 422
    with client_factory(g.o1_user_id) as client:
        released = client.post(
            f"/campaigns/{g.campaign_id}/characters/{c}/public-profile/releases",
            json={"expected_draft_row_version": 1},
        )
        read = client.get(f"/campaigns/{g.campaign_id}/characters/{c}/public-profile")
        refused_copy = client.post(
            f"/campaigns/{g.campaign_id}/characters/{c}/public-profile/draft/copy-legacy",
            json={"expected_row_version": 1, "field": "public_summary"},
        )
    assert released.status_code == 201, released.text
    assert read.json()["latest_release"]["public_summary"] == SUMMARY_MARKER
    assert read.json()["draft"]["public_summary"] == SUMMARY_MARKER
    assert refused_copy.status_code in (404, 422)  # the copy aid cannot target it
    cleared = _save(client_factory, g, c, 1, public_summary=None)
    assert cleared.status_code == 200 and cleared.json()["row_version"] == 2
    with client_factory(g.o1_user_id) as client:
        after = client.get(f"/campaigns/{g.campaign_id}/characters/{c}/public-profile").json()
    assert after["draft"]["public_summary"] is None
    assert after["latest_release"]["public_summary"] == SUMMARY_MARKER  # releases are immutable
    entries = audit(postgres_engine, g, "save_character_public_profile_draft")
    assert any('"public_summary"' in e["changed_fields"] for e in entries)
    assert all(SUMMARY_MARKER not in e["changed_fields"] for e in entries)


# --- A3a changes no audience response ---------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "audience"),
    [
        ("member", {"player"}),
        ("access_group", {"player"}),
        ("campaign_current", {"player"}),
        ("campaign_current_and_future", {"player"}),
    ],
)
def test_a_revelation_changes_only_the_audience_detail_to_the_public_tier(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    rev: Rev,
    kind: str,
    audience: set[str],
) -> None:
    """A3a stored revelations and changed no audience response; A4 opens exactly one thing. For
    each audience kind, the detail of the revealed character becomes the public tier for the
    callers the revelation reaches, and nothing else changes: every other path (sheet, inventory,
    relationships, public profile, party list) is byte-identical for everyone, and a caller outside
    the audience gets the identical response to before: the look-alike's custom role carries no
    `campaign.view`, so even a campaign-wide revelation opens nothing for it (403 throughout), and
    a non-member gets the same 404/403 as before."""
    c = rev.character_id
    detail = f"/campaigns/{g.campaign_id}/characters/{c}"
    others = [
        f"/campaigns/{g.campaign_id}/characters/{c}/sheet",
        f"/campaigns/{g.campaign_id}/characters/{c}/inventory",
        f"/campaigns/{g.campaign_id}/characters/{c}/relationships",
        f"/campaigns/{g.campaign_id}/characters/{c}/public-profile",
        f"/campaigns/{g.campaign_id}/parties",
    ]
    with postgres_engine.begin() as connection:
        stranger = make_user(connection, "Sweep Stranger")
    callers = {"player": g.player_user_id, "lookalike": m.lookalike_user_id, "stranger": stranger}

    def sweep(paths: list[str]) -> dict[tuple[str, str], tuple[int, str]]:
        out = {}
        for name, user in callers.items():
            with client_factory(user) as client:
                for path in paths:
                    response = client.get(path)
                    # The error envelope carries a per-request correlation id.
                    out[(name, path)] = (
                        response.status_code,
                        _CORRELATION.sub("", response.text),
                    )
        return out

    before = sweep([detail, *others])
    assert all(SUMMARY_MARKER not in text_ for _, text_ in before.values())
    body = (
        campaign_body(kind, REASON_MARKER)
        if kind.startswith("campaign")
        else group_body(rev.group_id, REASON_MARKER)
        if kind == "access_group"
        else member_body(g.player, REASON_MARKER)
    )
    assert create(client_factory, g.o1_user_id, g, c, body).status_code == 201
    after = sweep([detail, *others])

    # Unrelated responses are unchanged for every caller, in or out of the audience.
    for key, answer in before.items():
        if key[1] != detail:
            assert after[key] == answer, key

    for name in callers:
        status, text_ = after[(name, detail)]
        if name not in audience:
            assert (status, text_) == before[(name, detail)], name  # no leak outside the audience
            assert SUMMARY_MARKER not in text_ and REASON_MARKER not in text_
            continue
        assert before[(name, detail)][0] in (403, 404), name
        assert status == 200, (name, text_)
        assert REASON_MARKER not in text_  # the GM's reason never reaches the audience
        with client_factory(callers[name]) as client:
            payload = client.get(detail).json()
        assert set(payload) == {
            "view_tier",
            "character_id",
            "name",
            "character_kind",
            "sections",
            "public_profile",
        }
        assert payload["view_tier"] == "public_profile"
        assert payload["character_id"] == str(c) and payload["name"] == "Revealed Subject"
        assert payload["sections"]["public_profile"] is True
        assert payload["sections"]["details"] is True
        assert payload["sections"]["sheet"] is False
        assert payload["sections"]["relationships"] is False
        assert payload["sections"]["inventory"] is False
        assert payload["public_profile"] == {
            "summary": SUMMARY_MARKER,
            "appearance": "A weathered face",
            "background": None,
            "species": None,
            "size": None,
        }
