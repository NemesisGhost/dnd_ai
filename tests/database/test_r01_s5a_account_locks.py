# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-A: the target-account lock of the six access-management commands is `FOR KEY SHARE`.

What changed. `assign_membership_role` (and through it `transfer_campaign_ownership`),
`add_campaign_member`, `grant_character_relationship`, `change_character_relationship`,
`create_resource_grant` and `add_access_group_members` read the target membership's account status
under `FOR UPDATE OF u`. Every keyed request also takes the actor's account `FOR KEY SHARE`, through the
reservation's actor foreign key, before any role or membership lock. A command holding its target
membership and then asking `FOR UPDATE` for the account of a user who has a keyed request in flight
therefore waited on that request, which waited on the membership: a deadlock (design review finding 2,
cycle B1).

Evidence classes. Every test says which it is:

- **HTTP**: the authoring side is a real keyed route (`POST .../authoring/locations` with an
  `Idempotency-Key`), which takes the reservation and the authoring scope itself. The access-management
  side is the application *command*, called on its own connection, because the access-management routes
  are not migrated by S5-A and a command can be parked on one statement. One test drives both sides
  through routes.
- **command**: both sides are application commands (`dnd_ai.commands.*`) on their own connections.
  The reservation's account lock is stood in for by a held `FOR KEY SHARE`, which is exactly the lock the
  actor foreign key takes; it is labelled as a stand-in where it is used.

Nothing here adds the deferred-reservation migration: cycle C1 needs a deferrable reservation foreign key
that does not exist, and stays design evidence only.

