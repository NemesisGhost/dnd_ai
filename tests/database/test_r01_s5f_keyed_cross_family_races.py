# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-F: the DEF-019 keyed pairs (K1, K5, K6, K9, K10-K12) and the DEF-021 pairs (G1, G3, G4), over real HTTP.

Plan 6.21.6 gives S5-F the cross-family race suites (review section 11.1, tests 3 and 4). The per-slice race modules
(S5-E2..S5-E6) drive their pairs with **unkeyed** requests, so the reservation's campaign lock, the very thing the
K-cycles were made of (P03-A plan 10.8.6), was never in those schedules. Every request here sends its own
`Idempotency-Key`, the keyed execution being the portal path. The two members of each pair are one of the pairs the
plan names:

* K1  keyed end of M against keyed end of N
* K10 keyed end of M against keyed revoke of N's role
* K11 keyed end of M against keyed change of N's role
* K12 keyed end of M against keyed grant to N
* K6  keyed grant to M against keyed end of M
* K5  relinquishing transfer to M (a route that takes no key) against keyed end of M
* K9  keyed assign of `gm` to a member against keyed add of a new member with `gm` (the pair the rejected
      `INITIALLY DEFERRED` design made deadlock; the opt-in design must not)
* G1  keyed resource grant **by A** against keyed end **of A**
* G3  keyed relationship grant **by A** against keyed end of A
* G4  keyed add **by A** against keyed end of A

Each pair runs in **both orders** (either request is the parked one) and with each request parked at two points: *before
its campaign lock* (it holds everything it took earlier, which is where the old cycles formed) and *at its audit insert*
(its rows written, uncommitted). The parked request is held, the other is started, observed, released. Asserted for
every case: no driver exception and an unmoved deadlock counter (`assert_clean`), no 500, every status inside the
documented set, and the invariants of the pair (an ended member owns no open dependent row; a creator that answered 201
left exactly one row and one that did not left none). **Allowed outcomes are the serialized ones**: either request may
win, the loser is refused or is a no-op; the cases do not pin who wins.

Not claimed here: DEF-019 and DEF-021 stay open (the keyed authoring/operation/reveal routes are the later opt-in slice),
a COMMIT-time wait is not parked (the gates are statements), and `change_character_relationship` / group-target grants by
A against the end of A are covered by the S5-E4 and S5-E5 modules rather than repeated.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from tests.database.test_r01_s2_profile_routes import pooled, pooled_factory  # noqa: F401
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    Pool,
    assert_clean,
    pool,
    post,
    race,
    rows,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixture by name
    Scene,
    m,
    s,
)
from tests.database.test_r01_s5e3_end_membership import (  # noqa: F401 - fixture by name
    AUDIT_INSERT,
    Member,
    _tidy_end,
    build_member,
    e,
    open_dependents,
)
from tests.factories import make_character

pytestmark = pytest.mark.database

#: the statement just before a request takes its campaign lock (`FOR UPDATE` or `FOR KEY SHARE`)
BEFORE_CAMPAIGN = r"FROM campaign\.campaigns WHERE .* FOR (UPDATE|KEY SHARE)$"
GATES = {"before_campaign": BEFORE_CAMPAIGN, "at_audit": AUDIT_INSERT}
ALLOWED = {200, 201, 403, 404, 409}
NONE_OPEN = {
    "roles": 0,
    "delegations": 0,
    "relationships": 0,
    "grants": 0,
    "groups": 0,
    "revelations": 0,
    "snapshots": 0,
}


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def membership_open(sc: Scene, member: uuid.UUID) -> bool:
    return bool(
        rows(
            sc.w.engine,
            "SELECT ended_at IS NULL AS open FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :m",
            m=member,
        )[0]["open"]
    )


@dataclass
class Pair:
    """Two requests of one named pair, plus the checks that hold whoever won."""

    a: Callable[[], Any]
    b: Callable[[], Any]
    check: Callable[[Any, Any], None]  # (response of a, response of b)


