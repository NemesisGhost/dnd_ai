"""R01 S5-E5 infrastructure: the code of the existing cardinalities is unchanged (design 10.1, "Structure test").

I-1 (`PerEvidenceRow`), I-2 (`PerConfirmedRow`) and I-3 (the `GREATEST` form) are **additions**: new classes, new `isinstance`
branches and one new value form. The classes `Exactly`, `Between`, `EachLockedRow`, `PerEvidence`, `PerAbsence`, `AnyConfirmed` and
the branches of `AuthorizationPlan._skippable`, `._lower_bound_met` and `._check_admission` that serve them must not be edited by
this slice. Each is pinned by the digest of its syntax tree (line numbers and comments do not enter it), taken from the sources
as they were at the S5-E5 parent (`cde48d2`). A reviewed change of one of them updates its pin deliberately.
"""

import ast
import hashlib
from pathlib import Path
from types import ModuleType

import pytest

from dnd_ai.domain import authorization, authorization_steps
from tests.ast_support import dump

pytestmark = pytest.mark.unit

EXISTING = ("Exactly", "Between", "PerEvidence", "PerAbsence", "AnyConfirmed")
FUNCTIONS = ("_skippable", "_lower_bound_met", "_check_admission")

#: sha256 (first 16 hex digits) of `ast.dump` of the `if` statement of each existing branch, at `cde48d2`.
BRANCH_PINS = {
    "_check_admission:AnyConfirmed": "a6cfb5e00e4f8562",
    "_check_admission:Between": "ff61e5280fde6cc0",
    "_check_admission:Exactly": "af4f326a94290e21",
    "_check_admission:PerAbsence": "6b0fa6fd68d9179f",
    "_check_admission:PerEvidence": "1d06d0726084f293",
    "_lower_bound_met:AnyConfirmed": "84273f762a86afcf",
    "_lower_bound_met:Between": "8e4201df19bc1cbf",
    "_lower_bound_met:Exactly": "2e501f04d202e1ca",
    "_lower_bound_met:PerAbsence": "9e4a9391d869eef1",
    "_lower_bound_met:PerEvidence": "de0a0a9016b7ec85",
    "_lower_bound_met:complete": "7a5156f6be5118b4",
    "_skippable:AnyConfirmed": "df8e834ed5b26ec5",
    "_skippable:Between": "7a278b177c0b3f99",
    "_skippable:Exactly": "88eec9635aa5f279",
    "_skippable:PerAbsence": "c66fc48b05a946fe",
    "_skippable:PerEvidence": "ba6bb0676b0acb6c",
    "_skippable:complete": "ab8cdbf17012f06f",
}
CLASS_PINS = {
    "Exactly": "889d47f491956553",
    "Between": "f73fbc578cc1931b",
    "EachLockedRow": "99dd30f0542b80cd",
    "PerEvidence": "6a3a60922538d34c",
    "PerAbsence": "ee64a4b31f830ff3",
    "AnyConfirmed": "49fb3f854b4185ba",
}


def _digest(node: ast.AST) -> str:
    return hashlib.sha256(dump(node).encode()).hexdigest()[:16]


def _tree(module: ModuleType) -> ast.Module:
    path = Path(str(module.__file__))
    return ast.parse(path.read_text(encoding="utf-8"))


def test_the_branches_of_the_existing_cardinalities_are_unchanged() -> None:
    plan = next(
        n
        for n in ast.walk(_tree(authorization))
        if isinstance(n, ast.ClassDef) and n.name == "AuthorizationPlan"
    )
    found: dict[str, str] = {}
    for function in plan.body:
        if not isinstance(function, ast.FunctionDef) or function.name not in FUNCTIONS:
            continue
        for node in function.body:
            if not isinstance(node, ast.If):
                continue
            test = dump(node.test)
            named = [name for name in EXISTING if f"id='{name}'" in test]
            for name in named:
                found[f"{function.name}:{name}"] = _digest(node)
            if "complete" in test and not named:
                found[f"{function.name}:complete"] = _digest(node)
    assert found == BRANCH_PINS


def test_the_classes_of_the_existing_cardinalities_are_unchanged() -> None:
    found = {
        node.name: _digest(node)
        for node in _tree(authorization_steps).body
        if isinstance(node, ast.ClassDef) and node.name in CLASS_PINS
    }
    assert found == CLASS_PINS


def test_the_new_cardinalities_are_additions_with_their_own_branches() -> None:
    """The new classes exist and every plan function that decides skippability, completeness and admission has its own branch for
    them (so the pins above are not satisfied by deleting the new code)."""
    source = Path(str(authorization.__file__)).read_text(encoding="utf-8")
    for function in FUNCTIONS:
        body = source[source.index(f"def {function}") :]
        body = body[: body.index("\n    def ", 10)] if "\n    def " in body[10:] else body
        assert "PerEvidenceRow" in body, function
    assert "PerConfirmedRow" in source[source.index("def _skippable") :]
    assert hasattr(authorization_steps, "PerEvidenceRow") and hasattr(
        authorization_steps, "PerConfirmedRow"
    )
