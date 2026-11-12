# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""C1 to C8, KA1 to KA4 and the R01 expiry trace for the player-profile copy, over real HTTP
(P03-A A5c, design sections 10.4 and 10.5).

Every request runs through `TestClient` and the real routes on its own thread and connection.
`tests/http_race_support.py::StatementGate` stops the *first* request at a named statement, before it
executes, so the request holds every lock it took earlier and none it would take next; the test then
observes through `pg_blocking_pids` that the second request is genuinely waiting on that session
(never a sleep) and only then releases it. The only non-HTTP party is the profile edit of C1, which is
the fixture helper running the P03-B write shape in its own held transaction (design 10.4).

Each case asserts the status codes, the draft row (version, text, origin, provenance pair, watermark),
the release rows, the audit-row and receipt counts, and that a loser wrote nothing.

C-tests (unkeyed or independent keys) are deterministic and must serialise without a deadlock.
KA-tests run the keyed copy (or release) in the interleaving that realises DEF-019's reservation cycle
(the competitor holds its membership or role row and has not yet taken the campaign row; the keyed
request has already reserved its key, which holds the campaign row `FOR KEY SHARE`). They accept either
valid serialised outcome or the documented deadlock loser (SQLSTATE 40P01, proved through the
database's deadlock counter, never any other 5xx), record which occurred, and require the same
invariants whichever happens: a copy never commits after the authority loss committed, every 2xx
matches committed state, and a non-2xx loser leaves no draft change, audit row or receipt. They never
require a deadlock.
"""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (
    body,
    code,
    error_code,
    release,
    release_rows,
    save,
)
from tests.database.test_character_public_profile_grant_denies import post_grant
from tests.database.test_character_public_profile_restrictions import npc  # noqa: F401 - fixture
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_player_profile_copy import (
    copy_audit,
    copy_pp,
    draft,
    profile_state,
    source,  # noqa: F401 - fixture
    view,
)
from tests.factories import make_character
from tests.http_race_support import (
    StatementGate,
    deadlock_count,
    new_key,
    run_in_thread,
    wait_for_deadlock_count,
    wait_until_blocked,
    wait_until_pid_blocks,
)
from tests.player_profile_support import edit_player_profile_in

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

# Statements the gates stop at (whitespace-normalised, bind markers are `%(name)s`).
COPY_HEAD = r"FROM campaign\.character_player_profiles WHERE campaign_id = .* FOR SHARE"
DRAFT_INSERT = r"INSERT INTO campaign\.character_public_profiles"
DRAFT_UPDATE = r"UPDATE campaign\.character_public_profiles SET"
RELEASE_INSERT = r"INSERT INTO campaign\.character_public_profile_releases"
ROLE_REVOKE = r"UPDATE security\.membership_roles SET revoked_at"
CAMPAIGN_LOCK = r"FROM campaign\.campaigns WHERE campaign_id = .* FOR UPDATE"
GRANT_CAMPAIGN_LOCK = r"SELECT ls\.code FROM campaign\.campaigns c .* FOR UPDATE OF c"
GRANT_INSERT = r"INSERT INTO security\.resource_grants"
ENTITY_UPDATE = r"UPDATE core\.entities"


# --- operations ---------------------------------------------------------------------------------------------


def revoke_role(factory: Factory, g: Gate, role: uuid.UUID) -> Callable[[], Any]:
    def run() -> Any:
        with factory(g.o1_user_id) as client:
            return client.post(f"/campaigns/{g.campaign_id}/memberships/roles/{role}/revoke")

    return run


def end_membership(factory: Factory, g: Gate, membership: uuid.UUID) -> Callable[[], Any]:
    def run() -> Any:
        with factory(g.o1_user_id) as client:
            return client.post(f"/campaigns/{g.campaign_id}/memberships/{membership}/end")

    return run


def grant_deny(
    factory: Factory, g: Gate, npc: uuid.UUID, grantee: uuid.UUID, by: uuid.UUID
) -> Callable[[], Any]:
    return lambda: post_grant(factory, by, g, "canon.edit", npc, member=grantee)


def archive(factory: Factory, g: Gate, entity: uuid.UUID, version: int) -> Callable[[], Any]:
    def run() -> Any:
        with factory(g.o1_user_id) as client:
            return client.post(
                f"/campaigns/{g.campaign_id}/entities/{entity}/lifecycle/archive",
                json={"expected_row_version": version},
            )

    return run


def copier(
    factory: Factory, g: Gate, npc: uuid.UUID, user: uuid.UUID, **kwargs: Any
) -> Callable[[], Any]:
    return lambda: copy_pp(factory, user, g, npc, **kwargs)


def run_gated(
    engine: Engine, pattern: str, first: Callable[[], Any], second: Callable[[], Any]
) -> tuple[Any, Any, int]:
    """Runs `first` to the gated statement, starts `second`, proves `second` waits on `first`'s
    session, releases, and returns both responses and the deadlock-counter baseline."""
    baseline = deadlock_count(engine)
    with StatementGate(engine, pattern) as gate:
        a = run_in_thread("first", first)
        gate.wait_reached()
        b = run_in_thread("second", second)
        wait_until_blocked(engine, gate)  # the second request is waiting on the first's session
        assert not b.finished()
        gate.release()
        ra, rb = a.wait("first"), b.wait("second")
    return ra, rb, baseline


def receipts_for(engine: Engine, key: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :k"
                ),
                {"k": key},
            ).scalar_one()
        )


def completed_receipts_for(engine: Engine, key: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM security.idempotent_requests "
                    "WHERE idempotency_key = :k AND completed_at IS NOT NULL"
                ),
                {"k": key},
            ).scalar_one()
        )


def role_revoked(engine: Engine, role: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text(
                    "SELECT revoked_at IS NOT NULL FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": role},
            ).scalar_one()
        )


def membership_ended(engine: Engine, membership: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text(
                    "SELECT ended_at IS NOT NULL FROM security.campaign_memberships "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": membership},
            ).scalar_one()
        )


def denied(engine: Engine, g: Gate, membership: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("""
                    SELECT count(*) > 0 FROM security.resource_grants rg
                    JOIN security.capabilities c ON c.capability_id = rg.capability_id
                    WHERE rg.campaign_id = :c AND rg.grantee_campaign_membership_id = :m
                      AND c.code = 'canon.edit' AND rg.effect = 'deny' AND rg.revoked_at IS NULL
                """),
                {"c": g.campaign_id, "m": membership},
            ).scalar_one()
        )


def copy_commands_audited(engine: Engine, g: Gate) -> int:
    return len(copy_audit(engine, g))


def is_refusal(response: Any) -> bool:
    return code(response) in (403, 404)


# --- C1: a profile edit against a (keyed) copy ---------------------------------------------------------------


def test_c1_edit_first_the_copy_is_refused_as_source_changed_and_stores_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    key = new_key()
    before = profile_state(postgres_engine, g, npc)
    assert before == (1, 1)
    with postgres_engine.connect() as holder:
        transaction = holder.begin()
        edit_player_profile_in(
            holder, campaign_id=g.campaign_id, character_id=npc, editor_membership_id=g.o1,
            fields={**source, "personality": "PP-NEWER-PERSONALITY-4242"},
        )  # fmt: skip
        pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
        copying = run_in_thread("copy", copier(client_factory, g, npc, g.o1_user_id, key=key))
        wait_until_pid_blocks(postgres_engine, pid)  # the copy waits on the held head `FOR UPDATE`
        assert not copying.finished()
        transaction.commit()
    response = copying.wait("copy")
    assert (code(response), error_code(response)) == (409, "player_profile_source_changed")
    assert "PP-NEWER-PERSONALITY-4242" not in response.text
    assert draft(postgres_engine, g, npc) is None
    assert release_rows(postgres_engine, g, npc) == []
    assert copy_commands_audited(postgres_engine, g) == 0
    assert receipts_for(postgres_engine, key) == 0  # a refusal stores no receipt
    assert profile_state(postgres_engine, g, npc) == (2, 2)


def test_c1_copy_first_the_edit_waits_the_copy_cites_the_old_version_and_the_read_flags_it(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    key = new_key()

    def edit() -> int:
        with postgres_engine.begin() as connection:
            return edit_player_profile_in(
                connection, campaign_id=g.campaign_id, character_id=npc,
                editor_membership_id=g.o1, fields={**source, "personality": "PP-NEWER-5151"},
            )  # fmt: skip

    baseline = deadlock_count(postgres_engine)
    with StatementGate(postgres_engine, DRAFT_INSERT) as gate:
        copying = run_in_thread("copy", copier(client_factory, g, npc, g.o1_user_id, key=key))
        gate.wait_reached()  # the copy holds the profile head FOR SHARE and has not written
        editing = run_in_thread("edit", edit)
        wait_until_blocked(postgres_engine, gate)  # the edit waits for the head FOR UPDATE
        assert not editing.finished()
        gate.release()
        response = copying.wait("copy")
        new_version = editing.wait("edit")
    assert code(response) == 201, body(response)
    assert new_version == 2
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["public_background"] == source["personality"]
    assert (row["b_version"], row["b_field"], row["b_mark"]) == (
        1,
        "personality",
        1,
    )  # the OLD version
    assert completed_receipts_for(postgres_engine, key) == 1
    assert copy_commands_audited(postgres_engine, g) == 1
    assert deadlock_count(postgres_engine) == baseline
    flagged = view(client_factory, g.o1_user_id, g, npc)["draft"]
    assert flagged["public_background_player_profile_source_changed"] is True
    assert "PP-NEWER-5151" not in str(flagged)


# --- C2, C3, C4: the copier's authority against an unkeyed copy -------------------------------------------------


def _refused_and_unwritten(response: Any, engine: Engine, g: Gate, npc: uuid.UUID) -> None:
    assert is_refusal(response), (code(response), body(response))
    assert draft(engine, g, npc) is None
    assert copy_commands_audited(engine, g) == 0


def test_c2_revoke_first_the_copy_is_refused_copy_first_the_revoke_waits_and_both_commit(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    # Revoke first: the copy waits at the role rows, then is refused from committed state.
    revoked, copied, baseline = run_gated(
        postgres_engine, ROLE_REVOKE,
        revoke_role(client_factory, g, m.gm_role),
        copier(client_factory, g, npc, m.gm_user_id),
    )  # fmt: skip
    assert code(revoked) == 200, body(revoked)
    _refused_and_unwritten(copied, postgres_engine, g, npc)
    assert role_revoked(postgres_engine, m.gm_role)
    assert source["personality"] not in copied.text
    assert deadlock_count(postgres_engine) == baseline


def test_c2_copy_first_the_revoke_waits_and_the_copy_commits(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    copied, revoked, baseline = run_gated(
        postgres_engine, COPY_HEAD,
        copier(client_factory, g, npc, m.gm_user_id),
        revoke_role(client_factory, g, m.gm_role),
    )  # fmt: skip
    assert code(copied) == 201, body(copied)
    assert code(revoked) == 200, body(revoked)
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["public_background"] == source["personality"]
    assert copy_commands_audited(postgres_engine, g) == 1 and role_revoked(
        postgres_engine, m.gm_role
    )
    assert deadlock_count(postgres_engine) == baseline


def test_c3_grant_first_the_copy_is_refused_copy_first_the_grant_waits_and_the_copy_commits(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    granted, copied, baseline = run_gated(
        postgres_engine, GRANT_INSERT,
        grant_deny(client_factory, g, npc, g.o1, g.o2_user_id),
        copier(client_factory, g, npc, g.o1_user_id),
    )  # fmt: skip
    assert code(granted) == 201, body(granted)
    # o1 is an owner (reveal authority), so the refusal names the denied edit; nothing was written.
    assert (code(copied), error_code(copied)) == (403, "public_profile_edit_denied")
    assert draft(postgres_engine, g, npc) is None and copy_commands_audited(postgres_engine, g) == 0
    assert source["personality"] not in copied.text and denied(postgres_engine, g, g.o1)
    assert deadlock_count(postgres_engine) == baseline


def test_c3_copy_first_the_grant_waits_and_the_copy_commits(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    copied, granted, baseline = run_gated(
        postgres_engine, COPY_HEAD,
        copier(client_factory, g, npc, g.o1_user_id),
        grant_deny(client_factory, g, npc, g.o1, g.o2_user_id),
    )  # fmt: skip
    assert code(copied) == 201, body(copied)
    assert code(granted) == 201, body(granted)
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["public_background"] == source["personality"]
    assert denied(postgres_engine, g, g.o1) and copy_commands_audited(postgres_engine, g) == 1
    assert deadlock_count(postgres_engine) == baseline


def test_c4_end_first_the_copy_is_refused_copy_first_the_end_waits_and_the_copy_commits(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    ended, copied, baseline = run_gated(
        postgres_engine, CAMPAIGN_LOCK,
        end_membership(client_factory, g, m.gm),
        copier(client_factory, g, npc, m.gm_user_id),
    )  # fmt: skip
    assert code(ended) == 200, body(ended)
    _refused_and_unwritten(copied, postgres_engine, g, npc)
    assert membership_ended(postgres_engine, m.gm)
    assert deadlock_count(postgres_engine) == baseline


def test_c4_copy_first_the_end_waits_and_the_copy_commits(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    copied, ended, baseline = run_gated(
        postgres_engine, COPY_HEAD,
        copier(client_factory, g, npc, m.gm_user_id),
        end_membership(client_factory, g, m.gm),
    )  # fmt: skip
    assert code(copied) == 201, body(copied)
    assert code(ended) == 200, body(ended)
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["public_background"] == source["personality"]
    assert (
        membership_ended(postgres_engine, m.gm) and copy_commands_audited(postgres_engine, g) == 1
    )
    assert deadlock_count(postgres_engine) == baseline


# --- C5, C6: the public draft against a copy --------------------------------------------------------------------


def _a_draft(factory: Factory, g: Gate, npc: uuid.UUID) -> None:
    created = save(
        factory, g.o1_user_id, g, npc,
        {"expected_row_version": None, "public_appearance": "AUTHORED-FACE-9090"},
    )  # fmt: skip
    assert code(created) == 201, body(created)


def test_c5_a_keyed_save_first_the_keyed_copy_with_the_same_token_is_stale(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    _a_draft(client_factory, g, npc)
    save_key, copy_key = new_key(), new_key()
    saving = lambda: save(  # noqa: E731
        client_factory, g.o1_user_id, g, npc,
        {"expected_row_version": 1, "public_summary": "SAVED"}, key=save_key,
    )  # fmt: skip
    saved, copied, baseline = run_gated(
        postgres_engine, DRAFT_UPDATE, saving,
        copier(client_factory, g, npc, g.o1_user_id, draft=1, key=copy_key),
    )  # fmt: skip
    assert code(saved) == 200, body(saved)
    assert (code(copied), error_code(copied)) == (409, "stale_write")
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["public_summary"] == "SAVED" and row["row_version"] == 2
    assert (row["background_origin"], row["public_background"]) == ("authored", None)
    assert copy_commands_audited(postgres_engine, g) == 0
    assert (completed_receipts_for(postgres_engine, save_key), receipts_for(postgres_engine, copy_key)) == (1, 0)  # fmt: skip
    assert deadlock_count(postgres_engine) == baseline  # no cycle between the two keyed routes


def test_c5_a_keyed_copy_first_the_keyed_save_with_the_same_token_is_stale(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    _a_draft(client_factory, g, npc)
    save_key, copy_key = new_key(), new_key()
    saving = lambda: save(  # noqa: E731
        client_factory, g.o1_user_id, g, npc,
        {"expected_row_version": 1, "public_summary": "SAVED"}, key=save_key,
    )  # fmt: skip
    copied, saved, baseline = run_gated(
        postgres_engine, DRAFT_UPDATE,
        copier(client_factory, g, npc, g.o1_user_id, draft=1, key=copy_key), saving,
    )  # fmt: skip
    assert code(copied) == 200, body(copied)
    assert (code(saved), error_code(saved)) == (409, "stale_write")
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["row_version"] == 2 and row["public_summary"] is None
    assert row["public_background"] == source["personality"] and row["b_mark"] == 2
    assert copy_commands_audited(postgres_engine, g) == 1
    assert (completed_receipts_for(postgres_engine, copy_key), receipts_for(postgres_engine, save_key)) == (1, 0)  # fmt: skip
    assert deadlock_count(postgres_engine) == baseline


def test_c6_a_keyed_release_first_both_commit_and_the_release_holds_the_pre_copy_text(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    _a_draft(client_factory, g, npc)
    release_key, copy_key = new_key(), new_key()
    releasing = lambda: release(client_factory, g.o1_user_id, g, npc, 1, key=release_key)  # noqa: E731
    released, copied, baseline = run_gated(
        postgres_engine, RELEASE_INSERT, releasing,
        copier(client_factory, g, npc, g.o1_user_id, draft=1, key=copy_key),
    )  # fmt: skip
    assert code(released) == 201, body(released)
    assert code(copied) == 200, body(copied)
    rows = release_rows(postgres_engine, g, npc)
    assert [(r["version_number"], r["public_background"]) for r in rows] == [(1, None)]
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["row_version"] == 2 and row["b_mark"] == 2
    assert row["public_background"] == source["personality"]  # copied, restricted and uncovered
    assert row["b_mark"] > rows[0]["from_draft_row_version"]
    assert (completed_receipts_for(postgres_engine, release_key), completed_receipts_for(postgres_engine, copy_key)) == (1, 1)  # fmt: skip
    assert deadlock_count(postgres_engine) == baseline


def test_c6_a_keyed_copy_first_the_release_of_the_earlier_version_is_stale_and_writes_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    """Deviation from the design's table (it says both commit in either order): once the copy holds
    the draft and commits, the draft is at version n+1, so a release of version n is a stale write,
    exactly as for the A2b legacy copy (`test_a_copy_holding_the_draft_makes_a_release_of_the_earlier_
    version_stale`). The copy's field is restricted and uncovered."""
    _a_draft(client_factory, g, npc)
    release_key, copy_key = new_key(), new_key()
    releasing = lambda: release(client_factory, g.o1_user_id, g, npc, 1, key=release_key)  # noqa: E731
    copied, released, baseline = run_gated(
        postgres_engine, DRAFT_UPDATE,
        copier(client_factory, g, npc, g.o1_user_id, draft=1, key=copy_key), releasing,
    )  # fmt: skip
    assert code(copied) == 200, body(copied)
    assert (code(released), error_code(released)) == (409, "stale_write")
    assert release_rows(postgres_engine, g, npc) == []
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["row_version"] == 2 and row["b_mark"] == 2
    assert (completed_receipts_for(postgres_engine, copy_key), receipts_for(postgres_engine, release_key)) == (1, 0)  # fmt: skip
    assert deadlock_count(postgres_engine) == baseline


# --- C7: archive --------------------------------------------------------------------------------------------------


def _pc(engine: Engine, g: Gate) -> uuid.UUID:
    from tests.player_profile_support import markers, seed_player_profile

    with engine.begin() as connection:
        pc = make_character(
            connection, g.world_id, name="Archived Hero", entity_type_code="player_character"
        )
        connection.execute(
            text("INSERT INTO character.player_characters (player_character_id) VALUES (:c)"),
            {"c": pc},
        )
    seed_player_profile(
        engine, campaign_id=g.campaign_id, character_id=pc, editor_membership_id=g.o1,
        fields=markers("ARC"),
    )  # fmt: skip
    return pc


def _entity_version(engine: Engine, entity: uuid.UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": entity}
            ).scalar_one()
        )