def ender(
    sc: Scene, pool: Pool, user: uuid.UUID, target: uuid.UUID, *, keyed: bool = True
) -> Callable[[], Any]:
    return lambda: post(
        pool, user, f"{sc.w.base}/memberships/{target}/end", None, **(key() if keyed else {})
    )


def _ended_ok(sc: Scene, member: uuid.UUID, response: Any) -> None:
    """A 200 end left the member ended with no open dependent row; any other answer left it as it was."""
    if code(response) == 200:
        assert not membership_open(sc, member)
        assert open_dependents(sc, member) == NONE_OPEN
    else:
        assert code(response) in (403, 404, 409), (code(response), error_of(response))


def _count(sc: Scene, sql: str, **params: Any) -> int:
    return int(rows(sc.w.engine, sql, **params)[0]["n"])


def build_pair(name: str, sc: Scene, pool: Pool) -> Pair:
    owner, keeper, manager = sc.w.owner, sc.m.keeper_user, sc.m.manager_user
    base = sc.w.base
    if name in {"K1", "K10", "K11", "K12"}:
        m1 = build_member(sc, f"S5F {name} M")
        m2 = build_member(sc, f"S5F {name} N")
        a = ender(sc, pool, owner, m1.membership)
        if name == "K1":
            b = ender(sc, pool, keeper, m2.membership)
        elif name == "K10":
            b = lambda: post(  # noqa: E731
                pool, keeper, f"{base}/memberships/roles/{m2.player_row}/revoke", None, **key()
            )
        elif name == "K11":
            b = lambda: post(  # noqa: E731
                pool,
                keeper,
                f"{base}/memberships/roles/{m2.player_row}/change",
                {"new_role_id": str(sc.observer)},
                **key(),
            )
        else:
            with sc.w.engine.begin() as c:
                fresh = make_character(c, sc.w.world_id, name="S5F K12 character")
            b = lambda: post(  # noqa: E731
                pool,
                keeper,
                f"{base}/resource-grants",
                {
                    "capability_code": "character.view_summary",
                    "grantee_campaign_membership_id": str(m2.membership),
                    "character_id": str(fresh),
                },
                **key(),
            )

        def check(ra: Any, rb: Any) -> None:
            _ended_ok(sc, m1.membership, ra)
            if name == "K1":
                _ended_ok(sc, m2.membership, rb)
            else:
                assert code(rb) in ALLOWED

        return Pair(a, b, check)
    if name == "K6":
        m1 = build_member(sc, "S5F K6 M")
        with sc.w.engine.begin() as c:
            fresh = make_character(c, sc.w.world_id, name="S5F K6 character")
        a = lambda: post(  # noqa: E731
            pool,
            keeper,
            f"{base}/resource-grants",
            {
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(m1.membership),
                "character_id": str(fresh),
            },
            **key(),
        )
        b = ender(sc, pool, owner, m1.membership)

        def check(ra: Any, rb: Any) -> None:
            _ended_ok(sc, m1.membership, rb)
            created = _count(
                sc,
                "SELECT count(*) AS n FROM security.resource_grants WHERE character_id = :c "
                "AND grantee_campaign_membership_id = :m",
                c=fresh,
                m=m1.membership,
            )
            assert created == (1 if code(ra) == 201 else 0), (created, code(ra))

        return Pair(a, b, check)
    if name == "K5":
        m1 = build_member(sc, "S5F K5 M")
        a = lambda: post(  # noqa: E731
            pool,
            owner,
            f"{base}/ownership-transfer",
            {"target_campaign_membership_id": str(m1.membership), "relinquish_own_ownership": True},
        )
        b = ender(sc, pool, keeper, m1.membership)

        def check(ra: Any, rb: Any) -> None:
            assert code(ra) in ALLOWED
            _ended_ok(sc, m1.membership, rb)

        return Pair(a, b, check)
    if name == "K9":
        a = lambda: post(  # noqa: E731
            pool,
            keeper,
            f"{base}/memberships/{sc.target_membership}/roles",
            {"role_id": str(sc.gm)},
            **key(),
        )
        b = lambda: post(  # noqa: E731
            pool,
            keeper,
            f"{base}/memberships",
            {"user_id": str(sc.new_user), "role_id": str(sc.gm)},
            **key(),
        )

        def check(ra: Any, rb: Any) -> None:
            assert code(ra) in (201, 409) and code(rb) in (201, 409), (code(ra), code(rb))
            assert code(ra) == 201 and code(rb) == 201, "two different rows: both commit"

        return Pair(a, b, check)
    # G1, G3, G4: A (the manager) writes while B ends A
    other = build_member(sc, f"S5F {name} N")
    with sc.w.engine.begin() as c:
        fresh = make_character(c, sc.w.world_id, name=f"S5F {name} character")
    if name == "G1":
        a = lambda: post(  # noqa: E731
            pool,
            manager,
            f"{base}/resource-grants",
            {
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(other.membership),
                "character_id": str(fresh),
            },
            **key(),
        )
    elif name == "G3":
        a = lambda: post(  # noqa: E731
            pool,
            manager,
            f"{base}/memberships/{other.membership}/character-relationships",
            {"character_id": str(fresh), "relationship_type_code": "viewer"},
            **key(),
        )
    else:
        a = lambda: post(  # noqa: E731
            pool,
            manager,
            f"{base}/memberships",
            {"user_id": str(sc.new_user), "role_id": str(sc.player)},
            **key(),
        )
    b = ender(sc, pool, keeper, sc.m.manager_membership)

    def check(ra: Any, rb: Any) -> None:
        _ended_ok(sc, sc.m.manager_membership, rb)
        if name == "G1":
            n = _count(
                sc,
                "SELECT count(*) AS n FROM security.resource_grants WHERE character_id = :c "
                "AND grantee_campaign_membership_id = :m",
                c=fresh,
                m=other.membership,
            )
        elif name == "G3":
            n = _count(
                sc,
                "SELECT count(*) AS n FROM security.membership_character_relationships "
                "WHERE character_id = :c AND campaign_membership_id = :m",
                c=fresh,
                m=other.membership,
            )
        else:
            n = _count(
                sc,
                "SELECT count(*) AS n FROM security.campaign_memberships WHERE campaign_id = :c "
                "AND user_id = :u",
                c=sc.w.campaign_id,
                u=sc.new_user,
            )
        assert n == (1 if code(ra) == 201 else 0), (n, code(ra), error_of(ra))
        if code(ra) == 201 and name != "G4":
            # a row the ended actor created is the actor's, not the member's: the member's rows are untouched
            assert membership_open(sc, other.membership)

    return Pair(a, b, check)


