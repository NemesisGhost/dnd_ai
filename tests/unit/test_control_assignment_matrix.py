"""P15-C11-S01-T02: the closed control-assignment capability matrix (E25-E27).

Plan section 3.2 item 1: the matrix is code-only and identical for the two assignment roles (OD-2), exactly ADR 0021
section 2.5 item 2. It never holds a campaign, world or narrative capability, and no route or command consumes its
profile and operation codes yet (C12 and C20 add them behind their own gates).
"""

import ast
from pathlib import Path

import pytest

from dnd_ai.domain.access import CONTROL_ASSIGNMENT_CAPABILITIES

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"

_ADR_SECTION_2_5_ITEM_2 = frozenset(
    {
        "character.discover",
        "character.view_summary",
        "character.view_full",
        "character.view_inventory",
        "character.control",
        "character.edit_mechanical_state",
        "character.view_player_profile",
        "character.edit_player_profile",
    }
)

_EXCLUDED = (
    "canon.edit",
    "access.manage",
    "campaign.view",
    "character.view_private",
    "character.view_knowledge",
    "character.edit_narrative",
    "character.interact",
    "character.reveal",
    "character.view_public_profile",
    "character.assign_control",
)

_RESERVED_FOR_LATER_CHECKPOINTS = (
    "character.control",
    "character.edit_mechanical_state",
    "character.view_player_profile",
    "character.edit_player_profile",
)


def test_the_matrix_keys_are_exactly_the_two_assignment_roles_with_identical_sets() -> None:
    """E25."""
    assert set(CONTROL_ASSIGNMENT_CAPABILITIES) == {"primary_controller", "co_controller"}
    primary = CONTROL_ASSIGNMENT_CAPABILITIES["primary_controller"]
    assert primary == CONTROL_ASSIGNMENT_CAPABILITIES["co_controller"]
    assert primary == _ADR_SECTION_2_5_ITEM_2
    assert all(isinstance(codes, frozenset) for codes in CONTROL_ASSIGNMENT_CAPABILITIES.values())


@pytest.mark.parametrize("role", ["primary_controller", "co_controller"])
def test_no_excluded_capability_is_in_either_set(role: str) -> None:
    """E26."""
    codes = CONTROL_ASSIGNMENT_CAPABILITIES[role]
    assert not codes & set(_EXCLUDED)
    assert not any(code.startswith(("world.", "campaign.")) for code in codes)


def test_no_route_or_command_consumes_the_reserved_codes_yet() -> None:
    """E27 (guard): none of the four codes is passed as a literal anywhere under `api` or `commands`, so no
    `has_capability` call and no requirement names one. A later checkpoint adds its consumer and this test
    with it."""
    offenders: list[str] = []
    for folder in ("api", "commands"):
        for path in sorted((SRC / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {
                id(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and node.value in _RESERVED_FOR_LATER_CHECKPOINTS
                ):
                    offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    assert offenders == []
