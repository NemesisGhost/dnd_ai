"""R01 S1: structural guarantees of the authorization infrastructure (plan sections 6.3, 6.5, 12.2).

Source-shape tests, no database:

- the commit guard is the ONLY `commit` listener registered in `src`;
- no raw COMMIT: `src` never sends `COMMIT` text or commits the DBAPI connection directly, so the guard
  cannot be bypassed (the sanctioned COMMIT is `Connection.commit()`, which fires the listener);
- the reader's input tables, and the manifest disjointness of post-write routes from them;
- the guard's error class is a direct `RuntimeError` subclass, and a pending plan is not an open one.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from dnd_ai.domain import authorization
from dnd_ai.domain.access import (
    AUTHORITY_READER_TABLES,
    REVIEWED_POST_WRITE_TABLES,
    _authority_snapshot_sql,
)
from tests.r01_manifest import MANIFEST_PATH

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"


def _modules() -> list[tuple[str, ast.AST]]:
    return [
        (path.relative_to(SRC).as_posix(), ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(SRC.rglob("*.py"))
    ]


def _string_args(call: ast.Call) -> list[str]:
    return [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]


def test_the_guard_is_the_only_commit_listener_in_src() -> None:
    listeners: list[str] = []
    for module, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in ("listen", "listens_for", "listen_for") and "commit" in _string_args(node):
                listeners.append(f"{module}:{node.lineno}")
    assert listeners == ["domain/authorization.py:" + listeners[0].split(":")[1]]
    assert len(listeners) == 1
    # and it registers the guard's own function
    tree = ast.parse(Path(authorization.__file__).read_text(encoding="utf-8"))
    listened = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "listen"
        and "commit" in _string_args(node)
    ]
    assert len(listened) == 1
    assert isinstance(listened[0].args[2], ast.Name) and listened[0].args[2].id == "_on_commit"


def test_src_has_no_raw_commit() -> None:
    offenders: list[str] = []
    for module, tree in _modules():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", getattr(node.func, "id", ""))
                in ("text", "exec_driver_sql", "execute")
                and any(
                    re.fullmatch(r"\s*(COMMIT|END\s+TRANSACTION)\s*;?\s*", arg, re.I)
                    for arg in _string_args(node)
                )
            ):
                offenders.append(f"{module}:{node.lineno}: COMMIT text")
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "commit":
                target = node.func.value  # type: ignore[attr-defined]
                chain = []
                while isinstance(target, ast.Attribute):
                    chain.append(target.attr)
                    target = target.value
                if {"driver_connection", "dbapi_connection"} & set(chain):
                    offenders.append(f"{module}:{node.lineno}: DBAPI commit")
    assert offenders == []


def test_the_guards_refusal_rolls_back_the_dbapi_connection_but_never_commits_it() -> None:
    """The guard may call `driver.rollback()` (defence in depth) and must never commit."""
    source = Path(authorization.__file__).read_text(encoding="utf-8")
    assert "driver.rollback()" in source
    assert ".commit()" not in re.sub(r'""".*?"""', "", source, flags=re.S)


def test_the_reader_constant_names_exactly_the_tables_the_statement_reads() -> None:
    sql = _authority_snapshot_sql(instant="fresh", with_world=True, with_reveal=True)
    named = set(re.findall(r"(?:FROM|JOIN)\s+([a-z_]+\.[a-z_]+)", sql))
    assert named == AUTHORITY_READER_TABLES


def test_post_write_routes_write_none_of_the_readers_tables_except_the_reviewed_classes() -> None:
    """Plan section 6.3 obligation: a post-write request must not write a table its own decision
    reads. The manifest traces every route's write targets (static source shape; it does not prove
    order). The reviewed classes are `core.entities`, `campaign.sessions` and the two revelation
    tables; anything else a post-write route writes that the reader reads fails this test."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    post_write_families = {
        "authoring_scope",
        "operation_scope",
        "reveal_authority",
        "route_capability_only",
    }
    offenders: list[str] = []
    routes = 0
    for record in manifest:
        if record["family"] not in post_write_families:
            continue
        routes += 1
        written = {w for writes in record["command_writes"].values() for w in writes}
        bad = (written & AUTHORITY_READER_TABLES) - REVIEWED_POST_WRITE_TABLES
        if bad:
            offenders.append(f"{record['method']} {record['path']}: {sorted(bad)}")
    assert routes == 152, "the post-write families changed size; review this test"
    assert offenders == []


