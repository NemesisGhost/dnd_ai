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


def test_no_route_is_registered_in_o1() -> None:
    assert not r01_pre_write_routes.R01_DEFERRED_RESERVATION_ROUTES


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
    taken = set(r01_pre_write_routes.R01_KEYED_PRE_WRITE_ROUTES) | set(
        r01_pre_write_routes.R01_UNKEYED_PRE_WRITE_ROUTES
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
    pending = next(iter(r01_pending_routes.R01_PENDING_ROUTES))
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
    r"\.lock_campaign_evidence\(": set(),
    r"\bkeyed_post_write\s*=\s*(?!False)": {"api/r01_route_plans.py"},
    r"R01_DEFERRED_RESERVATION_ROUTES": {"api/r01_pre_write_routes.py", "api/r01_route_plans.py"},
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
    return hashlib.sha256("|".join(ast.dump(n) for n in nodes).encode()).hexdigest()[:16]


def _whole(function: ast.FunctionDef) -> list[ast.AST]:
    return [function]


def _body_from(index: int) -> Callable[[ast.FunctionDef], list[ast.AST]]:
    return lambda function: list(function.body[index:])


def _first_if_naming(word: str) -> Callable[[ast.FunctionDef], list[ast.AST]]:
    def select(function: ast.FunctionDef) -> list[ast.AST]:
        found = [n for n in function.body if isinstance(n, ast.If) and word in ast.dump(n.test)]
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
        n for n in f.body if isinstance(n, ast.If) and "PRE_WRITE" in ast.dump(n.test)
    ],
    "_has_campaign_evidence": lambda f: [f.body[-1]],
}

#: digests of the parent's statements (`git show 3a85ca5:src/dnd_ai/domain/authorization.py`)
PARENT_PINS: dict[str, str] = {
    "_any_confirmed": "5a27bb3638090b7b",
    "_authorizes_fk_mode": "196e18d9f6f60575",
    "_begin_call": "a985fae91a764cef",
    "_build_snapshot": "f2eb6d376215ea54",
    "_check_admission": "ed13fb5e9dc8067b",
    "_check_obligations": "4931573a69eab5e3",
    "_close": "92b2a72bdb5185f2",
    "_controlled": "404af2f10281ea22",
    "_guard_flight": "d26d62abe7f82275",
    "_has_campaign_evidence": "a367c89eaec3efc2",
    "_incomplete": "aea9e211c9ee2c9c",
    "_install_declaration": "f41ec77c38e4fce3",
    "_issue": "cb447030cc4eb407",
    "_lower_bound_met": "ed4496a340aed6c3",
    "_obligation_failure": "3d952e02178c8b9d",
    "_observe_statement": "57dd2a7903a529ee",
    "_on_after_cursor_execute": "dc559311c0859f04",
    "_on_after_execute": "1614a324fff89b14",
    "_on_before_cursor_execute": "a4fad91d603f6865",
    "_on_before_execute": "cfe463a4a9969dbd",
    "_on_do_execute": "517b830b4094ae05",
    "_on_handle_error": "0ef0d31e1456c142",
    "_on_savepoint_rollback": "1b0d04c28cf9f4a7",
    "_on_unsupported_dispatch": "f3cb8c84820ccecd",
    "_refuses_commit": "0491d23a2f8fe551",
    "_skippable": "b318238b66c6b6ee",
    "_validate_rows": "d0c8b05bfbe771cb",
    "_values_match": "c5e9f852b0f30122",
    "_verify_session": "f18c9782da5e831d",
    "defer_reservation_campaign_fk": "9d021e8971db405d",
    "execute": "9aa78aabd3a8b5eb",
    "finalize": "0bc934ca584f5220",
    "lock": "bd099087ed68017a",
    "require": "92302c364e2191b5",
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
    "_forget": "187433413743c452",
    "_on_after_cursor_execute": "73938ae179383597",
    "_on_after_execute": "cf78c2e7901a95c5",
    "_on_before_cursor_execute": "4ecea22d4eb4bd35",
    "_on_before_execute": "7cce1f9f8aa02c0b",
    "_on_commit": "b466739732017a51",
    "_on_do_execute": "ace8f86582a5386f",
    "_on_do_execute_no_params": "94f93121a572c34f",
    "_on_do_executemany": "fc89c090ed44401c",
    "_on_handle_error": "1b750f667fe0cdff",
    "_on_rollback": "2d1debe46bb5423a",
    "_on_rollback_savepoint": "96b7c78c0893ef3d",
    "_plans_for": "77a9650f7282fcd3",
    "install_authorization_guard": "73e31a6673e21b10",
}
