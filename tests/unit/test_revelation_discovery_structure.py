"""Structural guards for revelation-derived discovery (P03-A A3b, plan sections 10.6, 10.7, 10.13).

Which `src/` modules may name the revelation tables, that every discovery consumer reads the one
resolver query rather than the tables, and that the party roster exception (decision D4-C) has one
caller and feeds nothing back. They read source text; no database.
"""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"

REVELATION_TABLES = re.compile(r"security\.character_revelation(s|_members)\b")

# The modules that may name the tables: the persistence metadata, the revelation command, query
# and route modules, the two lifecycle hooks that close revelations (membership end, group
# deactivation), and the single resolver query in `domain/access.py`. Every other reader of
# revelation-derived access -- the discovery bundle, the explanation, the overview, search and the
# roster -- reaches them only through `AccessContext.revelations`
# or the resolver's exported SQL.
REVELATION_TABLE_MODULES = {
    "commands/access_groups.py",
    "commands/character_revelations.py",
    "commands/memberships.py",
    "domain/access.py",
    "persistence/tables/__init__.py",
    "persistence/tables/security.py",
    "queries/character_revelations.py",
}

DISCOVERY_CONSUMERS = (
    "api/access_overview.py",
    "api/parties.py",
    "api/world_explorer.py",
    "queries/access_overview.py",
    "queries/effective_access.py",
    "queries/world_explorer.py",
)


def _modules() -> dict[str, str]:
    return {
        path.relative_to(SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in SRC.rglob("*.py")
    }


def test_only_the_revelation_modules_and_the_resolver_name_the_revelation_tables() -> None:
    naming = {name for name, source in _modules().items() if REVELATION_TABLES.search(source)}
    assert naming <= REVELATION_TABLE_MODULES, sorted(naming - REVELATION_TABLE_MODULES)
    assert "domain/access.py" in naming  # the resolver's one definition of "live revelation"


def test_discovery_consumers_never_read_the_revelation_tables_themselves() -> None:
    modules = _modules()
    for name in DISCOVERY_CONSUMERS:
        assert not REVELATION_TABLES.search(modules[name]), name


def test_the_explanation_and_the_overview_reuse_the_resolvers_query() -> None:
    modules = _modules()
    for name in ("queries/effective_access.py", "queries/access_overview.py"):
        assert "LIVE_REVELATIONS_FOR_MEMBERSHIP_SQL" in modules[name], name


def test_the_party_roster_exception_has_exactly_one_caller() -> None:
    callers: list[str] = []
    for name, source in _modules().items():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "party_roster_controller_qualifies"
            ):
                function = _enclosing_function(tree, node)
                callers.append(f"{name}:{function}")
    assert callers == ["api/parties.py:get_party_roster_endpoint"]


def _enclosing_function(tree: ast.AST, target: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(child is target for child in ast.walk(node)):
            return node.name
    return None


def test_the_roster_exception_feeds_nothing_back_into_the_discovery_policy() -> None:
    modules = _modules()
    for name in ("domain/access.py", "api/world_explorer.py", "queries/world_explorer.py"):
        assert "party_roster_controller_qualifies" not in modules[name], name
    # The qualifying function confers no capability and writes nothing.
    source = modules["api/parties.py"]
    start = source.index("def party_roster_controller_qualifies")
    end = source.index('@router.get(_BASE + "/{party_id}/roster")')
    body = source[start:end]
    for forbidden in ("INSERT", "UPDATE", "DELETE", "AccessContext(", "replace("):
        assert forbidden not in body, forbidden


def test_a_revelation_confers_only_discovery_and_the_released_profile() -> None:
    from dnd_ai.domain.access import REVELATION_CONFERRED_CAPABILITIES

    assert (
        frozenset({"character.discover", "character.view_public_profile"})
        == REVELATION_CONFERRED_CAPABILITIES
    )