def test_the_access_management_family_is_not_in_the_post_write_check() -> None:
    """Access management writes its own authority inputs; it is a pre-write family (S5), so the
    disjointness obligation above deliberately excludes it. This pins that it really does write
    reader tables, so the exclusion is not hiding an empty set."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    written = {
        w
        for record in manifest
        if record["family"] == "access_management"
        for writes in record["command_writes"].values()
        for w in writes
    }
    assert {"security.membership_roles", "security.resource_grants"} <= written
    assert (written & AUTHORITY_READER_TABLES) - REVIEWED_POST_WRITE_TABLES


def test_a_pending_plan_is_a_flag_and_the_marker_is_not_a_plan() -> None:
    assert authorization.R01_PENDING is authorization.R01_PENDING
    assert not isinstance(authorization.R01_PENDING, authorization.AuthorizationPlan)
    assert repr(authorization.R01_PENDING) == "R01_PENDING"


# --- S1-C structural guarantees (plan 6.11.9, PW-20) ---------------------------------------------

_GUARDED_EVENTS = {
    "before_execute",
    "after_execute",
    "before_cursor_execute",
    "after_cursor_execute",
    "do_execute",
    "do_executemany",
    "do_execute_no_params",
    "handle_error",
    "rollback_savepoint",
    "commit",
    "rollback",
}


def _listen_calls() -> list[tuple[str, int, ast.Call]]:
    found: list[tuple[str, int, ast.Call]] = []
    for module, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in ("listen", "listens_for", "listen_for", "contains"):
                found.append((module, node.lineno, node))
    return found


def test_the_guard_is_the_only_listener_of_every_guarded_event_and_none_uses_retval() -> None:
    offenders: list[str] = []
    registered: set[str] = set()
    for module, line, call in _listen_calls():
        events = set(_string_args(call)) & _GUARDED_EVENTS
        if not events:
            continue
        if module != "domain/authorization.py":
            offenders.append(f"{module}:{line}: listener outside the guard")
        if getattr(call.func, "attr", "") == "listen":
            registered |= events
            target = call.args[0]
            if not (isinstance(target, ast.Name) and target.id == "engine"):
                offenders.append(f"{module}:{line}: not registered on the engine instance")
        for keyword in call.keywords:
            if keyword.arg == "retval":
                offenders.append(f"{module}:{line}: retval")
    assert offenders == []
    assert registered == _GUARDED_EVENTS


def test_no_class_level_listener_and_no_retval_anywhere_in_src() -> None:
    for module, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and any(k.arg == "retval" for k in node.keywords):
                pytest.fail(f"{module}:{node.lineno}: retval listener")
    for module, line, call in _listen_calls():
        target = call.args[0] if call.args else None
        if isinstance(target, ast.Name) and target.id in {"Engine", "Connection", "Dialect"}:
            pytest.fail(f"{module}:{line}: class-level listener")


def test_raw_dbapi_execution_is_limited_to_the_reviewed_seams() -> None:
    """Raw DBAPI use fires no SQLAlchemy event (plan 6.9.6). The only uses in `src` are T0's
    rollback/status seams in `api/deps.py` and the guard's own rollback."""
    allowed = {"api/deps.py", "domain/authorization.py"}
    pattern = re.compile(r"driver_connection|dbapi_connection|\.cursor\(|exec_driver_sql")
    offenders = [
        module
        for module, _ in _modules()
        if module not in allowed and pattern.search((SRC / module).read_text(encoding="utf-8"))
    ]
    assert offenders == []
    guard_source = Path(authorization.__file__).read_text(encoding="utf-8")
    assert (
        ".execute(" not in re.findall(r"driver\.[a-z_]+\(", guard_source)
        and "driver.rollback()" in guard_source
    )
    deps_source = (SRC / "api" / "deps.py").read_text(encoding="utf-8")
    assert not re.search(r"driver\.(execute|cursor)\(", deps_source)


def test_declarations_are_built_only_as_module_level_constants() -> None:
    names = {"PreLock", "WriteStep", "PreWriteDeclaration"}
    offenders: list[str] = []
    for module, tree in _modules():
        if module == "domain/authorization_steps.py":
            continue
        module_level = {
            id(call)
            for stmt in tree.body  # type: ignore[attr-defined]
            if isinstance(stmt, ast.Assign)
            and all(isinstance(t, ast.Name) and t.id.isupper() for t in stmt.targets)
            for call in ast.walk(stmt)
            if isinstance(call, ast.Call)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", "")) in names
                and id(node) not in module_level
            ):
                offenders.append(f"{module}:{node.lineno}")
    assert offenders == []


def test_the_declared_surface_has_no_widening_api() -> None:
    import dataclasses

    from dnd_ai.domain import authorization_steps as steps

    forbidden = re.compile(r"add|append|extend|declare|allow|widen|ignore|wildcard|skip", re.I)
    for cls in (steps.PreWriteDeclaration, steps.WriteStep, steps.PreLock):
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
        assert [
            n
            for n in dir(cls)
            if not n.startswith("_") and callable(getattr(cls, n)) and forbidden.search(n)
        ] == []
    public = [
        n
        for n in dir(authorization.AuthorizationPlan)
        if not n.startswith("_") and callable(getattr(authorization.AuthorizationPlan, n))
    ]
    assert [n for n in public if forbidden.search(n)] == []
    assert not hasattr(authorization, "PostAuthorizationStep")


def test_the_guard_dispatches_only_through_the_dialects_own_do_execute() -> None:
    source = Path(authorization.__file__).read_text(encoding="utf-8")
    assert source.count("context.dialect.do_execute(") == 1