Every wait is observed through `pg_blocking_pids`; no scenario relies on a timeout or on sampling.
"""

import re
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, event, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.access_grants import (
    change_character_relationship,
    create_resource_grant,
    grant_character_relationship,
)
from dnd_ai.commands.access_groups import add_access_group_members
from dnd_ai.commands.campaigns import create_campaign
from dnd_ai.commands.local_auth import _disable_local_account_impl
from dnd_ai.commands.memberships import (
    add_campaign_member,
    assign_membership_role,
)
from dnd_ai.commands.system_roles import assign_system_role
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.authorization import install_authorization_guard
from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name
from tests.factories import (
    lookup_id,
    make_access_group,
    make_character,
    make_external_identity,
    make_membership_character_relationship,
    make_platform_administrator,
    make_role,
    oidc_principal,
)
from tests.http_race_support import (
    StatementGate,
    new_key,
    run_in_thread,
    sessions_blocked_by,
    wait_for_deadlock_count,
    wait_until_pid_blocks,
)
from tests.lock_race_support import LockRace, Worker

pytestmark = pytest.mark.database

# The target-account statement of the six commands, whichever lock mode it names.
ACCOUNT_LOCK = (
    r"FROM security\.users u JOIN core\.lifecycle_statuses ls .* FOR (UPDATE|KEY SHARE) OF u"
)
# The first statement of `lock_authoring_scope` after the reservation: the actor's role rows and
# membership, `FOR SHARE`.
AUTHORING_SCOPE = r"FOR SHARE OF mr, cm"
EXPECT_KEY_SHARE = "FOR KEY SHARE"


# --- the committed scenario ---------------------------------------------------------------------------------


@dataclass
class Scene:
    """Campaign A (the S3 world): `owner` owns it; U (`w.gm_user`) is a member who can author. Campaign B
    is a second campaign of the same owner in which U is *not* a member, so U can be added to it."""

    w: World
    owner_membership: uuid.UUID
    campaign_b: uuid.UUID
    owner_membership_b: uuid.UUID
    admin: uuid.UUID
    custom_role: uuid.UUID
    template_gm: uuid.UUID
    character_grant: uuid.UUID
    character_change: uuid.UUID
    group: uuid.UUID
    relationship: uuid.UUID
    portrayer_type: uuid.UUID

    @property
    def engine(self) -> Engine:
        return self.w.engine

    @property
    def u(self) -> uuid.UUID:
        return self.w.gm_user

    def scalar(self, sql: str, **params: Any) -> Any:
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()


@pytest.fixture
def scene(w: World) -> Iterator[Scene]:
    with w.engine.begin() as setup:
        owner_membership = setup.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
            ),
            {"c": w.campaign_id, "u": w.owner},
        ).scalar_one()
        campaign = setup.execute(
            text(
                "SELECT timeline_id, ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"
            ),
            {"c": w.campaign_id},
        ).one()
        campaign_b = create_campaign(
            setup,
            timeline_id=campaign.timeline_id,
            ruleset_version_id=campaign.ruleset_version_id,
            name="S5-A Campaign B",
            creator_user_id=w.owner,
        ).campaign_id
        owner_membership_b = setup.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
            ),
            {"c": campaign_b, "u": w.owner},
        ).scalar_one()
        # `add_campaign_member` needs an unrevoked local-login identity on the target account
        make_external_identity(
            setup, w.gm_user, issuer=LOCAL_AUTH_ISSUER, subject=f"s5a-{uuid.uuid4().hex[:8]}"
        )
        admin = make_platform_administrator(setup, "S5-A Admin")
        custom_role = make_role(setup, campaign_id=w.campaign_id)
        template_gm = setup.execute(
            text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
        ).scalar_one()
        character_grant = make_character(setup, w.world_id, name="S5-A grant target")
        character_change = make_character(setup, w.world_id, name="S5-A change target")
        group = make_access_group(setup, w.campaign_id, name="S5-A group")
        viewer = lookup_id(
            setup,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "viewer",
        )
        portrayer = lookup_id(
            setup,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "portrayer",
        )
        relationship = make_membership_character_relationship(
            setup,
            w.gm_membership,
            character_change,
            viewer,
            granted_by_membership_id=owner_membership,
        )
    scene = Scene(
        w,
        owner_membership,
        campaign_b,
        owner_membership_b,
        admin,
        custom_role,
        template_gm,
        character_grant,
        character_change,
        group,
        relationship,
        portrayer,
    )
    try:
        yield scene
    finally:
        with w.engine.begin() as cleanup:
            cleanup.execute(text("SET LOCAL session_replication_role = replica"))
            for statement in (
                "DELETE FROM security.resource_grants WHERE campaign_id = :c",
                "DELETE FROM security.membership_character_relationships "
                "WHERE campaign_membership_id = :m",
                "DELETE FROM security.access_group_memberships WHERE access_group_id = :g",
                "DELETE FROM security.access_groups WHERE access_group_id = :g",
                "DELETE FROM security.membership_roles WHERE role_id = :r",
                "DELETE FROM security.roles WHERE role_id = :r",
                "DELETE FROM security.idempotent_requests WHERE campaign_id IN (:c, :b)",
                "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                "(SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :b)",
                "DELETE FROM security.campaign_memberships WHERE campaign_id = :b",
                "DELETE FROM campaign.campaigns WHERE campaign_id = :b",
                "DELETE FROM security.external_identities WHERE user_id = :u",
            ):
                cleanup.execute(
                    text(statement),
                    {
                        "c": w.campaign_id,
                        "b": campaign_b,
                        "m": w.gm_membership,
                        "g": group,
                        "r": custom_role,
                        "u": w.gm_user,
                    },
                )


# --- the six commands ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Command:
    name: str
    run: Callable[[Scene], Callable[[Connection], Any]]
    done: Callable[[Scene], bool]
    refused_with: str  # the classified refusal's class name (each module has its own)
    # the command also takes the campaign row `FOR UPDATE`, so a keyed request's own reservation holds
    # the campaign `FOR KEY SHARE` against it: a separate, pre-existing cycle (DEF-019, S5-E4)
    holds_campaign_for_update: bool


def _assign(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: assign_membership_role(
        c,
        campaign_membership_id=s.w.gm_membership,
        role_id=s.custom_role,
        campaign_id=s.w.campaign_id,
        granted_by_membership_id=s.owner_membership,
    )


def _add(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: add_campaign_member(
        c,
        campaign_id=s.campaign_b,
        user_id=s.u,
        role_id=s.template_gm,
        added_by_membership_id=s.owner_membership_b,
    )


def _grant_relationship(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: grant_character_relationship(
        c,
        campaign_membership_id=s.w.gm_membership,
        character_id=s.character_grant,
        relationship_type_code="viewer",
        campaign_id=s.w.campaign_id,
        expected_world_id=s.w.world_id,
        granted_by_membership_id=s.owner_membership,
    )


def _change_relationship(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: change_character_relationship(
        c,
        membership_character_relationship_id=s.relationship,
        campaign_id=s.w.campaign_id,
        expected_world_id=s.w.world_id,
        new_relationship_type_id=s.portrayer_type,
        granted_by_membership_id=s.owner_membership,
    )


def _resource_grant(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: create_resource_grant(
        c,
        campaign_id=s.w.campaign_id,
        grantee_campaign_membership_id=s.w.gm_membership,
        grantee_access_group_id=None,
        capability_code="character.view_full",
        effect="allow",
        expected_world_id=s.w.world_id,
        granted_by_membership_id=s.owner_membership,
        character_id=s.character_grant,
    )


def _group_add(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: add_access_group_members(
        c,
        access_group_id=s.group,
        campaign_membership_ids=(s.w.gm_membership,),
        campaign_id=s.w.campaign_id,
        added_by_membership_id=s.owner_membership,
    )


COMMANDS = (
    Command(
        "assign_membership_role",
        _assign,
        lambda s: bool(
            s.scalar(
                "SELECT count(*) FROM security.membership_roles "
                "WHERE campaign_membership_id = :m AND role_id = :r AND revoked_at IS NULL",
                m=s.w.gm_membership,
                r=s.custom_role,
            )
        ),
        "MembershipNotActiveError",
        False,
    ),
    Command(
        "add_campaign_member",
        _add,
        lambda s: bool(
            s.scalar(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL",
                c=s.campaign_b,
                u=s.u,
            )
        ),
        "AccountNotEligibleError",
        True,
    ),
    Command(
        "grant_character_relationship",
        _grant_relationship,
        lambda s: bool(
            s.scalar(
                "SELECT count(*) FROM security.membership_character_relationships "
                "WHERE campaign_membership_id = :m AND character_id = :c AND revoked_at IS NULL",
                m=s.w.gm_membership,
                c=s.character_grant,
            )
        ),
        "MembershipNotActiveError",
        True,
    ),
    Command(
        "change_character_relationship",
        _change_relationship,
        lambda s: bool(
            s.scalar(
                "SELECT revoked_at IS NOT NULL FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :r",
                r=s.relationship,
            )
        ),
        "CharacterRelationshipNotActiveError",
        True,
    ),
    Command(
        "create_resource_grant",
        _resource_grant,
        lambda s: bool(
            s.scalar(
                "SELECT count(*) FROM security.resource_grants "
                "WHERE campaign_id = :c AND grantee_campaign_membership_id = :m",
                c=s.w.campaign_id,
                m=s.w.gm_membership,
            )
        ),
        "MembershipNotActiveError",
        True,
    ),
    Command(
        "add_access_group_members",
        _group_add,
        lambda s: bool(
            s.scalar(
                "SELECT count(*) FROM security.access_group_memberships "
                "WHERE access_group_id = :g AND campaign_membership_id = :m AND removed_at IS NULL",
                g=s.group,
                m=s.w.gm_membership,
            )
        ),
        "MembershipNotActiveError",
        False,
    ),
)
BY_NAME = {command.name: command for command in COMMANDS}
NAMES = tuple(BY_NAME)


def _command_ids(names: tuple[str, ...]) -> list[Any]:
    return [pytest.param(name, id=name) for name in names]


# --- competitors on the account ---------------------------------------------------------------------------


def _deactivate(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: _disable_local_account_impl(c, admin_user_id=s.admin, target_user_id=s.u)


def _system_role(s: Scene) -> Callable[[Connection], Any]:
    return lambda c: assign_system_role(
        c, admin_user_id=s.admin, target_user_id=s.u, role_code="gm", allow_in_app_admin_grant=False
    )


COMPETITORS: dict[str, Callable[[Scene], Callable[[Connection], Any]]] = {
    "account_deactivation": _deactivate,
    "system_role_change": _system_role,
}


def _account_status(s: Scene) -> str:
    return str(
        s.scalar(
            "SELECT ls.code FROM security.users u "
            "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id "
            "WHERE u.user_id = :u",
            u=s.u,
        )
    )


def _system_role_open(s: Scene) -> bool:
    return bool(
        s.scalar(
            "SELECT count(*) FROM security.user_system_roles usr "
            "JOIN security.system_roles sr ON sr.system_role_id = usr.system_role_id "
            "WHERE usr.user_id = :u AND sr.code = 'gm' AND usr.revoked_at IS NULL",
            u=s.u,
        )
    )


# --- 1 (command). The competitors still serialise against the changed commands -----------------------------


@pytest.mark.parametrize("competitor", COMPETITORS)
@pytest.mark.parametrize("name", _command_ids(NAMES))
def test_command_evidence_a_competitor_waits_for_a_command_that_holds_the_account_lock(
    scene: Scene, name: str, competitor: str
) -> None:
    """Command evidence. The command is parked just after its account lock. The account's deactivation
    (or a system-role change, which takes the same row `FOR UPDATE`) must queue behind that session:
    `FOR KEY SHARE` is the weakest lock that conflicts with `FOR UPDATE`. Released, both commit, in that
    order: the command's effect exists and the competitor's effect follows."""
    command = BY_NAME[name]
    with LockRace(scene.engine) as race:
        pause = race.pause(thread_name="command", pattern=r".", after=ACCOUNT_LOCK)
        first = race.start("command", command.run(scene))
        pause.wait_reached(first)
        second = race.start("competitor", COMPETITORS[competitor](scene))
        race.wait_blocked_by(pause, second)
        assert not second.done, "the competitor finished while the command held the account"
        pause.release()
        race.join_all()
    assert first.error is None, first.describe()
    assert second.error is None, second.describe()
    assert command.done(scene)
    if competitor == "account_deactivation":
        assert _account_status(scene) == "inactive"
    else:
        assert _system_role_open(scene)


@pytest.mark.parametrize("name", _command_ids(NAMES))
def test_command_evidence_a_deactivation_that_holds_the_account_first_refuses_the_command_and_rolls_back(
    scene: Scene, name: str
) -> None:
    """Command evidence, refusal and rollback. The account's deactivation holds the row `FOR UPDATE`
    with its status already changed and uncommitted. The command queues on its protected account
    statement; the deactivation commits; the command re-reads the account, refuses with its own
    classified error, and nothing it would have written exists."""
    command = BY_NAME[name]
    with LockRace(scene.engine) as race:
        hold = race.hold(_deactivate(scene))
        victim = race.start("command", command.run(scene))
        race.wait_blocked_by(hold, victim)
        hold.commit()
        race.join_all()
    assert type(victim.error).__name__ == command.refused_with, victim.describe()
    assert not command.done(scene), "a refused command left its write behind"
    assert _account_status(scene) == "inactive"


@pytest.mark.parametrize("name", _command_ids(NAMES))
def test_command_evidence_a_system_role_change_that_holds_the_account_first_makes_the_command_wait(
    scene: Scene, name: str
) -> None:
    """Command evidence. A system-role change holds the account row `FOR UPDATE`. The command queues
    behind it (a conflicting lock, not a snapshot), then runs against the committed state and succeeds:
    a system-role change does not change the account's status."""
    command = BY_NAME[name]
    with LockRace(scene.engine) as race:
        hold = race.hold(_system_role(scene))
        waiter = race.start("command", command.run(scene))
        race.wait_blocked_by(hold, waiter)
        hold.commit()
        race.join_all()
    assert waiter.error is None, waiter.describe()
    assert command.done(scene)
    assert _system_role_open(scene)


