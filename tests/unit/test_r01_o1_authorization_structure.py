"""R01 O-1 (AM-1) structural pins: construction rules, the empty registry and the route-plan dispatch, who
may call the new entry points, and the pre-write code the amendment must not change.

No production route adopts the capability in O-1. These pins move only with the reviewed slice that does
(O-2, after the independent review of O-1).

The AST pins are taken from the parent commit `3a85ca54c29a3a7d786c4971e580546146b93645`: the whole of every
`AuthorizationPlan` method AM-1 does not touch, and, for the methods it does touch, the statements that carry
the pre-write behaviour. A digest is the first 16 hex digits of sha256 over `ast.dump` of those statements
(docstrings of the selected statements included, so a selector never silently drops code).
"""

import ast
import hashlib
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dnd_ai.api import r01_pending_routes, r01_pre_write_routes, r01_route_plans
from dnd_ai.commands import _pre_write_steps
from dnd_ai.domain import authorization
from dnd_ai.domain.authorization import (
    CAMPAIGN_EVIDENCE_LOCK,
    AuthorizationPlan,
    PlanMode,
    ReservationDeclarations,
    ViolationReason,
)
from dnd_ai.domain.authorization_steps import LockMode
from tests.ast_support import dump

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"

# --- construction ------------------------------------------------------------------------------------


def _connection() -> Any:
    connection = MagicMock()
    connection.get_transaction.return_value = object()
    return connection


def _plan(**kwargs: Any) -> AuthorizationPlan:
    arguments: dict[str, Any] = {
        "actor_user_id": uuid.uuid4(),
        "campaign_id": uuid.uuid4(),
        "mode": PlanMode.POST_WRITE,
        "pre_write": None,
        "pending": False,
    }
    arguments.update(kwargs)
    return AuthorizationPlan(_connection(), **arguments)


