"""Rule-content provenance and canon status (revision 025).

Split from test_phase4_corrections.py (DEVELOPMENT.md §2.1): the
source_id/canon_status_id provenance columns added to every rule-content
table, tracked separately from the other rule-content correction topics.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_ruleset_version_for_world,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def test_ruleset_content_defaults_to_canon(db_connection: Connection) -> None:
    version = make_ruleset_version_for_world(
        db_connection, make_world(db_connection, slug="canon-default-world")
    )
    ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name) "
            "VALUES (:v, 'strength', 'Strength') RETURNING canon_status_id"
        ),
        {"v": version},
    ).scalar()

    code = db_connection.execute(
        text("SELECT code FROM core.canon_statuses WHERE canon_status_id = :c"), {"c": ability}
    ).scalar()
    assert code == "canon"


def test_ruleset_content_canon_status_can_be_overridden(db_connection: Connection) -> None:
    version = make_ruleset_version_for_world(
        db_connection, make_world(db_connection, slug="canon-override-world")
    )
    draft_status = db_connection.execute(
        text("SELECT canon_status_id FROM core.canon_statuses WHERE code = 'draft'")
    ).scalar()

    ability = db_connection.execute(
        text(
            "INSERT INTO rules.abilities (ruleset_version_id, code, display_name, canon_status_id) "
            "VALUES (:v, 'strength', 'Strength', :status) RETURNING canon_status_id"
        ),
        {"v": version, "status": draft_status},
    ).scalar()
    assert ability == draft_status


def test_rulesets_itself_has_both_provenance_columns(db_connection: Connection) -> None:
    """The comment on rules.rulesets has always claimed both source and canon
    status — revision 025 makes that true rather than aspirational."""
    columns = {
        r[0]
        for r in db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'rules' AND table_name = 'rulesets'"
            )
        )
    }
    assert {"source_id", "canon_status_id"} <= columns


@pytest.mark.parametrize(
    "table",
    [
        "ruleset_versions",
        "abilities",
        "species",
        "damage_types",
        "conditions",
        "creature_types",
        "languages",
        "proficiency_types",
        "resource_definitions",
        "skills",
        "classes",
        "subclasses",
        "features",
        "feats",
        "spells",
    ],
)
def test_every_rule_content_table_has_provenance_columns(
    db_connection: Connection, table: str
) -> None:
    columns = {
        r[0]
        for r in db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'rules' AND table_name = :t"
            ),
            {"t": table},
        )
    }
    assert {"source_id", "canon_status_id"} <= columns
