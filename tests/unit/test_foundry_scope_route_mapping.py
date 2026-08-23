"""Explicit route-to-Foundry-scope completeness tripwire (Workstream 11R
High-severity finding 1, requirement 10: "Add an explicit route-to-scope
mapping in code or tests so future Foundry-enabled routes cannot omit
scope review silently").

`dnd_ai.api.access.require_campaign_capability` already fails at call
time (an application-startup-time `ValueError`, not a per-request one) if
a route sets `allow_foundry_access=True` without also declaring a
`foundry_scope` — see that function's own docstring. That guarantees a
scope was *declared*, but says nothing about whether the *chosen* scope
was actually reviewed by a human against the closed vocabulary's intended
meaning. This test is that second, independent guardrail: it walks the
real application's registered routes, collects every one gated by
`allow_foundry_access=True` together with its declared `foundry_scope`,
and asserts the result matches this file's own hand-maintained table
exactly — both directions. A new Foundry-enabled route that isn't added
here fails this test even though the application itself would still
start; a route removed from the application without updating this table
fails identically. No database needed — inspects `create_app()`'s route
tree directly, purely in-process.
"""

from collections.abc import Iterator

import pytest
from fastapi.routing import APIRoute, APIRouter

from dnd_ai.api.app import create_app
from dnd_ai.domain.foundry_pairing import FOUNDRY_SCOPES

pytestmark = pytest.mark.unit

# (HTTP method, path template) -> required Foundry scope. Every route in
# this table is expected to be gated by allow_foundry_access=True; every
# route gated by allow_foundry_access=True is expected to be in this
# table. Keep sorted by module, then declaration order, to match the
# source files this mirrors.
EXPECTED_FOUNDRY_SCOPE_ROUTES: dict[tuple[str, str], str] = {
    # dnd_ai.api.characters
    ("GET", "/campaigns/{campaign_id}/characters/{character_id}"): "encounter_read",
    # dnd_ai.api.character_state
    ("POST", "/campaigns/{campaign_id}/characters/{character_id}/hit-points"): (
        "character_state_sync"
    ),
    ("POST", "/campaigns/{campaign_id}/characters/{character_id}/conditions"): (
        "character_state_sync"
    ),
    (
        "POST",
        "/campaigns/{campaign_id}/characters/{character_id}/conditions/{condition_id}/remove",
    ): "character_state_sync",
    ("POST", "/campaigns/{campaign_id}/characters/{character_id}/resources"): (
        "character_state_sync"
    ),
    # dnd_ai.api.integration
    (
        "POST",
        "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/identifiers",
    ): "combat_sync",
    ("POST", "/campaigns/{campaign_id}/integration/foundry/combat-sync"): "combat_sync",
    (
        "GET",
        "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/sync-state",
    ): "sync_status_read",
}


def _iter_api_routes(routes: list[object]) -> Iterator[APIRoute]:
    """Recurses through `create_app().routes`, unwrapping both a plain
    `APIRouter`'s own `.routes` and the lazy `_IncludedRouter` wrapper
    Starlette's deferred-route-mounting uses (`.original_router.routes`)
    — neither is a public, stable API to import a type from, so this
    duck-types via `hasattr` rather than isinstance-checking either."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _iter_api_routes(route.original_router.routes)
        elif isinstance(route, APIRouter):
            yield from _iter_api_routes(route.routes)


def _discover_foundry_scope_routes() -> dict[tuple[str, str], str]:
    """Walks the real application and returns every route gated by
    `allow_foundry_access=True`, mapped to its declared `foundry_scope` —
    read directly off the `require_campaign_capability`-produced
    dependency closure's own `allow_foundry_access`/`foundry_scope`
    attributes (set for exactly this purpose)."""
    app = create_app()
    discovered: dict[tuple[str, str], str] = {}
    for route in _iter_api_routes(app.routes):
        for dependency in route.dependant.dependencies:
            call = dependency.call
            if call is None or not getattr(call, "allow_foundry_access", False):
                continue
            scope = call.foundry_scope
            assert isinstance(scope, str)
            for method in sorted(route.methods or ()):
                if method in ("HEAD", "OPTIONS"):
                    continue
                discovered[(method, route.path)] = scope
    return discovered


def test_every_foundry_scope_gated_route_matches_the_hand_maintained_table() -> None:
    assert _discover_foundry_scope_routes() == EXPECTED_FOUNDRY_SCOPE_ROUTES


def test_every_entry_in_the_table_names_a_scope_from_the_closed_vocabulary() -> None:
    for scope in EXPECTED_FOUNDRY_SCOPE_ROUTES.values():
        assert scope in FOUNDRY_SCOPES