def test_c7_archive_first_the_copy_is_refused_as_not_active_and_writes_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    pc = _pc(postgres_engine, g)
    archived, copied, baseline = run_gated(
        postgres_engine, ENTITY_UPDATE,
        archive(client_factory, g, pc, _entity_version(postgres_engine, pc)),
        copier(client_factory, g, pc, g.o1_user_id),
    )  # fmt: skip
    assert code(archived) == 200, body(archived)
    assert (code(copied), error_code(copied)) == (409, "public_profile_character_not_active")
    assert draft(postgres_engine, g, pc) is None and copy_commands_audited(postgres_engine, g) == 0
    assert deadlock_count(postgres_engine) == baseline


def test_c7_copy_first_the_archive_waits_on_the_entity_and_both_commit(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    pc = _pc(postgres_engine, g)
    version = _entity_version(postgres_engine, pc)
    copied, archived, baseline = run_gated(
        postgres_engine, COPY_HEAD,
        copier(client_factory, g, pc, g.o1_user_id),
        archive(client_factory, g, pc, version),
    )  # fmt: skip
    assert code(copied) == 201, body(copied)
    assert code(archived) == 200, body(archived)
    row = draft(postgres_engine, g, pc)
    assert row is not None and row["b_field"] == "personality"
    assert copy_commands_audited(postgres_engine, g) == 1
    assert deadlock_count(postgres_engine) == baseline


# --- C8: the same keyed copy, concurrently --------------------------------------------------------------------


def test_c8_the_same_key_and_body_executes_once_and_the_other_gets_the_stored_receipt(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    key = new_key()
    first, second, baseline = run_gated(
        postgres_engine, DRAFT_INSERT,
        copier(client_factory, g, npc, g.o1_user_id, key=key),
        copier(client_factory, g, npc, g.o1_user_id, key=key),
    )  # fmt: skip
    assert code(first) == 201, body(first)
    assert code(second) == 201 and body(second) == body(first)  # the stored receipt, same status
    assert source["personality"] not in second.text
    row = draft(postgres_engine, g, npc)
    assert row is not None and row["row_version"] == 1  # exactly one draft change
    assert copy_commands_audited(postgres_engine, g) == 1  # exactly one audit row
    assert completed_receipts_for(postgres_engine, key) == 1
    assert deadlock_count(postgres_engine) == baseline


# --- KA1 to KA3: the keyed copy under DEF-019's reservation cycle -----------------------------------------------

OUTCOMES: list[str] = []


def _classify(
    engine: Engine,
    *,
    copy_response: Any,
    competitor: Any,
    baseline: int,
    record: Callable[..., Any],
) -> str:
    """Names the outcome, and proves any 5xx is the documented 40P01 loser (the database's deadlock
    counter moved) and nothing else."""
    five = [r for r in (copy_response, competitor) if code(r) >= 500]
    assert len(five) <= 1, [code(copy_response), code(competitor)]
    if five:
        assert wait_for_deadlock_count(engine, baseline + 1) >= baseline + 1, (
            "a 5xx that is not a deadlock loser",
            code(copy_response),
            code(competitor),
        )
        outcome = (
            "deadlock-copy-aborted" if code(copy_response) >= 500 else "deadlock-competitor-aborted"
        )
    else:
        assert deadlock_count(engine) == baseline
        outcome = "serialized"
    OUTCOMES.append(outcome)
    record("outcome", outcome)
    print(f"DEF-019 outcome: {outcome}")  # noqa: T201 - the test records which outcome occurred
    return outcome


def _assert_copy_invariants(
    engine: Engine, g: Gate, npc: uuid.UUID, key: str, *, copy_response: Any, lost: bool,
    source: dict[str, str],
) -> None:  # fmt: skip
    copy_ok = code(copy_response) in (200, 201)
    assert not (copy_ok and lost), "a copy committed after the authority loss committed"
    row = draft(engine, g, npc)
    if copy_ok:  # every 2xx matches committed state
        assert row is not None and row["public_background"] == source["personality"]
        assert copy_commands_audited(engine, g) == 1
        assert completed_receipts_for(engine, key) == 1
    else:  # a loser left no draft change, audit row or receipt
        assert row is None, row
        assert copy_commands_audited(engine, g) == 0
        assert receipts_for(engine, key) == 0
        assert code(copy_response) >= 500 or is_refusal(copy_response)
        assert source["personality"] not in copy_response.text


COMPETITORS = ["revoke", "end", "grant"]


def _competitor(
    kind: str, factory: Factory, g: Gate, m: Members, npc: uuid.UUID
) -> tuple[uuid.UUID, str, str, Callable[[], Any], Callable[[Engine], bool]]:
    """(copier user, competitor-first gate pattern, copy-first gate pattern, competitor request,
    "the authority loss committed" probe)."""
    if kind == "revoke":
        return (
            m.gm_user_id, ROLE_REVOKE, COPY_HEAD,
            revoke_role(factory, g, m.gm_role),
            lambda e: role_revoked(e, m.gm_role),
        )  # fmt: skip
    if kind == "end":
        return (
            m.gm_user_id, CAMPAIGN_LOCK, COPY_HEAD,
            end_membership(factory, g, m.gm),
            lambda e: membership_ended(e, m.gm),
        )  # fmt: skip
    return (
        g.o1_user_id, GRANT_CAMPAIGN_LOCK, COPY_HEAD,
        grant_deny(factory, g, npc, g.o1, g.o2_user_id),
        lambda e: denied(e, g, g.o1),
    )  # fmt: skip


@pytest.mark.parametrize("kind", COMPETITORS)
def test_ka_competitor_first_the_keyed_copy_serialises_or_loses_to_the_documented_deadlock(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str], record_property: Callable[..., Any], kind: str,
) -> None:  # fmt: skip
    """KA1 (end), KA2 (revoke), KA3 (deny through the grant route): the competitor holds its row locks
    and has not yet taken the campaign row; the keyed copy reserves its key (the campaign row `FOR KEY
    SHARE`) and waits at the role rows. The competitor's campaign lock then closes DEF-019's cycle."""
    user, first_pattern, _copy_pattern, competitor, lost_probe = _competitor(
        kind, client_factory, g, m, npc
    )
    key = new_key()
    done, copied, baseline = run_gated(
        postgres_engine, first_pattern, competitor,
        copier(client_factory, g, npc, user, key=key),
    )  # fmt: skip
    _classify(
        postgres_engine, copy_response=copied, competitor=done, baseline=baseline,
        record=record_property,
    )  # fmt: skip
    lost = lost_probe(postgres_engine)
    assert lost == (code(done) in (200, 201)), (
        "a 2xx competitor committed; a failed one rolled back"
    )
    _assert_copy_invariants(
        postgres_engine, g, npc, key, copy_response=copied, lost=lost, source=source
    )
    if not lost:  # the competitor lost: the copy ran with its authority intact
        assert code(copied) in (200, 201)


@pytest.mark.parametrize("kind", COMPETITORS)
def test_ka_copy_first_the_competitor_waits_and_both_commit_in_order(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str], record_property: Callable[..., Any], kind: str,
) -> None:  # fmt: skip
    user, _first, copy_pattern, competitor, lost_probe = _competitor(
        kind, client_factory, g, m, npc
    )
    key = new_key()
    copied, done, baseline = run_gated(
        postgres_engine, copy_pattern, copier(client_factory, g, npc, user, key=key), competitor
    )  # fmt: skip
    outcome = _classify(
        postgres_engine, copy_response=copied, competitor=done, baseline=baseline,
        record=record_property,
    )  # fmt: skip
    if outcome == "serialized":  # the copy committed first; the competitor waited behind it
        assert code(copied) in (200, 201) and code(done) in (200, 201)
        assert lost_probe(postgres_engine)
    # The copy held the locks first, so an authority loss that committed afterwards is legal; the
    # invariant here is only that a 2xx matches committed state and a loser left nothing.
    _assert_copy_invariants(
        postgres_engine, g, npc, key, copy_response=copied, lost=False, source=source
    )


