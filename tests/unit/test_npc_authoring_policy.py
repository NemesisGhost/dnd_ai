"""Pure contract for NPC identity authoring (Phase 15.1)."""

import pytest

from dnd_ai.domain.authoring import AuthoringValidationError
from dnd_ai.domain.npc_authoring import NPC_TEXT_MAX_LENGTH, SIZE_CATEGORIES, normalize_npc_fields

BASE = {
    "name": "Mira",
    "summary": None,
    "size_category": "medium",
    "background": None,
    "appearance": None,
    "notes": None,
}


def test_sizes_mirror_the_database_check() -> None:
    assert [code for code, _ in SIZE_CATEGORIES] == [
        "tiny",
        "small",
        "medium",
        "large",
        "huge",
        "gargantuan",
    ]


def test_fields_are_trimmed_and_blank_becomes_null() -> None:
    fields = normalize_npc_fields(
        **{
            **BASE,
            "name": "  Mira  ",
            "summary": "  ",
            "background": " Raised in hills ",
            "notes": "",
        }
    )
    assert (fields.name, fields.summary, fields.background, fields.notes) == (
        "Mira",
        None,
        "Raised in hills",
        None,
    )


@pytest.mark.parametrize(
    "override",
    [
        {"name": ""},
        {"name": " "},
        {"name": "x" * 201},
        {"summary": "x" * 4001},
        {"size_category": "Medium"},
        {"size_category": "colossal"},
        {"size_category": None},
        {"background": "x" * (NPC_TEXT_MAX_LENGTH + 1)},
        {"appearance": "x" * (NPC_TEXT_MAX_LENGTH + 1)},
        {"notes": "x" * (NPC_TEXT_MAX_LENGTH + 1)},
    ],
)
def test_invalid_fields_are_refused(override: dict) -> None:
    with pytest.raises(AuthoringValidationError):
        normalize_npc_fields(**{**BASE, **override})  # type: ignore[arg-type]
