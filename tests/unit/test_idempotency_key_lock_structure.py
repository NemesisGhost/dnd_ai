"""Structural guards for the idempotency key lock (P03-A P2).

The lock is only safe if it is requested before a request holds any row lock, which holds because
every reserving route reserves first. These tests pin the places that guarantee it: the one
reservation INSERT sits right after the one key-lock call, and nothing else reserves into the
campaign-scoped store or takes the key lock. (The per-route evaluation that each route reserves
before its own row locks was done by reading every route at `a9ec4c4`; it is recorded in the plan,
section 10.11, and is not re-derived by a test.)
"""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"
IDEMPOTENCY = "api/idempotency.py"


def _sources() -> dict[str, str]:
    return {p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")}


def test_only_the_idempotency_module_inserts_into_the_campaign_scoped_store() -> None:
    inserting = {
        name
        for name, source in _sources().items()
        if re.search(r"INSERT\s+INTO\s+security\.idempotent_requests", source)
    }
    assert inserting == {IDEMPOTENCY}


REVELATIONS = "api/character_revelations.py"
_SCOPE_KEYWORDS = ("actor_user_id", "campaign_id", "idempotency_key")


def test_only_the_idempotency_module_and_the_designated_a3_routes_take_the_key_lock() -> None:
    callers = {
        name
        for name, source in _sources().items()
        if re.search(r"\block_idempotency_key\(", source)
    }
    assert callers == {IDEMPOTENCY, REVELATIONS}


def _call_scope(call: ast.Call) -> dict[str, str]:
    return {
        keyword.arg: ast.dump(keyword.value)
        for keyword in call.keywords
        if keyword.arg in _SCOPE_KEYWORDS
    }


def _calls_named(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name
    ]


def test_the_designated_a3_call_is_the_first_database_work_and_reserves_the_same_scope() -> None:
    """A3's early key lock (plan section 10.4, step 0): in each revelation route it is the first
    statement that touches the request connection, and the reservation made later through the
    command's `reserve()` callback uses exactly the same actor, campaign and key."""
    tree = ast.parse((SRC / REVELATIONS).read_text(encoding="utf-8"))
    routes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and _calls_named(node, "lock_idempotency_key")
    ]
    assert {route.name for route in routes} == {
        "create_character_revelation_endpoint",
        "revoke_character_revelation_endpoint",
    }
    for route in routes:
        locks = _calls_named(route, "lock_idempotency_key")
        assert len(locks) == 1, route.name
        lock = locks[0]
        # Nothing before it uses the connection: it is the first database statement.
        for statement in route.body:
            if statement.lineno >= lock.lineno:
                break
            uses = [
                n.id
                for n in ast.walk(statement)
                if isinstance(n, ast.Name) and n.id == "connection"
            ]
            assert not uses, (route.name, statement.lineno)
        assert isinstance(lock.args[0], ast.Name) and lock.args[0].id == "connection"
        # The reservation (inside the `reserve` closure) names the same scope.
        reservations = _calls_named(route, "start_campaign_idempotency")
        assert len(reservations) == 1, route.name
        assert _call_scope(reservations[0]) == _call_scope(lock), route.name
        assert set(_call_scope(lock)) == set(_SCOPE_KEYWORDS)
        # The command is handed the callback, never the key: it cannot reserve another scope.
        commands = [
            call
            for call in ast.walk(route)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id.endswith("_character_revelation")
        ]
        assert len(commands) == 1 and any(k.arg == "reserve" for k in commands[0].keywords)


def test_the_key_lock_is_taken_before_the_reservation_insert() -> None:
    tree = ast.parse((SRC / IDEMPOTENCY).read_text(encoding="utf-8"))
    begin = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "begin_idempotent_request"
    )
    lock_lines = [
        node.lineno
        for node in ast.walk(begin)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "lock_idempotency_key"
    ]
    insert_lines = [
        node.lineno
        for node in ast.walk(begin)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "INSERT INTO security.idempotent_requests" in node.value
    ]
    assert len(lock_lines) == 1 and len(insert_lines) == 1
    assert lock_lines[0] < insert_lines[0]
    # Nothing in the function touches the database before the lock.
    first_statement = min(
        node.lineno
        for node in ast.walk(begin)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    )
    assert lock_lines[0] <= first_statement


def test_the_other_two_stores_do_not_take_the_campaign_key_lock() -> None:
    tree = ast.parse((SRC / IDEMPOTENCY).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "begin_campaign_creation_request",
            "begin_actor_idempotent_request",
        ):
            names = {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            assert "lock_idempotency_key" not in names, node.name


def test_the_key_lock_uses_the_64_bit_hash_with_a_versioned_scope() -> None:
    source = (SRC / IDEMPOTENCY).read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock(hashtextextended(:scope, 0))" in source
    assert "dnd_ai.idempotency.campaign_key.v1" in source
