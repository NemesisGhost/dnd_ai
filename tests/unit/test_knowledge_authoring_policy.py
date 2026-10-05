"""Pure contract for Knowledge-item definition authoring (Phase 15.1)."""

import pytest

from dnd_ai.domain.authoring import AuthoringValidationError
from dnd_ai.domain.knowledge_authoring import (
    KNOWLEDGE_SUBJECT_TYPE_CODES,
    NAME_FROM_STATEMENT_MAX_LENGTH,
    SENSITIVITIES,
    STATEMENT_MAX_LENGTH,
    normalize_knowledge_fields,
    statement_to_name,
)


def test_the_statement_is_trimmed_and_required() -> None:
    fields = normalize_knowledge_fields(statement="  The duke lies.  ", sensitivity="secret")
    assert fields.statement == "The duke lies."
    for bad in (None, "", "   "):
        with pytest.raises(AuthoringValidationError):
            normalize_knowledge_fields(statement=bad, sensitivity="secret")


def test_the_statement_has_a_bound() -> None:
    normalize_knowledge_fields(statement="x" * STATEMENT_MAX_LENGTH, sensitivity="public")
    with pytest.raises(AuthoringValidationError):
        normalize_knowledge_fields(statement="x" * (STATEMENT_MAX_LENGTH + 1), sensitivity="public")


@pytest.mark.parametrize("sensitivity", [None, "", "Secret", "top-secret"])
def test_sensitivity_is_a_closed_set(sensitivity: str | None) -> None:
    with pytest.raises(AuthoringValidationError):
        normalize_knowledge_fields(statement="A claim.", sensitivity=sensitivity)


def test_every_listed_sensitivity_is_accepted() -> None:
    for code, _label in SENSITIVITIES:
        assert (
            normalize_knowledge_fields(statement="A claim.", sensitivity=code).sensitivity == code
        )


def test_the_derived_name_collapses_whitespace_and_marks_a_cut() -> None:
    assert statement_to_name("  The   duke\n is   a vampire. ") == "The duke is a vampire."
    long = statement_to_name("word " * 200)
    assert len(long) == NAME_FROM_STATEMENT_MAX_LENGTH and long.endswith("…")
    assert statement_to_name("x" * NAME_FROM_STATEMENT_MAX_LENGTH) == "x" * 200


def test_a_claim_is_never_its_own_subject_type() -> None:
    assert "knowledge_item" not in KNOWLEDGE_SUBJECT_TYPE_CODES
    assert {"npc", "quest", "religion"} <= KNOWLEDGE_SUBJECT_TYPE_CODES
    assert "player_character" not in KNOWLEDGE_SUBJECT_TYPE_CODES
