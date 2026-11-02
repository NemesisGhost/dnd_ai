"""Audit and receipt builders and the classification contract (checkpoint 15.2A-3)."""

import importlib.util
import uuid
from pathlib import Path

import pytest

from dnd_ai.domain.data_classification import (
    AUDIT_STRUCTURAL_FIELDS,
    COLUMN_CLASSES,
    REFERENCE_DATA_TABLES,
    DataClass,
    audit_change,
    audit_diff,
    audit_initial,
    content_receipt,
)

pytestmark = pytest.mark.unit

_MIGRATION_115 = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "115_reporting_role_boundary.py"
)


def test_structural_values_are_kept_and_content_is_redacted() -> None:
    assert audit_change("name", "Old", "New") == {"from": "Old", "to": "New"}
    assert audit_change("population", None, 12) == {"from": None, "to": 12}
    assert audit_change("summary", "a", "b") == {
        "from": {"redacted": True},
        "to": {"redacted": True},
    }
    assert audit_change("summary", None, "b") == {"from": None, "to": {"redacted": True}}


def test_an_unknown_field_is_redacted_by_default() -> None:
    assert audit_change("anything_new", None, "secret") == {
        "from": None,
        "to": {"redacted": True},
    }
    assert "secret" not in str(audit_initial({"anything_new": "secret"}))


def test_no_prose_field_name_is_in_the_structural_allowlist() -> None:
    prose = {
        "summary",
        "description",
        "notes",
        "background",
        "appearance",
        "statement",
        "internal_description",
        "public_description",
        "pantheon_structure",
        "building_use",
        "change_note",
        "reason",
    }
    assert not prose & AUDIT_STRUCTURAL_FIELDS


def test_long_structural_values_are_truncated() -> None:
    shown = audit_change("name", "", "n" * 500)["to"]
    assert shown == {"value": "n" * 200, "truncated": True}


def test_audit_diff_lists_only_changed_fields() -> None:
    assert audit_diff({"name": "A", "summary": "x"}, {"name": "A", "summary": "y"}) == {
        "summary": {"from": {"redacted": True}, "to": {"redacted": True}}
    }
    assert audit_diff({}, {"summary": None}) == {}


def test_receipts_hold_only_ids_version_and_flags() -> None:
    entity = uuid.uuid4()
    child = uuid.uuid4()
    assert content_receipt(
        id_field="npc_id", entity_id=entity, row_version=3, created=False, changed=True
    ) == {"npc_id": str(entity), "row_version": 3, "created": False, "changed": True}
    with_child = content_receipt(
        id_field="quest_id",
        entity_id=entity,
        row_version=4,
        created=False,
        changed=True,
        record_id=child,
    )
    assert with_child["record_id"] == str(child)
    same = content_receipt(
        id_field="quest_id",
        entity_id=entity,
        row_version=4,
        created=True,
        changed=True,
        record_id=entity,
    )
    assert "record_id" not in same


def test_player_private_is_reserved_and_unused() -> None:
    assert DataClass.PLAYER_PRIVATE not in set(COLUMN_CLASSES.values())
    assert DataClass.SECRET not in set(COLUMN_CLASSES.values())


def test_the_reference_table_list_agrees_with_the_reporting_allowlist() -> None:
    spec = importlib.util.spec_from_file_location("reporting_migration", _MIGRATION_115)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scanned = ("core.", "world.", "character.", "narrative.", "knowledge.", "campaign.")
    scanned += ("interaction.", "rules.", "ai.", "audit.")
    allowlisted = {t for t in module.REPORTING_READABLE_TABLES if t.startswith(scanned)}
    assert REFERENCE_DATA_TABLES - {"core.alembic_version"} == allowlisted