# --- 2 (command). The reservation's account lock no longer makes the commands wait -------------------------


@pytest.mark.parametrize("name", _command_ids(NAMES))
def test_command_evidence_a_held_key_share_on_the_account_does_not_make_the_command_wait(
    scene: Scene, name: str
) -> None:
    """Command evidence, with a stand-in: the held `FOR KEY SHARE` on U's account row is exactly the lock
    the reservation's actor foreign key takes for a keyed request by U (the HTTP tests below use the real
    request). The command must finish while it is held. On the parent it waits behind it."""
    command = BY_NAME[name]
    with LockRace(scene.engine) as race:
        hold = race.hold(
            lambda c: c.execute(
                text("SELECT 1 FROM security.users WHERE user_id = :u FOR KEY SHARE"),
                {"u": scene.u},
            ).all()
        )
        worker = race.start("command", command.run(scene))
        race.wait_done(
            worker, why=f"{command.name} is waiting behind a key-share lock on the target account"
        )
        hold.commit()
        race.join_all()
    assert worker.error is None, worker.describe()
    assert command.done(scene)


# --- 3 (HTTP). B1: a keyed authoring request by U against each command on U's account -----------------------


@pytest.fixture
def app_engine(w: World) -> Iterator[Engine]:
    """The application's engine: several connections, READ COMMITTED enforced and the real guard
    installed, as `get_engine` does."""
    engine = create_engine(
        w.engine.url, pool_size=4, max_overflow=4, isolation_level="READ COMMITTED"
    )
    install_authorization_guard(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _client(engine: Engine, user_id: uuid.UUID) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
    return TestClient(app, raise_server_exceptions=False)


def _keyed_authoring(w: World, engine: Engine) -> Callable[[], Any]:
    """U's keyed authoring request: reservation (the actor's account `FOR KEY SHARE`), then the authoring
    scope (U's role rows and membership `FOR SHARE`)."""
    key = new_key()
    name = f"S5-A {uuid.uuid4().hex[:6]}"

    def call() -> Any:
        with _client(engine, w.gm_user) as client:
            return client.post(
                f"{w.base}/authoring/locations",
                json={"category": "region", "name": name},
                headers={"Idempotency-Key": key},
            )

    return call


def _location_count(w: World) -> int:
    with w.engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM core.entities e JOIN world.locations l "
                    "ON l.location_id = e.entity_id WHERE e.created_by_user_id = :u"
                ),
                {"u": w.gm_user},
            ).scalar_one()
        )


