# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S02-T01: assign, replace and revoke campaign character control, and the control read (F1-F21, F28-F32).

Every case runs over real HTTP, through the R01 guard, on real committed data (the same harness as the S5-E2/S5-E4
route tests). The concurrency cases (F22-F27 and the unique-index races) are in
`test_control_assignment_concurrency.py`.

Test-first record (plan section 6): at the T01 baseline none of the four routes exist, so every case but F12 fails
with a 404/405 or an import error. F12 (a non-member gets the existing campaign 404) is a guard that passes at the
baseline.
"""

import dataclasses
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from dnd_ai.domain.access import CONTROL_ASSIGNMENT_CAPABILITIES, resolve_access_context
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    Scene,
    m,
    pooled2,
    pooled2_factory,
    s,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_control_assignment,
    make_membership_character_relationship,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_timeline_clock,
    make_user,
    make_world,
    make_world_time,
    relationship_type_id,
    system_role_id,
)
from tests.http_race_support import new_key

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

COMMANDS = (
    "assign_character_control",
    "replace_primary_controller",
    "revoke_character_control",
)
MATRIX = CONTROL_ASSIGNMENT_CAPABILITIES["primary_controller"]


@dataclasses.dataclass
class Person:
    user: uuid.UUID
    membership: uuid.UUID


@dataclasses.dataclass
class Env:
    owner: Person
    assistant: Person
    player: Person
    observer: Person
    p1: Person
    p2: Person
    p3: Person
    character: uuid.UUID
    character2: uuid.UUID
    t10: uuid.UUID
    t20: uuid.UUID
    t30: uuid.UUID
    timeline_id: uuid.UUID


def _person(c: Any, sc: Scene, label: str, role: uuid.UUID) -> Person:
    user = make_user(c, f"C11 {label}")
    membership = make_campaign_membership(c, sc.w.campaign_id, user)
    make_membership_role(c, membership, role)
    return Person(user, membership)


def build_env(sc: Scene) -> Env:
    with sc.w.engine.begin() as c:
        owner = _person(c, sc, "Owner", sc.owner)
        assistant = _person(c, sc, "Assistant", system_role_id(c, "assistant_gm"))
        player = _person(c, sc, "Player", sc.player)
        observer = _person(c, sc, "Observer", sc.observer)
        p1 = _person(c, sc, "P1", sc.player)
        p2 = _person(c, sc, "P2", sc.player)
        p3 = _person(c, sc, "P3", sc.player)
        character = make_character(c, sc.w.world_id, name="C11 Hero")
        character2 = make_character(c, sc.w.world_id, name="C11 Other")
        times = [make_world_time(c, sc.w.world_id, key) for key in (10, 20, 30)]
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": sc.w.campaign_id},
        ).scalar_one()
    return Env(
        owner, assistant, player, observer, p1, p2, p3, character, character2, *times, timeline
    )


@pytest.fixture
def env(s: Scene) -> Env:
    return build_env(s)


@pytest.fixture(autouse=True)
def _tidy(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE world_id = :w AND command_name = ANY(:c)"),
            {"w": w.world_id, "c": list(COMMANDS)},
        )


# --- requests ----------------------------------------------------------------------------------------------------


def assign_path(sc: Scene, character: uuid.UUID) -> str:
    return f"{sc.w.base}/characters/{character}/control-assignments"


def replace_path(sc: Scene, character: uuid.UUID) -> str:
    return f"{assign_path(sc, character)}/replace-primary"


def revoke_path(sc: Scene, assignment: uuid.UUID) -> str:
    return f"{sc.w.base}/control-assignments/{assignment}/revoke"


def post(
    factory: Factory,
    user: uuid.UUID,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    key: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(user) as client:
        return client.post(path, json=body if body is not None else {}, headers=headers)


def get(factory: Factory, user: uuid.UUID, path: str) -> Any:
    with factory(user) as client:
        return client.get(path)


def assign_body(
    who: Person, role: str = "co_controller", kind: str = "ongoing", **extra: Any
) -> dict[str, Any]:
    return {
        "campaign_membership_id": str(who.membership),
        "role": role,
        "assignment_period_kind": kind,
        **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in extra.items()},
    }


def replace_body(who: Person, kind: str = "ongoing", **extra: Any) -> dict[str, Any]:
    return {
        "campaign_membership_id": str(who.membership),
        "assignment_period_kind": kind,
        **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in extra.items()},
    }


def seed(
    sc: Scene,
    who: Person,
    character: uuid.UUID,
    role: str = "co_controller",
    kind: str = "ongoing",
    **kw: Any,
) -> uuid.UUID:
    with sc.w.engine.begin() as c:
        return make_control_assignment(
            c, who.membership, character, role, kind, campaign_id=sc.w.campaign_id, **kw
        )


def set_clock(sc: Scene, e: Env, key_time: uuid.UUID) -> None:
    with sc.w.engine.begin() as c:
        make_timeline_clock(c, e.timeline_id, key_time)


@dataclasses.dataclass
class State:
    rows: tuple[Any, ...]
    audits: tuple[Any, ...]


def state(sc: Scene) -> State:
    with sc.w.engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT mcr.membership_character_relationship_id, t.code, mcr.campaign_membership_id, "
                "mcr.character_id, mcr.assignment_period_kind, mcr.effective_period::text, "
                "mcr.granted_by_membership_id, mcr.revoked_at IS NOT NULL, mcr.revoked_by_membership_id, "
                "mcr.revocation_reason, mcr.campaign_id "
                "FROM security.membership_character_relationships mcr "
                "JOIN security.character_relationship_types t USING (character_relationship_type_id) "
                "WHERE mcr.is_control_assignment AND mcr.campaign_id = :c "
                "ORDER BY mcr.granted_at, mcr.membership_character_relationship_id"
            ),
            {"c": sc.w.campaign_id},
        ).all()
        audits = c.execute(
            text(
                "SELECT command_name, record_id FROM audit.change_log "
                "WHERE world_id = :w AND command_name = ANY(:c) ORDER BY change_log_id"
            ),
            {"w": sc.w.world_id, "c": list(COMMANDS)},
        ).all()
    return State(tuple(tuple(r) for r in rows), tuple(tuple(a) for a in audits))


def row_of(sc: Scene, assignment: uuid.UUID) -> dict[str, Any]:
    with sc.w.engine.connect() as c:
        found = (
            c.execute(
                text(
                    "SELECT t.code AS role, mcr.assignment_period_kind AS kind, mcr.effective_period::text AS period, "
                    "mcr.campaign_membership_id, mcr.character_id, mcr.granted_by_membership_id, "
                    "mcr.revoked_at, mcr.revoked_by_membership_id, mcr.revocation_reason, mcr.is_control_assignment, "
                    "mcr.campaign_id, mcr.notes "
                    "FROM security.membership_character_relationships mcr "
                    "JOIN security.character_relationship_types t USING (character_relationship_type_id) "
                    "WHERE mcr.membership_character_relationship_id = :r"
                ),
                {"r": assignment},
            )
            .mappings()
            .one()
        )
    return dict(found)


def fixed_body(response: Any) -> dict[str, Any]:
    """The error body without its per-request correlation id: what a caller can compare across two requests."""
    error = dict(response.json()["error"])
    error.pop("correlation_id", None)
    return error


def unchanged(sc: Scene, before: State) -> None:
    after = state(sc)
    assert after == before


# --- F1-F5: assign ------------------------------------------------------------------------------------------------


def test_f1_the_owner_assigns_an_ongoing_primary(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    response = post(
        pooled_factory,
        env.owner.user,
        assign_path(s, env.character),
        assign_body(env.p1, "primary_controller", reason="first hand-off"),
    )
    assert code(response) == 201, response.text
    new_id = uuid.UUID(response.json()["control_assignment_id"])
    row = row_of(s, new_id)
    assert row["role"] == "primary_controller" and row["kind"] == "ongoing"
    assert row["is_control_assignment"] is True and row["campaign_id"] == s.w.campaign_id
    assert row["campaign_membership_id"] == env.p1.membership
    assert row["character_id"] == env.character
    assert row["granted_by_membership_id"] == env.owner.membership
    assert row["period"] is None and row["revoked_at"] is None
    assert (
        row["notes"] == "first hand-off"
    )  # the reason stays on the row; the audit row holds no text
    audits = state(s).audits
    assert audits == (("assign_character_control", new_id),)


def test_f2_a_gm_assigns_a_dated_co_controller(s: Scene, env: Env, pooled_factory: Factory) -> None:
    response = post(
        pooled_factory,
        s.w.gm_user,
        assign_path(s, env.character),
        assign_body(
            env.p1,
            "co_controller",
            "dated",
            effective_from_world_time_id=env.t10,
            effective_to_world_time_id=env.t30,
        ),
    )
    assert code(response) == 201, response.text
    row = row_of(s, uuid.UUID(response.json()["control_assignment_id"]))
    assert row["role"] == "co_controller" and row["kind"] == "dated"
    assert row["period"] == "[10,30)"
    assert row["granted_by_membership_id"] == s.w.gm_membership


@pytest.mark.parametrize(
    "case",
    ["no-kind", "unknown-kind", "dated-without-start", "ongoing-with-time", "dated-end-only"],
)
def test_f3_a_malformed_kind_or_period_is_422_and_writes_nothing(
    s: Scene, env: Env, pooled_factory: Factory, case: str
) -> None:
    before = state(s)
    body = assign_body(env.p1)
    if case == "no-kind":
        del body["assignment_period_kind"]
    elif case == "unknown-kind":
        body["assignment_period_kind"] = "forever"
    elif case == "dated-without-start":
        body["assignment_period_kind"] = "dated"
    elif case == "ongoing-with-time":
        body["effective_from_world_time_id"] = str(env.t10)
    else:
        body["assignment_period_kind"] = "dated"
        body["effective_to_world_time_id"] = str(env.t20)
    response = post(pooled_factory, env.owner.user, assign_path(s, env.character), body)
    assert code(response) == 422, response.text
    unchanged(s, before)


@pytest.mark.parametrize("end", ["equal", "before"])
def test_f4_an_end_not_after_its_start_is_422(
    s: Scene, env: Env, pooled_factory: Factory, end: str
) -> None:
    before = state(s)
    body = assign_body(
        env.p1,
        "co_controller",
        "dated",
        effective_from_world_time_id=env.t20,
        effective_to_world_time_id=env.t20 if end == "equal" else env.t10,
    )
    response = post(pooled_factory, env.owner.user, assign_path(s, env.character), body)
    assert code(response) == 422, response.text
    unchanged(s, before)


def test_f5_a_world_time_of_another_world_is_404(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    # a positive control first: the route exists and assigns (an absent route also answers 404)
    control = post(
        pooled_factory,
        env.owner.user,
        assign_path(s, env.character),
        assign_body(env.p2, "co_controller"),
    )
    assert code(control) == 201, control.text
    with s.w.engine.begin() as c:
        other_world = make_world(c, slug=f"c11-other-{uuid.uuid4().hex[:8]}")
        foreign = make_world_time(c, other_world, 10)
    before = state(s)
    body = assign_body(env.p1, "co_controller", "dated", effective_from_world_time_id=foreign)
    response = post(pooled_factory, env.owner.user, assign_path(s, env.character), body)
    assert code(response) == 404, response.text
    unchanged(s, before)


# --- F6-F9: assign refusals ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["ongoing", "dated-in-effect", "dated-ended"])
def test_f6_a_live_primary_blocks_a_second_primary(
    s: Scene, env: Env, pooled_factory: Factory, shape: str
) -> None:
    if shape == "ongoing":
        seed(s, env.p1, env.character, "primary_controller", "ongoing")
    elif shape == "dated-in-effect":
        seed(
            s,
            env.p1,
            env.character,
            "primary_controller",
            "dated",
            from_time=env.t10,
            to_time=env.t30,
        )
        set_clock(s, env, env.t20)
    else:
        seed(
            s,
            env.p1,
            env.character,
            "primary_controller",
            "dated",
            from_time=env.t10,
            to_time=env.t20,
        )
        set_clock(s, env, env.t30)
    before = state(s)
    response = post(
        pooled_factory,
        env.owner.user,
        assign_path(s, env.character),
        assign_body(env.p2, "primary_controller"),
    )
    assert code(response) == 409 and error_of(response) == "primary_controller_exists", (
        response.text
    )
    unchanged(s, before)


def test_f7_an_assignee_who_already_holds_an_assignment_is_refused(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    seed(s, env.p1, env.character, "co_controller", "ongoing")
    before = state(s)
    for role in ("co_controller", "primary_controller"):
        response = post(
            pooled_factory, env.owner.user, assign_path(s, env.character), assign_body(env.p1, role)
        )
        assert code(response) == 409 and error_of(response) == "control_already_assigned", (
            response.text
        )
    unchanged(s, before)


@pytest.mark.parametrize(
    "case", ["ended", "inactive-status", "other-campaign", "inactive-account", "inactive-campaign"]
)
def test_f8_an_ineligible_membership_or_campaign_is_refused(
    s: Scene, env: Env, pooled_factory: Factory, case: str
) -> None:
    target = env.p1.membership
    expected = 409
    with s.w.engine.begin() as c:
        if case == "ended":
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET ended_at = now() WHERE campaign_membership_id = :m"
                ),
                {"m": target},
            )
        elif case == "inactive-status":
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET membership_status_id = "
                    "(SELECT membership_status_id FROM security.membership_statuses WHERE code = 'suspended') "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": target},
            )
        elif case == "other-campaign":
            timeline = make_timeline(c, s.w.world_id, "Other", is_primary=False)
            other_campaign = make_campaign(c, timeline, "Other campaign")
            stranger = make_user(c, "C11 Stranger")
            target = make_campaign_membership(c, other_campaign, stranger)
            make_membership_role(c, target, s.owner)  # a campaign must retain an access manager
            expected = 404
        elif case == "inactive-account":
            c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'archived') WHERE user_id = :u"
                ),
                {"u": env.p1.user},
            )
        else:
            # the campaign route's own refusal (an inactive campaign is not found) precedes the 409 that the plan
            # keeps for a campaign that becomes inactive while the request waits (see the concurrency module)
            expected = 404
            c.execute(
                text(
                    "UPDATE campaign.campaigns SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'archived') WHERE campaign_id = :c"
                ),
                {"c": s.w.campaign_id},
            )
    before = state(s)
    body = assign_body(Person(env.p1.user, target))
    response = post(pooled_factory, env.owner.user, assign_path(s, env.character), body)
    assert code(response) == expected, response.text
    unchanged(s, before)


@pytest.mark.parametrize("case", ["missing", "other-world", "archived"])
def test_f9_a_missing_foreign_or_archived_character_is_404(
    s: Scene, env: Env, pooled_factory: Factory, case: str
) -> None:
    # a positive control first: the route exists and assigns a valid character (an absent route also answers 404)
    control = post(
        pooled_factory,
        env.owner.user,
        assign_path(s, env.character),
        assign_body(env.p2, "co_controller"),
    )
    assert code(control) == 201, control.text
    character = uuid.uuid4()
    with s.w.engine.begin() as c:
        if case == "other-world":
            character = make_character(
                c, make_world(c, slug=f"c11-ow-{uuid.uuid4().hex[:8]}"), name="Elsewhere"
            )
        elif case == "archived":
            c.execute(
                text(
                    "UPDATE core.entities SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'archived') WHERE entity_id = :e"
                ),
                {"e": env.character2},
            )
            character = env.character2
    before = state(s)
    response = post(pooled_factory, env.owner.user, assign_path(s, character), assign_body(env.p1))
    assert code(response) == 404, response.text
    unchanged(s, before)


# --- F10-F12: authority ------------------------------------------------------------------------------------------


def test_f10_an_assistant_gm_without_a_delegation_is_refused_without_disclosure(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    before = state(s)
    existing = post(
        pooled_factory, env.assistant.user, assign_path(s, env.character), assign_body(env.p1)
    )
    missing = post(
        pooled_factory, env.assistant.user, assign_path(s, uuid.uuid4()), assign_body(env.p1)
    )
    assert code(existing) == 403 and code(missing) == 403
    assert error_of(existing) == "character_assign_control_required"
    assert fixed_body(existing) == fixed_body(missing)
    unchanged(s, before)


@pytest.mark.parametrize(
    "who", ["player", "observer", "custom-manager", "primary-controller", "co-controller"]
)
def test_f11_no_other_role_or_assignment_holds_the_authority(
    s: Scene, env: Env, pooled_factory: Factory, who: str
) -> None:
    """T78, T79: `access.manage` and `canon.edit` through a custom role, and the character's own controllers, never
    confer it; the refusal is one fixed body."""
    user = {"player": env.player.user, "observer": env.observer.user}.get(who)
    if who == "custom-manager":
        with s.w.engine.begin() as c:
            custom = Person(make_user(c, "C11 Custom"), uuid.uuid4())
            custom.membership = make_campaign_membership(c, s.w.campaign_id, custom.user)
            role = make_role(c, campaign_id=s.w.campaign_id)
            for capability in ("access.manage", "canon.edit", "campaign.view"):
                make_role_capability(
                    c,
                    role,
                    c.execute(
                        text("SELECT capability_id FROM security.capabilities WHERE code = :c"),
                        {"c": capability},
                    ).scalar_one(),
                )
            make_membership_role(c, custom.membership, role)
        user = custom.user
    elif who in ("primary-controller", "co-controller"):
        seed(
            s,
            env.p1,
            env.character,
            "primary_controller" if who == "primary-controller" else "co_controller",
        )
        user = env.p1.user
    assert user is not None
    before = state(s)
    existing = post(pooled_factory, user, assign_path(s, env.character2), assign_body(env.p2))
    missing = post(pooled_factory, user, assign_path(s, uuid.uuid4()), assign_body(env.p2))
    assert code(existing) == 403 == code(missing), existing.text
    assert fixed_body(existing) == fixed_body(missing)
    unchanged(s, before)


def test_f12_a_non_member_gets_the_existing_campaign_404(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    """Guard: the route requirement is judged before the operation authority."""
    with s.w.engine.begin() as c:
        outsider = make_user(c, "C11 Outsider")
    response = post(pooled_factory, outsider, assign_path(s, env.character), assign_body(env.p1))
    assert code(response) == 404, response.text


# --- F13-F20: replace and revoke ----------------------------------------------------------------------------------


def test_f13_replace_revokes_the_primary_inserts_the_new_one_and_leaves_co_controllers(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    old = seed(s, env.p1, env.character, "primary_controller", "ongoing")
    co1 = seed(s, env.p2, env.character, "co_controller", "ongoing")
    response = post(
        pooled_factory,
        s.w.gm_user,
        replace_path(s, env.character),
        replace_body(env.p3, reason="the new player takes over"),
    )
    assert code(response) == 201, response.text
    body = response.json()
    assert uuid.UUID(body["revoked_control_assignment_id"]) == old
    new = uuid.UUID(body["control_assignment_id"])
    old_row, new_row, co_row = row_of(s, old), row_of(s, new), row_of(s, co1)
    assert old_row["revoked_at"] is not None
    assert old_row["revoked_by_membership_id"] == s.w.gm_membership
    assert old_row["revocation_reason"] == "the new player takes over"
    assert new_row["role"] == "primary_controller" and new_row["revoked_at"] is None
    assert new_row["campaign_membership_id"] == env.p3.membership
    assert new_row["granted_by_membership_id"] == s.w.gm_membership
    assert co_row["revoked_at"] is None
    audits = state(s).audits
    assert sorted(audits) == sorted(
        [("replace_primary_controller", old), ("replace_primary_controller", new)]
    )


def test_f14_replace_with_no_live_primary_is_refused(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    seed(s, env.p1, env.character, "co_controller", "ongoing")
    before = state(s)
    response = post(
        pooled_factory, env.owner.user, replace_path(s, env.character), replace_body(env.p2)
    )
    assert code(response) == 409 and error_of(response) == "no_primary_controller", response.text
    unchanged(s, before)


@pytest.mark.parametrize("named", ["co-controller", "current-primary"])
def test_f15_replace_never_promotes_or_re_assigns_a_current_holder(
    s: Scene, env: Env, pooled_factory: Factory, named: str
) -> None:
    seed(s, env.p1, env.character, "primary_controller", "ongoing")
    seed(s, env.p2, env.character, "co_controller", "ongoing")
    before = state(s)
    who = env.p2 if named == "co-controller" else env.p1
    response = post(
        pooled_factory, env.owner.user, replace_path(s, env.character), replace_body(who)
    )
    assert code(response) == 409 and error_of(response) == "control_already_assigned", response.text
    unchanged(s, before)


def test_f16_revoking_a_primary_leaves_co_controllers_and_promotes_nobody(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    primary = seed(s, env.p1, env.character, "primary_controller", "ongoing")
    co1 = seed(s, env.p2, env.character, "co_controller", "ongoing")
    co2 = seed(s, env.p3, env.character, "co_controller", "ongoing")
    with s.w.engine.connect() as c:
        before = {
            p.user: resolve_access_context(c, user_id=p.user, campaign_id=s.w.campaign_id)
            for p in (env.p2, env.p3)
        }
    response = post(
        pooled_factory, env.owner.user, revoke_path(s, primary), {"reason": "stepping back"}
    )
    assert code(response) == 200 and response.json()["revoked"] is True, response.text
    assert row_of(s, primary)["revoked_at"] is not None
    for co in (co1, co2):
        assert row_of(s, co)["revoked_at"] is None and row_of(s, co)["role"] == "co_controller"
    with s.w.engine.connect() as c:
        for p in (env.p2, env.p3):
            after = resolve_access_context(c, user_id=p.user, campaign_id=s.w.campaign_id)
            assert after is not None and before[p.user] is not None
            assert after.character_capabilities == before[p.user].character_capabilities  # type: ignore[union-attr]
            assert after.character_capabilities[env.character] == MATRIX
        gone = resolve_access_context(c, user_id=env.p1.user, campaign_id=s.w.campaign_id)
        assert gone is not None and env.character not in gone.character_capabilities
    read = get(pooled_factory, env.owner.user, assign_path(s, env.character)).json()
    assert read["controller"] is None
    assert len(read["co_controllers"]) == 2


def test_f17_revoking_the_last_assignment_makes_the_read_gm_operated(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    only = seed(s, env.p1, env.character, "primary_controller", "ongoing")
    first = get(pooled_factory, env.owner.user, assign_path(s, env.character)).json()
    assert first["gm_operated"] is False and first["controller"] is not None
    assert code(post(pooled_factory, env.owner.user, revoke_path(s, only))) == 200
    second = get(pooled_factory, env.owner.user, assign_path(s, env.character)).json()
    assert (
        second["gm_operated"] is True
        and second["controller"] is None
        and second["co_controllers"] == []
    )


def test_f18_revoking_a_revoked_row_is_a_no_op(s: Scene, env: Env, pooled_factory: Factory) -> None:
    row = seed(s, env.p1, env.character, "co_controller", "ongoing")
    assert code(post(pooled_factory, env.owner.user, revoke_path(s, row), {"reason": "x"})) == 200
    before = state(s)
    again = post(pooled_factory, env.owner.user, revoke_path(s, row), {"reason": "y"})
    assert code(again) == 200 and again.json()["revoked"] is False, again.text
    unchanged(s, before)
    assert row_of(s, row)["revocation_reason"] == "x"


def test_f19_a_foreign_assignment_or_a_legacy_relationship_id_is_404(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.begin() as c:
        timeline = make_timeline(c, s.w.world_id, "Other", is_primary=False)
        other_campaign = make_campaign(c, timeline, "Other campaign")
        user = make_user(c, "C11 Elsewhere")
        membership = make_campaign_membership(c, other_campaign, user)
        make_membership_role(c, membership, s.owner)  # a campaign must retain an access manager
        foreign = make_control_assignment(
            c, membership, env.character, "co_controller", "ongoing", campaign_id=other_campaign
        )
        legacy = make_membership_character_relationship(
            c, env.p1.membership, env.character, relationship_type_id(c, "viewer")
        )
    before = state(s)
    for target in (foreign, legacy):
        response = post(pooled_factory, env.owner.user, revoke_path(s, target))
        assert code(response) == 404, response.text
    unchanged(s, before)
    assert row_of(s, foreign)["revoked_at"] is None


def test_f20_a_reason_over_a_thousand_characters_is_422(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    seed(s, env.p1, env.character, "primary_controller", "ongoing")
    row = seed(s, env.p2, env.character2, "co_controller", "ongoing")
    before = state(s)
    long_reason = "x" * 1001
    for path, body in (
        (assign_path(s, env.character), assign_body(env.p3, reason=long_reason)),
        (replace_path(s, env.character), replace_body(env.p3, reason=long_reason)),
        (revoke_path(s, row), {"reason": long_reason}),
    ):
        response = post(pooled_factory, env.owner.user, path, body)
        assert code(response) == 422, response.text
    unchanged(s, before)


# --- F21: keyed retries -------------------------------------------------------------------------------------------


def _receipt(sc: Scene, key: str) -> Any:
    with sc.w.engine.connect() as c:
        return c.execute(
            text(
                "SELECT response_status_code, response_body FROM security.idempotent_requests "
                "WHERE campaign_id = :c AND idempotency_key = :k"
            ),
            {"c": sc.w.campaign_id, "k": key},
        ).one_or_none()


@pytest.mark.parametrize("writer", ["assign", "replace", "revoke"])
def test_f21_a_keyed_retry_replays_the_receipt_and_a_changed_body_is_refused(
    s: Scene, env: Env, pooled_factory: Factory, writer: str
) -> None:
    key = new_key()
    if writer == "assign":
        path, body, changed = (
            assign_path(s, env.character),
            assign_body(env.p1),
            assign_body(env.p2),
        )
        expected = 201
    elif writer == "replace":
        seed(s, env.p3, env.character, "primary_controller", "ongoing")
        path, body, changed = (
            replace_path(s, env.character),
            replace_body(env.p1),
            replace_body(env.p2),
        )
        expected = 201
    else:
        row = seed(s, env.p1, env.character, "co_controller", "ongoing")
        path, body, changed = revoke_path(s, row), {"reason": "a"}, {"reason": "b"}
        expected = 200
    first = post(pooled_factory, env.owner.user, path, body, key=key)
    assert code(first) == expected, first.text
    after_first = state(s)
    receipt = _receipt(s, key)
    assert receipt is not None and receipt[0] == expected
    again = post(pooled_factory, env.owner.user, path, body, key=key)
    assert code(again) == expected and again.json() == first.json()
    unchanged(s, after_first)
    reused = post(pooled_factory, env.owner.user, path, changed, key=key)
    assert code(reused) in (409, 422), reused.text
    unchanged(s, after_first)


# --- F28-F29: the read -------------------------------------------------------------------------------------------


def test_f28_the_read_reports_current_control_clock_and_history(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    by = {"granted_by": env.owner.membership}
    primary = seed(s, env.p1, env.character, "primary_controller", "ongoing", **by)
    dated = seed(
        s, env.p2, env.character, "co_controller", "dated", from_time=env.t10, to_time=env.t20, **by
    )
    upcoming = seed(s, env.p3, env.character, "co_controller", "dated", from_time=env.t30, **by)
    revoked = seed(
        s,
        env.player,
        env.character,
        "co_controller",
        "ongoing",
        revoked=True,
        revoked_by=env.owner.membership,
        revocation_reason="no longer needed",
        **by,
    )

    def read() -> dict[str, Any]:
        response = get(pooled_factory, env.owner.user, assign_path(s, env.character))
        assert code(response) == 200, response.text
        return dict(response.json())

    undetermined = read()
    assert undetermined["clock"]["set"] is False
    by_id = {a["control_assignment_id"]: a for a in undetermined["assignments"]}
    assert by_id[str(primary)]["status"] == "in_effect" and by_id[str(primary)]["kind"] == "ongoing"
    assert by_id[str(dated)]["status"] == "undetermined"
    assert by_id[str(upcoming)]["status"] == "undetermined"
    assert by_id[str(revoked)]["status"] == "revoked"
    assert by_id[str(revoked)]["revocation_reason"] == "no longer needed"
    assert by_id[str(revoked)]["revoked_by"] is not None
    assert by_id[str(primary)]["granted_by"] is not None
    # an ongoing row carries its grant instant and never a fictional date
    assert by_id[str(primary)]["ongoing_since"] == by_id[str(primary)]["granted_at"]
    assert (
        by_id[str(primary)]["effective_from"] is None
        and by_id[str(primary)]["effective_to"] is None
    )

    expectations = [
        (env.t10, "in_effect", "upcoming"),  # lower bound inclusive
        (env.t20, "ended", "upcoming"),  # upper bound exclusive
        (env.t30, "ended", "in_effect"),
    ]
    for key_time, dated_status, upcoming_status in expectations:
        with s.w.engine.begin() as c:
            c.execute(
                text("DELETE FROM campaign.timeline_clocks WHERE timeline_id = :t"),
                {"t": env.timeline_id},
            )
            make_timeline_clock(c, env.timeline_id, key_time)
        data = read()
        assert data["clock"]["set"] is True and data["clock"]["display"]
        statuses = {a["control_assignment_id"]: a["status"] for a in data["assignments"]}
        assert statuses[str(dated)] == dated_status, key_time
        assert statuses[str(upcoming)] == upcoming_status, key_time
    final = read()
    assert final["controller"]["campaign_membership_id"] == str(env.p1.membership)
    assert {c["campaign_membership_id"] for c in final["co_controllers"]} == {
        str(env.p3.membership)
    }
    assert final["gm_operated"] is False
    assert final["truncated"] is False
    ordered = [a["granted_at"] for a in final["assignments"]]
    assert ordered == sorted(ordered, reverse=True)


def test_f28_the_history_is_bounded_and_flags_truncation(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.begin() as c:
        for index in range(201):
            who = make_user(c, f"C11 Bulk {index}")
            membership = make_campaign_membership(c, s.w.campaign_id, who)
            make_control_assignment(
                c,
                membership,
                env.character,
                "co_controller",
                "ongoing",
                campaign_id=s.w.campaign_id,
                revoked=True,
            )
    data = get(pooled_factory, env.owner.user, assign_path(s, env.character)).json()
    assert len(data["assignments"]) == 200 and data["truncated"] is True


@pytest.mark.parametrize("who", ["assistant", "player", "observer"])
def test_f29_the_read_refuses_a_non_holder_without_disclosure(
    s: Scene, env: Env, pooled_factory: Factory, who: str
) -> None:
    user = {
        "assistant": env.assistant.user,
        "player": env.player.user,
        "observer": env.observer.user,
    }[who]
    existing = get(pooled_factory, user, assign_path(s, env.character))
    missing = get(pooled_factory, user, assign_path(s, uuid.uuid4()))
    assert code(existing) == 403 == code(missing)
    assert error_of(existing) == "character_assign_control_required"
    assert fixed_body(existing) == fixed_body(missing)


# --- F30-F32: isolation, character shape, resolution --------------------------------------------------------------


def test_f30_one_campaigns_assignment_confers_nothing_in_another_on_the_same_timeline(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": s.w.campaign_id},
        ).scalar_one()
        other_campaign = make_campaign(c, timeline, "Second campaign")
        other_owner_user = make_user(c, "C11 Other owner")
        other_owner = make_campaign_membership(c, other_campaign, other_owner_user)
        make_membership_role(c, other_owner, s.owner)
        # the same person is a player in both campaigns
        in_b = make_campaign_membership(c, other_campaign, env.p1.user)
        make_membership_role(c, in_b, s.player)
    assert (
        code(
            post(
                pooled_factory,
                env.owner.user,
                assign_path(s, env.character),
                assign_body(env.p1, "primary_controller"),
            )
        )
        == 201
    )
    with s.w.engine.connect() as c:
        in_a = resolve_access_context(c, user_id=env.p1.user, campaign_id=s.w.campaign_id)
        also_b = resolve_access_context(c, user_id=env.p1.user, campaign_id=other_campaign)
    assert in_a is not None and in_a.character_capabilities[env.character] == MATRIX
    assert also_b is not None and env.character not in also_b.character_capabilities
    read_b = get(
        pooled_factory,
        other_owner_user,
        f"/campaigns/{other_campaign}/characters/{env.character}/control-assignments",
    )
    assert (
        code(read_b) == 200
        and read_b.json()["assignments"] == []
        and read_b.json()["gm_operated"] is True
    )


def test_f31_an_npc_assigned_to_a_player_keeps_its_identity_and_gains_no_private_view(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    with s.w.engine.begin() as c:
        before = c.execute(
            text("SELECT count(*) FROM character.characters WHERE character_id = :e"),
            {"e": env.character},
        ).scalar_one()
    assert (
        code(
            post(
                pooled_factory,
                env.owner.user,
                assign_path(s, env.character),
                assign_body(env.p1, "primary_controller"),
            )
        )
        == 201
    )
    with s.w.engine.connect() as c:
        after = c.execute(
            text("SELECT count(*) FROM character.characters WHERE character_id = :e"),
            {"e": env.character},
        ).scalar_one()
        access = resolve_access_context(c, user_id=env.p1.user, campaign_id=s.w.campaign_id)
    assert before == after == 1
    assert access is not None
    held = access.character_capabilities[env.character]
    assert "character.control" in held
    assert not {"character.view_private", "character.view_knowledge"} & held
    # a character with no build or class resolved and was assignable (T3)


def test_f32_a_command_made_assignment_resolves_on_the_next_request_and_revoke_removes_it(
    s: Scene, env: Env, pooled_factory: Factory
) -> None:
    created = post(
        pooled_factory,
        env.owner.user,
        assign_path(s, env.character),
        assign_body(env.p1, "co_controller"),
    )
    assert code(created) == 201
    with s.w.engine.connect() as c:
        access = resolve_access_context(c, user_id=env.p1.user, campaign_id=s.w.campaign_id)
    assert access is not None and access.character_capabilities[env.character] == MATRIX
    assert access.control_assignments[env.character].role == "co_controller"
    revoked = post(
        pooled_factory,
        env.owner.user,
        revoke_path(s, uuid.UUID(created.json()["control_assignment_id"])),
    )
    assert code(revoked) == 200
    with s.w.engine.connect() as c:
        after = resolve_access_context(c, user_id=env.p1.user, campaign_id=s.w.campaign_id)
    assert after is not None and env.character not in after.character_capabilities
    assert after.control_assignments == {}
