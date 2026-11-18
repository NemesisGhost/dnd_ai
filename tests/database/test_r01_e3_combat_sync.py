# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 E3: the Foundry combat sync with a fresh final authorization in each engine transaction (design 5).

Real route, real guard, real final statement, on a pool engine with the commit guard installed. One call runs R (the
request transaction, the early check, finalized and ended), then takes the operation's session advisory lock and runs
C (the claim, which also serves a replay) and W (the work: the combat writes and their completion bookkeeping) on that
one connection, each judged by its own final check, the last statement before COMMIT. The final statements of a new
operation are therefore the 1st (R), 2nd (C) and 3rd (W) `WITH clock AS MATERIALIZED ...` statements.

The capability that authorizes the sync is **`canon.edit`** (`_INTEGRATION_MANAGE_CAPABILITY` in `dnd_ai.api.integration`
is only the constant's name; there is no `integration.manage` capability). Its revocation is tested through the role
assignment, the role's capability row, the role's expiry, the membership and the campaign's lifecycle.
"""

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands import integration as integration_module
from dnd_ai.commands.foundry_pairing import (
    consume_foundry_pairing_code,
    create_foundry_pairing_code,
    revoke_foundry_connection,
    revoke_foundry_device,
)
from dnd_ai.domain.foundry_pairing import FOUNDRY_SCOPES
from tests.database.test_api_integration import (  # noqa: F401 - fixtures by name
    Fixture,
    _combat_sync_body,
    _combat_sync_url,
    _register_system_as_gm,
    _start_encounter,
    client_factory,
    f,
)
from tests.database.test_r01_s2_profile_routes import Recorder, idle_in_transaction
from tests.database.test_r01_s3_authoring_routes import code, error_of
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixtures by name
    NthGate,
    Pool,
    assert_clean,
    pool,
    race,
    rows,
)
from tests.factories import lookup_id, oidc_principal
from tests.http_race_support import run_in_thread

pytestmark = pytest.mark.database

# The final authorization statement (one per R, C and W).
FINAL_STATEMENT = r"^WITH clock AS MATERIALIZED \(SELECT clock_timestamp\(\) AS t_auth\)"
R_FINAL, C_FINAL, W_FINAL = 1, 2, 3
# W's round row lock, the first statement after `_lock_encounter` took the encounter row `FOR UPDATE`.
# W's first write that references the campaign (a foreign key: it takes the campaign row `KEY SHARE` until COMMIT).
INTERACTION_INSERT = r"^INSERT INTO interaction\.interactions"
ROUND_LOCK = r"^SELECT encounter_round_id FROM narrative\.encounter_rounds .* FOR UPDATE$"


# --- the scene ------------------------------------------------------------------------------------------------------


@dataclass
class Scene:
    f: Fixture
    pool: Pool
    system: uuid.UUID
    encounter: uuid.UUID
    base_state: dict[str, Any]
    #: The test's own engine (never the request pool): `race()` disposes the pool and then reads statistics through this one.
    engine: Any = None


def client_for(p: Pool, user: uuid.UUID | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: p.engine
    if user is not None:
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user)
    return TestClient(app, raise_server_exceptions=False)


def state(sc_f: Fixture, p: Pool, encounter: uuid.UUID, system: uuid.UUID) -> dict[str, Any]:
    """Every durable combat and bookkeeping fact one sync can write (jobs are read separately)."""
    return rows(
        p.engine,
        """
        SELECT (SELECT count(*) FROM narrative.encounter_turns t
                  JOIN narrative.encounter_rounds r ON r.encounter_round_id = t.encounter_round_id
                 WHERE r.encounter_id = :e) AS turns,
               (SELECT count(*) FROM narrative.encounter_rounds WHERE encounter_id = :e) AS rounds,
               (SELECT current_round FROM narrative.encounters WHERE encounter_id = :e) AS current_round,
               (SELECT count(*) FROM interaction.interactions WHERE campaign_id = :c) AS interactions,
               (SELECT count(*) FROM narrative.events WHERE campaign_id = :c) AS events,
               (SELECT count(*) FROM narrative.event_effects ee
                  JOIN narrative.events ev ON ev.event_id = ee.event_id WHERE ev.campaign_id = :c) AS effects,
               (SELECT current_hit_points FROM campaign.character_state
                 WHERE timeline_id = :t AND character_id = :d) AS hp,
               (SELECT count(*) FROM integration.sync_state WHERE external_system_id = :s) AS sync_state,
               (SELECT count(*) FROM integration.delivery_attempts da
                  JOIN integration.sync_jobs j ON j.sync_job_id = da.sync_job_id
                 WHERE j.external_system_id = :s) AS attempts
        """,
        e=encounter,
        c=sc_f.campaign_id,
        t=sc_f.timeline_id,
        d=sc_f.defender_id,
        s=system,
    )[0]


def jobs(p: Pool, system: uuid.UUID, op: str) -> list[dict[str, Any]]:
    return rows(
        p.engine,
        """
        SELECT j.sync_job_id, j.status, j.error_message, j.updated_at, j.resulting_event_id,
               (SELECT count(*) FROM integration.delivery_attempts d WHERE d.sync_job_id = j.sync_job_id) AS attempts,
               (SELECT count(*) FROM integration.delivery_attempts d
                 WHERE d.sync_job_id = j.sync_job_id AND d.succeeded) AS succeeded
        FROM integration.sync_jobs j WHERE j.external_system_id = :s AND j.external_operation_id = :o
        """,
        s=system,
        o=op,
    )


def advisory_locks_held(p: Pool) -> int:
    return int(
        rows(
            p.engine,
            "SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' "
            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())",
        )[0]["n"]
    )


def assert_cleaned_up(p: Pool) -> None:
    """No advisory lock, no open transaction and no connection left checked out."""
    assert advisory_locks_held(p) == 0
    assert idle_in_transaction(p.engine) == 0
    assert p.engine.pool.checkedout() == 0  # type: ignore[attr-defined]


@pytest.fixture
def sc(
    f: Fixture,
    pool: Pool,
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],
) -> Scene:
    system = _register_system_as_gm(client_factory, f, f.campaign_id)
    with client_factory(f.gm_user_id) as client:
        encounter = _start_encounter(client, f)
    return Scene(f, pool, system, encounter, state(f, pool, encounter, system), postgres_engine)


def op_id() -> str:
    return f"op-{uuid.uuid4().hex[:10]}"


def body(sc: Scene, op: str, **overrides: Any) -> dict[str, Any]:
    payload = _combat_sync_body(
        sc.f, sc.encounter, external_system_id=sc.system, external_operation_id=op
    )
    payload.update(overrides)
    return payload


def sync(
    sc: Scene,
    op: str,
    *,
    user: uuid.UUID | None = None,
    campaign: uuid.UUID | None = None,
    headers: dict[str, str] | None = None,
    **overrides: Any,
) -> Any:
    """One request. `user=None` with `headers` is a Foundry credential; otherwise a session caller (the GM by default)."""
    actor = None if headers else (user or sc.f.gm_user_id)
    with client_for(sc.pool, actor) as client:
        return client.post(
            _combat_sync_url(campaign or sc.f.campaign_id),
            json=body(sc, op, **overrides),
            headers=headers,
        )


def not_participant() -> dict[str, str]:
    """A payload that fails in W (the actor is not a participant), a domain failure. Build it ONCE per operation: a
    changed payload under one operation id is a conflict."""
    return {"actor_entity_id": str(uuid.uuid4())}


# --- authority changes (committed from outside the request) --------------------------------------------------------------


def membership_of(sc: Scene, user: uuid.UUID) -> uuid.UUID:
    return rows(
        sc.pool.engine,
        "SELECT campaign_membership_id AS m FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=sc.f.campaign_id,
        u=user,
    )[0]["m"]


def gm_role(sc: Scene) -> uuid.UUID:
    return rows(
        sc.pool.engine,
        "SELECT role_id AS r FROM security.membership_roles WHERE campaign_membership_id = :m",
        m=membership_of(sc, sc.f.gm_user_id),
    )[0]["r"]


def _exec(sc: Scene, sql: str, **params: Any) -> None:
    with sc.pool.engine.begin() as c:
        c.execute(text(sql), params)


def revoke_role(sc: Scene) -> None:
    _exec(
        sc,
        "UPDATE security.membership_roles SET revoked_at = now() WHERE campaign_membership_id = :m",
        m=membership_of(sc, sc.f.gm_user_id),
    )


def restore_role(sc: Scene) -> None:
    _exec(
        sc,
        "UPDATE security.membership_roles SET revoked_at = NULL, expires_at = NULL "
        "WHERE campaign_membership_id = :m",
        m=membership_of(sc, sc.f.gm_user_id),
    )


def expire_role(sc: Scene) -> None:
    _exec(
        sc,
        "UPDATE security.membership_roles SET expires_at = now() WHERE campaign_membership_id = :m",
        m=membership_of(sc, sc.f.gm_user_id),
    )


def remove_canon_edit(sc: Scene) -> None:
    """The role keeps `campaign.view` but loses `canon.edit`: the capability itself is revoked from the role."""
    with sc.pool.engine.begin() as c:
        canon_edit = lookup_id(c, "security", "capabilities", "capability_id", "canon.edit")
        c.execute(
            text(
                "DELETE FROM security.role_capabilities WHERE role_id = :r AND capability_id = :k"
            ),
            {"r": gm_role(sc), "k": canon_edit},
        )


def restore_canon_edit(sc: Scene) -> None:
    with sc.pool.engine.begin() as c:
        canon_edit = lookup_id(c, "security", "capabilities", "capability_id", "canon.edit")
        c.execute(
            text(
                "INSERT INTO security.role_capabilities (role_id, capability_id) VALUES (:r, :k) "
                "ON CONFLICT DO NOTHING"
            ),
            {"r": gm_role(sc), "k": canon_edit},
        )


def end_membership(sc: Scene) -> None:
    _exec(
        sc,
        "UPDATE security.campaign_memberships SET ended_at = now() WHERE campaign_membership_id = :m",
        m=membership_of(sc, sc.f.gm_user_id),
    )


def restore_membership(sc: Scene) -> None:
    _exec(
        sc,
        "UPDATE security.campaign_memberships SET ended_at = NULL WHERE campaign_membership_id = :m",
        m=membership_of(sc, sc.f.gm_user_id),
    )


def archive_campaign(sc: Scene) -> None:
    _exec(
        sc,
        "UPDATE campaign.campaigns SET lifecycle_status_id = "
        "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
        "WHERE campaign_id = :c",
        c=sc.f.campaign_id,
    )


def unarchive_campaign(sc: Scene) -> None:
    _exec(
        sc,
        "UPDATE campaign.campaigns SET lifecycle_status_id = "
        "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'pending') "
        "WHERE campaign_id = :c",
        c=sc.f.campaign_id,
    )


# change name -> (apply, undo, status the route refuses with)
CHANGES: dict[str, tuple[Callable[[Scene], None], Callable[[Scene], None], int]] = {
    "role_revoked": (revoke_role, restore_role, 403),
    "canon_edit_removed_from_the_role": (remove_canon_edit, restore_canon_edit, 403),
    "role_expired": (expire_role, restore_role, 403),
    "membership_ended": (end_membership, restore_membership, 404),
    "campaign_archived": (archive_campaign, unarchive_campaign, 404),
}


def gated(
    sc: Scene,
    nth: int,
    run: Callable[[], Any],
    during: Callable[[], None],
    *,
    pattern: str = FINAL_STATEMENT,
) -> Any:
    """Run `run` and stop it at the `nth` statement matching `pattern` (by default a final statement, after every earlier
    statement of that transaction); `during` commits from outside; then release. Returns the response."""
    with NthGate(sc.pool.engine, pattern, nth) as gate:
        request = gate.track(run_in_thread("sync", run))
        gate.wait_reached()
        assert gate.matched is not None and re.search(pattern, gate.matched)
        during()
        gate.release()
        assert request.done.wait(30.0)
    return request.result


# =====================================================================================================================
# The capability and the authorized path
# =====================================================================================================================


def test_an_authorized_sync_applies_the_combat_once_and_leaves_nothing_behind(sc: Scene) -> None:
    op = op_id()
    response = sync(sc, op)
    assert code(response) == 201, response.text
    assert response.json()["replayed"] is False and response.json()["new_hit_points"] == 13
    after = state(sc.f, sc.pool, sc.encounter, sc.system)
    assert after["turns"] == 1 and after["hp"] == 13 and after["attempts"] == 1
    assert after["sync_state"] == 1 and after["events"] == sc.base_state["events"] + 1
    [job] = jobs(sc.pool, sc.system, op)
    assert job["status"] == "completed" and job["attempts"] == 1 and job["succeeded"] == 1
    assert_cleaned_up(sc.pool)


def test_the_final_statement_runs_three_times_for_a_new_operation_and_twice_for_a_replay(
    sc: Scene,
) -> None:
    op = op_id()
    with Recorder(sc.pool.engine) as first:
        assert code(sync(sc, op)) == 201
    with Recorder(sc.pool.engine) as second:
        assert sync(sc, op).json()["replayed"] is True
    final = re.compile(FINAL_STATEMENT)
    assert sum(1 for s in first.events if final.search(s)) == 3  # R, C, W
    assert sum(1 for s in second.events if final.search(s)) == 2  # R, C (a replay never reaches W)


def test_a_role_without_canon_edit_is_refused_and_writes_nothing(sc: Scene) -> None:
    """`canon.edit` is the capability that authorizes the sync: a member who holds only `campaign.view` is refused."""
    remove_canon_edit(sc)
    response = sync(sc, op_id())
    assert (code(response), error_of(response)) == (403, "forbidden")
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == sc.base_state
    assert_cleaned_up(sc.pool)


# =====================================================================================================================
# Fresh final authorization at W: full combat rollback, a retry after the refusal
# =====================================================================================================================


# A role revoke, a role expiry and a membership end fire the deferred `retain_access_manager` triggers, whose COMMIT-time
# check waits for any transaction holding the campaign row `KEY SHARE`. W holds it from its first campaign-referencing
# write (`INSERT INTO interaction.interactions`) to its COMMIT, so such a change cannot commit while W is past that
# write: it commits after W (tested separately). A lapse is committed *before* that write, or, for the changes that do
# not wait, between W's last write and its final statement.
WAITS_FOR_THE_WRITER = frozenset({"role_revoked", "role_expired", "membership_ended"})
W_CASES = [(c, "first_write") for c in sorted(CHANGES)] + [
    (c, "final") for c in sorted(CHANGES) if c not in WAITS_FOR_THE_WRITER
]
W_POINT = {"first_write": (1, INTERACTION_INSERT), "final": (W_FINAL, FINAL_STATEMENT)}


@pytest.mark.parametrize(("change", "at"), W_CASES)
def test_a_lapse_before_the_works_final_check_rolls_back_the_whole_combat_and_a_retry_applies_it_once(
    change: str, at: str, sc: Scene
) -> None:
    apply, undo, refused = CHANGES[change]
    op = op_id()
    nth, pattern = W_POINT[at]
    response = gated(sc, nth, lambda: sync(sc, op), lambda: apply(sc), pattern=pattern)
    assert code(response) == refused, response.text
    # every combat and completion write rolled back together (the encounter row's UPDATE and the HP included)
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == sc.base_state
    # C's committed claim is all that remains: in progress, no attempt, retryable (decision E3-D2)
    [job] = jobs(sc.pool, sc.system, op)
    assert job["status"] == "in_progress" and job["attempts"] == 0 and job["error_message"] is None
    assert_cleaned_up(sc.pool)
    # authority restored, the same delivery is retried: one completion, one successful attempt, damage once
    undo(sc)
    again = sync(sc, op)
    assert code(again) == 201 and again.json()["replayed"] is False, again.text
    after = state(sc.f, sc.pool, sc.encounter, sc.system)
    assert after["turns"] == 1 and after["hp"] == 13 and after["attempts"] == 1
    [job] = jobs(sc.pool, sc.system, op)
    assert job["status"] == "completed" and job["succeeded"] == 1 and job["attempts"] == 1
    assert_cleaned_up(sc.pool)


# =====================================================================================================================
# Fresh final authorization at C: a new operation, a replay, a retry
# =====================================================================================================================


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_lapse_before_the_claims_final_check_keeps_no_job_for_a_new_operation(
    change: str, sc: Scene
) -> None:
    apply, undo, refused = CHANGES[change]
    op = op_id()
    response = gated(sc, C_FINAL, lambda: sync(sc, op), lambda: apply(sc))
    assert code(response) == refused, response.text
    assert jobs(sc.pool, sc.system, op) == []  # C rolled back: no sync_jobs row
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == sc.base_state
    assert_cleaned_up(sc.pool)
    undo(sc)
    assert code(sync(sc, op)) == 201


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_lapse_before_the_claims_final_check_refuses_a_replay_without_disclosing_it(
    change: str, sc: Scene
) -> None:
    apply, undo, refused = CHANGES[change]
    op = op_id()
    assert code(sync(sc, op)) == 201
    done = state(sc.f, sc.pool, sc.encounter, sc.system)
    [before] = jobs(sc.pool, sc.system, op)
    response = gated(sc, C_FINAL, lambda: sync(sc, op), lambda: apply(sc))
    assert code(response) == refused, response.text
    for field in ("sync_job_id", "encounter_turn_id", "new_hit_points", "replayed"):
        assert field not in response.text  # the original result is not disclosed
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == done
    assert jobs(sc.pool, sc.system, op) == [before]
    assert_cleaned_up(sc.pool)
    undo(sc)
    assert sync(sc, op).json()["replayed"] is True


def test_a_lapse_before_the_claims_final_check_leaves_a_failed_job_unchanged_on_retry(
    sc: Scene,
) -> None:
    op = op_id()
    payload = not_participant()
    failed = sync(sc, op, **payload)
    assert code(failed) == 400
    [before] = jobs(sc.pool, sc.system, op)
    assert before["status"] == "failed" and before["attempts"] == 1
    response = gated(sc, C_FINAL, lambda: sync(sc, op, **payload), lambda: revoke_role(sc))
    assert code(response) == 403, response.text
    assert jobs(sc.pool, sc.system, op) == [
        before
    ]  # status, attempts, error_message and updated_at untouched
    assert_cleaned_up(sc.pool)


# =====================================================================================================================
# Replay and conflict inside one campaign
# =====================================================================================================================


def test_a_same_campaign_replay_returns_the_original_result_and_a_changed_payload_conflicts(
    sc: Scene,
) -> None:
    op = op_id()
    first = sync(sc, op)
    replay = sync(sc, op)
    assert code(first) == code(replay) == 201
    assert replay.json()["replayed"] is True
    for key in (
        "sync_job_id",
        "encounter_turn_id",
        "combat_action_id",
        "event_id",
        "new_hit_points",
    ):
        assert replay.json()[key] == first.json()[key]
    conflict = sync(sc, op, damage_amount=3)
    assert (code(conflict), error_of(conflict)) == (409, "conflict")
    after = state(sc.f, sc.pool, sc.encounter, sc.system)
    assert after["turns"] == 1 and after["hp"] == 13
    assert_cleaned_up(sc.pool)


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_replay_after_the_authority_is_gone_is_refused(change: str, sc: Scene) -> None:
    apply, _undo, refused = CHANGES[change]
    op = op_id()
    assert code(sync(sc, op)) == 201
    apply(sc)
    response = sync(sc, op)
    assert code(response) == refused, response.text
    assert "sync_job_id" not in response.text
    assert_cleaned_up(sc.pool)


# =====================================================================================================================
# F-1: another campaign's route never replays, conflicts with or rewrites the operation
# =====================================================================================================================


def test_another_campaigns_route_gets_a_404_for_a_replay_and_for_a_conflicting_payload(
    sc: Scene,
) -> None:
    op = op_id()
    assert code(sync(sc, op)) == 201
    done = state(sc.f, sc.pool, sc.encounter, sc.system)
    [before] = jobs(sc.pool, sc.system, op)
    other = sc.f.other_campaign_id  # the GM holds canon.edit there too
    replay = sync(sc, op, campaign=other)
    assert (code(replay), error_of(replay)) == (404, "not_found"), replay.text
    assert "sync_job_id" not in replay.text
    conflict = sync(sc, op, campaign=other, damage_amount=3)
    assert (code(conflict), error_of(conflict)) == (
        404,
        "not_found",
    )  # never a 409 that confirms the id
    assert jobs(sc.pool, sc.system, op) == [before]
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == done
    assert_cleaned_up(sc.pool)


def test_another_campaigns_route_does_not_retry_or_rewrite_a_failed_job(sc: Scene) -> None:
    op = op_id()
    payload = not_participant()
    assert code(sync(sc, op, **payload)) == 400
    [before] = jobs(sc.pool, sc.system, op)
    done = state(sc.f, sc.pool, sc.encounter, sc.system)
    other = sync(sc, op, campaign=sc.f.other_campaign_id, **payload)
    assert code(other) == 404, other.text
    assert jobs(sc.pool, sc.system, op) == [
        before
    ]  # attempts, error_message and updated_at are untouched
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == done
    assert_cleaned_up(sc.pool)


def test_the_owning_campaign_still_retries_its_own_failed_job(sc: Scene) -> None:
    op = op_id()
    payload = not_participant()
    assert code(sync(sc, op, **payload)) == 400
    assert (
        code(sync(sc, op, **payload)) == 400
    )  # retried under the same job: a second failed attempt
    [job] = jobs(sc.pool, sc.system, op)
    assert job["status"] == "failed" and job["attempts"] == 2
    assert_cleaned_up(sc.pool)


# =====================================================================================================================
# The advisory lock is released on every path
# =====================================================================================================================


def test_the_advisory_lock_is_released_after_a_domain_failure_and_the_job_is_failed(
    sc: Scene,
) -> None:
    op = op_id()
    response = sync(sc, op, **not_participant())
    assert code(response) == 400, response.text
    [job] = jobs(sc.pool, sc.system, op)
    assert (
        job["status"] == "failed" and job["attempts"] == 1
    )  # the fail step still runs for a domain failure
    assert state(sc.f, sc.pool, sc.encounter, sc.system)["turns"] == 0
    assert_cleaned_up(sc.pool)


def test_the_advisory_lock_is_released_when_recording_the_failure_itself_fails(
    sc: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("the fail step failed")

    monkeypatch.setattr(integration_module, "_fail_sync_job", boom)
    response = sync(sc, op_id(), **not_participant())
    assert code(response) == 400, (
        response.text
    )  # the original domain failure, not the bookkeeping one
    assert_cleaned_up(sc.pool)


def test_the_fail_step_is_not_run_after_the_works_final_refusal(
    sc: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = integration_module._fail_sync_job
    monkeypatch.setattr(
        integration_module, "_fail_sync_job", lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    )
    response = gated(
        sc, 1, lambda: sync(sc, op_id()), lambda: revoke_role(sc), pattern=INTERACTION_INSERT
    )
    assert code(response) == 403
    assert calls == []


def test_a_waiting_replay_is_judged_after_the_wait_and_the_lock_is_released(sc: Scene) -> None:
    """The holder is stopped at W's first campaign write with the advisory lock held; a second delivery of the same operation
    queues on the lock. The role is revoked, the holder is released: the holder is refused at W, and the waiter, which
    gets the lock afterwards, is refused at C by its own fresh check. Nothing is applied; one redelivery then applies it
    exactly once."""
    op = op_id()
    with NthGate(sc.pool.engine, INTERACTION_INSERT, 1) as gate:
        holder = gate.track(run_in_thread("holder", lambda: sync(sc, op)))
        gate.wait_reached()
        waiter = run_in_thread("waiter", lambda: sync(sc, op))
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            queued = rows(
                sc.pool.engine,
                "SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' AND NOT granted",
            )[0]["n"]
            if queued:
                break
            time.sleep(0.05)
        assert queued == 1, "the second delivery never queued on the operation's advisory lock"
        revoke_role(sc)
        gate.release()
        assert holder.done.wait(30.0) and waiter.done.wait(30.0)
    assert code(holder.result) == 403 and code(waiter.result) == 403
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == sc.base_state
    assert_cleaned_up(sc.pool)
    restore_role(sc)
    again = sync(sc, op)
    assert code(again) == 201
    after = state(sc.f, sc.pool, sc.encounter, sc.system)
    assert after["turns"] == 1 and after["hp"] == 13  # damage applied exactly once


# =====================================================================================================================
# The approved Foundry credential revocation boundary (plan 2.1; S4b owner decision)
# =====================================================================================================================


def pair(sc: Scene) -> Any:
    issued = create_foundry_pairing_code(
        sc.pool.engine,
        requesting_user_id=sc.f.gm_user_id,
        campaign_id=sc.f.campaign_id,
        external_system_id=sc.system,
        requested_scopes=FOUNDRY_SCOPES,
    )
    return consume_foundry_pairing_code(
        sc.pool.engine,
        raw_code=issued.raw_code,
        foundry_user_id=f"foundry-user-{uuid.uuid4().hex[:8]}",
        foundry_origin="https://foundry.example.test",
        device_label="e3-test-device",
    )


def with_token(consumed: Any) -> dict[str, str]:
    return {"Authorization": f"FoundryAccess {consumed.raw_access_token}"}


def revoke_connection(sc: Scene, consumed: Any) -> None:
    with sc.pool.engine.begin() as c:
        revoke_foundry_connection(
            c,
            foundry_connection_id=consumed.foundry_connection_id,
            revoked_by_user_id=sc.f.gm_user_id,
        )


def revoke_device(sc: Scene, consumed: Any) -> None:
    with sc.pool.engine.begin() as c:
        revoke_foundry_device(
            c, foundry_device_id=consumed.foundry_device_id, revoked_by_user_id=sc.f.gm_user_id
        )


def test_a_foundry_credential_syncs_through_the_same_checks(sc: Scene) -> None:
    consumed = pair(sc)
    response = sync(sc, op_id(), headers=with_token(consumed))
    assert code(response) == 201, response.text
    assert state(sc.f, sc.pool, sc.encounter, sc.system)["turns"] == 1


@pytest.mark.parametrize("revoke", ("connection", "device"))
@pytest.mark.parametrize("final", (R_FINAL, W_FINAL))
def test_a_credential_revoked_after_authentication_does_not_stop_the_request_in_flight(
    revoke: str, final: int, sc: Scene
) -> None:
    """The approved boundary: explicit device or connection revocation is judged at the request's start only. The
    request, authenticated before the revocation, completes and its combat is kept."""
    consumed = pair(sc)
    act = revoke_connection if revoke == "connection" else revoke_device
    response = gated(
        sc,
        final,
        lambda: sync(sc, op_id(), headers=with_token(consumed)),
        lambda: act(sc, consumed),
    )
    assert code(response) == 201, response.text
    after = state(sc.f, sc.pool, sc.encounter, sc.system)
    assert after["turns"] == 1 and after["hp"] == 13
    assert_cleaned_up(sc.pool)


def test_the_contrast_a_canon_edit_revoke_before_the_works_final_check_does_refuse(
    sc: Scene,
) -> None:
    consumed = pair(sc)
    response = gated(
        sc,
        1,
        lambda: sync(sc, op_id(), headers=with_token(consumed)),
        lambda: revoke_role(sc),
        pattern=INTERACTION_INSERT,
    )
    assert code(response) == 403, response.text
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == sc.base_state


@pytest.mark.parametrize("revoke", ("connection", "device"))
def test_a_credential_revoked_before_the_request_is_refused_and_nothing_is_written(
    revoke: str, sc: Scene
) -> None:
    consumed = pair(sc)
    (revoke_connection if revoke == "connection" else revoke_device)(sc, consumed)
    op = op_id()
    response = sync(sc, op, headers=with_token(consumed))
    assert code(response) == 401, response.text
    assert jobs(sc.pool, sc.system, op) == []
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == sc.base_state
    assert_cleaned_up(sc.pool)


def test_a_replay_with_a_revoked_credential_is_refused_without_disclosure(sc: Scene) -> None:
    consumed = pair(sc)
    op = op_id()
    assert code(sync(sc, op, headers=with_token(consumed))) == 201
    revoke_connection(sc, consumed)
    replay = sync(sc, op, headers=with_token(consumed))
    assert code(replay) == 401, replay.text
    assert "sync_job_id" not in replay.text


# =====================================================================================================================
# Concurrency: no cycle with another sync, a human combat turn, or an access change
# =====================================================================================================================


def human_turn(sc: Scene, **overrides: Any) -> Any:
    payload = {
        "round_number": 1,
        "turn_order": 5,
        "actor_entity_id": str(sc.f.attacker_id),
        "world_time_id": str(sc.f.world_time_id),
        "target_entity_id": str(sc.f.defender_id),
        "hit": True,
        "damage_amount": 2,
    }
    payload.update(overrides)
    with client_for(sc.pool, sc.f.gm_user_id) as client:
        return client.post(
            f"/campaigns/{sc.f.campaign_id}/encounters/{sc.encounter}/turns", json=payload
        )


def test_a_sync_and_a_human_combat_turn_on_one_encounter_serialize_in_both_orders(
    sc: Scene,
) -> None:
    first = race(
        sc,
        sc.pool,
        gate_pattern=ROUND_LOCK,
        parked=lambda: sync(sc, op_id()),
        second=lambda: human_turn(sc, round_number=2),
    )
    assert_clean(first)
    assert code(first.results["parked"]) == 201 and code(first.results["second"]) == 201, (
        first.summary()
    )
    other = race(
        sc,
        sc.pool,
        gate_pattern=ROUND_LOCK,
        parked=lambda: human_turn(sc, round_number=3),
        second=lambda: sync(sc, op_id(), round_number=4),
    )
    assert_clean(other)
    assert code(other.results["parked"]) == 201 and code(other.results["second"]) == 201, (
        other.summary()
    )
    assert state(sc.f, sc.pool, sc.encounter, sc.system)["hp"] == 20 - 7 - 2 - 2 - 7
    assert_cleaned_up(sc.pool)


def test_two_operations_on_one_encounter_serialize_without_a_cycle(sc: Scene) -> None:
    o = race(
        sc,
        sc.pool,
        gate_pattern=ROUND_LOCK,
        parked=lambda: sync(sc, op_id()),
        second=lambda: sync(sc, op_id(), round_number=2),
    )
    assert_clean(o)
    assert code(o.results["parked"]) == 201 and code(o.results["second"]) == 201, o.summary()
    assert_cleaned_up(sc.pool)


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_an_access_change_before_the_works_campaign_writes_does_not_wait_for_the_sync(
    change: str, sc: Scene
) -> None:
    """Until W's first campaign-referencing write the sync holds nothing an access change needs: the change commits
    while the sync is parked at its round lock, without waiting, and the sync's own final check then sees it."""
    apply, undo, refused = CHANGES[change]
    with NthGate(sc.pool.engine, ROUND_LOCK, 1) as gate:
        request = gate.track(run_in_thread("sync", lambda: sync(sc, op_id())))
        gate.wait_reached()
        started = time.monotonic()
        apply(sc)  # would block here if the sync held a lock the change needs
        assert time.monotonic() - started < 5.0
        gate.release()
        assert request.done.wait(30.0)
    assert code(request.result) == refused, request.result.text
    assert state(sc.f, sc.pool, sc.encounter, sc.system) == sc.base_state
    assert_cleaned_up(sc.pool)
    undo(sc)


def blocked_by(sc: Scene, pid: int, *, timeout: float = 15.0) -> list[dict[str, Any]]:
    """The backends waiting on a lock held by `pid`, polled until one appears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = rows(
            sc.pool.engine,
            "SELECT pid, wait_event_type, left(query, 60) AS query FROM pg_stat_activity "
            "WHERE datname = current_database() AND :p = ANY(pg_blocking_pids(pid))",
            p=pid,
        )
        if found:
            return found
        time.sleep(0.05)
    return []


@pytest.mark.parametrize("change", sorted(WAITS_FOR_THE_WRITER))
def test_a_role_or_membership_change_arriving_during_the_work_commits_after_it(
    change: str, sc: Scene
) -> None:
    """The lock order between the work and a relevant access change, one way and without a cycle: the change's COMMIT
    waits for W (which holds the campaign `KEY SHARE`), W judges authority before the change is visible and commits, then
    the change commits and the next sync is refused."""
    apply, _undo, refused = CHANGES[change]
    op = op_id()
    with NthGate(sc.pool.engine, FINAL_STATEMENT, W_FINAL) as gate:
        request = gate.track(run_in_thread("sync", lambda: sync(sc, op)))
        gate.wait_reached()
        changer = run_in_thread("change", lambda: apply(sc))
        waiting = blocked_by(sc, gate.pid)
        assert waiting, "the access change never queued behind the work"
        assert not changer.done.is_set()
        gate.release()
        assert request.done.wait(30.0) and changer.done.wait(30.0)
    assert code(request.result) == 201, request.result.text  # ordered before the change
    after = state(sc.f, sc.pool, sc.encounter, sc.system)
    assert after["turns"] == 1 and after["hp"] == 13
    later = sync(sc, op_id())
    assert code(later) == refused, later.text  # the change committed afterwards and now applies
    assert_cleaned_up(sc.pool)