PAIRS = ("K1", "K10", "K11", "K12", "K6", "K5", "K9", "G1", "G3", "G4")


@pytest.mark.parametrize("gate", tuple(GATES))
@pytest.mark.parametrize("parked", ("a", "b"))
@pytest.mark.parametrize("name", PAIRS)
def test_the_keyed_pair_serializes_without_a_cycle_in_both_orders(
    name: str, parked: str, gate: str, s: Scene, pool: Pool
) -> None:
    """*race*: pair `name` (module docstring) with its request `parked` held at `gate` and the other started behind it.
    No driver exception, no deadlock, every status documented, and the pair's invariants hold whoever won."""
    pair = build_pair(name, s, pool)
    first, second = (pair.a, pair.b) if parked == "a" else (pair.b, pair.a)
    o = race(s.w, pool, gate_pattern=GATES[gate], parked=first, second=second)
    assert_clean(o)
    statuses = {code(r) for r in o.results.values()}
    assert statuses <= ALLOWED, o.summary()
    ra, rb = (
        (o.results["parked"], o.results["second"])
        if parked == "a"
        else (o.results["second"], o.results["parked"])
    )
    pair.check(ra, rb)
    assert (
        _count(
            s,
            "SELECT count(*) AS n FROM pg_stat_activity WHERE state = 'idle in transaction' AND datname = current_database()",
        )
        == 0
    )