def _settle(
    worker: Worker, request: Any, *, why: str, deadlocks_before: int, engine: Engine
) -> list[str]:
    """What a finished pair looked like, so the failure of a deadlock says so."""
    problems: list[str] = []
    if worker.error is not None:
        problems.append(f"command ended with {worker.error!r}")
    if request.error is not None:
        problems.append(f"request raised {request.error!r}")
    elif request.result is not None and request.result.status_code != 201:
        problems.append(
            f"keyed authoring request answered {request.result.status_code} {request.result.text}"
        )
    if problems:  # the counter is flushed lazily, so look for it only to explain a failure
        count = wait_for_deadlock_count(engine, deadlocks_before + 1)
        if count > deadlocks_before:
            problems.append(
                f"the database aborted {count - deadlocks_before} transaction(s) as a deadlock"
            )
    return [f"{why}: {problem}" for problem in problems]


def _deadlock_total(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()")
            ).scalar_one()
        )


@pytest.mark.parametrize("name", _command_ids(NAMES))
def test_http_evidence_the_command_first_then_a_keyed_authoring_request_by_the_target(
    scene: Scene, app_engine: Engine, name: str
) -> None:
    """HTTP evidence, ordering 1. The command is parked just before its account statement, holding what
    it took first (the target membership; for most, the campaign row too). U's keyed authoring request
    then reserves its key (U's account `FOR KEY SHARE`) and queues behind the command. Released, the
    command asks for the account: with `FOR UPDATE` that waits for the request, which waits for the
    command's membership (a deadlock); with `FOR KEY SHARE` it does not, and both commit."""
    command = BY_NAME[name]
    w = scene.w
    before = _deadlock_total(scene.engine)
    with LockRace(scene.engine) as race:
        pause = race.pause(thread_name="command", pattern=ACCOUNT_LOCK)
        first = race.start("command", command.run(scene))
        pause.wait_reached(first)
        request = run_in_thread("authoring", _keyed_authoring(w, app_engine))
        waited = _wait_for(
            lambda: request.finished() or sessions_blocked_by(scene.engine, pause.pid) >= 1
        )
        assert waited, "the request neither finished nor queued behind the command"
        blocked_before_release = not request.finished()
        pause.release()
        race.join_all()
    request.wait("the keyed authoring request finishes")
    if name != "add_campaign_member":  # B is another campaign: nothing of U's A rows is held
        assert blocked_before_release, "the request did not queue behind the command's locks"
    problems = _settle(
        first, request, why=command.name, deadlocks_before=before, engine=scene.engine
    )
    assert not problems, "; ".join(problems)
    assert command.done(scene)
    assert _location_count(w) == 1


