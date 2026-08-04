"""A character's languages must come from a ruleset its own world allows
(revision 037).

Split from test_phase4_remaining_issues.py (DEVELOPMENT.md §2.1).
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    current_ruleset_version_id,
    make_character,
    make_ruleset_for_world,
    make_ruleset_version,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class CharacterLanguageFixture:
    """A world with one allowed (non-default) ruleset and a character, plus a
    second allowed ruleset/language (positive: multiple allowed families) and
    a third ruleset/language never added to the world's allow-list
    (negative: disallowed family)."""

    def __init__(self, connection: Connection, slug: str) -> None:
        base = slug.replace("-", "_")
        self.world_id = make_world(connection, slug=slug)
        self.character_id = make_character(connection, self.world_id)

        self.ruleset_id = make_ruleset_for_world(
            connection, self.world_id, code=f"lang_{base}", is_default=False
        )
        self.version_id = current_ruleset_version_id(connection, self.ruleset_id)
        self.language_id = self._make_language(connection, self.version_id, "common")

        self.other_allowed_ruleset_id = make_ruleset_for_world(
            connection, self.world_id, code=f"lang_other_{base}", is_default=False
        )
        self.other_allowed_version_id = current_ruleset_version_id(
            connection, self.other_allowed_ruleset_id
        )
        self.other_allowed_language_id = self._make_language(
            connection, self.other_allowed_version_id, "elvish"
        )

        self.disallowed_version_id = make_ruleset_version(
            connection, code=f"lang_disallowed_{base}"
        )
        self.disallowed_language_id = self._make_language(
            connection, self.disallowed_version_id, "draconic"
        )

    @staticmethod
    def _make_language(connection: Connection, version_id: uuid.UUID, code: str) -> uuid.UUID:
        return connection.execute(
            text(
                "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
                "VALUES (:v, :c, :c) RETURNING language_id"
            ),
            {"v": version_id, "c": code},
        ).scalar()


@pytest.fixture
def clf(db_connection: Connection) -> CharacterLanguageFixture:
    return CharacterLanguageFixture(db_connection, f"lang-{uuid.uuid4().hex[:6]}")


def test_a_character_can_know_a_language_from_its_worlds_allowed_ruleset(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO character.character_languages (character_id, language_id) VALUES (:c, :l)"
        ),
        {"c": clf.character_id, "l": clf.language_id},
    )


def test_a_character_can_know_languages_from_multiple_allowed_ruleset_families(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    for language_id in (clf.language_id, clf.other_allowed_language_id):
        db_connection.execute(
            text(
                "INSERT INTO character.character_languages (character_id, language_id) "
                "VALUES (:c, :l)"
            ),
            {"c": clf.character_id, "l": language_id},
        )
    count = db_connection.execute(
        text("SELECT count(*) FROM character.character_languages WHERE character_id = :c"),
        {"c": clf.character_id},
    ).scalar()
    assert count == 2


def test_a_language_from_a_disallowed_ruleset_family_is_rejected_on_insert(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_languages (character_id, language_id) "
                "VALUES (:c, :l)"
            ),
            {"c": clf.character_id, "l": clf.disallowed_language_id},
        )
    assert "ruleset is not allowed" in str(exc.value)


def test_updating_a_character_language_to_a_disallowed_ruleset_family_is_rejected(
    db_connection: Connection, clf: CharacterLanguageFixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO character.character_languages (character_id, language_id) VALUES (:c, :l)"
        ),
        {"c": clf.character_id, "l": clf.language_id},
    )

    # SAVEPOINT (begin_nested): the failed UPDATE aborts the outer
    # transaction in PostgreSQL, which would poison the follow-up SELECT
    # below unless the failure is scoped to a sub-transaction.
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text(
                "UPDATE character.character_languages SET language_id = :new "
                "WHERE character_id = :c AND language_id = :old"
            ),
            {"new": clf.disallowed_language_id, "c": clf.character_id, "old": clf.language_id},
        )
    assert "ruleset is not allowed" in str(exc.value)

    unchanged = db_connection.execute(
        text(
            "SELECT count(*) FROM character.character_languages "
            "WHERE character_id = :c AND language_id = :l"
        ),
        {"c": clf.character_id, "l": clf.language_id},
    ).scalar()
    assert unchanged == 1, "the failed UPDATE must not have partially applied"
