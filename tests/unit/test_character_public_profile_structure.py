"""Structural guards for the public-profile slice (P03-A A2a, plan section 5.11, criterion 9).

Which `src/` modules may name the new tables, which may name the legacy character description
table, that the profile modules import no sheet, calculation or rules module, and that the new
columns are classified. They read source text and the classification registry; no database.
"""

import ast
import re
from pathlib import Path

from dnd_ai.domain.data_classification import COLUMN_CLASSES, DataClass

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"

PROFILE_TABLES = re.compile(r"character_public_profile(s|_releases)\b")
LEGACY_DESCRIPTIONS = re.compile(r"character_descriptions\b")

# The only modules that may name the draft and release tables: the persistence metadata, the
# classification and entity-reference registries, and the profile's own command, query, API and
# domain modules (the API names the tables only as audit labels).
PROFILE_TABLE_MODULES = {
    "api/character_public_profile.py",
    "commands/character_public_profile.py",
    "commands/entity_lifecycle.py",
    "domain/data_classification.py",
    "domain/public_profiles.py",
    "persistence/tables/__init__.py",
    "persistence/tables/campaign.py",
    "queries/character_public_profile.py",
}
# The only modules that may name the legacy description table. A2a adds none; A2b adds the copy
# command.
LEGACY_DESCRIPTION_MODULES = {
    "commands/entity_lifecycle.py",
    "commands/npcs.py",
    "domain/data_classification.py",
    "persistence/tables/__init__.py",
    "persistence/tables/characters.py",
    "queries/npc_authoring.py",
}
PROFILE_MODULES = (
    "api/character_public_profile.py",
    "commands/character_public_profile.py",
    "domain/public_profiles.py",
    "queries/character_public_profile.py",
)
FORBIDDEN_IMPORT_PARTS = ("character_sheet", "character_calculations", "rules")


def _modules() -> dict[str, str]:
    return {
        path.relative_to(SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in SRC.rglob("*.py")
    }


def test_only_the_profile_modules_name_the_draft_and_release_tables() -> None:
    naming = {name for name, source in _modules().items() if PROFILE_TABLES.search(source)}
    assert naming <= PROFILE_TABLE_MODULES, sorted(naming - PROFILE_TABLE_MODULES)
    # The query module is the only reader of the tables outside the commands that write them.
    assert "queries/character_public_profile.py" in naming
    assert "commands/character_public_profile.py" in naming


def test_the_legacy_description_table_is_named_by_no_new_module() -> None:
    naming = {name for name, source in _modules().items() if LEGACY_DESCRIPTIONS.search(source)}
    assert naming <= LEGACY_DESCRIPTION_MODULES, sorted(naming - LEGACY_DESCRIPTION_MODULES)


def test_the_profile_modules_import_no_sheet_calculation_or_rules_module() -> None:
    offenders: list[tuple[str, str]] = []
    for relative in PROFILE_MODULES:
        tree = ast.parse((SRC / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                parts = re.split(r"[./]", name)
                if any(part in FORBIDDEN_IMPORT_PARTS for part in parts):
                    offenders.append((relative, name))
    assert offenders == []


def test_every_new_text_column_is_classified() -> None:
    draft = {
        "campaign.character_public_profiles.public_appearance": DataClass.GM_ONLY,
        "campaign.character_public_profiles.public_background": DataClass.GM_ONLY,
    }
    release = {
        "campaign.character_public_profile_releases.public_appearance": DataClass.CAMPAIGN_VISIBLE,
        "campaign.character_public_profile_releases.public_background": DataClass.CAMPAIGN_VISIBLE,
        "campaign.character_public_profile_releases.release_note": DataClass.GM_ONLY,
        "campaign.character_public_profile_releases.authority_source_code": DataClass.STRUCTURAL,
    }
    for column, expected in {**draft, **release}.items():
        assert COLUMN_CLASSES[column] is expected, column
    # The origins lookup is not in the (frozen) reporting allowlist, so its columns are classified.
    for column in ("code", "description", "display_name"):
        assert (
            COLUMN_CLASSES[f"campaign.public_profile_field_origins.{column}"]
            is DataClass.STRUCTURAL
        )