@pytest.mark.parametrize(
    "name",
    [pytest.param(n, id=n) for n in NAMES if not BY_NAME[n].holds_campaign_for_update],
)
def test_http_evidence_a_keyed_authoring_request_by_the_target_first_then_the_command(
    scene: Scene, app_engine: Engine, name: str
) -> None:
    """HTTP evidence, ordering 2. U's keyed authoring request has reserved its key (holding U's account
    `FOR KEY SHARE` and the campaign `FOR KEY SHARE`) and is parked before its authoring scope. The
    command then runs. With `FOR UPDATE` it queues on the account behind the request; with `FOR KEY
    SHARE` it does not queue there. Released, the request asks for U's membership: the command's hold
    on it (the target membership) is the other half of the cycle.

    The commands that take the campaign row `FOR UPDATE` (the other three) are excluded: the request's
    own reservation holds the campaign `FOR KEY SHARE`, so they cycle at the campaign row before any
    account lock, which S5-A does not change (DEF-019, the access-management slice)."""
    command = BY_NAME[name]
    w = scene.w
    before = _deadlock_total(scene.engine)
    with StatementGate(app_engine, AUTHORING_SCOPE) as gate:
        request = run_in_thread("authoring", _keyed_authoring(w, app_engine))
        gate.wait_reached()
        with LockRace(scene.engine) as race:
            second = race.start("command", command.run(scene))
            finished_while_parked = _wait_for(
                lambda: second.done or sessions_blocked_by(scene.engine, gate.pid or 0) >= 1
            )
            assert finished_while_parked
            queued_on_request = not second.done
            gate.release()
            race.join_all()
        # inside the gate: removing its listener while the request still runs mutates the listener
        # list that request is iterating
        request.wait("the keyed authoring request finishes")
    problems = _settle(
        second, request, why=command.name, deadlocks_before=before, engine=scene.engine
    )
    if queued_on_request:
        problems.insert(0, "the command queued behind the request's account key-share lock")
    assert not problems, "; ".join(problems)
    assert command.done(scene)
    assert _location_count(w) == 1


