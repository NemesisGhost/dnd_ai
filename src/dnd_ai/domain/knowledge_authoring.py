"""Pure contract for Knowledge-item definition authoring (Phase 15.1, ADR 0015).

A knowledge item is a *claim*: a statement, how the world classifies it
(`knowledge_type`), what is objectively true about it (`truth_status`), how
sensitive it is, and optionally what it is about (a subject entity). Who knows,
believes, or has discovered it is per-knower state (`knowledge.entity_knowledge`,
`campaign.party_knowledge`, ...) -- never a field here (CLAUDE.md rule 8) -- and
revealing it is Phase 15.2. Truth status is not canon status: a `false` claim
can be perfectly canonical.

The entity's own `canonical_name` is derived from the statement (the same
convention the rest of the codebase uses) and kept in step with it.
"""

from dataclasses import dataclass

from .authoring import AuthoringValidationError
from .content_authoring import AUTHORABLE_LOCATION_CATEGORIES
from .organization_authoring import ORGANIZATION_ENTITY_TYPE_CODES

STATEMENT_MAX_LENGTH = 4000
NAME_FROM_STATEMENT_MAX_LENGTH = 200

SENSITIVITIES: tuple[tuple[str, str], ...] = (
    ("public", "Public"),
    ("restricted", "Restricted"),
    ("secret", "Secret"),
    ("dangerous", "Dangerous"),
)
_SENSITIVITY_CODES = frozenset(code for code, _ in SENSITIVITIES)

# What a claim may be about. A knowledge item is never its own subject.
KNOWLEDGE_SUBJECT_TYPE_CODES: frozenset[str] = frozenset(
    AUTHORABLE_LOCATION_CATEGORIES | ORGANIZATION_ENTITY_TYPE_CODES | {"religion", "npc", "quest"}
)


@dataclass(frozen=True)
class KnowledgeFields:
    statement: str
    sensitivity: str


def statement_to_name(statement: str) -> str:
    """The entity name derived from a statement: whitespace collapsed, at most
    200 characters (an ellipsis marks a cut)."""
    collapsed = " ".join(statement.split())
    if len(collapsed) <= NAME_FROM_STATEMENT_MAX_LENGTH:
        return collapsed
    return collapsed[: NAME_FROM_STATEMENT_MAX_LENGTH - 1].rstrip() + "…"


def normalize_knowledge_fields(
    *, statement: str | None, sensitivity: str | None
) -> KnowledgeFields:
    if statement is None or not statement.strip():
        raise AuthoringValidationError("statement is required")
    stripped = statement.strip()
    if len(stripped) > STATEMENT_MAX_LENGTH:
        raise AuthoringValidationError(f"statement exceeds {STATEMENT_MAX_LENGTH} characters")
    if sensitivity not in _SENSITIVITY_CODES:
        raise AuthoringValidationError("sensitivity is not an allowed choice")
    assert sensitivity is not None
    return KnowledgeFields(statement=stripped, sensitivity=sensitivity)