# --- KA4: the keyed release of an uncovered player-profile field ------------------------------------------------------


def _uncovered_copy(factory: Factory, g: Gate, npc: uuid.UUID) -> None:
    assert code(copy_pp(factory, g.o1_user_id, g, npc)) == 201


def test_ka4_competitor_first_the_keyed_release_serialises_or_loses_to_the_documented_deadlock(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str],
    record_property: Callable[..., Any],
) -> None:  # fmt: skip
    """The releaser `o2` (an owner, so reveal authority) is given a `canon.edit` deny through the grant
    route while a keyed release of a draft holding an uncovered player-profile field is in flight."""
    _uncovered_copy(client_factory, g, npc)
    key = new_key()
    granted, released, baseline = run_gated(
        postgres_engine, GRANT_CAMPAIGN_LOCK,
        grant_deny(client_factory, g, npc, g.o2, g.o1_user_id),
        lambda: release(client_factory, g.o2_user_id, g, npc, 1, key=key),
    )  # fmt: skip
    _classify(
        postgres_engine, copy_response=released, competitor=granted, baseline=baseline,
        record=record_property,
    )  # fmt: skip
    lost = denied(postgres_engine, g, g.o2)
    assert lost == (code(granted) in (200, 201))
    rows = release_rows(postgres_engine, g, npc)
    released_ok = code(released) in (200, 201)
    assert not (released_ok and lost), "an uncovered field was released after the deny committed"
    if released_ok:
        assert [r["version_number"] for r in rows] == [1] and completed_receipts_for(postgres_engine, key) == 1  # fmt: skip
    else:
        assert rows == [] and receipts_for(postgres_engine, key) == 0
        assert (code(released), error_code(released) if code(released) < 500 else "") in (
            (403, "public_profile_field_withheld"),
            (500, ""),
        ), (code(released), body(released))
        assert source["personality"] not in released.text
    state_row = draft(postgres_engine, g, npc)
    assert (
        state_row is not None and state_row["row_version"] == 1
    )  # a release never changes the draft


