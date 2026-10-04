"""Route registry for the archived-campaign gate (Phase 14, D10).

`require_campaign_capability` refuses an `archived`/`deleted` campaign unless a
route opts in with `allow_archived_campaign=True`. This pins the *exact* set of
opt-ins, and that every campaign-scoped route actually goes through that
dependency, so a new route cannot silently bypass the gate.
"""

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute

from dnd_ai.api.app import create_app

pytestmark = pytest.mark.unit

EXPECTED_ARCHIVED_ALLOWED = {
    ("GET", "/campaigns/{campaign_id}/settings"),
    ("POST", "/campaigns/{campaign_id}/reactivate"),
}


def _iter_api_routes(routes: list[object]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _iter_api_routes(route.original_router.routes)
        elif isinstance(route, APIRouter):
            yield from _iter_api_routes(route.routes)


def _capability_dependencies(route: APIRoute) -> list[object]:
    return [
        dependency.call
        for dependency in route.dependant.dependencies
        if "require_campaign_capability" in getattr(dependency.call, "__qualname__", "")
    ]


def test_exactly_settings_read_and_reactivate_allow_an_archived_campaign() -> None:
    allowed: set[tuple[str, str]] = set()
    for route in _iter_api_routes(create_app().routes):
        for call in _capability_dependencies(route):
            if getattr(call, "allow_archived_campaign", False):
                for method in route.methods or ():
                    if method not in ("HEAD", "OPTIONS"):
                        allowed.add((method, route.path))
    assert allowed == EXPECTED_ARCHIVED_ALLOWED


def test_every_campaign_scoped_route_uses_the_capability_dependency() -> None:
    """A route with `{campaign_id}` in its path that skipped
    `require_campaign_capability` would also skip the archived gate."""
    missing = [
        (sorted(route.methods or ())[0], route.path)
        for route in _iter_api_routes(create_app().routes)
        if "{campaign_id}" in route.path and not _capability_dependencies(route)
    ]
    assert missing == []


def test_the_archived_opt_in_defaults_to_false() -> None:
    from dnd_ai.api.access import require_campaign_capability

    dependency = require_campaign_capability("campaign.view")
    assert dependency.allow_archived_campaign is False  # type: ignore[attr-defined]
