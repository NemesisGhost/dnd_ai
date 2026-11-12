"""Unit and structural guards for the A5a player-profile slice (P03-A, no database).

The field vocabulary against migration 147, the GM branch of the read rule against
`has_effective_character_canon_edit`, the classification of the profile text, and the structure A5
promises: no `src/` writer of the profile tables (decision D18), no GM-private store, rules or sheet
module, no `character.view_player_profile` / `character.edit_player_profile` vocabulary (P03-B), no
preview adapter, and raw test writes confined to the one fixture helper.
"""

import ast
import importlib.util
import itertools
import re
import uuid
from pathlib import Path

import pytest

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.data_classification import COLUMN_CLASSES, DataClass
from dnd_ai.domain.player_profiles import (
    COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS,
    PLAYER_PROFILE_FIELD_LABELS,
    PLAYER_PROFILE_FIELDS,
    PLAYER_PROFILE_TEXT_MAX_LENGTH,
    may_read_player_profile,
    may_read_player_profile_as_gm,
)
from dnd_ai.domain.public_profiles import (
    PUBLIC_PROFILE_TEXT_MAX_LENGTH,
    has_effective_character_canon_edit,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dnd_ai"
MIGRATION = ROOT / "database" / "migrations" / "versions" / "147_character_player_profiles.py"

PROFILE_TABLE = re.compile(r"character_player_profile(s|_versions)\b|player_profile_fields\b")
RAW_WRITE = re.compile(
    r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(\s+TABLE)?)\s+(ONLY\s+)?"
    r"campaign\.character_player_profile(s|_versions)\b",
    re.IGNORECASE,
)
# The only src modules that may name the profile tables: the metadata, the two registries, and the
# read-only query module.
TABLE_MODULES = {
    "commands/entity_lifecycle.py",
    "domain/data_classification.py",
    "persistence/tables/__init__.py",
    "persistence/tables/campaign.py",
    "queries/player_profiles.py",
}
PROFILE_MODULES = (
    "api/player_profiles.py",
    "domain/player_profiles.py",
    "queries/player_profiles.py",
)
FORBIDDEN_NAMES = (
    "character_descriptions",
    "npc_portrayal_profiles",
    "entity_types",
    "entity_revisions",
    "capture_revision",
    "character_sheet",
    "character_calculations",
)
# Raw writes of the profile tables under tests/ are confined to the fixture writer and to the files
# that probe the schema's own refusals or clean up after the Gate.
RAW_WRITE_TEST_FILES = {
    "tests/player_profile_support.py",
    "tests/database/test_character_player_profiles_schema.py",
    "tests/database/test_character_player_profiles_migration.py",
}


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("migration_147", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _without_docstrings(source: str) -> str:
    """The module's code and string literals with every docstring removed, so a guard sees what the
    module does and not what its documentation says it does not do."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _modules() -> dict[str, str]:
    return {
        path.relative_to(SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in SRC.rglob("*.py")
    }


# --- the vocabulary ---------------------------------------------------------------------------


def test_the_field_constants_match_migration_147_exactly() -> None:
    fields = _load_migration()._FIELDS  # type: ignore[attr-defined]
    assert tuple(code for code, *_ in fields) == PLAYER_PROFILE_FIELDS
    assert {code: label for code, label, *_ in fields} == PLAYER_PROFILE_FIELD_LABELS
    assert tuple(code for code, _l, _d, eligible in fields if eligible) == (
        COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS
    )
    assert _load_migration()._TEXT_MAX == PLAYER_PROFILE_TEXT_MAX_LENGTH  # type: ignore[attr-defined]


def test_the_eleven_d13_fields_in_order_with_the_two_exclusions() -> None:
    assert PLAYER_PROFILE_FIELDS == (
        "portrayal_guidance",
        "personality",
        "ideals",
        "bonds",
        "flaws",
        "goals",
        "fears",
        "loyalties",
        "boundaries",
        "speech_patterns",
        "profile_notes",
    )
    assert set(PLAYER_PROFILE_FIELDS) - set(COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS) == {
        "boundaries",
        "profile_notes",
    }
    assert PLAYER_PROFILE_FIELD_LABELS["profile_notes"] == "Notes for the GM and controllers"
    assert "player_notes" not in PLAYER_PROFILE_FIELDS
    assert PLAYER_PROFILE_TEXT_MAX_LENGTH == PUBLIC_PROFILE_TEXT_MAX_LENGTH == 4000


# --- the read rule ----------------------------------------------------------------------------


def _access(
    character: uuid.UUID,
    *,
    roles: frozenset[str],
    whole_deny: bool,
    edit_deny: bool,
    edit_allow_grant: bool,
    other_character_deny: bool,
) -> AccessContext:
    effects: dict[tuple[str, uuid.UUID], dict[str, str]] = {}
    if whole_deny:
        effects.setdefault(("entity_id", character), {})["campaign.view"] = "deny"
    if edit_deny:
        effects.setdefault(("entity_id", character), {})["canon.edit"] = "deny"
    if edit_allow_grant:
        effects.setdefault(("entity_id", character), {}).setdefault("canon.edit", "allow")
    if other_character_deny:
        effects[("entity_id", uuid.uuid4())] = {"canon.edit": "deny", "campaign.view": "deny"}
    return AccessContext(
        user_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        campaign_membership_id=uuid.uuid4(),
        timeline_id=uuid.uuid4(),
        role_capabilities=roles,
        character_capabilities={},
        grant_effects=effects,
    )


_ROLE_SETS = (
    frozenset(),
    frozenset({"campaign.view"}),
    frozenset({"campaign.view", "canon.edit"}),
    frozenset({"canon.edit"}),
    frozenset({"campaign.view", "character.reveal"}),
    frozenset({"campaign.view", "access.manage", "character.view_summary"}),
)


@pytest.mark.parametrize(
    ("roles", "whole_deny", "edit_deny", "edit_allow_grant", "other_character_deny"),
    list(itertools.product(_ROLE_SETS, (False, True), (False, True), (False, True), (False, True))),
)
def test_the_gm_branch_is_exactly_effective_character_scoped_canon_edit(
    roles: frozenset[str],
    whole_deny: bool,
    edit_deny: bool,
    edit_allow_grant: bool,
    other_character_deny: bool,
) -> None:
    character = uuid.uuid4()
    access = _access(
        character,
        roles=roles,
        whole_deny=whole_deny,
        edit_deny=edit_deny,
        edit_allow_grant=edit_allow_grant,
        other_character_deny=other_character_deny,
    )
    expected = has_effective_character_canon_edit(access, character)
    assert may_read_player_profile_as_gm(access, character) is expected
    # A5's only branch is the GM branch.
    assert may_read_player_profile(access, character) is expected
    # Independently: the role canon.edit (with campaign.view, the base of any character-scoped
    # check) and neither deny. An allow grant, reveal authority or another capability add nothing.
    assert expected == (
        {"canon.edit", "campaign.view"} <= roles and not whole_deny and not edit_deny
    )


def test_reveal_authority_and_an_allow_grant_alone_confer_no_read() -> None:
    character = uuid.uuid4()
    revealer = _access(
        character,
        roles=frozenset({"campaign.view", "character.reveal"}),
        whole_deny=False,
        edit_deny=False,
        edit_allow_grant=True,
        other_character_deny=False,
    )
    assert may_read_player_profile(revealer, character) is False


def test_the_edit_rule_implies_the_read_rule() -> None:
    """Whoever may edit a public-profile draft (the D8 rule) also passes the GM read."""
    character = uuid.uuid4()
    for roles, whole, edit in itertools.product(_ROLE_SETS, (False, True), (False, True)):
        access = _access(
            character,
            roles=roles,
            whole_deny=whole,
            edit_deny=edit,
            edit_allow_grant=False,
            other_character_deny=False,
        )
        if has_effective_character_canon_edit(access, character):
            assert may_read_player_profile(access, character)


def test_the_read_rule_never_consults_kind_labels_or_the_controller_vocabulary() -> None:
    tree = ast.parse((SRC / "domain" / "player_profiles.py").read_text(encoding="utf-8"))
    identifiers: set[str] = set()
    for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for statement in function.body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Name):
                    identifiers.add(node.id)
                elif isinstance(node, ast.Attribute):
                    identifiers.add(node.attr)
    assert identifiers == {
        "access",
        "character_id",
        "has_effective_character_canon_edit",
        "may_read_player_profile_as_gm",
    }


# --- classification ---------------------------------------------------------------------------


def test_every_profile_text_column_is_character_visible_and_the_lookup_is_structural() -> None:
    for code in PLAYER_PROFILE_FIELDS:
        key = f"campaign.character_player_profile_versions.{code}"
        assert COLUMN_CLASSES[key] is DataClass.CHARACTER_VISIBLE, key
    for column in ("code", "description", "display_name"):
        assert COLUMN_CLASSES[f"campaign.player_profile_fields.{column}"] is DataClass.STRUCTURAL
    # PLAYER_PRIVATE stays reserved and unused (ADR 0016 is unchanged).
    assert not [k for k, v in COLUMN_CLASSES.items() if v is DataClass.PLAYER_PRIVATE]


# --- structure: no writer, no private store, no controller vocabulary --------------------------------


def test_only_the_read_query_the_metadata_and_the_registries_name_the_profile_tables() -> None:
    naming = {name for name, source in _modules().items() if PROFILE_TABLE.search(source)}
    assert naming == TABLE_MODULES, sorted(naming ^ TABLE_MODULES)


def test_nothing_in_src_writes_the_profile_tables() -> None:
    offenders = [name for name, source in _modules().items() if RAW_WRITE.search(source)]
    assert offenders == []
    # No Core insert/update/delete/truncate against the table objects either.
    core_write = re.compile(
        r"(insert|update|delete)\(\s*(tables\.)?(character_player_profiles|"
        r"character_player_profile_versions|player_profile_fields)\b"
    )
    assert [n for n, s in _modules().items() if core_write.search(s)] == []


def test_the_profile_modules_reference_no_private_store_rules_sheet_or_revision_machinery() -> None:
    for relative in PROFILE_MODULES:
        source = _without_docstrings((SRC / relative).read_text(encoding="utf-8"))
        for name in FORBIDDEN_NAMES:
            assert name not in source, (relative, name)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                assert not any(
                    part in ("rules", "commands", "character_sheet")
                    for part in re.split(r"[./]", name)
                ), (relative, name)


def test_no_controller_capability_vocabulary_exists_in_the_application_or_the_seeds() -> None:
    needle = re.compile(r"""["']character\.(view|edit)_player_profile["']""")
    offenders = [name for name, source in _modules().items() if needle.search(source)]
    assert offenders == []
    for seed in (ROOT / "database" / "seeds").rglob("*"):
        if seed.is_file():
            assert not needle.search(seed.read_text(encoding="utf-8", errors="ignore")), seed
    assert not needle.search(MIGRATION.read_text(encoding="utf-8"))


def test_the_player_profile_routes_are_get_only_and_filtered_by_campaign_view() -> None:
    from dnd_ai.api.app import create_app
    from tests.unit.test_world_gate_registry import _iter_api_routes

    routes = [
        (route.path, sorted(route.methods or ()))
        for route in _iter_api_routes(create_app().routes)
        if "/player-profile" in route.path
    ]
    assert sorted(routes) == [
        ("/campaigns/{campaign_id}/characters/{character_id}/player-profile", ["GET"]),
        (
            "/campaigns/{campaign_id}/characters/{character_id}/player-profile/versions/"
            "{profile_row_version}",
            ["GET"],
        ),
    ]
    api_source = _without_docstrings((SRC / "api" / "player_profiles.py").read_text("utf-8"))
    assert "require_campaign_capability('campaign.view')" in api_source
    assert "canon.edit" not in api_source
    for forbidden in ("idempotency", "record_change_log", "router.post", "router.put"):
        assert forbidden not in api_source


def test_no_preview_adapter_admits_a_profile_table_or_column() -> None:
    from dnd_ai.api.preview import PREVIEW_ADAPTERS

    for adapter in PREVIEW_ADAPTERS.values():
        assert adapter.table_name not in (
            "character_player_profiles",
            "character_player_profile_versions",
            "player_profile_fields",
        )
    preview_source = (SRC / "api" / "preview.py").read_text(encoding="utf-8")
    assert not PROFILE_TABLE.search(preview_source)


def test_released_profile_sql_and_the_audience_tier_do_not_read_the_profile() -> None:
    from dnd_ai.queries import character_public_profile as module

    assert not PROFILE_TABLE.search(module._RELEASED_PROFILE_SQL)
    for relative in (
        "queries/character_public_profile.py",
        "queries/public_profile_restrictions.py",
        "queries/world_explorer.py",
        "api/character_public_profile.py",
    ):
        assert not PROFILE_TABLE.search((SRC / relative).read_text(encoding="utf-8")), relative


def test_raw_writes_of_the_profile_tables_under_tests_are_confined() -> None:
    tests_root = ROOT / "tests"
    this_file = Path(__file__).resolve()
    offenders = []
    for path in tests_root.rglob("*.py"):
        if path.resolve() == this_file:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in RAW_WRITE_TEST_FILES:
            continue
        source = path.read_text(encoding="utf-8")
        # A write through a constant such as f"INSERT INTO {HEAD}" is in the allowed files only.
        if RAW_WRITE.search(source):
            offenders.append(relative)
    assert offenders == []
    support = (ROOT / "tests" / "player_profile_support.py").read_text(encoding="utf-8")
    assert "INSERT INTO" in support
