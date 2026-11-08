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


def test_only_the_idempotency_module_takes_the_key_lock() -> None:
    callers = {
        name
        for name, source in _sources().items()
        if re.search(r"\block_idempotency_key\(", source)
    }
    assert callers == {IDEMPOTENCY}


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