def _wait_for(condition: Callable[[], bool], seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


# --- 4 (HTTP, both sides). The assignment route against the authoring route --------------------------------


def test_http_evidence_both_sides_through_routes_the_assignment_route_against_a_keyed_authoring_request(
    scene: Scene, app_engine: Engine
) -> None:
    """HTTP evidence on both sides. The owner's assignment route (no key) is parked before the account
    statement of `assign_membership_role`; U's keyed authoring request queues behind its membership lock;
    released, both commit with 201."""
    w = scene.w
    assign_engine = create_engine(
        w.engine.url, pool_size=2, max_overflow=2, isolation_level="READ COMMITTED"
    )
    install_authorization_guard(assign_engine)
    before = _deadlock_total(scene.engine)
    try:
        with StatementGate(assign_engine, ACCOUNT_LOCK) as gate:

            def assign() -> Any:
                with _client(assign_engine, w.owner) as client:
                    return client.post(
                        f"{w.base}/memberships/{w.gm_membership}/roles",
                        json={"role_id": str(scene.custom_role)},
                    )

            assigning = run_in_thread("assign-route", assign)
            gate.wait_reached()
            authoring = run_in_thread("authoring", _keyed_authoring(w, app_engine))
            assert gate.pid is not None
            wait_until_pid_blocks(scene.engine, gate.pid)
            gate.release()
            first = assigning.wait("the assignment route finishes")
            second = authoring.wait("the keyed authoring request finishes")
    finally:
        assign_engine.dispose()
    problems: list[str] = []
    if first.status_code != 201:
        problems.append(f"assignment route answered {first.status_code} {first.text}")
    if second.status_code != 201:
        problems.append(f"keyed authoring route answered {second.status_code} {second.text}")
    if problems and wait_for_deadlock_count(scene.engine, before + 1) > before:
        problems.append("the database aborted a transaction as a deadlock")
    assert not problems, "; ".join(problems)
    assert BY_NAME["assign_membership_role"].done(scene)


# --- 5. The lock statement itself -----------------------------------------------------------------------


@pytest.mark.parametrize("name", _command_ids(NAMES))
def test_command_evidence_the_account_statement_is_key_share_and_still_reads_the_fresh_status(
    scene: Scene, name: str
) -> None:
    """Command evidence. The recorded account statement of each command, in a real run, names `FOR KEY
    SHARE OF u` and returns the status the command then judges. Pins the mode at the statement that
    runs, not only in the source text."""
    command = BY_NAME[name]
    seen: list[str] = []
    pattern = re.compile(ACCOUNT_LOCK)

    def record(conn: Any, cursor: Any, statement: Any, *_: Any) -> None:
        flat = " ".join(str(statement).split())
        if pattern.search(flat):
            seen.append(flat)

    event.listen(scene.engine, "before_cursor_execute", record)
    try:
        with scene.engine.begin() as connection:
            command.run(scene)(connection)
    finally:
        event.remove(scene.engine, "before_cursor_execute", record)
    assert seen, "the command never ran its account statement"
    assert all(EXPECT_KEY_SHARE in statement for statement in seen), seen