def test_ka4_release_first_the_grant_waits_and_both_commit(
    client_factory: Factory, postgres_engine: Engine, g: Gate, npc: uuid.UUID, source: dict[str, str]
) -> None:  # fmt: skip
    _uncovered_copy(client_factory, g, npc)
    key = new_key()
    released, granted, baseline = run_gated(
        postgres_engine, RELEASE_INSERT,
        lambda: release(client_factory, g.o2_user_id, g, npc, 1, key=key),
        grant_deny(client_factory, g, npc, g.o2, g.o1_user_id),
    )  # fmt: skip
    # The release was the first holder: it must commit (o2 has no deny yet) and the grant waits.
    assert code(released) == 201, body(released)
    assert code(granted) == 201, body(granted)
    assert [r["version_number"] for r in release_rows(postgres_engine, g, npc)] == [1]
    assert denied(postgres_engine, g, g.o2)
    assert deadlock_count(postgres_engine) == baseline


# --- R01: the actual reachability of time-based expiry during a lock wait ---------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="R01 / DEF-015 F-1: expiry during a lock wait is not re-judged (inherited by every "
    "authoring write; design 10.5). Remove this marker when R01 is corrected.",
)
def test_r01_a_role_that_expires_during_the_copys_lock_wait_must_refuse_the_copy(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID,
    source: dict[str, str],
) -> None:  # fmt: skip
    """States the *desired* fresh-authorization behaviour and is a strict xfail today. The copy judges the caller's `canon.edit` in
    `lock_authoring_scope`, then waits (here on the character's entity row). `resolve_access_context`
    judges `expires_at` against `now()`, the transaction's *start*, and nothing re-judges after the
    wait, so a role that lapses while the copy waits still lets it commit (observed: 201). This is the
    inherited R01 / DEF-015 F-1 gap that every authoring write shares (design 10.5); A5c adds no
    fresh-instant re-check and does not widen it. The final assertions state the required behaviour,
    so the strict xfail turns into a failure (and must be removed) the moment R01 is corrected."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + interval '3 seconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": m.gm_role},
        )
    with postgres_engine.connect() as holder:
        transaction = holder.begin()
        holder.execute(
            text("SELECT 1 FROM core.entities WHERE entity_id = :e FOR UPDATE"), {"e": npc}
        )
        pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
        copying = run_in_thread("copy", copier(client_factory, g, npc, m.gm_user_id))
        wait_until_pid_blocks(postgres_engine, pid)  # past the role check, waiting on the entity
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with postgres_engine.connect() as probe:
                if probe.execute(
                    text(
                        "SELECT expires_at <= now() FROM security.membership_roles "
                        "WHERE membership_role_id = :r"
                    ),
                    {"r": m.gm_role},
                ).scalar_one():
                    break
            threading.Event().wait(0.2)
        assert not copying.finished()
        transaction.commit()
    response = copying.wait("copy")
    with postgres_engine.connect() as connection:
        expired = connection.execute(
            text(
                "SELECT expires_at <= now() FROM security.membership_roles "
                "WHERE membership_role_id = :r"
            ),
            {"r": m.gm_role},
        ).scalar_one()
    assert expired, "the role must have lapsed before the copy committed"
    assert is_refusal(response), (code(response), "the copy committed after the role expired")
    assert draft(postgres_engine, g, npc) is None
