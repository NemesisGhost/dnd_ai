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

pytestmark = pytest.mark.unit

EXISTING = ("Exactly", "Between", "PerEvidence", "PerAbsence", "AnyConfirmed")
FUNCTIONS = ("_skippable", "_lower_bound_met", "_check_admission")

#: sha256 (first 16 hex digits) of `ast.dump` of the `if` statement of each existing branch, at `cde48d2`.
BRANCH_PINS = {
    "_check_admission:AnyConfirmed": "3c994beca8706e75",
    "_check_admission:Between": "544717729c116f52",
    "_check_admission:Exactly": "1762207c97b8d746",
    "_check_admission:PerAbsence": "81cfb9d150cbb61c",
    "_check_admission:PerEvidence": "813796b4585c3492",
    "_lower_bound_met:AnyConfirmed": "c87f0b27e9d5061b",
    "_lower_bound_met:Between": "2348b62f6feb8ffa",
    "_lower_bound_met:Exactly": "b381c6e5039b0323",
    "_lower_bound_met:PerAbsence": "5d8665bb903c2513",
    "_lower_bound_met:PerEvidence": "1286b40f15f43569",
    "_lower_bound_met:complete": "c90a68180ea74de5",
    "_skippable:AnyConfirmed": "428d2195ba790a34",
    "_skippable:Between": "97d555ad0fef2bb7",
    "_skippable:Exactly": "753f40ac70c007bb",
    "_skippable:PerAbsence": "9f01e41da762e0de",
    "_skippable:PerEvidence": "69272cdee2bb744d",
    "_skippable:complete": "9c731d6ecada1d97",
}
CLASS_PINS = {
    "Exactly": "b3203d116089bfde",
    "Between": "17e802dbbe9c9d97",
    "EachLockedRow": "fac792121afe8983",
    "PerEvidence": "87ab426db36cd680",
    "PerAbsence": "b95d8742e8dcbbbc",
    "AnyConfirmed": "3921b8839b06436a",
}


def _digest(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node).encode()).hexdigest()[:16]


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
            test = ast.dump(node.test)
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
