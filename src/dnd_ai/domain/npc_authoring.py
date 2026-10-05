"""Pure contract for NPC identity authoring (Phase 15.1).

Identity only: name, summary, species, size, origin location, and the three
description fields. An NPC's build, timeline state, goals, routines, and AI
portrayal are separate write boundaries and are not authored here (docs/PLAN.md
Phase 15C; the rest is Phase 15.2 or later).
"""

from dataclasses import dataclass

from .authoring import AuthoringValidationError, normalize_description, normalize_name
from .organization_authoring import normalize_optional_text

NPC_TEXT_MAX_LENGTH = 4000

# Mirrors `ck_characters_size_category`; the database is the backstop.
SIZE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("tiny", "Tiny"),
    ("small", "Small"),
    ("medium", "Medium"),
    ("large", "Large"),
    ("huge", "Huge"),
    ("gargantuan", "Gargantuan"),
)
_SIZE_CODES = frozenset(code for code, _ in SIZE_CATEGORIES)


@dataclass(frozen=True)
class NpcFields:
    name: str
    summary: str | None
    size_category: str
    background: str | None
    appearance: str | None
    notes: str | None


def normalize_npc_fields(
    *,
    name: str | None,
    summary: str | None,
    size_category: str | None,
    background: str | None,
    appearance: str | None,
    notes: str | None,
) -> NpcFields:
    if size_category not in _SIZE_CODES:
        raise AuthoringValidationError("size_category is not an allowed size")
    return NpcFields(
        name=normalize_name(name),
        summary=normalize_description(summary),
        size_category=size_category,
        background=normalize_optional_text(
            background, field="background", max_length=NPC_TEXT_MAX_LENGTH
        ),
        appearance=normalize_optional_text(
            appearance, field="appearance", max_length=NPC_TEXT_MAX_LENGTH
        ),
        notes=normalize_optional_text(notes, field="notes", max_length=NPC_TEXT_MAX_LENGTH),
    )