def test_a_keyed_post_write_plan_is_post_write_final_and_declares_nothing() -> None:
    plan = _plan(keyed_post_write=True)
    assert plan.keyed_post_write and plan.mode is PlanMode.POST_WRITE and not plan.pending
    assert not plan.deferred and plan.reservation_kind is None
    assert not plan.owes_campaign_evidence  # nothing deferred, nothing bound
    assert not _plan().keyed_post_write  # off by default


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": PlanMode.PRE_WRITE},
        {"pending": True},
        {"by_outcome": MagicMock(spec=ReservationDeclarations)},
        {"pre_write": MagicMock()},
    ],
    ids=["pre_write_mode", "pending", "by_outcome", "pre_write_declaration"],
)
def test_a_keyed_post_write_plan_is_refused_with_any_other_plan_kind(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        _plan(keyed_post_write=True, **overrides)


def test_the_evidence_lock_is_the_domain_constant_and_the_command_alias() -> None:
    assert _pre_write_steps.CAMPAIGN_KEY_SHARE_LOCK is CAMPAIGN_EVIDENCE_LOCK
    lock = CAMPAIGN_EVIDENCE_LOCK
    assert (lock.table.schema, lock.table.name) == ("campaign", "campaigns")
    assert [c.name for c in lock.key] == ["campaign_id"]
    assert lock.mode is LockMode.KEY_SHARE
    assert set(lock.specs) == {"campaign"}
    assert authorization._is_campaign_lock(lock)


def test_the_new_entry_points_have_the_designed_shape() -> None:
    import inspect

    assert list(inspect.signature(AuthorizationPlan.lock_campaign_evidence).parameters) == [
        "self",
        "connection",
    ]  # the campaign is the plan's: no caller value
    assert isinstance(AuthorizationPlan.owes_campaign_evidence, property)
    assert ViolationReason.CAMPAIGN_EVIDENCE.value == "campaign_evidence"


# --- the registry and the route-plan dispatch --------------------------------------------------------


# R01 O-2 deliberate change: O-1 pinned the registry empty (`test_no_route_is_registered_in_o1`). O-2 registers the
# 129 routes, generated into `api/r01_pending_routes.py`; the registry's content is pinned in
# `tests/unit/test_r01_o2_structure.py`, and the dispatch below is unchanged.


class _Recorder:
    calls: list[dict[str, Any]] = []

    @classmethod
    def begin(cls, connection: Any, **kwargs: Any) -> str:
        cls.calls.append(kwargs)
        return "plan"


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> type[_Recorder]:
    _Recorder.calls = []
    monkeypatch.setattr(r01_route_plans, "AuthorizationPlan", _Recorder)
    return _Recorder


def _post_write_route() -> tuple[str, str]:
    taken = (
        set(r01_pre_write_routes.R01_KEYED_PRE_WRITE_ROUTES)
        | set(r01_pre_write_routes.R01_UNKEYED_PRE_WRITE_ROUTES)
        | set(
            r01_pending_routes.R01_DEFERRED_RESERVATION_ROUTES
        )  # O-2: a registered route is not "unregistered"
    )
    return next(
        key
        for key in sorted(r01_pending_routes.R01_FINALIZED_ROUTES)
        if key not in taken and key[0] == "POST"
    )


def _begin(key: tuple[str, str]) -> None:
    r01_route_plans.begin_route_plan(
        MagicMock(),
        method=key[0],
        route_path=key[1],
        actor_user_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
    )


def test_an_unregistered_route_gets_an_ordinary_post_write_plan(
    recorder: type[_Recorder],
) -> None:
    _begin(_post_write_route())
    assert recorder.calls[-1]["keyed_post_write"] is False
    assert "mode" not in recorder.calls[-1]


def test_a_registered_finalized_route_gets_a_keyed_post_write_plan(
    recorder: type[_Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _post_write_route()
    monkeypatch.setattr(r01_route_plans, "R01_DEFERRED_RESERVATION_ROUTES", frozenset({key}))
    _begin(key)
    assert recorder.calls[-1]["keyed_post_write"] is True
    assert recorder.calls[-1]["pending"] is False
    assert "by_outcome" not in recorder.calls[-1] and "pre_write" not in recorder.calls[-1]


def test_a_registered_route_that_is_pending_or_pre_write_is_unclassified(
    recorder: type[_Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    # R01 E4: the production pending set is empty, so the pending case uses a TEST-ONLY pending route
    pending = ("POST", "/campaigns/{campaign_id}/test-only-pending")
    monkeypatch.setattr(r01_pending_routes, "R01_PENDING_ROUTES", {pending: "engine_early_commit"})
    monkeypatch.setattr(r01_route_plans, "R01_PENDING_ROUTES", {pending: "engine_early_commit"})
    keyed = next(iter(r01_pre_write_routes.R01_KEYED_PRE_WRITE_ROUTES))
    unkeyed = next(iter(r01_pre_write_routes.R01_UNKEYED_PRE_WRITE_ROUTES))
    for key in (pending, keyed, unkeyed):
        monkeypatch.setattr(r01_route_plans, "R01_DEFERRED_RESERVATION_ROUTES", frozenset({key}))
        with pytest.raises(r01_route_plans.UnclassifiedRouteError):
            _begin(key)
    assert recorder.calls == []


# --- who may use the new entry points ----------------------------------------------------------------


def _sources() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


_ADOPTERS = {
    # R01 O-2 deliberate change: the two evidence sites (design 2.2 step 5) and the generated registry
    r"\.lock_campaign_evidence\(": {
        "commands/_content.py",
        "commands/character_public_profile.py",
    },
    r"\bkeyed_post_write\s*=\s*(?!False)": {"api/r01_route_plans.py"},
    r"R01_DEFERRED_RESERVATION_ROUTES": {"api/r01_pending_routes.py", "api/r01_route_plans.py"},
    r"\bCAMPAIGN_EVIDENCE_LOCK\b": {"commands/_pre_write_steps.py"},
}


@pytest.mark.parametrize("pattern", list(_ADOPTERS))
def test_nothing_outside_the_mechanism_uses_the_new_entry_points(pattern: str) -> None:
    regex = re.compile(pattern)
    mechanism = SRC / "domain" / "authorization.py"
    users = {
        path.relative_to(SRC).as_posix()
        for path in _sources()
        if path != mechanism and regex.search(path.read_text(encoding="utf-8"))
    }
    assert users == _ADOPTERS[pattern], f"{pattern}: {users}"


# --- the pre-write code is unchanged -----------------------------------------------------------------


def _digest(nodes: list[ast.AST]) -> str:
    return hashlib.sha256("|".join(dump(n) for n in nodes).encode()).hexdigest()[:16]


def _whole(function: ast.FunctionDef) -> list[ast.AST]:
    return [function]


def _body_from(index: int) -> Callable[[ast.FunctionDef], list[ast.AST]]:
    return lambda function: list(function.body[index:])


def _first_if_naming(word: str) -> Callable[[ast.FunctionDef], list[ast.AST]]:
    def select(function: ast.FunctionDef) -> list[ast.AST]:
        found = [n for n in function.body if isinstance(n, ast.If) and word in dump(n.test)]
        return found[:1]

    return select


def _handle_error_pre_write_test(function: ast.FunctionDef) -> list[ast.AST]:
    node = function.body[-1]
    assert isinstance(node, ast.If)
    test = node.test
    # parent: `mode is PRE_WRITE and (...)`; AM-1: `(that) or (keyed ...)`
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return [test.values[0]]
    return [test]


#: method name -> selector of the statements that carry the pre-write behaviour
SELECTORS: dict[str, Callable[[ast.FunctionDef], list[ast.AST]]] = {
    "_begin_call": _whole,
    "lock": _whole,
    "execute": _whole,
    "_check_admission": _whole,
    "_validate_rows": _whole,
    "_skippable": _whole,
    "_lower_bound_met": _whole,
    "_any_confirmed": _whole,
    "_incomplete": _whole,
    "_issue": _whole,
    "_build_snapshot": _whole,
    "_verify_session": _whole,
    "_install_declaration": _whole,
    "_authorizes_fk_mode": _whole,
    "_check_obligations": _whole,
    "_refuses_commit": _whole,
    "_guard_flight": _whole,
    "_observe_statement": _whole,
    "_values_match": _whole,
    "_on_before_execute": _whole,
    "_on_do_execute": _whole,
    "_on_after_cursor_execute": _whole,
    "_on_after_execute": _whole,
    "_on_unsupported_dispatch": _whole,
    "_close": _whole,
    "require": _whole,
    "finalize": _first_if_naming("PRE_WRITE"),
    "defer_reservation_campaign_fk": _body_from(1),  # after the docstring
    "_obligation_failure": lambda f: list(f.body[-4:]),
    "_controlled": lambda f: [f.body[-1]],
    "_on_before_cursor_execute": _body_from(2),
    "_on_handle_error": _handle_error_pre_write_test,
    "_on_savepoint_rollback": lambda f: [
        n for n in f.body if isinstance(n, ast.If) and "PRE_WRITE" in dump(n.test)
    ],
    "_has_campaign_evidence": lambda f: [f.body[-1]],
}

#: digests of the parent's statements (`git show 3a85ca5:src/dnd_ai/domain/authorization.py`)
PARENT_PINS: dict[str, str] = {
    "_any_confirmed": "ecb2463ba5ba0942",
    "_authorizes_fk_mode": "871967dd2a028f4b",
    "_begin_call": "f4978e8238c68e79",
    "_build_snapshot": "10ae810c482048f0",
    "_check_admission": "5083e9b8e4c4eb92",
    "_check_obligations": "6f05a0c23c2d36e9",
    "_close": "59b26693336f3f6d",
    "_controlled": "404af2f10281ea22",
    "_guard_flight": "4eeb87324e36da10",
    "_has_campaign_evidence": "ab4ced72cd725094",
    "_incomplete": "28067ce47a9c597d",
    "_install_declaration": "cbee75ddc08de038",
    "_issue": "35ba591c9722ae10",
    "_lower_bound_met": "eb1d4c6b7ab178ea",
    "_obligation_failure": "7591e2d9ac2df947",
    "_observe_statement": "d7478a346c11deab",
    "_on_after_cursor_execute": "b9c4fc0341d26aba",
    "_on_after_execute": "d560847f49484cca",
    "_on_before_cursor_execute": "2a6c71d76afd467d",
    "_on_before_execute": "09cd49e6744f8bb9",
    "_on_do_execute": "451b1a9124d1692d",
    "_on_handle_error": "0ef0d31e1456c142",
    "_on_savepoint_rollback": "b60be1a56a35eb13",
    "_on_unsupported_dispatch": "3fb63fa9de916647",
    "_refuses_commit": "30f2a0f499251933",
    "_skippable": "926d422e0067a02b",
    "_validate_rows": "9b13cc843bbc6684",
    "_values_match": "5f45f24e3df78925",
    "_verify_session": "f57e9c13f0cfbafd",
    "defer_reservation_campaign_fk": "09eb2b8be5696071",
    "execute": "aae5e024ef1d1210",
    "finalize": "902df922d8c19b98",
    "lock": "4617045beaab9180",
    # R01 E2 correction C-1: one declared party perspective per plan (was 92302c364e2191b5); P15-C11-S02 correction
    # S02-R2: one declared assistant_gm subject per plan, the same guard for the new final-statement source
    # (was 742c5127e08b421e)
    "require": "4be22a5b90b82899",
}


def _plan_class(tree: ast.Module) -> ast.ClassDef:
    return next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AuthorizationPlan"
    )


def pins_of(source: str) -> dict[str, str]:
    plan = _plan_class(ast.parse(source))
    methods = {n.name: n for n in plan.body if isinstance(n, ast.FunctionDef)}
    return {name: _digest(select(methods[name])) for name, select in SELECTORS.items()}


def test_the_pre_write_code_is_unchanged_from_the_parent() -> None:
    path = Path(str(authorization.__file__))
    assert pins_of(path.read_text(encoding="utf-8")) == PARENT_PINS


def test_the_module_level_guard_is_unchanged_where_it_is_not_amended() -> None:
    """The commit guard and the listeners other than the one keyed-policing line are pinned whole."""
    tree = ast.parse(Path(str(authorization.__file__)).read_text(encoding="utf-8"))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    found = {name: _digest([functions[name]]) for name in sorted(MODULE_PINS)}
    assert found == MODULE_PINS


MODULE_PINS: dict[str, str] = {
    "_forget": "f406ecbf55ff8c6b",
    "_on_after_cursor_execute": "869924a6c3ba9c6a",
    "_on_after_execute": "e332fd573840e26a",
    "_on_before_cursor_execute": "86000c29ad38c802",
    "_on_before_execute": "17a907e31582edd1",
    "_on_commit": "a221a461ffe47706",
    "_on_do_execute": "6209758d53d36ce3",
    "_on_do_execute_no_params": "3c7525553c4486a9",
    "_on_do_executemany": "35ccaca729225a50",
    "_on_handle_error": "9e6adbb71cf4f879",
    "_on_rollback": "6ca3ab6eb21e5880",
    "_on_rollback_savepoint": "be3c2fbd0e02ef8c",
    "_plans_for": "7ba47218880545e2",
    "install_authorization_guard": "136f63a647f24f51",
}
