"""Structural pins for the public-profile tier (P03-A A4b, plan sections 12.3, 12.4 and 12.9 item 16).

The public tier is served by a read that names only the releases table, an explicit allowlisted DTO
with a pinned key set, and a route branch that never reaches the sheet, calculations, inventory or the
encounter readers. The link producers share one test, and `resolve_character_view_tier` is untouched."""

import ast
import re
from pathlib import Path

from dnd_ai.api.characters import (
    CharacterIdentityValueResponse,
    CharacterPublicProfileResponse,
    CharacterResponse,
    CharacterSectionsResponse,
    PublicCharacterResponse,
)
from dnd_ai.queries import character_public_profile as profile_queries

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"


def _function(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((SRC / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def test_the_public_projection_names_only_the_releases_table() -> None:
    sql = profile_queries._RELEASED_PROFILE_SQL
    tables = set(re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", sql, flags=re.IGNORECASE))
    assert tables == {"campaign.character_public_profile_releases"}
    for forbidden in (
        "rules.",
        "character.characters",
        "character_descriptions",
        "character_public_profiles",
        "core.entities",
        "summary_text",
    ):
        assert forbidden not in sql, forbidden
    assert "e.summary" not in sql and "released_species_id" not in sql  # the id never leaves


def test_the_public_read_never_calls_the_character_sheet_or_mechanical_readers() -> None:
    function = _function("queries/character_public_profile.py", "read_public_character")
    body = (
        function.body[1:] if isinstance(function.body[0], ast.Expr) else function.body
    )  # no docstring
    names: set[str] = set()
    strings: list[str] = []
    for statement in body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value)
    assert {"read_released_profile", "character_kind"} <= names
    for forbidden in ("get_character_view", "get_character_sheet_view", "get_inventory_view"):
        assert forbidden not in names, forbidden
    sql = " ".join(strings)
    for forbidden in ("rules.", "character.characters", "character_descriptions", "species_id"):
        assert forbidden not in sql, forbidden
    assert "e.summary" not in sql


def test_the_dto_key_sets_are_pinned_allowlists_and_none_subclasses_another() -> None:
    assert set(PublicCharacterResponse.model_fields) == {
        "view_tier", "character_id", "name", "character_kind", "sections", "public_profile",
    }  # fmt: skip
    assert set(CharacterPublicProfileResponse.model_fields) == {
        "summary", "appearance", "background", "species", "size",
    }  # fmt: skip
    assert set(CharacterIdentityValueResponse.model_fields) == {"code", "label"}
    assert set(CharacterSectionsResponse.model_fields) == {
        "details", "sheet", "relationships", "inventory", "parties", "public_profile",
    }  # fmt: skip
    assert {"view_tier", "public_profile"} <= set(CharacterResponse.model_fields)
    for model in (PublicCharacterResponse, CharacterPublicProfileResponse, CharacterResponse):
        assert model.__mro__[1].__name__ == "BaseModel", model.__name__
    # Nothing from the definition, the mechanics or the release's metadata is an allowlisted field.
    forbidden = {
        "authoring", "canon_status", "lifecycle_status", "species_code", "size_category",
        "current_hit_points", "active_encounter_id", "current_location_id", "conditions",
        "resources", "release_note", "version_number", "released_at", "species_id",
        "identity_entity_row_version", "from_draft_row_version",
    }  # fmt: skip
    assert not forbidden & set(PublicCharacterResponse.model_fields)
    assert not forbidden & set(CharacterPublicProfileResponse.model_fields)


def test_the_detail_route_branch_for_the_public_tier_reaches_no_mechanical_reader() -> None:
    route = _function("api/characters.py", "get_character_endpoint")
    branch = next(
        node
        for node in route.body
        if isinstance(node, ast.If) and "public_profile" in ast.dump(node.test)
    )
    called = {
        n.func.id
        for n in ast.walk(branch)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "read_public_character" in called
    for forbidden in (
        "get_character_view",
        "get_character_sheet_view",
        "get_inventory_view",
        "EncounterAudience",
        "record_authoring_response",
        "get_entity_status_summary",
        "resolve_world_entity_visibility",
    ):
        assert forbidden not in called, forbidden


def test_the_link_producers_use_can_open_character_and_the_session_helper_is_gone() -> None:
    access = (SRC / "api" / "access.py").read_text(encoding="utf-8")
    participant = ast.get_source_segment(access, _function("api/access.py", "can_open_participant"))
    assert participant is not None and "can_open_character(" in participant
    assert "resolve_character_view_tier" not in participant
    sessions = (SRC / "api" / "sessions.py").read_text(encoding="utf-8")
    assert "_can_open_character" not in sessions
    assert "can_open_character(access, p.character_id)" in sessions


def test_resolve_character_view_tier_is_unchanged() -> None:
    """Its three checks, in order, and the fixed refusal: every caller that gates mechanics on it
    (the sheet, builds, inventory's full tier, relationships, `may_read_build`) keeps its meaning."""
    function = _function("api/access.py", "resolve_character_view_tier")
    checked = [
        (ast.literal_eval(call.args[0]), call.keywords[0].arg)
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "has_capability"
    ]
    assert checked == [
        ("canon.edit", "character_id"),
        ("character.view_full", "character_id"),
        ("character.view_summary", "character_id"),
    ]
    returns = [
        n.value.value
        for n in ast.walk(function)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
    ]
    assert returns == [True, True, False]
    raised = [n for n in ast.walk(function) if isinstance(n, ast.Raise)]
    assert len(raised) == 1
    assert "public" not in ast.dump(function).lower()
    assert [a.arg for a in function.args.kwonlyargs] == ["character_id"]


def test_the_pure_policy_functions_take_no_database_access() -> None:
    for path, names in (
        ("domain/public_profiles.py", ("view_public_profile_denied", "may_read_released_profile")),
        ("api/access.py", ("resolve_character_detail_tier", "can_open_character")),
    ):
        for name in names:
            arguments = [a.arg for a in _function(path, name).args.args]
            assert "connection" not in arguments, name
